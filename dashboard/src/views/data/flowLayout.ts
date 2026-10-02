import type { FlowEdgeSpec, FlowNodeSpec } from '@/api/flow';
import type { FlowNodeState } from '@/stores/flowReducer';

export interface SpecLike {
  lanes: Array<[string, string]>;
  nodes: FlowNodeSpec[];
  edges: FlowEdgeSpec[];
  entry_roots: Record<string, string>;
}

// 消息流程画布布局（计划 §6.7）：ComfyUI 式**分层左→右流式布局**——
// 全图按最长路径排名分列（有始有终：最左「开始」锚点接入所有源节点，
// 最右「结束」锚点接所有汇节点），列内按泳道聚簇并垂直居中。无外部
// 布局依赖（Vue Flow/elkjs 为计划中的 [assumed] 项，离线环境无法验证
// 装包；此实现保证可测、可复现）。
//
// 完整/实际两种视图共用这套坐标：切换只是淡出未走过的节点与边（UI 层
// CSS 过渡），不是重排成另一张图——这就是视图切换平滑动画的基础。

export const NODE_W = 128;
export const NODE_H = 40;
export const COL_GAP = 56;
export const ROW_PITCH = 52;
export const CANVAS_PAD = 28;
export const ANCHOR_W = 64;
export const ANCHOR_H = 26;

export interface LaidNode {
  nodeId: string;
  label: string;
  status: string;
  outcome: string;
  instances: number;
  x: number;
  y: number;
  lane: string;
  spec?: FlowNodeSpec;
  anchor?: 'start' | 'end'; // 合成锚点（非目录节点）
}

export interface LaidEdge {
  id: string;
  from: LaidNode;
  to: LaidNode;
  kind: string;
  label: string;
  active?: boolean; // 完整视图高亮：两端都执行过且为 order/condition
  traversed?: boolean; // 两端都实际执行过（实际视图的可见性判据）
}

export interface FullLayoutInput {
  spec: SpecLike;
  /** 已执行节点的状态投影；未在表中的节点渲染为 not_observed。 */
  executed: Map<string, FlowNodeState>;
  labelOf: (nodeId: string) => string;
  laneOf: (nodeId: string) => string;
}

export interface LayoutResult {
  nodes: LaidNode[];
  edges: LaidEdge[];
  width: number;
  height: number;
}

/**
 * 分层布局：排名（列）= 沿全部静态边（order/condition/spawn/cause）的
 * 最长路径；自环忽略，环由迭代上限兜底——**绝不丢节点**。列内按泳道
 * 聚簇、整列垂直居中；start/end 锚点分别接入源/汇。
 */
