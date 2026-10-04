import type { FlowEvent, FlowNodeSpec } from '@/api/flow';
import type { SpecLike } from '@/views/data/flowLayout';
import {
  ANCHOR_H,
  ANCHOR_W,
  CANVAS_PAD,
  edgePath,
  layoutLayered,
  NODE_H,
  NODE_W,
} from '@/views/data/flowLayout';
import { describe, expect, it } from 'vitest';

// 分层流式布局合同（用户验收：流程图要有始有终，参考 ComfyUI 的左→右
// 工作流可读性）。两种视图共用这套坐标——切换是淡出，不是重排。

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
  } as FlowEvent;
}

function execMap(...nodes: ReturnType<typeof exec>[]) {
  return new Map(nodes.map((n) => [n.nodeId, n]));
}

const LANES: Array<[string, string]> = [
  ['ingress', '入口'],
  ['generate', '生成'],
  ['delivery', '交付'],
];

describe('layoutLayered ranking', () => {
  it('ranks a chain left→right: every hop moves to a later column', () => {
    const s = spec({
      lanes: LANES,
      nodes: [node('a', 'ingress'), node('b', 'ingress'), node('c', 'ingress')],
      edges: [
        { src: 'a', dst: 'b', kind: 'order', label: '' },
        { src: 'b', dst: 'c', kind: 'order', label: '' },
      ],
    });
    const out = layoutLayered({
      spec: s,
      executed: new Map(),
      labelOf: (id) => id,
      laneOf: () => 'ingress',
    });
    const byId = new Map(out.nodes.map((n) => [n.nodeId, n]));
    expect(byId.get('a')!.x).toBeLessThan(byId.get('b')!.x);
    expect(byId.get('b')!.x).toBeLessThan(byId.get('c')!.x);
  });

  it('spawn/cause edges also advance the rank (one grand flow)', () => {
    const s = spec({
      lanes: LANES,
      nodes: [node('a', 'ingress'), node('bg', 'background')],
      edges: [{ src: 'a', dst: 'bg', kind: 'spawn', label: '' }],
    });
    const out = layoutLayered({
      spec: s,
      executed: new Map(),
      labelOf: (id) => id,
      laneOf: (id) => (id === 'a' ? 'ingress' : 'background'),
    });
    const byId = new Map(out.nodes.map((n) => [n.nodeId, n]));
    expect(byId.get('bg')!.x).toBeGreaterThan(byId.get('a')!.x);
  });

  it('ignores self edges and tolerates cycles without dropping nodes', () => {
    const s = spec({
      lanes: LANES,
      nodes: [node('x', 'generate'), node('y', 'generate')],
      edges: [
        { src: 'x', dst: 'x', kind: 'cause', label: 'BOT_SELF' },
        { src: 'x', dst: 'y', kind: 'order', label: '' },
        { src: 'y', dst: 'x', kind: 'order', label: '' },
      ],
    });
    const out = layoutLayered({
      spec: s,
      executed: new Map(),
      labelOf: (id) => id,
      laneOf: () => 'generate',
    });
    // 环（y→x 为回边）被排除出排名：x 在左、y 在右的相邻列，不被推远
    const byId = new Map(out.nodes.map((n) => [n.nodeId, n]));
    expect(byId.get('y')!.x - byId.get('x')!.x).toBe(NODE_W + 56);
    expect(out.nodes.filter((n) => n.anchor === undefined)).toHaveLength(2);
    // 回边仍参与渲染
    expect(out.edges.some((e) => e.from.nodeId === 'y' && e.to.nodeId === 'x')).toBe(true);
  });
});

