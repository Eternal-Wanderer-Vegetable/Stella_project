import type { FlowEdgeSpec, FlowNodeSpec } from '@/api/flow';
import type { FlowNodeState } from '@/stores/flowReducer';

export interface SpecLike {
  lanes: Array<[string, string]>;
  nodes: FlowNodeSpec[];
  edges: FlowEdgeSpec[];
  entry_roots: Record<string, string>;
}

// 消息流程画布布局（计划 §6.7）：确定性分层——泳道为行、行内按执行顺序
// 排布。无外部布局依赖（Vue Flow/elkjs 为计划中的 [assumed] 项，离线
// 环境无法验证装包；此实现保证可测、可复现）。

export const NODE_W = 128;
export const NODE_H = 40;
export const NODE_GAP_X = 56;
export const NODE_GAP_Y = 72;
export const CANVAS_PAD = 28;

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
}

export interface LaidEdge {
  id: string;
  from: LaidNode;
  to: LaidNode;
  kind: string;
  label: string;
  active?: boolean; // 完整视图：两端都实际执行过（spawn/cause 永远不算）
}

export interface LayoutInput {
  nodeStates: FlowNodeState[];
  laneOf: (nodeId: string) => string;
  laneOrder: string[];
  specEdges: FlowEdgeSpec[];
  specNodes?: Record<string, FlowNodeSpec>;
}

export interface LayoutResult {
  nodes: LaidNode[];
  edges: LaidEdge[];
  width: number;
  height: number;
}

/** 泳道分组 → 行坐标；行内按执行顺序 → 列坐标。 */
export function layoutFlow(input: LayoutInput): LayoutResult {
  const byLane = new Map<string, FlowNodeState[]>();
  for (const n of input.nodeStates) {
    const lane = input.laneOf(n.nodeId);
    const list = byLane.get(lane) ?? [];
    list.push(n);
    byLane.set(lane, list);
  }
  // 目录外的动态泳道（如 hook.custom 落 other 之外的意外值）追加在尾部，
  // 绝不静默丢节点。
  const rows = [
    ...input.laneOrder.filter((lane) => byLane.has(lane)),
    ...[...byLane.keys()].filter((lane) => !input.laneOrder.includes(lane)),
  ];
  const nodes: LaidNode[] = [];
  rows.forEach((lane, rowIdx) => {
    const laneNodes = byLane.get(lane) ?? [];
    laneNodes.forEach((n, colIdx) => {
      nodes.push({
        nodeId: n.nodeId,
        label: n.label,
        status: n.status,
        outcome: n.businessOutcome,
        instances: n.instances,
        lane,
        spec: input.specNodes?.[n.nodeId],
        x: CANVAS_PAD + colIdx * (NODE_W + NODE_GAP_X),
        y: CANVAS_PAD + rowIdx * (NODE_H + NODE_GAP_Y),
      });
    });
  });
  return {
    nodes,
    edges: layoutEdges(nodes, input.specEdges),
    width: maxX(nodes) + CANVAS_PAD,
    height: maxY(nodes) + CANVAS_PAD,
  };
}

/** 静态边（双方都出现才画，去重）+ 同泳道相邻执行节点兜底顺序边。 */
function layoutEdges(nodes: LaidNode[], specEdges: FlowEdgeSpec[]): LaidEdge[] {
  const byId = new Map(nodes.map((n) => [n.nodeId, n]));
  const edges: LaidEdge[] = [];
  const seen = new Set<string>();
  const connectedPairs = new Set<string>();
  for (const e of specEdges) {
    const a = byId.get(e.src);
    const b = byId.get(e.dst);
    if (!a || !b || a === b) continue;
    const key = `${e.src}->${e.dst}:${e.kind}`;
    if (seen.has(key)) continue;
    seen.add(key);
    connectedPairs.add(`${e.src}->${e.dst}`);
    edges.push({ id: key, from: a, to: b, kind: e.kind, label: e.label });
  }
  const lanesSeen = new Map<string, LaidNode[]>();
  for (const n of nodes) {
    const list = lanesSeen.get(n.lane) ?? [];
    list.push(n);
    lanesSeen.set(n.lane, list);
  }
  for (const list of lanesSeen.values()) {
    for (let i = 1; i < list.length; i += 1) {
      const key = `seq:${list[i - 1].nodeId}->${list[i].nodeId}`;
      if (seen.has(key)) continue;
      // 该对节点已有 spec 边（任意 kind）就不补顺序边，避免同一对画双箭头
      if (connectedPairs.has(`${list[i - 1].nodeId}->${list[i].nodeId}`)) {
        continue;
      }
      seen.add(key);
      edges.push({
        id: key,
        from: list[i - 1],
        to: list[i],
        kind: 'order',
        label: '',
      });
    }
  }
  return edges;
}

function maxX(nodes: LaidNode[]): number {
  return nodes.reduce((m, n) => Math.max(m, n.x + NODE_W), 0);
}

function maxY(nodes: LaidNode[]): number {
  return nodes.reduce((m, n) => Math.max(m, n.y + NODE_H), 0);
}

