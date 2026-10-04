import type { FlowEvent, FlowNodeSpec } from '@/api/flow';
import type { SpecLike } from '@/views/data/flowLayout';
import {
  ANCHOR_H,
  ANCHOR_W,
  CANVAS_PAD,
  edgePath,
  layoutExecuted,
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

// ============================================================
// 外观反馈 2：画布缩放锚点数学——以光标为锚缩放时该点保持原位。
// ============================================================
describe('zoomAround anchor math', () => {
  it('keeps the anchored point fixed while scaling', async () => {
    const { zoomAround } = await import('@/views/data/flowLayout');
    const view = { x: 0, y: 0, scale: 1 };
    // 锚点 (200, 100)：放大 1.25x 后该点仍映射到 (200, 100)
    const next = zoomAround(view, 200, 100, 1.25);
    expect(next.scale).toBeCloseTo(1.25);
    // 点在视图中的位置 = p * scale + translate；缩放前后应相等
    expect(200 * next.scale + next.x).toBeCloseTo(200);
    expect(100 * next.scale + next.y).toBeCloseTo(100);
  });

  it('pans the view when zooming on an off-center anchor', async () => {
    const { zoomAround } = await import('@/views/data/flowLayout');
    const view = { x: 0, y: 0, scale: 1 };
    const next = zoomAround(view, 0, 0, 2); // 以左上角为锚放大：无位移
    expect(next.x).toBeCloseTo(0);
    expect(next.y).toBeCloseTo(0);
    expect(next.scale).toBeCloseTo(2);
    const corner = zoomAround(view, 400, 300, 2); // 以右下区域为锚：视图反向平移
    expect(corner.x).toBeCloseTo(-400);
    expect(corner.y).toBeCloseTo(-300);
  });

  it('clamps scale into [ZOOM_MIN, ZOOM_MAX]', async () => {
    const { zoomAround, ZOOM_MIN, ZOOM_MAX } = await import('@/views/data/flowLayout');
    const tiny = zoomAround({ x: 0, y: 0, scale: 0.4 }, 0, 0, 0.01);
    expect(tiny.scale).toBe(ZOOM_MIN);
    const huge = zoomAround({ x: 0, y: 0, scale: 2.9 }, 0, 0, 10);
    expect(huge.scale).toBe(ZOOM_MAX);
  });
});

// ============================================================
// 外观反馈 2：视图适配——内容包围盒 → 整体缩放 + 居中。
// ============================================================
describe('fitAround centers and scales content into the viewport', async () => {
  const { fitAround, ZOOM_MIN, ZOOM_MAX } = await import('@/views/data/flowLayout');

  it('centers the content bounding box', () => {
    const next = fitAround(
      { minX: 100, minY: 50, maxX: 300, maxY: 250 },
      { width: 800, height: 600 },
    );
    // 内容中心 (200,150) 应映射到视口中心 (400,300)
    expect(200 * next.scale + next.x).toBeCloseTo(400);
    expect(150 * next.scale + next.y).toBeCloseTo(300);
  });

  it('scales down large graphs and caps upscaling of small ones', () => {
    // 大图（缩放比在钳制区间内）：按视口/内容取最小比率（含四周留白）
    const big = fitAround(
      { minX: 0, minY: 0, maxX: 1600, maxY: 700 },
      { width: 800, height: 600 },
    );
    expect(big.scale).toBeCloseTo(Math.min(800 / 1656, 600 / 756));
    // 小图：放大但不超过 1.25 上限
    const small = fitAround(
      { minX: 0, minY: 0, maxX: 100, maxY: 80 },
      { width: 800, height: 600 },
    );
    expect(small.scale).toBe(1.25);
    // 极端比率仍被 ZOOM_MIN/ZOOM_MAX 钳制
    const tiny = fitAround({ minX: 0, minY: 0, maxX: 99999, maxY: 99999 },
      { width: 200, height: 200 });
    expect(tiny.scale).toBe(ZOOM_MIN);
    expect(ZOOM_MAX).toBeGreaterThan(0);
  });
});

// ============================================================
// 外观反馈 6/7：起止锚按连通分量分离；「结束」锚可整体隐藏。
// ============================================================
describe('per-component anchors', () => {
  function twoChainsSpec() {
    return spec({
      lanes: LANES,
      nodes: [node('a', 'ingress'), node('b', 'ingress'),
              node('x', 'delivery'), node('y', 'delivery')],
      edges: [
        { src: 'a', dst: 'b', kind: 'order', label: '' },
        { src: 'x', dst: 'y', kind: 'order', label: '' },
      ],
    });
  }

  it('disconnected components get separate start/end anchor pairs', () => {
    const out = layoutLayered({
      spec: twoChainsSpec(),
      executed: new Map(),
      labelOf: (id) => id,
      laneOf: () => 'ingress',
      rootEnded: true,
    });
    const starts = out.nodes.filter((n) => n.anchor === 'start');
    const ends = out.nodes.filter((n) => n.anchor === 'end');
    expect(starts.length).toBe(2);
    expect(ends.length).toBe(2);
    // 两条链不在同一行：各自的开始锚 y 不同（不再全图共享一个均值点）
    expect(new Set(starts.map((n) => n.y)).size).toBe(2);
    // 每条链的汇接各自分量的结束锚
    expect(out.edges.filter((e) => e.to.anchor === 'end')
      .map((e) => e.from.nodeId).sort()).toEqual(['b', 'y']);
    expect(out.edges.filter((e) => e.from.anchor === 'start')
      .map((e) => e.to.nodeId).sort()).toEqual(['a', 'x']);
  });

  it('showEndAnchors:false hides end anchors and their edges, narrows width', () => {
    const withEnd = layoutLayered({
      spec: twoChainsSpec(),
      executed: new Map(),
      labelOf: (id) => id,
      laneOf: () => 'ingress',
      rootEnded: true,
    });
    const without = layoutLayered({
      spec: twoChainsSpec(),
      executed: new Map(),
      labelOf: (id) => id,
      laneOf: () => 'ingress',
      rootEnded: true,
      showEndAnchors: false,
    });
    expect(without.nodes.filter((n) => n.anchor === 'end')).toHaveLength(0);
    expect(without.edges.filter((e) => e.to.anchor === 'end')).toHaveLength(0);
    // 开始锚不受影响
    expect(without.nodes.filter((n) => n.anchor === 'start')).toHaveLength(2);
    expect(without.width).toBeLessThan(withEnd.width);
  });
});

// ============================================================
// 外观反馈 8/10：观测缺口不把同一条目录流程撕成多个「开始」；
// 同侧锚点最小间距摊开。
// ============================================================
describe('catalog-level components and anchor spreading', () => {
  it('observation gaps do not split one catalog flow into multiple starts', () => {
    // 目录链 a → mid → b；执行视图只有 a、b（mid 无事件）
    const s = spec({
      lanes: LANES,
      nodes: [node('a', 'ingress'), node('mid', 'ingress'), node('b', 'ingress')],
      edges: [
        { src: 'a', dst: 'mid', kind: 'order', label: '' },
        { src: 'mid', dst: 'b', kind: 'order', label: '' },
      ],
    });
    const executed = new Map<string, FlowNodeState>([
      ['a', exec('a')],
      ['b', exec('b')],
    ]);
    const out = layoutExecuted({
      spec: s,
      executed,
      labelOf: (id) => id,
      laneOf: () => 'ingress',
    });
    expect(out.nodes.filter((n) => n.anchor === 'start')).toHaveLength(1);
    expect(out.nodes.filter((n) => n.anchor === 'end')).toHaveLength(1);
  });

  it('spreads coinciding anchor ys to a minimum gap', async () => {
    const { spreadAnchorYs, ANCHOR_H } = await import('@/views/data/flowLayout');
    const out = spreadAnchorYs([100, 100, 100]);
    const ys = out.map((y) => y as number);
    expect(ys[0]).toBeCloseTo(100);
    expect(ys[1]).toBeCloseTo(100 + ANCHOR_H + 8);
    expect(ys[2]).toBeCloseTo(100 + 2 * (ANCHOR_H + 8));
    // null 穿透：该侧无锚的分量不受影响
    const mixed = spreadAnchorYs([null, 50, 50]);
    expect(mixed[0]).toBeNull();
    expect(mixed[1]! + ANCHOR_H + 8).toBeCloseTo(mixed[2]!);
  });
});
