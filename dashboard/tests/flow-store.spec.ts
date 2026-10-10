import { createPinia, setActivePinia } from 'pinia';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type {
  FlowEvent,
  FlowMessageDetail,
  FlowMessageIo,
  FlowSpec,
} from '@/api/flow';
import * as flowApi from '@/api/flow';
import { SseAuthError, sseStream } from '@/api/sse';
import { useFlowStore } from '@/stores/flow';

// store 集成测试：去重合并、播放切片与钳位、spec 缺失回退标签。
// 网络层（api/flow、api/sse）在本文件 mock 掉：O04/O09 的合同
// （spec 缓存、代际防护、分页高水位、断线重连、可见性生命周期）在这里验证。

vi.mock('@/api/flow', () => ({
  getEvents: vi.fn(),
  getMessage: vi.fn(),
  getMessageIo: vi.fn(),
  getSpec: vi.fn(),
  getSpecByDigest: vi.fn(),
  getTraceEntities: vi.fn(async () => []),
  getEntityHistory: vi.fn(async () => []),
  listMessages: vi.fn(),
}));

vi.mock('@/api/sse', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/sse')>();
  return { ...actual, sseStream: vi.fn() };
});

function ev(over: Partial<FlowEvent> & { event_id: string; row_id: number }): FlowEvent {
  return {
    span_id: '',
    parent_span_id: '',
    node_id: 'n',
    instance_key: '',
    seq: over.row_id,
    kind: 'decision',
    status: 'succeeded',
    reason_code: '',
    ts_utc: '2026-10-02T00:00:00',
    duration_ms: null,
    summary: '',
    metrics: {},
    ...over,
  } as FlowEvent;
}

function detail(
  over: Partial<FlowMessageDetail> & { trace_id: string },
): FlowMessageDetail {
  return {
    root_kind: 'qq_chat',
    platform: 'qq',
    scope: 'qq:1',
    source_message_key: '',
    started_utc: '2026-10-03T00:00:00',
    ended_utc: '',
    outcome: '',
    status: 'running',
    complete: false,
    loss: false,
    topology_version: 'v1',
    process_instance_id: 'p',
    detail: {},
    event_count: 0,
    high_watermark: 0,
    spans: [],
    relations: [],
    ...over,
  };
}

const EMPTY_IO: FlowMessageIo = {
  input: null,
  output: { lines: [], count: 0 },
  notes: [],
};

function makeSpec(version: string): FlowSpec {
  return {
    schema_version: 1,
    topology_version: version,
    lanes: [['gate', '闸门']],
    nodes: [{ id: 'chat.group_lock', label: '群锁排队', lane: 'gate', kind: 'lock' }],
    edges: [],
    entry_roots: {},
  };
}

/** 挂住的 SSE mock：记录帧处理器，abort 时以异常断开。 */
function hangSse(
  onConnect?: (call: number) => void,
): Array<(id: string, data: string) => void> {
  const handlers: Array<(id: string, data: string) => void> = [];
  vi.mocked(sseStream).mockImplementation(async (_url, onMessage, opts) => {
    handlers.push(onMessage);
    onConnect?.(handlers.length);
    return new Promise((_, reject) => {
      opts?.signal?.addEventListener('abort', () => reject(new Error('aborted')));
    });
  });
  return handlers;
}

beforeEach(() => {
  setActivePinia(createPinia());
  vi.useFakeTimers();
  // 全局缺省 mock（各用例可覆盖）：M5 的 bundle 刷新会同时触达
  // getMessageIo / getTraceEntities，未 mock 的调用返回 undefined 会炸
  vi.mocked(flowApi.getMessageIo).mockResolvedValue(EMPTY_IO);
  vi.mocked(flowApi.getEvents).mockResolvedValue([]);
  vi.mocked(flowApi.getTraceEntities).mockResolvedValue([]);
});

afterEach(() => {
  vi.resetAllMocks();
  vi.useRealTimers();
});

