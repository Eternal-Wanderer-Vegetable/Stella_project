import type { FlowEvent, FlowNodeSpec } from '@/api/flow';
import type { SpecLike } from '@/views/data/flowLayout';
import type { FlowNodeState } from '@/stores/flowReducer';
import {
  layoutExecuted,
  layoutLayered,
  NODE_W,
} from '@/views/data/flowLayout';
import { describe, expect, it } from 'vitest';

// 实际路径布局合同（用户验收 #2）：显示实际路径时收束成完整的一条——
// 未执行节点不占位，已执行子图用同一套分层算法排成连通的左→右流。

function node(id: string, lane: string): FlowNodeSpec {
  return { id, label: `L:${id}`, lane, kind: 'task' };
}

function spec(partial: Partial<SpecLike>): SpecLike {
  return {
    lanes: partial.lanes ?? [],
    nodes: partial.nodes ?? [],
    edges: partial.edges ?? [],
    entry_roots: partial.entry_roots ?? {},
  };
}

function evFact(
  eventId: string,
  nodeId: string,
  kind: FlowEvent['kind'],
  status: string,
  over: Partial<FlowEvent> = {},
): FlowEvent {
  return {
    row_id: 0,
    event_id: eventId,
    span_id: '',
    parent_span_id: '',
    node_id: nodeId,
    instance_key: '',
    seq: 0,
    kind,
    status,
    reason_code: '',
    ts_utc: '2026-10-02T00:00:00',
    duration_ms: null,
    summary: '',
    metrics: {},
    ...over,
  };
}

function exec(nodeId: string, status = 'succeeded') {
  // O05 合同：traversed 由真实 transition 事实判定，exec 节点默认带
  // start + finish(同状态)事件——「端点出现过」不再足以标 traversed。
  return {
    nodeId,
    label: nodeId,
    status,
    businessOutcome: '',
    instances: 1,
    firstSeq: 0,
    lastTs: '',
    durationMs: null,
    metrics: [],
    events: [
      evFact(`${nodeId}:s`, nodeId, 'start', 'running'),
      evFact(`${nodeId}:f`, nodeId, 'finish', status),
    ] as FlowEvent[],
  };
}

const LANES: Array<[string, string]> = [
  ['ingress', '入口'],
  ['generate', '生成'],
  ['delivery', '交付'],
];

describe('layoutExecuted', () => {
  const fullSpec = spec({
    lanes: LANES,
    nodes: [
      node('entry', 'ingress'),
      node('skip', 'ingress'),
      node('a', 'generate'),
      node('b', 'delivery'),
    ],
    edges: [
      { src: 'entry', dst: 'skip', kind: 'order', label: '' },
      { src: 'skip', dst: 'a', kind: 'order', label: '' },
      { src: 'entry', dst: 'a', kind: 'condition', label: '未走到' },
      { src: 'a', dst: 'b', kind: 'order', label: '' },
    ],
  });

  // R3 合同：边激活只看显式 transition 事实；这里给出 entry→a→b 的
  // 真实跳转事实，root 已真实结束。
  function transitionFact(from: string, to: string): FlowEvent {
    return evFact(`t-${from}-${to}`, from, 'decision', 'succeeded', {
      fact_kind: 'transition',
      metrics: { transition_v: 1, from_node: from, to_node: to },
    });
  }

  function layoutArgs(executed: Map<string, FlowNodeState>) {
    return {
      spec: fullSpec,
      executed,
      labelOf: (id: string) => id,
      laneOf: (id: string) =>
        ({ entry: 'ingress', skip: 'ingress', a: 'generate', b: 'delivery' })[id]!,
      transitions: [transitionFact('entry', 'a'), transitionFact('a', 'b')],
      rootEnded: true,
    };
  }

  function runExecuted() {
    return layoutExecuted(
      layoutArgs(new Map(
        [exec('entry'), exec('a'), exec('b')].map((n) => [n.nodeId, n]),
      )),
    );
  }

  it('contains ONLY executed nodes (unvisited never occupy positions)', () => {
    const out = runExecuted();
    const content = out.nodes.filter((n) => n.anchor === undefined);
    expect(content.map((n) => n.nodeId).sort()).toEqual(['a', 'b', 'entry']);
  });

  it('collapses into a contiguous chain (no gap left by skipped node)', () => {
    const out = runExecuted();
    const byId = new Map(out.nodes.map((n) => [n.nodeId, n]));
    const entry = byId.get('entry')!;
    const a = byId.get('a')!;
    const b = byId.get('b')!;
    // 相邻执行节点紧挨：列距 = 节点宽 + 固定列距，没有空洞
    expect(a.x - entry.x).toBe(NODE_W + 56);
    expect(b.x - a.x).toBe(NODE_W + 56);
    expect(entry.x).toBeLessThan(a.x);
    expect(a.x).toBeLessThan(b.x);
  });

  it('is strictly narrower than the full layout for the same spec', () => {
    const full = layoutLayered(
      layoutArgs(new Map(
        [exec('entry'), exec('a'), exec('b')].map((n) => [n.nodeId, n]),
      )),
    );
    expect(runExecuted().width).toBeLessThan(full.width);
  });

  it('drops edges that leave unexecuted nodes; retained edges are traversed', () => {
    const out = runExecuted();
    expect(
      out.edges.some((e) => e.from.nodeId === 'skip' || e.to.nodeId === 'skip'),
    ).toBe(false);
    // entry→a 的 condition 两端都执行过：保留且 traversed
    const cond = out.edges.find((e) => e.kind === 'condition');
    expect(cond).toBeDefined();
    expect(cond!.traversed).toBe(true);
  });

  it('anchors wire the subgraph source (entry) and sink (b)', () => {
    const out = runExecuted();
    const startEdges = out.edges.filter((e) => e.from.anchor === 'start');
    const endEdges = out.edges.filter((e) => e.to.anchor === 'end');
    expect(startEdges.map((e) => e.to.nodeId)).toEqual(['entry']);
    expect(endEdges.map((e) => e.from.nodeId)).toEqual(['b']);
  });

  it('empty execution yields an empty canvas (anchors need components)', () => {
    const out = layoutExecuted({
      spec: fullSpec,
      executed: new Map(),
      labelOf: (id) => id,
      laneOf: () => 'ingress',
    });
    // 没有任何已执行内容时连锚点也不渲染——没有流程就没有起止
    expect(out.nodes).toHaveLength(0);
  });
});

