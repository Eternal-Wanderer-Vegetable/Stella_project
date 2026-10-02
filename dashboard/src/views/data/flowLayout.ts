import type { FlowEdgeSpec, FlowNodeSpec } from '@/api/flow';
import type { FlowNodeState } from '@/stores/flowReducer';

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