describe('layoutLayered anchors (有始有终)', () => {
  const s = spec({
    lanes: LANES,
    nodes: [
      node('entry', 'ingress'),
      node('mid', 'generate'),
      node('end1', 'delivery'),
      node('end2', 'delivery'),
    ],
    edges: [
      { src: 'entry', dst: 'mid', kind: 'order', label: '' },
      { src: 'mid', dst: 'end1', kind: 'order', label: '' },
      { src: 'mid', dst: 'end2', kind: 'order', label: '' },
    ],
  });

  function layout(executed = new Map<string, ReturnType<typeof exec>>()) {
    return layoutLayered({
      spec: s,
      executed,
      labelOf: (id) => id,
      laneOf: (id) =>
        ({ entry: 'ingress', mid: 'generate' })[id] ?? 'delivery',
    });
  }

  it('places one start anchor left of everything and one end anchor right', () => {
    const out = layout();
    const start = out.nodes.find((n) => n.anchor === 'start')!;
    const end = out.nodes.find((n) => n.anchor === 'end')!;
    const content = out.nodes.filter((n) => n.anchor === undefined);
    expect(start.x).toBe(CANVAS_PAD);
    expect(end.x + ANCHOR_W).toBeLessThanOrEqual(out.width);
    for (const n of content) {
      expect(start.x).toBeLessThan(n.x);
      expect(n.x + NODE_W).toBeLessThan(end.x);
    }
  });

  it('wires start to every source and end from every sink', () => {
    const out = layout();
    const startEdges = out.edges.filter((e) => e.from.anchor === 'start');
    const endEdges = out.edges.filter((e) => e.to.anchor === 'end');
    expect(startEdges.map((e) => e.to.nodeId)).toEqual(['entry']);
    expect(endEdges.map((e) => e.from.nodeId).sort()).toEqual(['end1', 'end2']);
  });

  it('anchor wires follow execution in traversed flag', () => {
    const out = layout(execMap(exec('entry'), exec('mid')));
    const startEdge = out.edges.find((e) => e.from.anchor === 'start')!;
    expect(startEdge.traversed).toBe(true);
    const endEdges = out.edges.filter((e) => e.to.anchor === 'end');
    expect(endEdges.every((e) => e.traversed === false)).toBe(true);
  });

  it('vertical centering: start anchor aligns with its targets mean', () => {
    const out = layout();
    const start = out.nodes.find((n) => n.anchor === 'start')!;
    const entry = out.nodes.find((n) => n.nodeId === 'entry')!;
    expect(start.y + ANCHOR_H / 2).toBeCloseTo(entry.y + NODE_H / 2, 6);
  });
});

describe('layoutLayered executed overlay', () => {
  it('unexecuted nodes are not_observed with zero instances; executed keep facts', () => {
    const s = spec({
      lanes: LANES,
      nodes: [node('a', 'ingress'), node('b', 'ingress')],
      edges: [{ src: 'a', dst: 'b', kind: 'order', label: '' }],
    });
    const out = layoutLayered({
      spec: s,
      executed: execMap(exec('a', 'blocked')),
      labelOf: (id) => id,
      laneOf: () => 'ingress',
    });
    const byId = new Map(out.nodes.map((n) => [n.nodeId, n]));
    expect(byId.get('a')!.status).toBe('blocked');
    expect(byId.get('b')!.status).toBe('not_observed');
    expect(byId.get('b')!.instances).toBe(0);
  });

  it('edge traversed/active semantics include spawn handling', () => {
    const s = spec({
      lanes: LANES,
      nodes: [node('a', 'ingress'), node('bg', 'background')],
      edges: [{ src: 'a', dst: 'bg', kind: 'spawn', label: '' }],
    });
    // R3 合同：spawn 边由显式 transition 事实（relation_kind=spawn）激活；
    // 没有事实时保持静态未确认。
    const noFact = layoutLayered({
      spec: s,
      executed: execMap(exec('a'), exec('bg')),
      labelOf: (id) => id,
      laneOf: (id) => (id === 'a' ? 'ingress' : 'background'),
    });
    const unconfirmed = noFact.edges.find((e) => e.kind === 'spawn')!;
    expect(unconfirmed.traversed).toBe(false);
    const withFact = layoutLayered({
      spec: s,
      executed: execMap(exec('a'), exec('bg')),
      labelOf: (id) => id,
      laneOf: (id) => (id === 'a' ? 'ingress' : 'background'),
      transitions: [evFact('t1', 'a', 'decision', 'succeeded', {
        fact_kind: 'transition',
        metrics: { transition_v: 1, from_node: 'a', to_node: 'bg', relation_kind: 'spawn' },
      })],
      rootEnded: true,
    });
    const spawn = withFact.edges.find((e) => e.kind === 'spawn')!;
    expect(spawn.traversed).toBe(true); // 实际路径视图可见
    expect(spawn.active).toBe(false); // spawn 不做实线高亮
  });
});

describe('layoutLayered geometry', () => {
  it('bounds contain all nodes and anchors; edgePath handles anchors', () => {
    const s = spec({
      lanes: LANES,
      nodes: [node('a', 'ingress'), node('b', 'ingress')],
      edges: [{ src: 'a', dst: 'b', kind: 'order', label: '' }],
    });
    const out = layoutLayered({
      spec: s,
      executed: new Map(),
      labelOf: (id) => id,
      laneOf: () => 'ingress',
    });
    expect(out.width).toBeGreaterThan(NODE_W);
    expect(out.height).toBeGreaterThan(NODE_H);
    const start = out.nodes.find((n) => n.anchor === 'start')!;
    const a = out.nodes.find((n) => n.nodeId === 'a')!;
    const d = edgePath(start, a);
    expect(d).toMatch(/^M \d+ \d+ [LC]/);
    const straight = edgePath(a, out.nodes.find((n) => n.nodeId === 'b')!);
    expect(straight).toMatch(/^M \d+ \d+ L/);
  });
});
