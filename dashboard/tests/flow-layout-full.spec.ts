import type { FlowEvent, FlowNodeSpec } from '@/api/flow';
import type { SpecLike } from '@/views/data/flowLayout';
import { CANVAS_PAD, layoutFull, NODE_H } from '@/views/data/flowLayout';
import { describe, expect, it } from 'vitest';

// 完整流程布局合同（用户验收 #2：画出完整流程而不是只有被激活的节点）。

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
    events: [] as FlowEvent[],
  };
}

describe('layoutFull', () => {
  it('places EVERY spec node, executed or not', () => {
    const s = spec({
      lanes: [['ingress', '入口'], ['generate', '生成']],
      nodes: [node('a', 'ingress'), node('g', 'generate'), node('p', 'ingress')],
      edges: [{ src: 'a', dst: 'g', kind: 'order', label: '' }],
    });
    const out = layoutFull({
      spec: s,
      executed: new Map([exec('a'), exec('g')].map((n) => [n.nodeId, n])),
      labelOf: (id) => id,
      laneOf: (id) => (id === 'g' ? 'generate' : 'ingress'),
    });
    expect(out.nodes.map((n) => n.nodeId).sort()).toEqual(['a', 'g', 'p']);
    const p = out.nodes.find((n) => n.nodeId === 'p')!;
    expect(p.status).toBe('not_observed');
    expect(p.instances).toBe(0);
  });

  it('orders each lane topologically along in-lane order edges', () => {
    const s = spec({
      lanes: [['ingress', '入口']],
      nodes: [node('c', 'ingress'), node('a', 'ingress'), node('b', 'ingress')],
      edges: [
        { src: 'a', dst: 'b', kind: 'order', label: '' },
        { src: 'b', dst: 'c', kind: 'order', label: '' },
      ],
    });
    const out = layoutFull({
      spec: s,
      executed: new Map(),
      labelOf: (id) => id,
      laneOf: () => 'ingress',
    });
    expect(out.nodes.map((n) => n.nodeId)).toEqual(['a', 'b', 'c']);
    // 列坐标随拓扑序单调递增
    const xs = out.nodes.map((n) => n.x);
    expect(xs[0]).toBeLessThan(xs[1]!);
    expect(xs[1]!).toBeLessThan(xs[2]!);
  });

  it('lays lanes as rows in spec order', () => {
    const s = spec({
      lanes: [['ingress', '入口'], ['generate', '生成'], ['delivery', '交付']],
      nodes: [node('a', 'ingress'), node('g', 'generate'), node('d', 'delivery')],
      edges: [],
    });
    const out = layoutFull({
      spec: s,
      executed: new Map(),
      labelOf: (id) => id,
      laneOf: (id) => ({ a: 'ingress', g: 'generate', d: 'delivery' })[id]!,
    });
    expect(out.nodes[0].y).toBe(CANVAS_PAD);
    expect(out.nodes[1].y).toBe(CANVAS_PAD + NODE_H + 72);
    expect(out.nodes[2].y).toBe(CANVAS_PAD + 2 * (NODE_H + 72));
  });

  it('marks edges active only when both endpoints executed and edge is causal-order', () => {
    const s = spec({
      lanes: [['ingress', '入口'], ['generate', '生成']],
      nodes: [node('a', 'ingress'), node('g', 'generate'), node('o', 'generate')],
      edges: [
        { src: 'a', dst: 'g', kind: 'order', label: '' },
        { src: 'a', dst: 'o', kind: 'spawn', label: '' },
        { src: 'g', dst: 'o', kind: 'order', label: '' },
      ],
    });
    const out = layoutFull({
      spec: s,
      executed: new Map([exec('a'), exec('g')].map((n) => [n.nodeId, n])),
      labelOf: (id) => id,
      laneOf: (id) => (id === 'a' ? 'ingress' : 'generate'),
    });
    const byId = (id: string) => out.edges.find((e) => e.id.startsWith(`${id}->`) || e.id.startsWith(id));
    const aToG = out.edges.find((e) => e.from.nodeId === 'a' && e.to.nodeId === 'g')!;
    const aToO = out.edges.find((e) => e.from.nodeId === 'a' && e.to.nodeId === 'o')!;
    const gToO = out.edges.find((e) => e.from.nodeId === 'g' && e.to.nodeId === 'o')!;
    expect(aToG.active).toBe(true);
    expect(aToO?.active).toBe(false); // spawn 永远不算「走过」
    expect(gToO.active).toBe(false); // o 未执行
    void byId;
  });

  it('never drops nodes even with cyclic edges', () => {
    const s = spec({
      lanes: [['generate', '生成']],
      nodes: [node('x', 'generate'), node('y', 'generate')],
      edges: [
        { src: 'x', dst: 'y', kind: 'order', label: '' },
        { src: 'y', dst: 'x', kind: 'order', label: '' },
      ],
    });
    const out = layoutFull({
      spec: s,
      executed: new Map(),
      labelOf: (id) => id,
      laneOf: () => 'generate',
    });
    expect(out.nodes).toHaveLength(2);
    expect(out.width).toBeGreaterThan(CANVAS_PAD);
  });
});
