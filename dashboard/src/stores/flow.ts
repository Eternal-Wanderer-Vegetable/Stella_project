import { defineStore } from 'pinia';

import type {
  FlowEvent,
  FlowMessageDetail,
  FlowMessageSummary,
  FlowSpec,
} from '@/api/flow';
import { getEvents, getMessage, getSpec, listMessages } from '@/api/flow';
import { sseStream } from '@/api/sse';

// 消息流程 store（计划 §6.7）：纯 reducer 投影 + 历史播放。
// 播放状态完全留在前端；任何动作都不发消息、不写业务（回放零副作用）。

export interface FlowNodeState {
  nodeId: string;
  label: string;
  status: string; // 投影出的展示状态
  businessOutcome: string; // reason/summary 携带的业务事实
  instances: number; // 事件实例数（重试/多段/多轮）
  firstSeq: number;
  lastTs: string;
  durationMs: number | null;
  metrics: Array<Record<string, unknown>>;
  events: FlowEvent[];
}

interface EventType {
  kind: FlowEvent['kind'];
  status: string;
}

/** 单节点投影：以「最近事件」为展示状态；finish 缺失即 running。 */
function projectNode(nodeId: string, events: FlowEvent[], label: string): FlowNodeState {
  let status = 'not_observed';
  let businessOutcome = '';
  let durationMs: number | null = null;
  let lastTs = '';
  const metrics: Array<Record<string, unknown>> = [];
  for (const ev of events) {
    lastTs = ev.ts_utc || lastTs;
    const et: EventType = { kind: ev.kind, status: ev.status };
    if (et.kind === 'finish' || et.kind === 'decision' || et.kind === 'trace_end') {
      status = et.status || status;
      businessOutcome = ev.reason_code || ev.summary || businessOutcome;
    } else if (et.kind === 'checkpoint') {
      status = 'succeeded';
      businessOutcome = ev.summary || businessOutcome;
    } else if (et.kind === 'start') {
      if (status === 'not_observed') status = 'running';
    }
    if (ev.duration_ms != null) durationMs = ev.duration_ms;
    if (Object.keys(ev.metrics ?? {}).length > 0) metrics.push(ev.metrics);
  }
  return {
    nodeId,
    label,
    status,
    businessOutcome,
    instances: new Set(events.map((e) => e.instance_key || e.span_id || e.event_id)).size,
    firstSeq: events.length ? events[0].seq : 0,
    lastTs,
    durationMs,
    metrics,
    events,
  };
}

