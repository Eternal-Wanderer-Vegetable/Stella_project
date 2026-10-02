import { defineStore } from 'pinia';

import type {
  FlowEvent,
  FlowMessageDetail,
  FlowMessageSummary,
  FlowNodeSpec,
  FlowSpec,
} from '@/api/flow';
import { getEvents, getMessage, getSpec, listMessages } from '@/api/flow';
import { sseStream } from '@/api/sse';
import {
  dedupeAndOrder,
  fallbackNodeLabel,
  projectNodes,
} from '@/stores/flowReducer';

// 消息流程 store（计划 §6.7）：纯 reducer 投影 + 历史播放。
// 播放状态完全留在前端；任何动作都不发消息、不写业务（回放零副作用）。
// 投影逻辑在 flowReducer.ts（纯函数，tests/ 下有单测）。

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
      return dedupeAndOrder(state.events);
    },

    /** 当前播放时点之前的事件切片（纯 reducer，无副作用）。 */
    visibleEvents(): FlowEvent[] {
      const all = this.orderedEvents;
      if (this.playbackIndex < 0) return all;
      return all.slice(0, this.playbackIndex + 1);
    },

    nodeStates(): ReturnType<typeof projectNodes> {
      // kind=link 是 trace 间关系事实（详情区展示），不是画布节点
      const nodeEvents = this.visibleEvents.filter((e) => e.kind !== 'link');
      return projectNodes(nodeEvents, (nodeId) => this.nodeLabel(nodeId));
    },

    /** 已执行节点索引（完整视图把未执行节点渲染成灰色 not_observed）。 */
    executedNodeMap(): Map<string, ReturnType<typeof projectNodes>[number]> {
      return new Map(this.nodeStates.map((n) => [n.nodeId, n]));
    },

    /** manifest 的 nodes 是数组：按 ID 建一次索引（label/lane 查找的唯一来源）。 */
    specNodeById(state): Map<string, FlowNodeSpec> {
      return new Map((state.spec?.nodes ?? []).map((n) => [n.id, n]));
    },

    nodeLabel(): (nodeId: string) => string {
      return (nodeId: string) => {
        const spec = this.specNodeById.get(nodeId);
        if (spec) return spec.label;
        // 旧轨迹的 root span node_id 是 root_kind（如 compact）：经入口映射
        // 落到目录入口节点（计划 §6.3），不是裸 ID。
        const entryNode = this.spec?.entry_roots?.[nodeId];
        if (entryNode) {
          const entry = this.specNodeById.get(entryNode);
          if (entry) return entry.label;
        }
        return fallbackNodeLabel(nodeId);
      };
    },

    nodeLane(): (nodeId: string) => string {
      return (nodeId: string) => {
        const spec = this.specNodeById.get(nodeId);
        if (spec) return spec.lane;
        const entryNode = this.spec?.entry_roots?.[nodeId];
        if (entryNode) {
          const entry = this.specNodeById.get(entryNode);
          if (entry) return entry.lane;
        }
        return 'other';
      };
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
      this.setPlayback(
        this.playbackIndex < 0
          ? this.orderedEvents.length - 1 + delta
          : this.playbackIndex + delta,
      );
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