export interface FullLayoutInput {
  spec: SpecLike;
  /** 已执行节点的状态投影；未在表中的节点渲染为 not_observed。 */
  executed: Map<string, FlowNodeState>;
  labelOf: (nodeId: string) => string;
  laneOf: (nodeId: string) => string;
}

/**
 * 完整流程布局（计划 §6.4「全部可能路径」）：画下目录里的**每一个**节点，
 * 执行过的叠加真实状态，没执行的灰色 not_observed——未走过的路径不消失。
 * 行内顺序 = 泳道内 order/condition 边的拓扑序（声明序兜底），跨泳道边不
 * 参与排序。
 */
export function layoutFull(input: FullLayoutInput): LayoutResult {
  const byId = new Map(input.spec.nodes.map((n) => [n.id, n]));
  const order = topoOrderPerLane(input.spec, input.laneOf);
  const nodes: LaidNode[] = [];
  const rows = [
    ...input.spec.lanes.map(([id]) => id).filter((lane) => order.has(lane)),
  ];
  rows.forEach((lane, rowIdx) => {
    const laneNodes = order.get(lane) ?? [];
    laneNodes.forEach((nodeId, colIdx) => {
      const spec = byId.get(nodeId);
      const exec = input.executed.get(nodeId);
      nodes.push({
        nodeId,
        label: input.labelOf(nodeId),
        status: exec?.status ?? 'not_observed',
        outcome: exec?.businessOutcome ?? '',
        instances: exec?.instances ?? 0,
        lane,
        spec,
        x: CANVAS_PAD + colIdx * (NODE_W + NODE_GAP_X),
        y: CANVAS_PAD + rowIdx * (NODE_H + NODE_GAP_Y),
      });
    });
  });
  // 执行高亮：两端都实际执行过的边才算「走过」
  const edges = input.spec.edges
    .filter((e) => byId.has(e.src) && byId.has(e.dst))
    .map((e) => {
      const from = nodes.find((n) => n.nodeId === e.src)!;
      const to = nodes.find((n) => n.nodeId === e.dst)!;
      return {
        id: `${e.src}->${e.dst}:${e.kind}`,
        from,
        to,
        kind: e.kind,
        label: e.label,
        active:
          input.executed.has(e.src) &&
          input.executed.has(e.dst) &&
          e.kind !== 'spawn' && e.kind !== 'cause',
      };
    });
  return {
    nodes,
    edges,
    width: maxX(nodes) + CANVAS_PAD,
    height: maxY(nodes) + CANVAS_PAD,
  };
}

/** 泳道内拓扑排序：只沿本泳道内的 order/condition 边走，声明序做稳定兜底。 */
function topoOrderPerLane(
  spec: SpecLike,
  laneOf: (nodeId: string) => string,
): Map<string, string[]> {
  const laneOfNode = new Map(spec.nodes.map((n) => [n.id, laneOf(n.id)]));
  const inLanePreds = new Map<string, Set<string>>();
  for (const node of spec.nodes) {
    inLanePreds.set(node.id, new Set());
  }
  for (const e of spec.edges) {
    if (
      e.kind !== 'order' && e.kind !== 'condition'
    ) continue;
    if (laneOfNode.get(e.src) !== laneOfNode.get(e.dst)) continue;
    inLanePreds.get(e.dst)?.add(e.src);
  }
  const declaration = new Map(spec.nodes.map((n, i) => [n.id, i]));
  const placed = new Set<string>();
  const lanes = new Map<string, string[]>();
  const remaining = spec.nodes.map((n) => n.id);
  let progressed = true;
  while (remaining.length > 0 && progressed) {
    progressed = false;
    for (let i = 0; i < remaining.length; i += 1) {
      const id = remaining[i];
      const preds = [...inLanePreds.get(id) ?? []].filter((p) => p !== id);
      if (!preds.every((p) => placed.has(p))) continue;
      const lane = laneOfNode.get(id) ?? 'other';
      const list = lanes.get(lane) ?? [];
      list.push(id);
      lanes.set(lane, list);
      placed.add(id);
      remaining.splice(i, 1);
      i -= 1;
      progressed = true;
    }
  }
  // 环/孤岛兜底：按声明序塞进各自泳道，绝不丢节点
  for (const id of remaining) {
    const lane = laneOfNode.get(id) ?? 'other';
    const list = lanes.get(lane) ?? [];
    list.push(id);
    lanes.set(lane, list);
    placed.add(id);
  }
  void declaration;
  return lanes;
}

/** 节点间的贝塞尔路径（同行为直线，跨行走曲线）。 */
export function edgePath(a: LaidNode, b: LaidNode): string {
  const ax = a.x + NODE_W;
  const ay = a.y + NODE_H / 2;
  const bx = b.x;
  const by = b.y + NODE_H / 2;
  if (Math.abs(ay - by) < 4) {
    return `M ${ax} ${ay} L ${bx} ${by}`;
  }
  const mx = (ax + bx) / 2;
  return `M ${ax} ${ay} C ${mx} ${ay}, ${mx} ${by}, ${bx} ${by}`;
}
