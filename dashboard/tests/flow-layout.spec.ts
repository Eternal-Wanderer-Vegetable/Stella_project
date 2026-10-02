import type { FlowEdgeSpec } from '@/api/flow';
import {
  CANVAS_PAD,
  edgePath,
  layoutFlow,
  NODE_GAP_X,
  NODE_GAP_Y,
  NODE_H,
  NODE_W,
} from '@/views/data/flowLayout';
import { describe, expect, it } from 'vitest';

// 画布布局合同（计划 §8.1 canvas tests）：泳道行 × 执行顺序列的确定性
// 布局；spec 边只画双方都在场的；同泳道补执行顺序兜底边。

function state(nodeId: string, status = 'succeeded') {
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
    events: [],
  };
}

const LANE_ORDER = ['ingress', 'generate', 'delivery', 'other'];

function layout(
  nodeStates: ReturnType<typeof state>[],
  laneOf: (id: string) => string,
  specEdges: FlowEdgeSpec[] = [],
) {
  return layoutFlow({ nodeStates, laneOf, laneOrder: LANE_ORDER, specEdges });
}

describe('layoutFlow nodes', () => {
  it('assigns one row per lane in laneOrder sequence', () => {
    const out = layout(
      [state('a'), state('g'), state('d')],
      (id) => ({ a: 'ingress', g: 'generate', d: 'delivery' })[id]!,
    );
    expect(out.nodes.map((n) => n.lane)).toEqual(['ingress', 'generate', 'delivery']);
    expect(out.nodes[0].y).toBeLessThan(out.nodes[1].y);
    expect(out.nodes[1].y).toBeLessThan(out.nodes[2].y);
  });

  it('stacks same-lane nodes along x with fixed pitch', () => {
    const out = layout(
      [state('a1'), state('a2')],
      () => 'ingress',
    );
    expect(out.nodes[1].x - out.nodes[0].x).toBe(NODE_W + NODE_GAP_X);
    expect(out.nodes[1].y).toBe(out.nodes[0].y);
  });

  it('rows start at padding with fixed lane pitch', () => {
    const out = layout(
      [state('a'), state('g')],
      (id) => (id === 'a' ? 'ingress' : 'generate'),
    );
    expect(out.nodes[0].y).toBe(CANVAS_PAD);
    expect(out.nodes[1].y).toBe(CANVAS_PAD + NODE_H + NODE_GAP_Y);
  });

  it('unknown lanes fall into the trailing other row', () => {
    const out = layout(
      [state('x'), state('a')],
      (id) => (id === 'a' ? 'ingress' : 'mystery'),
    );
    expect(out.nodes.map((n) => n.lane)).toEqual(['ingress', 'mystery']);
  });

  it('computes canvas size from the rightmost and bottom nodes', () => {
    const out = layout(
      [state('a'), state('g')],
      (id) => (id === 'a' ? 'ingress' : 'generate'),
    );
    const last = out.nodes[out.nodes.length - 1];
    expect(out.width).toBe(last.x + NODE_W + CANVAS_PAD);
    expect(out.height).toBe(last.y + NODE_H + CANVAS_PAD);
  });

  it('empty input yields padded empty canvas', () => {
    const out = layout([], () => 'ingress');
    expect(out.nodes).toEqual([]);
    expect(out.edges).toEqual([]);
    expect(out.width).toBe(CANVAS_PAD);
    expect(out.height).toBe(CANVAS_PAD);
  });
});

describe('layoutFlow edges', () => {
  it('draws spec edges only when both endpoints are present', () => {
    const edges = layout(
      [state('a'), state('g')],
      (id) => (id === 'a' ? 'ingress' : 'generate'),
      [
        { src: 'a', dst: 'g', kind: 'order', label: '' },
        { src: 'a', dst: 'missing', kind: 'order', label: '' },
      ],
    ).edges;
    expect(edges).toHaveLength(1);
    expect(edges[0].kind).toBe('order');
  });

  it('dedupes repeated spec edges and skips self edges', () => {
    const edges = layout(
      [state('a'), state('g')],
      () => 'ingress',
      [
        { src: 'a', dst: 'g', kind: 'order', label: '' },
        { src: 'a', dst: 'g', kind: 'order', label: 'again' },
        { src: 'g', dst: 'g', kind: 'cause', label: 'BOT_SELF' },
      ],
    ).edges;
    // spec 去重 + 自环跳过；该对已有 spec 边，不再补 seq 兜底边
    expect(edges.map((e) => e.id)).toEqual(['a->g:order']);
  });

  it('adds fallback order edges between adjacent executed nodes per lane', () => {
    const edges = layout(
      [state('a1'), state('a2'), state('g')],
      (id) => (id === 'g' ? 'generate' : 'ingress'),
    ).edges;
    expect(edges.map((e) => e.id)).toContain('seq:a1->a2');
    // 跨泳道没有兜底边
    expect(edges.every((e) => e.from.lane === e.to.lane)).toBe(true);
  });

  it('spec edge wins over the fallback duplicate', () => {
    const edges = layout(
      [state('a1'), state('a2')],
      () => 'ingress',
      [{ src: 'a1', dst: 'a2', kind: 'condition', label: '通过' }],
    ).edges;
    expect(edges).toHaveLength(1);
    expect(edges[0].kind).toBe('condition');
    expect(edges[0].label).toBe('通过');
  });

  it('preserves spawn/cause edge kinds for dashed rendering', () => {
    const edges = layout(
      [state('a'), state('c'), state('b')],
      () => 'ingress',
      [{ src: 'a', dst: 'c', kind: 'spawn', label: '' }],
    ).edges;
    const spawn = edges.find((e) => e.kind === 'spawn');
    expect(spawn).toBeDefined();
  });
});

describe('edgePath', () => {
  it('straight line when both endpoints share a row', () => {
    const nodes = layout([state('a1'), state('a2')], () => 'ingress').nodes;
    const d = edgePath(nodes[0], nodes[1]);
    expect(d).toMatch(/^M \d+ \d+ L \d+ \d+$/);
  });

  it('bezier across rows', () => {
    const out = layout(
      [state('a'), state('g')],
      (id) => (id === 'a' ? 'ingress' : 'generate'),
    );
    const d = edgePath(out.nodes[0], out.nodes[1]);
    expect(d).toContain('C');
  });
});
