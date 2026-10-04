import type { FlowEdgeSpec, FlowEvent, FlowNodeSpec } from '@/api/flow';
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
  component?: number; // 锚点所属连通分量（不同流程的起止相互分离）
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
  /** 边级 transition 事实（修复计划 §6.4 R3）：只有这些显式事实激活边。 */
  transitions?: FlowEvent[];
  /** root 是否已真实结束（trace_end + writer finality）；未结束不得把
   * 汇节点接到「结束」锚点装作运行完成（R3/R8）。 */
  rootEnded?: boolean;
  /** 是否渲染「结束」锚点（外观反馈 5）：运行未真实结束前显示「结束」
   * 具有欺骗性——回放场景按已播到的 trace_end 事实控制。默认 true。 */
  showEndAnchors?: boolean;
}

export interface LayoutResult {
  nodes: LaidNode[];
  edges: LaidEdge[];
  width: number;
  height: number;
}

/**
 * 完整流程布局：目录全节点分层（见 {@link layered}）。
 */
export function layoutLayered(input: FullLayoutInput): LayoutResult {
  return layered({
    nodes: input.spec.nodes,
    edges: input.spec.edges,
    lanes: input.spec.lanes,
    executed: input.executed,
    labelOf: input.labelOf,
    laneOf: input.laneOf,
    transitions: input.transitions,
    rootEnded: input.rootEnded,
    showEndAnchors: input.showEndAnchors,
  });
}

/**
 * 实际路径布局：**只取已执行节点与其间的边**再走同一套分层算法——
 * 未走过的节点不占位，路径收束成一条连通的左→右流（用户验收 #2）。
 * 边 traversed 由真实 transition 事实判定（O05/R3）；unknown 节点（事件
 * 里有、spec 里没有）以占位节点参与布局，始终可见（O05）。
 */
export function layoutExecuted(input: FullLayoutInput): LayoutResult {
  const known = new Set(input.spec.nodes.map((n) => n.id));
  const unknownNodes: FlowNodeSpec[] = [...input.executed.keys()]
    .filter((id) => !known.has(id))
    .map((id) => ({
      id,
      label: input.labelOf(id),
      lane: input.laneOf(id),
      kind: 'unknown',
    }));
  const nodes = [
    ...input.spec.nodes.filter((n) => input.executed.has(n.id)),
    ...unknownNodes,
  ];
  const kept = new Set(nodes.map((n) => n.id));
  const edges = input.spec.edges.filter(
    (e) => e.src !== e.dst && kept.has(e.src) && kept.has(e.dst),
  );
  const lanesUsed = new Set(nodes.map((n) => input.laneOf(n.id)));
  return layered({
    nodes,
    edges,
    lanes: input.spec.lanes.filter(([id]) => lanesUsed.has(id)),
    executed: input.executed,
    labelOf: input.labelOf,
    laneOf: input.laneOf,
    transitions: input.transitions,
    rootEnded: input.rootEnded,
    showEndAnchors: input.showEndAnchors,
  });
}

interface LayeredInput {
  nodes: FlowNodeSpec[];
  edges: FlowEdgeSpec[];
  lanes: Array<[string, string]>;
  executed: Map<string, FlowNodeState>;
  labelOf: (nodeId: string) => string;
  laneOf: (nodeId: string) => string;
  transitions?: FlowEvent[];
  rootEnded?: boolean;
  showEndAnchors?: boolean;
}

/**
 * 分层内核：排名（列）= 沿给定静态边（order/condition/spawn/cause）的
 * 最长路径；自环忽略，环用 DFS 去回边——**绝不丢节点**。列内按泳道
 * 聚簇、整列垂直居中；start/end 锚点分别接入源/汇。
 *
 * O05：事件里有、目录里没有的 unknown 节点以占位节点补进画布（始终可见，
 * 不丢事实）；边 traversed 由真实 transition 事实判定（见 {@link edgeTraversed}）。
 */