describe('flow store', () => {
  it('mergeEvents dedupes by event_id and keeps row order', () => {
    const store = useFlowStore();
    store.mergeEvents([
      ev({ event_id: 'a', row_id: 2, node_id: 'x' }),
      ev({ event_id: 'b', row_id: 1, node_id: 'y' }),
    ]);
    store.mergeEvents([ev({ event_id: 'a', row_id: 2, node_id: 'x' })]);
    expect(store.orderedEvents.map((e) => e.event_id)).toEqual(['b', 'a']);
  });

  it('playback slices visible events and clamps the index', () => {
    const store = useFlowStore();
    store.mergeEvents([
      ev({ event_id: 'a', row_id: 1 }),
      ev({ event_id: 'b', row_id: 2 }),
      ev({ event_id: 'c', row_id: 3 }),
    ]);
    store.setPlayback(1);
    expect(store.visibleEvents).toHaveLength(2);
    store.setPlayback(99);
    expect(store.playbackIndex).toBe(2);
    store.setPlayback(-5);
    expect(store.playbackIndex).toBe(-1); // 回到实时
    expect(store.visibleEvents).toHaveLength(3);
  });

  it('stepPlayback starts from the tail when live', () => {
    const store = useFlowStore();
    store.mergeEvents([
      ev({ event_id: 'a', row_id: 1 }),
      ev({ event_id: 'b', row_id: 2 }),
    ]);
    store.stepPlayback(-1);
    expect(store.playbackIndex).toBe(0);
    store.resetPlayback();
    store.stepPlayback(1);
    expect(store.playbackIndex).toBe(1);
  });

  it('node projection follows playback position', () => {
    const store = useFlowStore();
    store.mergeEvents([
      ev({ event_id: 'a', row_id: 1, node_id: 'gate', kind: 'decision',
           status: 'blocked', reason_code: 'pause_all' }),
      ev({ event_id: 'b', row_id: 2, node_id: 'gen', kind: 'start',
           status: 'running' }),
    ]);
    expect(store.nodeStates.map((n) => n.nodeId)).toEqual(['gate', 'gen']);
    store.setPlayback(0); // 只回放到第一个事件
    expect(store.nodeStates.map((n) => n.nodeId)).toEqual(['gate']);
    const gate = store.nodeStates[0];
    expect(gate.status).toBe('blocked');
    expect(gate.businessOutcome).toBe('pause_all');
  });

  it('unmapped nodes fall back to readable labels', () => {
    const store = useFlowStore();
    expect(store.nodeLabel('chat.group_lock')).toBe('chat.group_lock');
    expect(store.nodeLabel('hook.custom:ext')).toBe('扩展钩子 ext');
    expect(store.nodeLane('anything')).toBe('other');
  });

  it('selectNode tracks selection', () => {
    const store = useFlowStore();
    store.selectNode('send.segment');
    expect(store.selectedNodeId).toBe('send.segment');
  });
});

describe('flow store spec lookup', () => {
  it('resolves labels from the manifest node ARRAY (not Record)', () => {
    // 回归：manifest.nodes 是数组；曾误写成 Record 导致整页裸 ID
    const store = useFlowStore();
    store.spec = {
      schema_version: 1,
      topology_version: 't',
      lanes: [['gate', '闸门']],
      nodes: [{ id: 'chat.group_lock', label: '群锁排队', lane: 'gate', kind: 'lock' }],
      edges: [],
      entry_roots: { compact: 'compact.preflight' },
    };
    expect(store.nodeLabel('chat.group_lock')).toBe('群锁排队');
    expect(store.nodeLane('chat.group_lock')).toBe('gate');
  });

  it('maps legacy root_kind node ids through entry_roots', () => {
    const store = useFlowStore();
    store.spec = {
      schema_version: 1,
      topology_version: 't',
      lanes: [['background', '后台']],
      nodes: [
        { id: 'compact.preflight', label: '压缩预检', lane: 'background', kind: 'gate' },
      ],
      edges: [],
      entry_roots: { compact: 'compact.preflight' },
    };
    expect(store.nodeLabel('compact')).toBe('压缩预检');
    expect(store.nodeLane('compact')).toBe('background');
  });

  it('excludes trace.link pseudo nodes from the canvas', () => {
    const store = useFlowStore();
    store.mergeEvents([
      ev({ event_id: 'a', row_id: 1, node_id: 'compact.preflight', kind: 'start',
           status: 'running' }),
      ev({ event_id: 'b', row_id: 2, node_id: 'trace.link', kind: 'link',
           status: 'succeeded' }),
    ]);
    expect(store.nodeStates.map((n) => n.nodeId)).toEqual(['compact.preflight']);
    // link 事件仍在时间线（回放）里
    expect(store.orderedEvents).toHaveLength(2);
  });

  it('executedNodeMap indexes projected nodes by id', () => {
    const store = useFlowStore();
    store.mergeEvents([
      ev({ event_id: 'a', row_id: 1, node_id: 'gate', kind: 'decision',
           status: 'blocked' }),
    ]);
    expect(store.executedNodeMap.get('gate')?.status).toBe('blocked');
    expect(store.executedNodeMap.has('missing')).toBe(false);
  });
});

