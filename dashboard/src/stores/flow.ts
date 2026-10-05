import { defineStore } from 'pinia';

import type {
  FlowEntityChange,
  FlowEvent,
  FlowMessageDetail,
  FlowMessageIo,
  FlowMessageSummary,
  FlowNodeSpec,
  FlowSpec,
} from '@/api/flow';
import {
  getEvents,
  getMessage,
  getMessageIo,
  getSpec,
  getSpecByDigest,
  getTraceEntities,
  listMessages,
} from '@/api/flow';
import { SseAuthError, sseStream } from '@/api/sse';
import {
  dedupeAndOrder,
  fallbackNodeLabel,
  projectNodes,
} from '@/stores/flowReducer';

// 消息流程 store（计划 §6.7 + 修复计划 §6.6）：纯 reducer 投影 + 历史播放。
// 播放状态完全留在前端；任何动作都不发消息、不写业务（回放零副作用）。
// 投影逻辑在 flowReducer.ts（纯函数，tests/ 下有单测）。
//
// O04/O09：spec 缓存；打开轨迹用请求代际（generation counter）防护快速
// 切换；事件分页拉到快照高水位；SSE 断线带 cursor 指数退避重连（1s 起、
// 15s 封顶），终帧/401/页面隐藏时停止。
//
// 修复计划 §6.6（M5，R6/R8）：refreshTraceBundle 一次刷新 detail/IO/实体
// （trace_end 与手动刷新必触发，receipt 事实节流触发）；列表 keyset 游标
// 加载更多；事件分页区分「已加载」与「存储总量」，达页数上限显式 partial
// 并可继续加载；spec 按 digest 精确缓存，缺 spec 时回退事件时间线。

// 事件单页上限（与 api/flow.getEvents 缺省一致；后端 route 上限 1000）
const EVENT_PAGE_LIMIT = 1000;
// 分页软上限：100 页 ≈ 10 万事件；达到后显式 partial + 可手动继续
const MAX_EVENT_PAGES = 100;
// 断线重连退避：1s 起，指数翻倍，15s 封顶
const RECONNECT_BASE_MS = 1000;
const RECONNECT_MAX_MS = 15000;
// receipt 事实触发的 IO 刷新节流（毫秒）
const IO_REFRESH_THROTTLE_MS = 2000;
// 消息列表单页条数（keyset 游标续读）
const LIST_PAGE_LIMIT = 100;

/** 列表页合并（验收报告 M2）：新首屏覆盖顶部，已加载的历史页按
 * (started_utc, trace_id) 降序保留；reset 时整体替换。 */
function mergeListPage(
  existing: FlowMessageSummary[],
  incoming: FlowMessageSummary[],
  reset: boolean,
): FlowMessageSummary[] {
  if (reset) return [...incoming];
  const seen = new Set(incoming.map((m) => m.trace_id));
  const kept = existing.filter((m) => !seen.has(m.trace_id));
  return [...incoming, ...kept].sort((a, b) =>
    b.started_utc.localeCompare(a.started_utc)
    || b.trace_id.localeCompare(a.trace_id));
}

/** 循环累计取最大 row_id（修复计划 §6.6：大数组禁用 Math.max(...) 展开）。 */
function maxRowId(events: Array<{ row_id: number }>): number {
  let max = 0;
  for (const e of events) {
    if (e.row_id > max) max = e.row_id;
  }
  return max;
}