export const useFlowStore = defineStore('flow', {
  state: () => ({
    messages: [] as FlowMessageSummary[],
    messagesTotal: 0,
    loadingList: false,
    platformFilter: '' as string,
    rootKindFilter: '' as string,
    detail: null as FlowMessageDetail | null,
    detailLoading: false,
    events: [] as FlowEvent[],
    seenEventIds: new Set<string>(),
    spec: null as FlowSpec | null,
    specVersion: '',
    playbackIndex: -1, // -1 = 实时（最新）；>=0 = 历史播放位置（events 下标）
    live: false, // SSE 订阅中
    streaming: false,
    selectedNodeId: '' as string,
    abort: null as AbortController | null,
  }),

  getters: {
    /** 去重 + seq 稳定排序后的全量事件（回放权威，计划 §6.5）。 */
    orderedEvents(state): FlowEvent[] {
      const seen = new Set<string>();
      const uniq = state.events.filter((e) => {
        if (seen.has(e.event_id)) return false;
        seen.add(e.event_id);
        return true;
      });
      return uniq.sort((a, b) => a.row_id - b.row_id);
    },

    /** 当前播放时点之前的事件切片（纯 reducer，无副作用）。 */
    visibleEvents(): FlowEvent[] {
      const all = this.orderedEvents;
      if (this.playbackIndex < 0) return all;
      return all.slice(0, this.playbackIndex + 1);
    },

    nodeStates(): FlowNodeState[] {
      const byNode = new Map<string, FlowEvent[]>();
      for (const ev of this.visibleEvents) {
        const list = byNode.get(ev.node_id) ?? [];
        list.push(ev);
        byNode.set(ev.node_id, list);
      }
      const nodes = [...byNode.entries()]
        .map(([nodeId, evs]) =>
          projectNode(nodeId, evs, this.nodeLabel(nodeId)),
        )
        .sort((a, b) => a.firstSeq - b.firstSeq);
      return nodes;
    },

    nodeLabel(state): (nodeId: string) => string {
      return (nodeId: string) => {
        const spec = state.spec?.nodes?.[nodeId];
        if (spec) return spec.label;
        if (nodeId.startsWith('hook.custom:')) {
          return `扩展钩子 ${nodeId.split(':')[1]}`;
        }
        return nodeId;
      };
    },

    nodeLane(state): (nodeId: string) => string {
      return (nodeId: string) => state.spec?.nodes?.[nodeId]?.lane ?? 'other';
    },
  },

  actions: {
    async loadMessages() {
      this.loadingList = true;
      try {
        const data = await listMessages({
          platform: this.platformFilter || undefined,
          root_kind: this.rootKindFilter || undefined,
          limit: 100,
        });
        this.messages = data.items;
        this.messagesTotal = data.total;
      } finally {
        this.loadingList = false;
      }
    },

    async openTrace(traceId: string) {
      this.stopStream();
      this.detailLoading = true;
      this.events = [];
      this.seenEventIds = new Set();
      this.playbackIndex = -1;
      this.selectedNodeId = '';
      try {
        this.detail = await getMessage(traceId);
        await this.fetchEvents();
        if (this.detail?.status === 'interrupted') {
          // 中断的 trace 不会再有新事件：不订阅
          this.live = false;
        }
      } finally {
        this.detailLoading = false;
      }
    },

    async fetchEvents() {
      if (!this.detail) return;
      const after = this.events.length
        ? Math.max(...this.events.map((e) => e.row_id))
        : 0;
      const items = await getEvents(this.detail.trace_id, after);
      this.mergeEvents(items);
    },

    mergeEvents(items: FlowEvent[]) {
      for (const ev of items) {
        if (this.seenEventIds.has(ev.event_id)) continue;
        this.seenEventIds.add(ev.event_id);
        this.events.push(ev);
      }
    },

    async loadSpec() {
      if (this.spec) return;
      try {
        this.spec = await getSpec(this.detail?.topology_version || '');
        this.specVersion = this.spec.topology_version;
      } catch {
        // 版本缺失：显式 unmapped，不用最新图解释旧轨迹（计划 §6.6）
        this.spec = null;
      }
    },

    /** 实时订阅：SSE 推增量；失败静默降级为手动刷新（轮询由用户触发）。 */
    async startStream() {
      if (!this.detail || this.streaming) return;
      const traceId = this.detail.trace_id;
      if (this.detail.status !== 'interrupted') this.live = true;
      this.streaming = true;
      this.abort = new AbortController();
      const after = this.events.length
        ? Math.max(...this.events.map((e) => e.row_id))
        : 0;
      try {
        await sseStream(
          streamUrlSafe(traceId, after),
          (_id, data) => {
            try {
              const parsed = JSON.parse(data) as
                | FlowEvent
                | { type: 'trace_end' | 'missing' };
              if ('type' in parsed) {
                this.live = false;
                if (parsed.type === 'trace_end' && this.detail) {
                  // 终帧后补一次元数据（outcome/complete 可能已更新）
                  void getMessage(traceId).then((d) => {
                    if (this.detail?.trace_id === traceId) this.detail = d;
                  });
                }
                this.abort?.abort();
                return;
              }
              this.mergeEvents([parsed]);
            } catch {
              /* 忽略坏帧 */
            }
          },
          { signal: this.abort.signal },
        );
      } catch {
        // 断线：保留已有事件，live 熄灭；用户可手动刷新或重开
      } finally {
        this.streaming = false;
        this.live = this.live && this.streaming;
      }
    },

    stopStream() {
      this.abort?.abort();
      this.abort = null;
      this.streaming = false;
      this.live = false;
    },

    selectNode(nodeId: string) {
      this.selectedNodeId = nodeId;
    },

    setPlayback(index: number) {
      const max = this.orderedEvents.length - 1;
      this.playbackIndex = Math.max(-1, Math.min(index, max));
    },

    stepPlayback(delta: number) {
      this.setPlayback(this.playbackIndex < 0 ? this.orderedEvents.length - 1 + delta : this.playbackIndex + delta);
    },

    resetPlayback() {
      this.playbackIndex = -1;
    },
  },
});

function streamUrlSafe(traceId: string, after: number): string {
  // 独立函数避免 store 循环依赖 api/flow 的 streamUrl
  return `/api/v1/trace/messages/${traceId}/stream?after=${after}`;
}