// ============================================================
// O04（计划 §2.2/§6.6）：spec 按 topology_version 缓存；快速切换 A→B→A
// 时旧响应按请求代际丢弃，绝不覆盖新详情。
// ============================================================
describe('flow store: spec cache & generation guard (O04)', () => {
  it('loadSpec caches by version and does not refetch the same version', async () => {
    const store = useFlowStore();
    vi.mocked(flowApi.getSpec).mockResolvedValue(makeSpec('v1'));
    store.detail = detail({ trace_id: 'a', topology_version: 'v1' });
    await store.loadSpec();
    expect(store.spec?.topology_version).toBe('v1');
    // 换一条轨迹、同版本：缓存命中，不再请求
    store.detail = detail({ trace_id: 'b', topology_version: 'v1' });
    await store.loadSpec();
    expect(flowApi.getSpec).toHaveBeenCalledTimes(1);
    // 换版本才发新请求
    vi.mocked(flowApi.getSpec).mockResolvedValue(makeSpec('v2'));
    store.detail = detail({ trace_id: 'c', topology_version: 'v2' });
    await store.loadSpec();
    expect(flowApi.getSpec).toHaveBeenCalledTimes(2);
    expect(store.spec?.topology_version).toBe('v2');
    // 回到 v1：又是缓存命中
    store.detail = detail({ trace_id: 'd', topology_version: 'v1' });
    await store.loadSpec();
    expect(store.spec?.topology_version).toBe('v1');
    expect(flowApi.getSpec).toHaveBeenCalledTimes(2);
  });

  it('fast A→B switching drops the stale A response (generation guard)', async () => {
    const store = useFlowStore();
    let resolveA!: (d: FlowMessageDetail) => void;
    vi.mocked(flowApi.getMessage).mockImplementation(async (id: string) => {
      if (id === 'a') {
        return new Promise<FlowMessageDetail>((resolve) => { resolveA = resolve; });
      }
      return detail({ trace_id: 'b', topology_version: 'v2' });
    });
    vi.mocked(flowApi.getMessageIo).mockResolvedValue(EMPTY_IO);
    vi.mocked(flowApi.getEvents).mockResolvedValue([]);
    const pA = store.openTrace('a');
    const pB = store.openTrace('b');
    resolveA(detail({ trace_id: 'a', topology_version: 'v1', high_watermark: 9 }));
    await Promise.all([pA, pB]);
    expect(store.detail?.trace_id).toBe('b');
    // A 的过期响应没有把事件/高水位带进来
    expect(store.events).toHaveLength(0);
    expect(store.detailLoading).toBe(false);
  });

  it('stale getEvents/getSpec responses are discarded after switching traces', async () => {
    const store = useFlowStore();
    vi.mocked(flowApi.getMessage).mockResolvedValue(
      detail({ trace_id: 'a', topology_version: 'v1', high_watermark: 0 }),
    );
    vi.mocked(flowApi.getMessageIo).mockResolvedValue(EMPTY_IO);
    // 事件响应拖到切走之后才回来
    let resolveEvents!: (items: FlowEvent[]) => void;
    vi.mocked(flowApi.getEvents).mockImplementation(async () => {
      await new Promise<FlowEvent[]>((r) => { resolveEvents = r; });
      return [ev({ event_id: 'stale', row_id: 1 })];
    });
    vi.mocked(flowApi.getSpec).mockResolvedValue(makeSpec('v1'));
    const pOpen = store.openTrace('a');
    await vi.advanceTimersByTimeAsync(0);
    store.traceGeneration += 1; // 模拟已切到另一条轨迹
    resolveEvents([ev({ event_id: 'stale', row_id: 1 })]);
    await pOpen;
    expect(store.events).toHaveLength(0); // 过期分页整包丢弃
  });
});

// ============================================================
// O09（计划 §2.2/§6.6）：事件分页拉到快照高水位；SSE 断线带 cursor
// 指数退避重连（1s 起、15s 封顶）；终帧/401 停止；页面隐藏停流、
// 恢复先补读再重连。
// ============================================================
describe('flow store: event pagination to high watermark (O09)', () => {
  it('fetchEvents loops until the short page, not just one page', async () => {
    const store = useFlowStore();
    store.detail = detail({ trace_id: 'big', high_watermark: 2500 });
    vi.mocked(flowApi.getEvents).mockImplementation(async (_id, after = 0) => {
      const start = after + 1;
      const count = Math.min(1000, 2500 - after);
      return Array.from({ length: count }, (_, i) =>
        ev({ event_id: `e${start + i}`, row_id: start + i }));
    });
    await store.fetchEvents();
    expect(flowApi.getEvents).toHaveBeenCalledTimes(3);
    // M5 + 验收报告补充项：每一页都钳制在同一冻结水位（稳定快照）
    expect(flowApi.getEvents).toHaveBeenNthCalledWith(1, 'big', 0, 1000, 2500);
    expect(flowApi.getEvents).toHaveBeenNthCalledWith(2, 'big', 1000, 1000, 2500);
    expect(flowApi.getEvents).toHaveBeenNthCalledWith(3, 'big', 2000, 1000, 2500);
    expect(store.events).toHaveLength(2500);
    expect(store.orderedEvents.at(-1)?.row_id).toBe(2500);
  });

  it('single short page stops immediately for small traces', async () => {
    const store = useFlowStore();
    store.detail = detail({ trace_id: 'small', high_watermark: 2 });
    vi.mocked(flowApi.getEvents).mockResolvedValue([
      ev({ event_id: 'e1', row_id: 1 }),
      ev({ event_id: 'e2', row_id: 2 }),
    ]);
    await store.fetchEvents();
    expect(flowApi.getEvents).toHaveBeenCalledTimes(1);
    expect(store.events).toHaveLength(2);
  });
});

