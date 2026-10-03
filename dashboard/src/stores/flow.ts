import { defineStore } from 'pinia';

import type {
  FlowEvent,
  FlowMessageDetail,
  FlowMessageIo,
  FlowMessageSummary,
  FlowNodeSpec,
  FlowSpec,
} from '@/api/flow';
import { getEvents, getMessage, getMessageIo, getSpec, listMessages } from '@/api/flow';
import { SseAuthError, sseStream } from '@/api/sse';
import {
  dedupeAndOrder,
  fallbackNodeLabel,
  projectNodes,
} from '@/stores/flowReducer';

// 消息流程 store（计划 §6.7）：纯 reducer 投影 + 历史播放。
// 播放状态完全留在前端；任何动作都不发消息、不写业务（回放零副作用）。
// 投影逻辑在 flowReducer.ts（纯函数，tests/ 下有单测）。
//
// O04/O09（计划 §2.2/§6.6）：spec 按 topology_version 缓存；打开轨迹用请求
// 代际（generation counter）防护快速切换；事件分页拉到快照高水位；SSE 断线
// 带 cursor 指数退避重连（1s 起、15s 封顶），终帧/401/页面隐藏时停止。

// 事件单页上限（与 api/flow.getEvents 缺省一致；后端 route 上限 1000）
const EVENT_PAGE_LIMIT = 1000;
// 分页硬上限：100 页 ≈ 10 万事件，防历史超长轨迹把页面拖死
const MAX_EVENT_PAGES = 100;
// 断线重连退避：1s 起，指数翻倍，15s 封顶
const RECONNECT_BASE_MS = 1000;
const RECONNECT_MAX_MS = 15000;