// ============================================================
// R3（修复计划 §6.4）：边激活只看显式 transition 事实。端点出现过、
// 同 instance_key、span 父子都不再激活边；transition 携带 attempt，
// 跨 attempt 不串边。
// ============================================================
describe('layoutExecuted: edge traversed needs explicit transition facts (R3)', () => {
  const transitionSpec = spec({
    lanes: LANES,
    nodes: [node('a', 'ingress'), node('b', 'delivery')],
    edges: [{ src: 'a', dst: 'b', kind: 'condition', label: '分支' }],
  });

  function execRaw(nodeId: string, events: FlowEvent[]): FlowNodeState {
    return {
      nodeId,
      label: nodeId,
      status: 'running',
      businessOutcome: '',
      instances: 1,
      firstSeq: 0,
      lastTs: '',
      durationMs: null,
      metrics: [],
      events,
      running_count: 0,
      succeeded_count: 0,
      failed_count: 0,
      latest: null,
    };
  }

  function transitionFact(over: Partial<FlowEvent> = {}): FlowEvent {
    return evFact(`t-${Math.random()}`, 'a', 'decision', 'succeeded', {
      fact_kind: 'transition',
      metrics: { transition_v: 1, from_node: 'a', to_node: 'b' },
      ...over,
    });
  }

  function layoutWith(
    executed: Map<string, FlowNodeState>,
    transitions: FlowEvent[] = [],
    rootEnded = false,
  ) {
    return layoutExecuted({
      spec: transitionSpec,
      executed,
      labelOf: (id) => id,
      laneOf: (id) => (id === 'a' ? 'ingress' : 'delivery'),
      transitions,
      rootEnded,
    });
  }

  function condEdge(out: ReturnType<typeof layoutWith>) {
    return out.edges.find((e) => e.kind === 'condition')!;
  }

  it('full chain WITHOUT transition fact is NOT traversed (no endpoint inference)', () => {
    const out = layoutWith(new Map([
      ['a', execRaw('a', [
        evFact('a:s', 'a', 'start', 'running', { row_id: 1, span_id: 's1' }),
        evFact('a:f', 'a', 'finish', 'succeeded', { row_id: 2, span_id: 's1' }),
      ])],
      ['b', execRaw('b', [
        evFact('b:s', 'b', 'start', 'running', { row_id: 3, span_id: 's2' }),
        evFact('b:f', 'b', 'finish', 'succeeded', { row_id: 4, span_id: 's2' }),
      ])],
    ]));
    expect(condEdge(out).traversed).toBe(false);
  });

  it('explicit transition fact (matching endpoints, same attempt) IS traversed', () => {
    const out = layoutWith(
      new Map([
        ['a', execRaw('a', [
          evFact('a:s', 'a', 'start', 'running', { row_id: 1, span_id: 's1' }),
          evFact('a:f', 'a', 'finish', 'succeeded', { row_id: 2, span_id: 's1' }),
        ])],
        ['b', execRaw('b', [
          evFact('b:s', 'b', 'start', 'running', { row_id: 3, span_id: 's2' }),
          evFact('b:f', 'b', 'finish', 'succeeded', { row_id: 4, span_id: 's2' }),
        ])],
      ]),
      [transitionFact({ row_id: 2, span_id: 's1' })],
      true,
    );
    expect(condEdge(out).traversed).toBe(true);
    expect(condEdge(out).active).toBe(true);
  });

  it('arrival without transition (start-only / checkpoint-only) is NOT traversed', () => {
    const a = execRaw('a', [
      evFact('a:s', 'a', 'start', 'running', { row_id: 1, span_id: 's1' }),
      evFact('a:f', 'a', 'finish', 'succeeded', { row_id: 2, span_id: 's1' }),
    ]);
    const startOnly = layoutWith(new Map([
      ['a', a],
      ['b', execRaw('b', [
        evFact('b:s', 'b', 'start', 'running', { row_id: 3 }),
      ])],
    ]), [transitionFact({ row_id: 2, span_id: 's1' })]);
    // dst 无到达事实：即使有 transition 也不激活（attempt/端点不匹配）
    expect(condEdge(startOnly).traversed).toBe(false);
    const checkpointOnly = layoutWith(new Map([
      ['a', a],
      ['b', execRaw('b', [
        evFact('b:c', 'b', 'checkpoint', 'succeeded', { row_id: 3 }),
      ])],
    ]));
    expect(condEdge(checkpointOnly).traversed).toBe(false);
  });

  it('transition on another attempt does not cross-activate', () => {
    const out = layoutWith(
      new Map([
        ['a', execRaw('a', [
          evFact('a:s0', 'a', 'start', 'running', { row_id: 1, span_id: 's-a0', attempt: 0 }),
        ])],
        ['b', execRaw('b', [
          evFact('b:f1', 'b', 'finish', 'succeeded', { row_id: 3, span_id: 's-b1', attempt: 1 }),
        ])],
      ]),
      [transitionFact({
        row_id: 2, span_id: 's-a1', attempt: 1,
        metrics: { transition_v: 1, from_node: 'a', to_node: 'b', attempt: 1 },
      })],
    );
    expect(condEdge(out).traversed).toBe(false);
  });

  it('end anchor requires a real root finish (rootEnded), not static sink arrival', () => {
    const executed = new Map([
      ['a', execRaw('a', [
        evFact('a:s', 'a', 'start', 'running', { row_id: 1 }),
        evFact('a:f', 'a', 'finish', 'succeeded', { row_id: 2 }),
      ])],
      ['b', execRaw('b', [
        evFact('b:s', 'b', 'start', 'running', { row_id: 3 }),
        evFact('b:f', 'b', 'finish', 'succeeded', { row_id: 4 }),
      ])],
    ]);
    const running = layoutWith(executed, [], false);
    expect(running.edges.filter((e) => e.to.anchor === 'end')
      .every((e) => e.traversed === false)).toBe(true);
    const ended = layoutWith(executed, [], true);
    expect(ended.edges.filter((e) => e.to.anchor === 'end')
      .every((e) => e.traversed === true)).toBe(true);
  });

    it('unknown nodes (in events, missing from spec) stay visible in both views', () => {
    const executed = new Map<string, FlowNodeState>([
      ['a', exec('a')],
      ['hook.custom:ext', execRaw('hook.custom:ext', [
        evFact('x:s', 'hook.custom:ext', 'start', 'running', { row_id: 3 }),
        evFact('x:f', 'hook.custom:ext', 'finish', 'succeeded', { row_id: 4 }),
      ])],
    ]);
    const executedView = layoutExecuted({
      spec: transitionSpec,
      executed,
      labelOf: (id) => id,
      laneOf: () => 'other',
    });
    const ids = executedView.nodes.filter((n) => n.anchor === undefined).map((n) => n.nodeId);
    expect(ids).toContain('hook.custom:ext');
    expect(executedView.nodes.find((n) => n.nodeId === 'hook.custom:ext')?.spec?.kind)
      .toBe('unknown');
    const fullView = layoutLayered({
      spec: transitionSpec,
      executed,
      labelOf: (id) => id,
      laneOf: () => 'other',
    });
    expect(fullView.nodes.map((n) => n.nodeId)).toContain('hook.custom:ext');
  });
});