export function layoutLayered(input: FullLayoutInput): LayoutResult {
  const specNodes = input.spec.nodes;
  const idSet = new Set(specNodes.map((n) => n.id));
  const edges = input.spec.edges.filter(
    (e) => e.src !== e.dst && idSet.has(e.src) && idSet.has(e.dst),
  );

  // ── 排名：先 DFS 去掉回边（环），再在 DAG 上做最长路径松弛 ──
  // 回边仍参与渲染（画成回指曲线），只是不计入列排名——否则环内节点会被
  // 迭代上限推到离谱的远列。
  const edgeKey = (e: FlowEdgeSpec) => `${e.src}->${e.dst}:${e.kind}`;
  const adj = new Map<string, FlowEdgeSpec[]>();
  for (const e of edges) {
    const list = adj.get(e.src);
    if (list) list.push(e);
    else adj.set(e.src, [e]);
  }
  const backIds = new Set<string>();
  {
    const color = new Map<string, number>(); // 1=在栈上 2=完成
    const onStack = new Set<string>();
    const dfs = (u: string): void => {
      color.set(u, 1);
      onStack.add(u);
      for (const e of adj.get(u) ?? []) {
        const vState = color.get(e.dst) ?? 0;
        if (vState === 1) backIds.add(edgeKey(e));
        else if (vState === 0) dfs(e.dst);
      }
      onStack.delete(u);
      color.set(u, 2);
    };
    for (const n of specNodes) {
      if (!color.get(n.id)) dfs(n.id);
    }
  }
  const rankEdges = edges.filter((e) => !backIds.has(edgeKey(e)));
  const depth = new Map<string, number>(specNodes.map((n) => [n.id, 0]));
  for (let pass = 0; pass < specNodes.length + 2; pass += 1) {
    let changed = false;
    for (const e of rankEdges) {
      const candidate = depth.get(e.src)! + 1;
      if (candidate > depth.get(e.dst)!) {
        depth.set(e.dst, candidate);
        changed = true;
      }
    }
    if (!changed) break;
  }
  // 列压缩：稀疏深度值 → 连续列号
  const columnOf = new Map<string, number>();
  {
    const depths = [...new Set(depth.values())].sort((a, b) => a - b);
    const indexOf = new Map(depths.map((d, i) => [d, i]));
    for (const [id, d] of depth) columnOf.set(id, indexOf.get(d)!);
  }

  // ── 列内排序：泳道序聚簇，再按声明序稳定兜底 ──
  const laneIndex = new Map(input.spec.lanes.map(([id], i) => [id, i]));
  const declaration = new Map(specNodes.map((n, i) => [n.id, i]));
  const columns: string[][] = [];
  for (const n of specNodes) {
    const col = columnOf.get(n.id)!;
    const list = columns[col];
    if (list) list.push(n.id);
    else columns[col] = [n.id];
  }
  const laneOfNode = (id: string) => laneIndex.get(input.laneOf(id)) ?? 999;
  for (const col of columns) {
    if (col) {
      col.sort(
        (a, b) =>
          laneOfNode(a) - laneOfNode(b) ||
          declaration.get(a)! - declaration.get(b)!,
      );
    }
  }

  // ── 坐标：整列垂直居中 ──
  const maxRows = columns.reduce((m, c) => Math.max(m, c?.length ?? 0), 1);
  const nodes: LaidNode[] = [];
  const nodeById = new Map<string, LaidNode>();
  columns.forEach((col, colIdx) => {
    const list = col ?? [];
    const top =
      CANVAS_PAD + ((maxRows - list.length) * ROW_PITCH) / 2;
    list.forEach((id, rowIdx) => {
      const exec = input.executed.get(id);
      const node: LaidNode = {
        nodeId: id,
        label: input.labelOf(id),
        status: exec?.status ?? 'not_observed',
        outcome: exec?.businessOutcome ?? '',
        instances: exec?.instances ?? 0,
        lane: input.laneOf(id),
        spec: input.spec.nodes.find((n) => n.id === id),
        x: CANVAS_PAD + ANCHOR_W + 32 + colIdx * (NODE_W + COL_GAP),
        y: top + rowIdx * ROW_PITCH,
      };
      nodes.push(node);
      nodeById.set(id, node);
    });
  });

  // ── 源 / 汇（沿全部静态边的入度/出度为零者；渲染边与排名边一致口径）──
  const hasIn = new Set(edges.map((e) => e.dst));
  const hasOut = new Set(edges.map((e) => e.src));
  const sources = specNodes.map((n) => n.id).filter((id) => !hasIn.has(id));
  const sinks = specNodes.map((n) => n.id).filter((id) => !hasOut.has(id));

  const contentW =
    CANVAS_PAD + ANCHOR_W + 32 + columns.length * (NODE_W + COL_GAP);
  const height = Math.max(maxRows * ROW_PITCH + 2 * CANVAS_PAD, 120);

  // ── start / end 锚点（垂直对齐各自接入节点的均值）──
  const centerY = (ids: string[]) => {
    const ys = ids.map((id) => nodeById.get(id)!.y + NODE_H / 2);
    return ys.length ? ys.reduce((a, b) => a + b, 0) / ys.length : height / 2;
  };
  const startY = centerY(sources);
  const endY = centerY(sinks);
  const startAnchor: LaidNode = {
    nodeId: '__start__',
    label: '开始',
    status: 'anchor',
    outcome: '',
    instances: 0,
    lane: '',
    x: CANVAS_PAD,
    y: startY - ANCHOR_H / 2,
    anchor: 'start',
  };
  const endAnchor: LaidNode = {
    nodeId: '__end__',
    label: '结束',
    status: 'anchor',
    outcome: '',
    instances: 0,
    lane: '',
    x: contentW,
    y: endY - ANCHOR_H / 2,
    anchor: 'end',
  };
  nodes.push(startAnchor, endAnchor);

  // ── 边：普通边 + 锚点接入边；traversed 驱动实际视图可见性 ──
  const layoutEdges: LaidEdge[] = edges.map((e) => {
    const traversed =
      input.executed.has(e.src) && input.executed.has(e.dst);
    return {
      id: `${e.src}->${e.dst}:${e.kind}`,
      from: nodeById.get(e.src)!,
      to: nodeById.get(e.dst)!,
      kind: e.kind,
      label: e.label,
      traversed,
      active: traversed && e.kind !== 'spawn' && e.kind !== 'cause',
    };
  });
  for (const id of sources) {
    layoutEdges.push({
      id: `__start__->${id}`,
      from: startAnchor,
      to: nodeById.get(id)!,
      kind: 'order',
      label: '',
      traversed: input.executed.has(id),
      active: input.executed.has(id),
    });
  }
  for (const id of sinks) {
    layoutEdges.push({
      id: `${id}->__end__`,
      from: nodeById.get(id)!,
      to: endAnchor,
      kind: 'order',
      label: '',
      traversed: input.executed.has(id),
      active: input.executed.has(id),
    });
  }

  return {
    nodes,
    edges: layoutEdges,
    width: contentW + ANCHOR_W + CANVAS_PAD,
    height,
  };
}

/** 节点间的贝塞尔路径（同列为直线，跨列走曲线）。 */
export function edgePath(a: LaidNode, b: LaidNode): string {
  const isAnchorA = a.anchor !== undefined;
  const ax = isAnchorA ? a.x + ANCHOR_W : a.x + NODE_W;
  const ay = a.y + (isAnchorA ? ANCHOR_H : NODE_H) / 2;
  const bx = b.x;
  const by = b.y + (b.anchor !== undefined ? ANCHOR_H : NODE_H) / 2;
  if (Math.abs(ay - by) < 4) {
    return `M ${ax} ${ay} L ${bx} ${by}`;
  }
  const mx = (ax + bx) / 2;
  return `M ${ax} ${ay} C ${mx} ${ay}, ${mx} ${by}, ${bx} ${by}`;
}