export const useFlowStore = defineStore('flow', {
  state: () => ({
    messages: [] as FlowMessageSummary[],
    messagesTotal: 0,
    messagesCursor: '' as string, // keyset 游标；'' = 无更多
    listFilterKey: '|', // 当前列表查询的过滤键（平台|入口）
    listSeq: 0, // 列表请求代际：过滤变化/轮询竞态防护（验收报告 M2）
    loadingList: false,
    platformFilter: '' as string,
    rootKindFilter: '' as string,
    detail: null as FlowMessageDetail | null,
    io: null as FlowMessageIo | null,
    ioLoading: false,
    detailLoading: false,
    events: [] as FlowEvent[],
    seenEventIds: new Set<string>(),
    eventsTruncated: false, // 达到 MAX_EVENT_PAGES 软上限：partial，可继续
    eventsLoading: false,
    traceEntities: [] as FlowEntityChange[],
    spec: null as FlowSpec | null,
    specVersion: '',
    specCache: new Map<string, FlowSpec>(), // 按 digest（legacy 按 version+binding）
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
    ioRefreshTimer: null as number | null,
    bundleSeq: 0, // bundle 请求代际（验收报告 M2：旧响应不得覆盖终态）
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

    /** 边级 transition 事实（修复计划 §6.4）：布局边激活的唯一依据。 */
    transitionFacts(): FlowEvent[] {
      return this.visibleEvents.filter(
        (e) => e.fact_kind === 'transition',
      );
    },

    /** root 是否已真实结束（修复计划 §6.4：终点锚依据真实 trace end）。 */
    rootEnded(state): boolean {
      return Boolean(state.detail?.ended_utc);
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
      // 过滤变化 → 重置累积；否则轮询只刷新首屏并保留已加载的历史页
      // （验收报告 M2：直接替换会让「加载更早」的历史页在 5s 轮询后消失）
      const filterKey = `${this.platformFilter ?? ''}|${this.rootKindFilter ?? ''}`;
      const reset = filterKey !== this.listFilterKey;
      const seq = ++this.listSeq;
      if (reset) {
        this.listFilterKey = filterKey;
        this.messages = [];
        this.messagesCursor = '';
      }
      this.loadingList = true;
      try {
        const data = await listMessages({
          platform: this.platformFilter || undefined,
          root_kind: this.rootKindFilter || undefined,
          limit: LIST_PAGE_LIMIT,
        });
        if (seq !== this.listSeq
            || filterKey !== `${this.platformFilter ?? ''}|${this.rootKindFilter ?? ''}`) {
          return; // 请求期间过滤已变：旧响应整包丢弃
        }
        this.messages = mergeListPage(this.messages, data.items, reset);
        this.messagesTotal = data.total;
        if (!this.messagesCursor || reset) {
          this.messagesCursor = data.next_cursor ?? '';
        }
      } finally {
        if (seq === this.listSeq) this.loadingList = false;
      }
    },

    /**
     * 加载更多（修复计划 §6.6 R8）：keyset 游标续读——offset 在不断插入的
     * 列表里会漏行/重复；游标以 (started_utc, trace_id) 稳定续读。默认 100
     * 条只是单页大小，不是总量上限。
     */
    async loadMoreMessages() {
      if (!this.messagesCursor || this.loadingList) return;
      const filterKey = `${this.platformFilter ?? ''}|${this.rootKindFilter ?? ''}`;
      if (filterKey !== this.listFilterKey) {
        // 过滤已切走：不再向旧过滤的游标追加（验收报告 M2 反例）
        this.messagesCursor = '';
        return;
      }
      const seq = this.listSeq;
      this.loadingList = true;
      try {
        const data = await listMessages({
          platform: this.platformFilter || undefined,
          root_kind: this.rootKindFilter || undefined,
          limit: LIST_PAGE_LIMIT,
          cursor: this.messagesCursor,
        });
        const currentKey = `${this.platformFilter ?? ''}|${this.rootKindFilter ?? ''}`;
        if (seq !== this.listSeq || currentKey !== filterKey) {
          return; // 期间发生过滤切换/重置：旧页丢弃（验收报告 M2）
        }
        this.messages = mergeListPage(this.messages, data.items, false);
        this.messagesTotal = data.total;
        this.messagesCursor = data.next_cursor ?? '';
      } finally {
        if (seq === this.listSeq) this.loadingList = false;
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
      this.eventsTruncated = false;
      this.traceEntities = [];
      this.playbackIndex = -1;
      this.selectedNodeId = '';
      this.io = null;
      // spec 先清空：等 loadSpec 按（缓存命中的）digest/版本就位，绝不用
      // 上一条轨迹的图解释这条轨迹（O04；缺版本显式 unmapped，计划 §6.6）
      this.spec = null;
      this.specVersion = '';
      this.streamEnded = false;
      this.resumeStreamOnVisible = false;
      try {
        const detail = await getMessage(traceId);
        if (gen !== this.traceGeneration) return;
        this.detail = detail;
        // 输入/输出是独立来源（记忆库），失败不阻塞拓扑展示
        this.ioLoading = true;
        void getMessageIo(traceId)
          .then((io) => {
            if (gen === this.traceGeneration && this.detail?.trace_id === traceId) {
              this.io = io;
            }
          })
          .catch(() => {})
          .finally(() => {
            if (gen === this.traceGeneration) this.ioLoading = false;
          });
        const entitiesPromise = getTraceEntities(traceId)
          .then((entities) => {
            if (gen === this.traceGeneration && this.detail?.trace_id === traceId) {
              this.traceEntities = entities;
            }
          })
          .catch(() => {});
        await Promise.all([this.fetchEvents(), entitiesPromise]);
      } finally {
        if (gen === this.traceGeneration) this.detailLoading = false;
      }
    },

    /**
     * bundle 刷新（修复计划 §6.6 R6）：一次刷新 detail（含 relations）、IO
     * 与对象事实。trace_end 与手动刷新必须触发；receipt 事实走节流入口
     * {@link scheduleIoRefresh}。每个回包都校验代际与当前轨迹。
     */
    async refreshTraceBundle(options: { awaitFinality?: boolean } = {}) {
      const gen = this.traceGeneration;
      const traceId = this.detail?.trace_id;
      if (!traceId) return;
      // 请求代际（验收报告 M2 + 复验 A2）：旧 bundle 响应不得覆盖新终态；
      // alive 同时绑定 session——页面隐藏（stopStream 递增 session）后，
      // 在途 bundle 回包一律作废
      const seq = ++this.bundleSeq;
      const session = this.streamSession;
      const alive = () =>
        seq === this.bundleSeq
        && gen === this.traceGeneration
        && session === this.streamSession
        && this.detail?.trace_id === traceId;
      // detail 先行（事件补读需要它的新水位）；短暂失败进入有界重试，
      // 绝不因此取消独立的 IO/实体/事件刷新（复验 A1）
      const detailOk = await (async () => {
        for (let attempt = 0; attempt < 2; attempt += 1) {
          try {
            const detail = await getMessage(traceId);
            if (!alive()) return false;
            this.detail = detail;
            return true;
          } catch {
            if (attempt === 0) {
              await new Promise((r) => setTimeout(r, 500));
              if (!alive()) return false;
            }
          }
        }
        return false;
      })();
      // 整体失效（切轨迹/隐藏页面/session 递增）→ 全部中止；仅 detail
      // 瞬时失败时，独立来源仍照常刷新（复验 A1）
      if (!alive()) return;
      // 独立来源第一轮：detail 失败也照常刷新
      await Promise.all([
        this.fetchEvents().catch(() => {}),
        getMessageIo(traceId)
          .then((io) => {
            if (alive()) this.io = io;
          })
          .catch(() => {}),
        getTraceEntities(traceId)
          .then((entities) => {
            if (alive()) this.traceEntities = entities;
          })
          .catch(() => {}),
      ]);
      if (!options.awaitFinality) return;
      // writer finality 有界等待（复验 A1）：producer 已结束但 integrity
      // 尚未落账时，短暂重试直到账本确认或次数用尽（绝不无限等待）
      let finalized = false;
      for (let attempt = 0; attempt < 3 && !finalized; attempt += 1) {
        const d = this.detail;
        if (!alive()) return;
        finalized = Boolean(
          d
          && d.producer_ended
          && (d.integrity === 'complete'
            || d.integrity === 'partial'
            || d.integrity === 'unknown'),
        );
        if (finalized) break;
        await new Promise((r) => setTimeout(r, 1500));
        if (!alive()) return;
        try {
          const detail = await getMessage(traceId);
          if (!alive()) return;
          this.detail = detail;
        } catch {
          continue; // 瞬时失败继续重试（有界）
        }
      }
      if (!alive()) return;
      // finality 确认（或重试用尽→显式按当前水位）后，按新水位补齐事件
      // 并再刷一轮独立来源（复验 A1 探针：确认后 loaded 停在旧值 = 漏补读）
      await this.fetchEvents().catch(() => {});
      await Promise.all([
        getMessageIo(traceId)
          .then((io) => {
            if (alive()) this.io = io;
          })
          .catch(() => {}),
        getTraceEntities(traceId)
          .then((entities) => {
            if (alive()) this.traceEntities = entities;
          })
          .catch(() => {}),
      ]);
    },

    /**
     * receipt 事实的节流 IO 刷新（修复计划 §6.6）：发送/回执类事件高频，
     * 不能每条事件全量查 IO——节流窗口内的多次触发合并为一次。
     */
    scheduleIoRefresh() {
      if (this.ioRefreshTimer !== null) return;
      // node 环境无 window：用全局 setTimeout（浏览器返回 number）
      this.ioRefreshTimer = setTimeout(() => {
        this.ioRefreshTimer = null;
        void this.refreshTraceBundle();
      }, IO_REFRESH_THROTTLE_MS) as unknown as number;
    },

    /**
     * 事件分页拉取（O09 + 修复计划 §6.6）：循环 after=已取最大 row_id，
     * 首读固定快照高水位（until）；到达 MAX_EVENT_PAGES 软上限时标
     * truncated（partial + 可 loadMoreEvents），绝不当成完整。
     */
    async fetchEvents() {
      if (!this.detail) return;
      const gen = this.traceGeneration;
      const traceId = this.detail.trace_id;
      // high_watermark = 本 trace 已提交事件的最大全局 row_id（与分页游标
      // 同单位）；persisted_events 是 MAX(seq)（trace 内序列水位），两者
      // 单位不同，绝不可互比（验收报告 H4）
      const highWatermark = Number(this.detail.high_watermark ?? 0);
      this.eventsLoading = true;
      try {
        for (let page = 0; page < MAX_EVENT_PAGES; page += 1) {
          const after = maxRowId(this.events);
          // 稳定快照：每一页都钳制在同一冻结水位（验收报告补充项——此前
          // 只有首页传 until，后续页会读到快照外的新提交）
          const items = await getEvents(
            traceId, after, EVENT_PAGE_LIMIT, highWatermark);
          if (gen !== this.traceGeneration || this.detail?.trace_id !== traceId) {
            return;
          }
          if (!items.length) break; // 空页：服务端已取尽
          this.mergeEvents(items);
          if (items.length < EVENT_PAGE_LIMIT) break; // 不满页：没有更多
          if (highWatermark > 0 && maxRowId(this.events) >= highWatermark) break;
        }
        // 软上限判定（H4 合同）：游标单位 = row_id，对比本 trace 的
        // high_watermark；超过软上限仍有余量 → 显式 partial
        this.eventsTruncated =
          highWatermark > 0 && maxRowId(this.events) < highWatermark;
      } finally {
        if (gen === this.traceGeneration) this.eventsLoading = false;
      }
    },

    /**
     * 超长轨迹的显式「继续加载」（修复计划 §6.6 R8 + 复验 A2）：在同一
     * 冻结快照水位内续读——继续页与首读共用快照边界，不得越过水位读到
     * 快照外的新提交；主动刷新（refreshTraceBundle）才开启新快照。
     */
    async loadMoreEvents() {
      if (!this.detail || !this.eventsTruncated || this.eventsLoading) return;
      const gen = this.traceGeneration;
      const traceId = this.detail.trace_id;
      const highWatermark = Number(this.detail.high_watermark ?? 0);
      this.eventsLoading = true;
      try {
        const after = maxRowId(this.events);
        const items = await getEvents(traceId, after, EVENT_PAGE_LIMIT, highWatermark);
        if (gen !== this.traceGeneration || this.detail?.trace_id !== traceId) {
          return;
        }
        this.mergeEvents(items);
        this.eventsTruncated =
          highWatermark > 0 && maxRowId(this.events) < highWatermark;
      } finally {
        if (gen === this.traceGeneration) this.eventsLoading = false;
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
     * spec 目录加载（O04 + 修复计划 §6.2/§6.6）：有 spec_digest 时按 digest
     * 精确读取/缓存（同 version 不同 digest 并存，绝不互串）；digest 为空
     * 的 legacy 轨迹按版本回退读取（legacy_unverified，明确不保证精确）。
     * 404（缺版本）不缓存，保留之后重试的机会。
     */
    async loadSpec() {
      const version = this.detail?.topology_version || '';
      const digest = this.detail?.spec_digest || '';
      const gen = this.traceGeneration;
      if (!version) {
        this.spec = null;
        this.specVersion = '';
        return;
      }
      const cacheKey = digest ? `digest:${digest}` : `legacy:${version}`;
      const cached = this.specCache.get(cacheKey);
      if (cached) {
        this.spec = cached;
        this.specVersion = cached.topology_version;
        return;
      }
      try {
        const spec = digest
          ? await getSpecByDigest(version, digest)
          : await getSpec(version);
        this.specCache.set(cacheKey, spec);
        if (gen !== this.traceGeneration) return;
        this.spec = spec;
        this.specVersion = spec.topology_version;
      } catch {
        if (gen !== this.traceGeneration) return;
        // 版本缺失/无精确归档：显式 unmapped，不用最新图解释旧轨迹
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
          const after = maxRowId(this.events);
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
                    // 终帧后 bundle 刷新（修复计划 §6.6 R6 + 验收报告 H5）：
                    // detail/事件补读/IO/关系/对象一次到位，并等待 writer
                    // finality 落账（有界重试，不无限等待）
                    void this.refreshTraceBundle({ awaitFinality: true });
                  }
                  controller.abort();
                  return;
                }
                this.reconnectAttempts = 0; // 有数据流动：重置退避
                this.mergeEvents([parsed]);
                // receipt/投递事实 → 节流刷新 IO（修复计划 §6.6）：
                // 不给每条 SSE 事件做全量 IO 查询
                if (
                  parsed.node_id.startsWith('send.') ||
                  parsed.node_id === 'reply.bookkeeping'
                ) {
                  this.scheduleIoRefresh();
                }
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