// ============================================================
// M0/M3（修复计划 R3 探针固化）：兄弟 span 无 transition 事实不得激活边。
// 旧实现退化为端点时序推断（A start + B finish → true），是误报来源；
// 新合同：只有显式 transition 事实（fact_kind='transition'，携带 edge_id、
// attempt 与端点 span/occurrence）才激活，legacy 事件一律不虚构路径。
// ============================================================
describe('edgeTraversed transition facts (R3)', () => {
  function siblingExec(id: string, events: FlowEvent[]): FlowNodeState {
    return {
      nodeId: id, label: id, status: 'succeeded', businessOutcome: '',
      instances: 1, firstSeq: 0, lastTs: '', durationMs: null, metrics: [],
      events, running_count: 0, succeeded_count: 1, failed_count: 0,
      latest: null,
    };
  }

  function transitionEvent(over: Partial<FlowEvent>): FlowEvent {
    return evFact(`t-${Math.random()}`, 'x', 'decision', 'succeeded', {
      fact_kind: 'transition',
      metrics: { transition_v: 1, edge_id: 'a->b:order', from_node: 'a', to_node: 'b' },
      ...over,
    });
  }

  it('sibling spans without transition facts do NOT activate the edge', async () => {
    const { edgeTraversed } = await import('@/views/data/flowLayout');
    const a = siblingExec('a', [
      evFact('a:s', 'a', 'start', 'running', { row_id: 1, span_id: 's-a' }),
    ]);
    const b = siblingExec('b', [
      evFact('b:f', 'b', 'finish', 'succeeded', { row_id: 2, span_id: 's-b' }),
    ]);
    // 无任何 transition 事实：不证明 A→B（旧实现返回 true）
    expect(edgeTraversed(a, b, [])).toBe(false);
  });

  it('explicit transition fact activates the edge', async () => {
    const { edgeTraversed } = await import('@/views/data/flowLayout');
    const a = siblingExec('a', [
      evFact('a:s', 'a', 'start', 'running', { row_id: 1, span_id: 's-a' }),
    ]);
    const b = siblingExec('b', [
      evFact('b:f', 'b', 'finish', 'succeeded', { row_id: 3, span_id: 's-a' }),
    ]);
    const t = transitionEvent({ row_id: 2, span_id: 's-a' });
    expect(edgeTraversed(a, b, [t])).toBe(true);
  });

  it('transition on another attempt does not cross-activate', async () => {
    const { edgeTraversed } = await import('@/views/data/flowLayout');
    const a0 = siblingExec('a', [
      evFact('a:s0', 'a', 'start', 'running', { row_id: 1, span_id: 's-a0', attempt: 0 }),
    ]);
    const b1 = siblingExec('b', [
      evFact('b:f1', 'b', 'finish', 'succeeded', { row_id: 3, span_id: 's-b1', attempt: 1 }),
    ]);
    const tAttempt1 = transitionEvent({
      row_id: 2, span_id: 's-a1', attempt: 1,
      metrics: { transition_v: 1, edge_id: 'a->b:order', from_node: 'a', to_node: 'b', attempt: 1 },
    });
    expect(edgeTraversed(a0, b1, [tAttempt1])).toBe(false);
  });

  it('legacy events without transitions never fabricate paths', async () => {
    const { edgeTraversed } = await import('@/views/data/flowLayout');
    const a = siblingExec('a', [
      evFact('a:s', 'a', 'start', 'running', { row_id: 1 }),
    ]);
    const b = siblingExec('b', [
      evFact('b:f', 'b', 'finish', 'succeeded', { row_id: 2 }),
    ]);
    expect(edgeTraversed(a, b, [])).toBe(false);
    // 同 instance_key 也不足够（R3：同轮业务≠经过某条静态边）
    const a2 = siblingExec('a', [
      evFact('a:s2', 'a', 'start', 'running', { row_id: 1, instance_key: 'seg:1' }),
    ]);
    const b2 = siblingExec('b', [
      evFact('b:f2', 'b', 'finish', 'succeeded', { row_id: 2, instance_key: 'seg:1' }),
    ]);
    expect(edgeTraversed(a2, b2, [])).toBe(false);
  });
});