function layered(input: LayeredInput): LayoutResult {
  const specNodes = [...input.nodes];
  {
    // unknown 节点（事件有、spec 无）：占位节点进画布，标签走兜底映射
    const known = new Set(specNodes.map((n) => n.id));
    for (const id of input.executed.keys()) {
      if (!known.has(id)) {
        specNodes.push({
          id,
          label: input.labelOf(id),
          lane: input.laneOf(id),
          kind: 'unknown',
        });
      }
    }
  }
  const idSet = new Set(specNodes.map((n) => n.id));
  const edges = input.edges.filter(
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
  const laneIndex = new Map(input.lanes.map(([id], i) => [id, i]));
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
        spec: specNodes.find((n) => n.id === id),
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

  const contentW =
    CANVAS_PAD + ANCHOR_W + 32 + columns.length * (NODE_W + COL_GAP);
  const height = Math.max(maxRows * ROW_PITCH + 2 * CANVAS_PAD, 120);

  // ── 起止锚点（外观反馈 6/7）：按**弱连通分量**各配一对开始/结束——
  // 不同流程（消息链/记忆链/知识链…）不再共享同一对锚点；纯环分量
  // （无源无汇）不设锚。「结束」锚整体可隐藏：运行未真实结束前显示
  // 「结束」在视觉上具有欺骗性（回放场景按已播到的 trace_end 控制）。
  const showEnd = input.showEndAnchors !== false;
  const parent = new Map<string, string>();
  for (const n of specNodes) parent.set(n.id, n.id);
  const find = (x: string): string => {
    let root = x;
    while (parent.get(root) !== root) root = parent.get(root)!;
    let cur = x;
    while (cur !== root) {
      const next = parent.get(cur)!;
      parent.set(cur, root);
      cur = next;
    }
    return root;
  };
  for (const e of edges) {
    const a = find(e.src);
    const b = find(e.dst);
    if (a !== b) parent.set(a, b);
  }
  const compIndex = new Map<string, number>();
  for (const n of specNodes) {
    const root = find(n.id);
    if (!compIndex.has(root)) compIndex.set(root, compIndex.size);
  }
  const compCount = compIndex.size;
  const compSources: string[][] = Array.from({ length: compCount }, () => []);
  const compSinks: string[][] = Array.from({ length: compCount }, () => []);
  for (const n of specNodes) {
    const ci = compIndex.get(find(n.id))!;
    if (!hasIn.has(n.id)) compSources[ci].push(n.id);
    if (!hasOut.has(n.id)) compSinks[ci].push(n.id);
  }

  const centerY = (ids: string[]) => {
    const ys = ids.map((id) => nodeById.get(id)!.y + NODE_H / 2);
    return ys.length ? ys.reduce((a, b) => a + b, 0) / ys.length : height / 2;
  };

  // ── 边：普通边 + 锚点接入边；traversed 由显式 transition 事实判定 ──
  const transitions = input.transitions ?? [];
  const rootEnded = input.rootEnded ?? false;
  const layoutEdges: LaidEdge[] = edges.map((e) => {
    const traversed = edgeTraversed(
      input.executed.get(e.src),
      input.executed.get(e.dst),
      transitions,
    );
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

  for (let ci = 0; ci < compCount; ci += 1) {
    if (compSources[ci].length) {
      const startAnchor: LaidNode = {
        nodeId: `__start__#${ci}`,
        label: '开始',
        status: 'anchor',
        outcome: '',
        instances: 0,
        lane: '',
        x: CANVAS_PAD,
        y: centerY(compSources[ci]) - ANCHOR_H / 2,
        anchor: 'start',
        component: ci,
      };
      nodes.push(startAnchor);
      for (const id of compSources[ci]) {
        const traversed = nodeStarted(input.executed.get(id));
        layoutEdges.push({
          id: `${startAnchor.nodeId}->${id}`,
          from: startAnchor,
          to: nodeById.get(id)!,
          kind: 'order',
          label: '',
          traversed,
          active: traversed,
        });
      }
    }
    if (showEnd && compSinks[ci].length) {
      const endAnchor: LaidNode = {
        nodeId: `__end__#${ci}`,
        label: '结束',
        status: 'anchor',
        outcome: '',
        instances: 0,
        lane: '',
        x: contentW,
        y: centerY(compSinks[ci]) - ANCHOR_H / 2,
        anchor: 'end',
        component: ci,
      };
      nodes.push(endAnchor);
      for (const id of compSinks[ci]) {
        // 终点锚（修复计划 §6.4）：依据真实 root finish（rootEnded），
        // 不由静态 sink + 节点到达推断「运行结束」。
        const traversed = rootEnded && nodeArrived(input.executed.get(id));
        layoutEdges.push({
          id: `${id}->${endAnchor.nodeId}`,
          from: nodeById.get(id)!,
          to: endAnchor,
          kind: 'order',
          label: '',
          traversed,
          active: traversed,
        });
      }
    }
  }

  return {
    nodes,
    edges: layoutEdges,
    width: contentW + CANVAS_PAD + (showEnd ? ANCHOR_W : 0),
    height,
  };
}

// ============================================================
// O05/R3（修复计划 §6.4）：「两端点出现过」≠「边已执行」。
// traversed 只由**显式 transition 事实**激活（fact_kind='transition'，
// 携带 transition_v=1、from_node/to_node 与 attempt）；兄弟 span、同
// instance_key、时间先后都不构成到达。legacy 事件（无 transition）一律
// 显示为静态未确认，不虚构路径。
// ============================================================

/** 流程确实在该节点启动过（start 事件）。 */
function nodeStarted(state: FlowNodeState | undefined): boolean {
  return Boolean(state?.events.some((e) => e.kind === 'start'));
}

/** 有真实到达事实收束在该节点（finish/decision，不含边级 transition）。 */
function nodeArrived(state: FlowNodeState | undefined): boolean {
  return Boolean(
    state?.events.some(
      (e) =>
        e.fact_kind !== 'transition' &&
        (e.kind === 'finish' || e.kind === 'decision'),
    ),
  );
}

/** transition 事实是否激活 spec 边 src→dst（修复计划 §6.4 合同）：
 * 1. metrics.transition_v === 1 且 from/to 节点与边端点一致；
 * 2. attempt 匹配：transition 的 attempt 必须在两端各有一条同 attempt 的
 *    发起/到达事实（跨 attempt 不串边）；
 * 3. 事件归属由调用方保证同 trace（事件按 trace 拉取）。 */
export function edgeTraversed(
  src: FlowNodeState | undefined,
  dst: FlowNodeState | undefined,
  transitions: FlowEvent[] = [],
): boolean {
  if (!src || !dst) return false;
  return transitions.some((t) => {
    const m = (t.metrics ?? {}) as Record<string, unknown>;
    if (Number(m.transition_v ?? 0) !== 1) return false;
    if (String(m.from_node ?? '') !== src.nodeId) return false;
    if (String(m.to_node ?? '') !== dst.nodeId) return false;
    const tAttempt = Number(t.attempt ?? 0) || 0;
    const departed = src.events.some(
      (e) =>
        e.fact_kind !== 'transition' &&
        (e.kind === 'start' || e.kind === 'decision') &&
        (e.attempt ?? 0) === tAttempt,
    );
    const arrived = dst.events.some(
      (e) =>
        e.fact_kind !== 'transition' &&
        (e.kind === 'finish' || e.kind === 'decision') &&
        (e.attempt ?? 0) === tAttempt,
    );
    return departed && arrived;
  });
}

/** 画布视图状态（修复计划外外观反馈：右键平移 + 滚轮缩放）。 */
export interface ViewState {
  x: number;
  y: number;
  scale: number;
}

export const ZOOM_MIN = 0.35;
export const ZOOM_MAX = 3;

/** 以画布上的一点 (px, py) 为锚缩放：该点在缩放前后保持原位。 */
export function zoomAround(
  view: ViewState,
  px: number,
  py: number,
  factor: number,
): ViewState {
  const scale = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, view.scale * factor));
  const ratio = scale / view.scale;
  return {
    scale,
    x: px - (px - view.x) * ratio,
    y: py - (py - view.y) * ratio,
  };
}

/** 以内容包围盒适配视口：返回整体缩放 + 居中平移（外观反馈 2）。 */
export function fitAround(
  bounds: { minX: number; minY: number; maxX: number; maxY: number },
  viewport: { width: number; height: number },
  pad = 28,
  maxScale = 1.25,
): ViewState {
  const bw = bounds.maxX - bounds.minX + pad * 2;
  const bh = bounds.maxY - bounds.minY + pad * 2;
  const scale = Math.min(
    ZOOM_MAX,
    Math.max(ZOOM_MIN, Math.min(viewport.width / bw, viewport.height / bh, maxScale)),
  );
  const cx = (bounds.minX + bounds.maxX) / 2;
  const cy = (bounds.minY + bounds.maxY) / 2;
  return {
    scale,
    x: viewport.width / 2 - cx * scale,
    y: viewport.height / 2 - cy * scale,
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