export const useFlowStore = defineStore('flow', {
  state: () => ({
    messages: [] as FlowMessageSummary[],
    messagesTotal: 0,
    loadingList: false,
    platformFilter: '' as string,
    rootKindFilter: '' as string,
    detail: null as FlowMessageDetail | null,
    io: null as FlowMessageIo | null,
    detailLoading: false,
    events: [] as FlowEvent[],
    seenEventIds: new Set<string>(),
    spec: null as FlowSpec | null,
    specVersion: '',
    specCache: new Map<string, FlowSpec>(), // O04：按 topology_version 缓存
    traceGeneration: 0, // O04：openTrace 代际，旧响应按代际丢弃
    playbackIndex: -1, // -1 = 实时（最新）；>=0 = 历史播放位置（events 下标）
    live: false, // SSE 订阅中
    streaming: false,
    streamSession: 0, // O09：主动 stop/start 递增，使后台重连循环失效
    streamEnded: false, // O09：已收到 trace_end/interrupted/missing 终帧
    reconnectAttempts: 0, // O09：当前退避轮数（有数据流动即重置）
    resumeStreamOnVisible: false, // O09：隐藏页面时记住「原本在直播」
    selectedNodeId: '' as string,
    abort: null as AbortController | null,
    listTimer: null as number | null,
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

    /** 已执行节点索引（完整视图把未观测节点渲染成灰色 not_observed）。 */
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
    /**
     * 列表轮询（用户验收：新消息实时出现，不等手动刷新）。5s 一次；
     * 页面不可见/正在加载时跳过该轮。轮询比 SSE 简单且足够：列表只是
     * 轻量元数据，单条轨迹的实时性由已打开的 SSE 流负责。
     */
    startListPolling() {
      if (this.listTimer !== null) return;
      this.listTimer = window.setInterval(() => {
        if (document.visibilityState !== 'visible') return;
        if (this.loadingList) return;
        void this.loadMessages();
      }, 5000);
    },

    stopListPolling() {
      if (this.listTimer !== null) {
        window.clearInterval(this.listTimer);
        this.listTimer = null;
      }
    },

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

    /**
     * 打开轨迹（O04）：先递增请求代际再发请求——getMessage / getMessageIo /
     * getEvents 的响应返回时代际已变（快速切换 A→B→A）就整包丢弃，
     * 旧响应绝不覆盖新详情。
     */
    async openTrace(traceId: string) {
      const gen = ++this.traceGeneration;
      this.stopStream();
      this.detailLoading = true;
      this.events = [];
      this.seenEventIds = new Set();
      this.playbackIndex = -1;
      this.selectedNodeId = '';
      this.io = null;
      // spec 先清空：等 loadSpec 按（缓存命中的）版本就位，绝不用上一条
      // 轨迹的图解释这条轨迹（O04；缺版本显式 unmapped，计划 §6.6）
      this.spec = null;
      this.specVersion = '';
      this.streamEnded = false;
      this.resumeStreamOnVisible = false;
      try {
        const detail = await getMessage(traceId);
        if (gen !== this.traceGeneration) return;
        this.detail = detail;
        // 输入/输出是独立来源（记忆库），失败不阻塞拓扑展示
        void getMessageIo(traceId)
          .then((io) => {
            if (gen === this.traceGeneration && this.detail?.trace_id === traceId) {
              this.io = io;
            }
          })
          .catch(() => {});
        await this.fetchEvents();
      } finally {
        if (gen === this.traceGeneration) this.detailLoading = false;
      }
    },

    /**
     * 事件分页拉取（O09）：循环 after=已取最大 row_id，直到空页/不满页或
     * 到达详情快照的 high_watermark——>1000 事件的轨迹不再只读一页。
     * 拉取期间切换轨迹（代际变化）即中止，不污染新轨迹的事件。
     */
    async fetchEvents() {
      if (!this.detail) return;
      const gen = this.traceGeneration;
      const traceId = this.detail.trace_id;
      const highWatermark = Number(this.detail.high_watermark ?? 0);
      for (let page = 0; page < MAX_EVENT_PAGES; page += 1) {
        const after = this.events.length
          ? Math.max(...this.events.map((e) => e.row_id))
          : 0;
        const items = await getEvents(traceId, after, EVENT_PAGE_LIMIT);
        if (gen !== this.traceGeneration || this.detail?.trace_id !== traceId) {
          return;
        }
        if (!items.length) break; // 空页：服务端已取尽
        this.mergeEvents(items);
        if (items.length < EVENT_PAGE_LIMIT) break; // 不满页：没有更多
        const maxRow = Math.max(...items.map((e) => e.row_id));
        if (highWatermark > 0 && maxRow >= highWatermark) break; // 已到快照高水位
      }
    },

    mergeEvents(items: FlowEvent[]) {
      for (const ev of items) {
        if (this.seenEventIds.has(ev.event_id)) continue;
        this.seenEventIds.add(ev.event_id);
        this.events.push(ev);
      }
    },

    /**
     * spec 目录加载（O04）：按 topology_version 缓存（Map），同版本不重复
     * 请求；响应返回时若已切换轨迹（代际变化）则只进缓存、不进视图。
     * 404（缺版本）不缓存，保留之后重试的机会。
     */
    async loadSpec() {
      const version = this.detail?.topology_version || '';
      const gen = this.traceGeneration;
      if (!version) {
        this.spec = null;
        this.specVersion = '';
        return;
      }
      const cached = this.specCache.get(version);
      if (cached) {
        this.spec = cached;
        this.specVersion = cached.topology_version;
        return;
      }
      try {
        const spec = await getSpec(version);
        this.specCache.set(version, spec);
        if (gen !== this.traceGeneration) return;
        this.spec = spec;
        this.specVersion = spec.topology_version;
      } catch {
        if (gen !== this.traceGeneration) return;
        // 版本缺失：显式 unmapped，不用最新图解释旧轨迹（计划 §6.6）
        this.spec = null;
      }
    },

    /** SSE 循环是否还活着：代际/会话/终帧/当前轨迹任一失效即退出。 */
    streamAlive(gen: number, session: number, traceId: string): boolean {
      return (
        gen === this.traceGeneration &&
        session === this.streamSession &&
        !this.streamEnded &&
        this.detail?.trace_id === traceId
      );
    },

    /**
     * 实时订阅（O09）：SSE 推增量；断线自动重连——cursor 取已取最大
     * row_id，指数退避 1s 起步、15s 封顶，有数据流动即重置；收到
     * trace_end / interrupted / missing 终帧后停止（活跃 running root
     * 不会再发 trace_end，生产者真正结束才发）；401 与 Axios 同一处理
     * （sse 层已清登录态回登录页），凭 SseAuthError 停止重连。
     */
    async startStream() {
      if (!this.detail || this.streaming) return;
      if (this.detail.status === 'interrupted') return; // 过期化身：不再有事件
      const traceId = this.detail.trace_id;
      const gen = this.traceGeneration;
      this.streamSession += 1;
      const session = this.streamSession;
      this.streamEnded = false;
      this.reconnectAttempts = 0;
      this.live = true;
      void this.streamLoop(traceId, gen, session);
    },

    async streamLoop(traceId: string, gen: number, session: number) {
      this.streaming = true;
      try {
        while (this.streamAlive(gen, session, traceId)) {
          const controller = new AbortController();
          this.abort = controller;
          const after = this.events.length
            ? Math.max(...this.events.map((e) => e.row_id))
            : 0;
          try {
            await sseStream(streamUrlSafe(traceId, after), (_id, data) => {
              try {
                const parsed = JSON.parse(data) as
                  | FlowEvent
                  | { type: 'trace_end' | 'interrupted' | 'missing' };
                if ('type' in parsed) {
                  // 终帧（O09）：producer 结束 / 过期化身 / 轨迹缺失
                  this.streamEnded = true;
                  this.live = false;
                  if (parsed.type === 'trace_end') {
                    // 终帧后补一次元数据（integrity/outcome 可能已更新）
                    void getMessage(traceId)
                      .then((d) => {
                        if (
                          gen === this.traceGeneration &&
                          this.detail?.trace_id === traceId
                        ) {
                          this.detail = d;
                        }
                      })
                      .catch(() => {});
                  }
                  controller.abort();
                  return;
                }
                this.reconnectAttempts = 0; // 有数据流动：重置退避
                this.mergeEvents([parsed]);
              } catch {
                /* 忽略坏帧 */
              }
            }, { signal: controller.signal });
            // 服务端干净断流但没发终帧：视为断线 → 退避重连
          } catch (err) {
            if (err instanceof SseAuthError) break; // 401：已回登录页，不重连
            if (controller.signal.aborted) break; // 主动停止 / 切轨迹 / 页面隐藏
            // 其余异常：断线 → 退避重连（cursor 从已取最大 row_id 续读）
          }
          if (!this.streamAlive(gen, session, traceId)) break;
          const backoff = Math.min(
            RECONNECT_BASE_MS * 2 ** this.reconnectAttempts,
            RECONNECT_MAX_MS,
          );
          this.reconnectAttempts += 1;
          await sleep(backoff, controller.signal);
        }
      } finally {
        if (gen === this.traceGeneration && session === this.streamSession) {
          this.streaming = false;
          this.live = false;
          this.abort = null;
        }
      }
    },

    /**
     * 页面可见性生命周期（O09）：隐藏时停 SSE（记住「原本在直播」）；
     * 恢复可见先 fetchEvents 补读断连期间的事件，再重连。FlowPage 挂
     * visibilitychange 监听；测试可传显式布尔值（node 环境无 document）。
     */
    onVisibilityChange(visible: boolean = isDocumentVisible()) {
      if (!visible) {
        this.resumeStreamOnVisible = this.streaming || this.live;
        this.stopStream();
        return;
      }
      if (!this.resumeStreamOnVisible) return;
      this.resumeStreamOnVisible = false;
      void this.fetchEvents()
        .catch(() => {})
        .then(() => {
          void this.startStream();
        });
    },

    stopStream() {
      this.streamSession += 1; // 使后台重连循环失效
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

/** 可中断的退避等待：signal 中止（stopStream/切轨迹）时立即唤醒。 */
function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    if (signal?.aborted) {
      resolve();
      return;
    }
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener('abort', () => {
      clearTimeout(timer);
      resolve();
    }, { once: true });
  });
}

function isDocumentVisible(): boolean {
  return typeof document === 'undefined' || document.visibilityState !== 'hidden';
}

function streamUrlSafe(traceId: string, after: number): string {
  // 独立函数避免 store 循环依赖 api/flow 的 streamUrl
  return `/api/v1/trace/messages/${traceId}/stream?after=${after}`;
}
