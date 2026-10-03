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
    expect(flowApi.getEvents).toHaveBeenNthCalledWith(1, 'big', 0, 1000);
    expect(flowApi.getEvents).toHaveBeenNthCalledWith(2, 'big', 1000, 1000);
    expect(flowApi.getEvents).toHaveBeenNthCalledWith(3, 'big', 2000, 1000);
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
