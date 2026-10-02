import type { FlowEvent, FlowNodeSpec } from '@/api/flow';
import type { SpecLike } from '@/views/data/flowLayout';
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

  function runExecuted() {
    return layoutExecuted({
      spec: fullSpec,
      executed: new Map(
        [exec('entry'), exec('a'), exec('b')].map((n) => [n.nodeId, n]),
      ),
      labelOf: (id) => id,
      laneOf: (id) =>
        ({ entry: 'ingress', skip: 'ingress', a: 'generate', b: 'delivery' })[id]!,
    });
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
    const full = layoutLayered({
      spec: fullSpec,
      executed: new Map(
        [exec('entry'), exec('a'), exec('b')].map((n) => [n.nodeId, n]),
      ),
      labelOf: (id) => id,
      laneOf: (id) =>
        ({ entry: 'ingress', skip: 'ingress', a: 'generate', b: 'delivery' })[id]!,
    });
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

  it('empty execution yields just the anchors', () => {
    const out = layoutExecuted({
      spec: fullSpec,
      executed: new Map(),
      labelOf: (id) => id,
      laneOf: () => 'ingress',
    });
    expect(out.nodes.filter((n) => n.anchor === undefined)).toHaveLength(0);
    expect(out.nodes.filter((n) => n.anchor !== undefined)).toHaveLength(2);
  });
});