describe('flow store: SSE reconnect & lifecycle (O09)', () => {
  function prepare(traceId: string) {
    const store = useFlowStore();
    store.detail = detail({ trace_id: traceId, status: 'running' });
    vi.mocked(flowApi.getEvents).mockResolvedValue([]);
    vi.mocked(flowApi.getMessage).mockResolvedValue(
      detail({ trace_id: traceId, status: 'running' }),
    );
    return store;
  }

  it('reconnects with exponential backoff (1s base) after a dropped connection', async () => {
    const store = prepare('live');
    let calls = 0;
    vi.mocked(sseStream).mockImplementation(async (_url, _on, opts) => {
      calls += 1;
      if (calls === 1) throw new Error('network down');
      return new Promise((_, reject) => {
        opts?.signal?.addEventListener('abort', () => reject(new Error('aborted')));
      });
    });
    void store.startStream();
    await vi.advanceTimersByTimeAsync(0);
    expect(calls).toBe(1);
    expect(store.streaming).toBe(true); // 断线后仍处于重连循环
    await vi.advanceTimersByTimeAsync(999);
    expect(calls).toBe(1); // 1s 退避未到，不重连
    await vi.advanceTimersByTimeAsync(1);
    expect(calls).toBe(2); // 退避到期重连（cursor 续读）
    store.stopStream();
    await vi.advanceTimersByTimeAsync(60000);
    expect(calls).toBe(2); // 主动停止后不再重连
    expect(store.streaming).toBe(false);
  });

  it('trace_end frame stops the loop and refreshes detail; no more reconnects', async () => {
    const store = prepare('end');
    const handlers = hangSse();
    void store.startStream();
    await vi.advanceTimersByTimeAsync(0);
    handlers[0]('', JSON.stringify({ type: 'trace_end' }));
    await vi.advanceTimersByTimeAsync(60000);
    expect(vi.mocked(sseStream)).toHaveBeenCalledTimes(1);
    expect(store.streaming).toBe(false);
    expect(store.live).toBe(false);
    // 终帧后补一次元数据（integrity/outcome 可能已更新）
    expect(flowApi.getMessage).toHaveBeenCalledWith('end');
  });

  it('interrupted frame stops the loop without refreshing detail', async () => {
    const store = prepare('gone');
    const handlers = hangSse();
    void store.startStream();
    await vi.advanceTimersByTimeAsync(0);
    handlers[0]('', JSON.stringify({ type: 'interrupted' }));
    await vi.advanceTimersByTimeAsync(60000);
    expect(vi.mocked(sseStream)).toHaveBeenCalledTimes(1);
    expect(store.streaming).toBe(false);
    expect(flowApi.getMessage).not.toHaveBeenCalled();
  });

  it('401 stops reconnecting (same handling as the axios layer)', async () => {
    const store = prepare('auth');
    vi.mocked(sseStream).mockImplementation(async () => {
      throw new SseAuthError();
    });
    void store.startStream();
    await vi.advanceTimersByTimeAsync(60000);
    expect(vi.mocked(sseStream)).toHaveBeenCalledTimes(1);
    expect(store.streaming).toBe(false);
    expect(store.live).toBe(false);
  });

  it('visibility lifecycle: hidden stops SSE, visible refetches then reconnects', async () => {
    const store = prepare('vis');
    const handlers = hangSse();
    void store.startStream();
    await vi.advanceTimersByTimeAsync(0);
    expect(store.streaming).toBe(true);
    // 页面隐藏：停流并记住「原本在直播」
    store.onVisibilityChange(false);
    expect(store.streaming).toBe(false);
    expect(store.live).toBe(false);
    // 恢复可见：先 fetchEvents 补读，再重连
    store.onVisibilityChange(true);
    await vi.advanceTimersByTimeAsync(0);
    expect(flowApi.getEvents).toHaveBeenCalled();
    expect(store.streaming).toBe(true);
    expect(vi.mocked(sseStream)).toHaveBeenCalledTimes(2);
    expect(handlers).toHaveLength(2);
    // 未在直播时恢复可见：不补读不重连
    store.onVisibilityChange(false);
    store.resumeStreamOnVisible = false;
    store.onVisibilityChange(true);
    await vi.advanceTimersByTimeAsync(0);
    expect(store.streaming).toBe(false);
  });
});

// ============================================================
// M5（修复计划 §6.6，R6/R8）：bundle 刷新、keyset 列表、事件软上限。
// ============================================================
describe('flow store M5 contracts', () => {
  it('refreshTraceBundle refreshes detail, IO and entities with generation guard', async () => {
    const store = useFlowStore();
    const d1 = detail({ trace_id: 'rt-1', ended_utc: '' });
    vi.mocked(flowApi.getMessage).mockResolvedValue(d1);
    vi.mocked(flowApi.getMessageIo).mockResolvedValue(
      { ...EMPTY_IO, output: { lines: ['第一段'], count: 1 } });
    vi.mocked(flowApi.getEvents).mockResolvedValue([]);
    await store.openTrace('rt-1');
    // 轨迹结束后（R6）：IO/详情/对象一次刷新——不再停留打开时快照
    vi.mocked(flowApi.getMessage).mockResolvedValue(
      detail({ trace_id: 'rt-1', ended_utc: '2026-10-03T01:00:00' }));
    vi.mocked(flowApi.getMessageIo).mockResolvedValue(
      { ...EMPTY_IO, output: { lines: ['第一段', '第二段'], count: 2 } });
    vi.mocked(flowApi.getTraceEntities).mockResolvedValue([
      { entity_type: 'memory_candidate', entity_id: 'c1', from_state: 'NEW',
        to_state: 'OBSERVING', ts_utc: '2026-10-03T01:00:00' },
    ]);
    await store.refreshTraceBundle();
    expect(store.io?.output.lines).toEqual(['第一段', '第二段']);
    expect(store.detail?.ended_utc).toBe('2026-10-03T01:00:00');
    expect(store.traceEntities).toHaveLength(1);
  });

  it('quick switch invalidates late bundle responses', async () => {
    const store = useFlowStore();
    vi.mocked(flowApi.getMessage)
      .mockResolvedValueOnce(detail({ trace_id: 'a' }))
      .mockResolvedValueOnce(detail({ trace_id: 'b' }));
    // A 的 IO 慢返回：代际已切换到 B，旧响应不得覆盖
    let releaseA!: (io: FlowMessageIo) => void;
    vi.mocked(flowApi.getMessageIo).mockImplementationOnce(
      () => new Promise((resolve) => { releaseA = resolve; }));
    await store.openTrace('a');
    await store.openTrace('b');
    releaseA({ ...EMPTY_IO, output: { lines: ['A 的回复'], count: 1 } });
    await vi.waitFor(() => {
      expect(store.detail?.trace_id).toBe('b');
      expect(store.io).toEqual(EMPTY_IO);
    });
  });

  it('loadMoreMessages appends via keyset cursor without overlap', async () => {
    const store = useFlowStore();
    const page1 = { total: 3, next_cursor: 'c1', items: [
      { trace_id: 't1', root_kind: 'qq_chat', platform: 'qq', scope: '',
        source_message_key: '', started_utc: '2026-10-03T00:00:00', ended_utc: '',
        outcome: '', status: 'closed', complete: true, loss: false },
      { trace_id: 't2', root_kind: 'qq_chat', platform: 'qq', scope: '',
        source_message_key: '', started_utc: '2026-10-03T00:00:01', ended_utc: '',
        outcome: '', status: 'closed', complete: true, loss: false },
    ] as FlowMessageSummary[] };
    const page2 = { total: 3, next_cursor: null, items: [
      { trace_id: 't3', root_kind: 'qq_chat', platform: 'qq', scope: '',
        source_message_key: '', started_utc: '2026-10-03T00:00:02', ended_utc: '',
        outcome: '', status: 'closed', complete: true, loss: false },
    ] as FlowMessageSummary[] };
    vi.mocked(flowApi.listMessages)
      .mockResolvedValueOnce(page1)
      .mockResolvedValueOnce(page2);
    await store.loadMessages();
    expect(store.messages).toHaveLength(2);
    expect(store.messagesCursor).toBe('c1');
    await store.loadMoreMessages();
    // 合并后保持 (started_utc, trace_id) 降序（与列表展示一致，验收 M2）
    expect(store.messages.map((m) => m.trace_id)).toEqual(['t3', 't2', 't1']);
    expect(store.messagesCursor).toBe('');
  });

  it('fetchEvents truncation compares row_id with high_watermark (H4 units)', async () => {
    const store = useFlowStore();
    // H4 场景：seq 水位(123)与全局 row_id 单位不同——只看 high_watermark
    vi.mocked(flowApi.getMessage).mockResolvedValue(detail({
      trace_id: 'rt-big', high_watermark: 3, persisted_events: 123,
    }));
    vi.mocked(flowApi.getEvents)
      .mockResolvedValueOnce([ev({ event_id: 'e1', row_id: 1 })])
      .mockResolvedValueOnce([ev({ event_id: 'e2', row_id: 2 }),
                              ev({ event_id: 'e3', row_id: 3 })]);
    await store.openTrace('rt-big');
    expect(store.eventsTruncated).toBe(true);
    await store.loadMoreEvents();
    expect(store.eventsTruncated).toBe(false);
    expect(store.orderedEvents).toHaveLength(3);
  });

  it('large global row_id offset does not hide remaining events (H4 probe)', async () => {
    const store = useFlowStore();
    // 旧实现比较 maxRowId(200000) < persisted_events(100001) → false，
    // 继续按钮消失；新实现只比 high_watermark(200001)
    vi.mocked(flowApi.getMessage).mockResolvedValue(detail({
      trace_id: 'rt-offset', high_watermark: 200001, persisted_events: 100001,
    }));
    vi.mocked(flowApi.getEvents).mockImplementation(async (_id, after) =>
      Array.from({ length: 1000 }, (_, i) =>
        ev({ event_id: `e${Number(after) + i + 1}`,
             row_id: Number(after) + i + 1 })));
    await store.openTrace('rt-offset');
    // 100 页后已载 100000 条、maxRow=100000 < 200001 → 仍 partial
    expect(store.orderedEvents.length).toBe(100000);
    expect(store.eventsTruncated).toBe(true);
    await store.loadMoreEvents();
    expect(store.eventsTruncated).toBe(true); // 还有余量，按钮不消失
    // 首读需跨 100 页加载 100000 个事件，验证分页软上限与水位单位。
    // 共享 CI runner 曾用时 5.17s；保留规模与断言，只给本功能用例留余量。
    // 布局性能预算由 perf-10k-layout.spec.ts 单独验证。
  }, 15_000);

  it('loadSpec uses digest-exact cache for digest traces and version fallback for legacy', async () => {
    const store = useFlowStore();
    vi.mocked(flowApi.getEvents).mockResolvedValue([]);
    vi.mocked(flowApi.getMessageIo).mockResolvedValue(EMPTY_IO);
    vi.mocked(flowApi.getTraceEntities).mockResolvedValue([]);
    const digestSpec = makeSpec('2026.10.04');
    vi.mocked(flowApi.getSpecByDigest).mockResolvedValue(digestSpec);
    vi.mocked(flowApi.getMessage).mockResolvedValue(detail({
      trace_id: 'rt-digest', topology_version: '2026.10.04',
      spec_digest: 'a'.repeat(64),
    }));
    await store.openTrace('rt-digest');
    await store.loadSpec();
    expect(flowApi.getSpecByDigest).toHaveBeenCalledWith(
      '2026.10.04', 'a'.repeat(64));
    expect(flowApi.getSpec).not.toHaveBeenCalled();
    expect(store.spec?.topology_version).toBe('2026.10.04');
    // legacy：无 digest → 按版本回退
    vi.mocked(flowApi.getSpec).mockResolvedValue(makeSpec('old-v'));
    vi.mocked(flowApi.getMessage).mockResolvedValue(detail({
      trace_id: 'rt-legacy', topology_version: 'old-v', spec_digest: '',
    }));
    await store.openTrace('rt-legacy');
    await store.loadSpec();
    expect(flowApi.getSpec).toHaveBeenCalledWith('old-v');
    expect(store.spec?.topology_version).toBe('old-v');
  });

  it('poll keeps accumulated history pages (M2 list merge)', async () => {
    const store = useFlowStore();
    const tsOf: Record<string, string> = {
      t1: '2026-10-03T00:00:01', t2: '2026-10-03T00:00:02',
      t3: '2026-10-03T00:00:03',
    };
    const rows = (ids: string[], total: number, cursor: string | null) => ({
      total,
      next_cursor: cursor,
      items: ids.map((id) => ({
        trace_id: id, root_kind: 'qq_chat', platform: 'qq', scope: '',
        source_message_key: '', started_utc: tsOf[id],
        ended_utc: '', outcome: '', status: 'closed', complete: true,
        loss: false,
      })) as FlowMessageSummary[],
    });
    vi.mocked(flowApi.listMessages)
      .mockResolvedValueOnce(rows(['t2', 't1'], 3, 'c1'))
      .mockResolvedValueOnce(rows(['t3'], 3, null))          // loadMore
      .mockResolvedValueOnce(rows(['t2', 't1'], 3, 'c1'));   // 轮询首屏
    await store.loadMessages();
    await store.loadMoreMessages();
    expect(store.messages.map((m) => m.trace_id)).toEqual(['t3', 't2', 't1']);
    await store.loadMessages(); // 5s 轮询：只刷新首屏
    // 历史页 t3 不被首屏替换掉（旧实现直接替换 → t3 消失）
    expect(store.messages.map((m) => m.trace_id)).toEqual(['t3', 't2', 't1']);
  });

  it('loadMore discards the page when filters changed mid-flight (M2)', async () => {
    const store = useFlowStore();
    vi.mocked(flowApi.listMessages)
      .mockResolvedValueOnce({ total: 2, next_cursor: 'c1', items: [
        { trace_id: 'q1', root_kind: 'qq_chat', platform: 'qq', scope: '',
          source_message_key: '', started_utc: '2026-10-03T00:00:00',
          ended_utc: '', outcome: '', status: 'closed', complete: true,
          loss: false },
      ] as FlowMessageSummary[] })
      .mockResolvedValueOnce({ total: 1, next_cursor: null, items: [
        { trace_id: 'w1', root_kind: 'webchat', platform: 'webchat', scope: '',
          source_message_key: '', started_utc: '2026-10-03T00:00:00',
          ended_utc: '', outcome: '', status: 'closed', complete: true,
          loss: false },
      ] as FlowMessageSummary[] });
    await store.loadMessages();
    const pending = store.loadMoreMessages();
    // 请求在途时切换过滤（QQ → WebChat）：旧过滤的游标页必须整包丢弃，
    // 不得混入新过滤的列表（下一次 loadMessages 会按新键重置）
    store.platformFilter = 'webchat';
    await pending;
    expect(store.messages.map((m) => m.trace_id)).toEqual(['q1']);
  });

  it('stale bundle response cannot overwrite terminal detail (M2 seq)', async () => {
    const store = useFlowStore();
    store.detail = detail({ trace_id: 'rt-seq' }); // 先有当前轨迹
    let releaseFirst!: (d: FlowMessageDetail) => void;
    const first = new Promise<FlowMessageDetail>((r) => { releaseFirst = r; });
    vi.mocked(flowApi.getMessage)
      .mockImplementationOnce(() => first)
      .mockResolvedValue(detail({
        trace_id: 'rt-seq', ended_utc: '2026-10-03T01:00:00',
        event_count: 9, high_watermark: 9,
      }));
    vi.mocked(flowApi.getEvents).mockResolvedValue([]);
    vi.mocked(flowApi.getMessageIo).mockResolvedValue(EMPTY_IO);
    vi.mocked(flowApi.getTraceEntities).mockResolvedValue([]);
    const p1 = store.refreshTraceBundle();       // 挂起（seq=1）
    const p2 = store.refreshTraceBundle();       // 立即返回终态（seq=2）
    await p2;
    expect(store.detail?.ended_utc).toBe('2026-10-03T01:00:00');
    releaseFirst(detail({ trace_id: 'rt-seq', ended_utc: '' })); // 旧响应迟到
    await p1;
    // 旧响应不得把 ended 清空（M2 反例：ended 被清空、水位降回）
    expect(store.detail?.ended_utc).toBe('2026-10-03T01:00:00');
    expect(store.detail?.high_watermark).toBe(9);
  });

  it('manual refresh refetches events after watermark advanced (H5)', async () => {
    const store = useFlowStore();
    vi.mocked(flowApi.getMessage).mockResolvedValue(
      detail({ trace_id: 'rt-h5', event_count: 2, high_watermark: 2 }));
    vi.mocked(flowApi.getEvents).mockResolvedValue([]);
    vi.mocked(flowApi.getMessageIo).mockResolvedValue(EMPTY_IO);
    vi.mocked(flowApi.getTraceEntities).mockResolvedValue([]);
    await store.openTrace('rt-h5');
    expect(store.orderedEvents).toHaveLength(0);
    vi.mocked(flowApi.getMessage).mockResolvedValue(
      detail({ trace_id: 'rt-h5', event_count: 2, high_watermark: 2 }));
    vi.mocked(flowApi.getEvents).mockResolvedValue([
      ev({ event_id: 'e1', row_id: 1 }),
      ev({ event_id: 'e2', row_id: 2 }),
    ]);
    vi.mocked(flowApi.getEvents).mockClear();
    await store.refreshTraceBundle();
    // 手动刷新必须补读事件（旧实现 eventCalls=0）
    expect(flowApi.getEvents).toHaveBeenCalled();
    expect(store.orderedEvents).toHaveLength(2);
  });

  it('finality confirmation triggers final catch-up at the new watermark (A1)', async () => {
    const store = useFlowStore();
    // detail 1: pending（producer 未落账、水位 1）；detail 2: 终态（水位 2）
    vi.mocked(flowApi.getMessage)
      .mockResolvedValueOnce(detail({
        trace_id: 'rt-fin', producer_ended: false, integrity: '',
        event_count: 1, high_watermark: 1,
      }))
      .mockResolvedValue(detail({
        trace_id: 'rt-fin', ended_utc: '2026-10-05T01:00:00',
        producer_ended: true, integrity: 'complete',
        event_count: 2, high_watermark: 2,
      }));
    vi.mocked(flowApi.getEvents)
      .mockResolvedValueOnce([ev({ event_id: 'e1', row_id: 1 })])
      .mockResolvedValueOnce([ev({ event_id: 'e2', row_id: 2 })]);
    vi.mocked(flowApi.getMessageIo)
      .mockResolvedValueOnce({ ...EMPTY_IO, output: { lines: ['part1'], count: 1 } })
      .mockResolvedValue({ ...EMPTY_IO, output: { lines: ['part1', 'part2'], count: 2 } });
    vi.mocked(flowApi.getTraceEntities).mockResolvedValue([]);
    await store.openTrace('rt-fin');
    expect(store.orderedEvents).toHaveLength(1);
    const p = store.refreshTraceBundle({ awaitFinality: true });
    // finality 循环内的 1.5s 退避用假计时器推进
    await vi.advanceTimersByTimeAsync(1700);
    await p;
    // 确认后按新水位补齐：loaded=2、IO 已更新为最终片段（A1 反例原 loaded=1/ioCalls=1）
    expect(store.orderedEvents).toHaveLength(2);
    expect(store.io?.output.lines).toEqual(['part1', 'part2']);
    // openTrace 首拉 + round1 + finality 确认后的最终补读 = 3 次
    expect(flowApi.getEvents).toHaveBeenCalledTimes(3);
  });

  it('detail transient failure does not cancel independent IO/entities refresh (A1)', async () => {
    const store = useFlowStore();
    store.detail = detail({ trace_id: 'rt-tr' });
    vi.mocked(flowApi.getMessage)
      .mockRejectedValueOnce(new Error('transient'))
      .mockResolvedValue(detail({ trace_id: 'rt-tr', producer_ended: true, integrity: 'complete' }));
    vi.mocked(flowApi.getEvents).mockResolvedValue([]);
    vi.mocked(flowApi.getMessageIo).mockResolvedValue(
      { ...EMPTY_IO, output: { lines: ['seg'], count: 1 } });
    vi.mocked(flowApi.getTraceEntities).mockResolvedValue([
      { entity_type: 'x', entity_id: '1', from_state: '', to_state: 'S', ts_utc: '' },
    ]);
    const p = store.refreshTraceBundle();
    await vi.advanceTimersByTimeAsync(600); // detail 瞬时重试退避
    await p;
    // detail 失败也照常刷新独立来源
    expect(flowApi.getMessageIo).toHaveBeenCalled();
    expect(flowApi.getTraceEntities).toHaveBeenCalled();
    expect(flowApi.getEvents).toHaveBeenCalled();
    // 有界重试恢复 detail
    expect(store.detail?.producer_ended).toBe(true);
  });

  it('hidden page invalidates in-flight bundles via session (A2)', async () => {
    const store = useFlowStore();
    store.detail = detail({ trace_id: 'rt-s2' });
    let releaseFirst!: (d: FlowMessageDetail) => void;
    const first = new Promise<FlowMessageDetail>((r) => { releaseFirst = r; });
    vi.mocked(flowApi.getMessage).mockImplementationOnce(() => first);
    vi.mocked(flowApi.getEvents).mockClear();
    vi.mocked(flowApi.getEvents).mockResolvedValue([]);
    vi.mocked(flowApi.getMessageIo).mockResolvedValue(EMPTY_IO);
    vi.mocked(flowApi.getTraceEntities).mockResolvedValue([]);
    const p1 = store.refreshTraceBundle(); // 挂起（session=S）
    const sessionAtIssue = store.streamSession;
    store.stopStream(); // 页面隐藏：session 递增
    expect(store.streamSession).toBeGreaterThan(sessionAtIssue || -1);
    releaseFirst(detail({ trace_id: 'rt-s2', ended_utc: '' }));
    await p1;
    // 旧 session 的回包不得落地，也不得触发事件请求
    expect(flowApi.getEvents).not.toHaveBeenCalled();
    expect(store.detail?.ended_utc).toBe('');
  });

  it('loadMoreEvents stays inside the frozen snapshot watermark (A2)', async () => {
    const store = useFlowStore();
    store.detail = detail({ trace_id: 'rt-fz', high_watermark: 1500 });
    store.events = Array.from({ length: 1000 }, (_, i) =>
      ev({ event_id: `e${i + 1}`, row_id: i + 1 }));
    store.eventsTruncated = true;
    vi.mocked(flowApi.getEvents).mockResolvedValue(
      Array.from({ length: 500 }, (_, i) =>
        ev({ event_id: `e${i + 1001}`, row_id: i + 1001 })));
    await store.loadMoreEvents();
    // 继续页必须携带同一冻结水位 until=1500（旧实现不传 → 读到快照外）
    expect(flowApi.getEvents).toHaveBeenCalledWith('rt-fz', 1000, 1000, 1500);
    expect(store.orderedEvents).toHaveLength(1500);
    expect(store.eventsTruncated).toBe(false);
  });

  it('events in flight when page hides do not merge (B1)', async () => {
    const store = useFlowStore();
    store.detail = detail({ trace_id: 'rt-b1', high_watermark: 2 });
    let releaseEvents!: (items: FlowEvent[]) => void;
    vi.mocked(flowApi.getMessage).mockResolvedValue(
      detail({ trace_id: 'rt-b1', high_watermark: 2 }));
    vi.mocked(flowApi.getEvents).mockImplementationOnce(
      () => new Promise((r) => { releaseEvents = r; }));
    vi.mocked(flowApi.getMessageIo).mockResolvedValue(EMPTY_IO);
    vi.mocked(flowApi.getTraceEntities).mockResolvedValue([]);
    const sessionBefore = store.streamSession;
    const p = store.refreshTraceBundle(); // detail 完成，events 在途
    await vi.advanceTimersByTimeAsync(10);
    store.stopStream(); // 隐藏页面：session 递增 → bundle 失效
    expect(store.streamSession).toBeGreaterThan(sessionBefore);
    releaseEvents([ev({ event_id: 'e2', row_id: 2 })]);
    await p;
    // 旧 session 的 events 回包不得合并（复验 B1 探针：lateEvents=['e2']）
    expect(store.orderedEvents).toHaveLength(0);
  });

  it('new-gap reopen after exhaustion (B2)', async () => {
    const store = useFlowStore();
    const tsOf: Record<string, string> = { old: '2026-10-05T00:00:00' };
    const rows = (ids: string[], total: number, cursor: string | null) => ({
      total,
      next_cursor: cursor,
      items: ids.map((id, i) => ({
        trace_id: id, root_kind: 'qq_chat', platform: 'qq', scope: '',
        source_message_key: '',
        started_utc: tsOf[id] ?? `2026-10-05T01:${String(i % 60).padStart(2, '0')}:${String(i % 60).padStart(2, '0')}.00`,
        ended_utc: '', outcome: '', status: 'closed', complete: true,
        loss: false,
      })) as FlowMessageSummary[],
    });
    // 初始 1 条已取尽
    vi.mocked(flowApi.listMessages)
      .mockResolvedValueOnce(rows(['old'], 1, null))
      // 隐藏期间新增 101 条 → 新首屏（100 条全新 + cursor）
      .mockResolvedValueOnce(rows(
        Array.from({ length: 100 }, (_, i) => `new${String(i).padStart(3, '0')}`),
        102, 'c2'))
      // 从新游标继续：命中缺口记录
      .mockResolvedValueOnce(rows(['old'], 102, null));
    await store.loadMessages();
    expect(store.listExhausted).toBe(true);
    await store.loadMessages(); // 恢复后首屏：新缺口重开游标
    expect(store.listExhausted).toBe(false);
    expect(store.messagesCursor).toBe('c2');
    await store.loadMoreMessages();
    const ids = store.messages.map((m) => m.trace_id);
    expect(ids).toContain('old');
    expect(store.listExhausted).toBe(true);
  });

  it('scheduleIoRefresh throttles burst receipt facts into one refresh', async () => {
    const store = useFlowStore();
    vi.mocked(flowApi.getMessage).mockResolvedValue(detail({ trace_id: 'rt-io' }));
    vi.mocked(flowApi.getMessageIo).mockResolvedValue(EMPTY_IO);
    vi.mocked(flowApi.getEvents).mockResolvedValue([]);
    await store.openTrace('rt-io');
    vi.mocked(flowApi.getMessageIo).mockClear();
    store.scheduleIoRefresh();
    store.scheduleIoRefresh();
    store.scheduleIoRefresh();
    await vi.advanceTimersByTimeAsync(2100);
    // 节流窗口内三次触发合并为一次 IO 查询
    expect(flowApi.getMessageIo).toHaveBeenCalledTimes(1);
  });
});
