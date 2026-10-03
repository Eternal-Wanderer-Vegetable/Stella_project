import type { FlowEvent } from '@/api/flow';

// 消息流程投影 reducer（计划 §6.7）：纯函数、无副作用——回放/实时共用
// 同一份投影逻辑，任何动作都不发消息、不写业务（历史播放零副作用）。

export interface FlowInstanceState {
  key: string; // 实例键（instance_key || span_id || 匿名桶 与 attempt 组合）
  status: string; // 实例自己的展示状态
  businessOutcome: string; // 实例自己的业务事实（不跨实例继承）
  firstSeq: number;
  lastSeq: number;
  lastTs: string;
  durationMs: number | null;
}

export interface FlowNodeState {
  nodeId: string;
  label: string;
  status: string; // 聚合展示状态：有 running 实例 → running，否则 latest 实例状态
  businessOutcome: string; // latest 实例的业务事实（失败 reason 不继承到新实例）
  instances: number; // 事件实例数（重试/多段/多轮）
  firstSeq: number;
  lastTs: string;
  durationMs: number | null;
  metrics: Array<Record<string, unknown>>;
  events: FlowEvent[];
  // O06（计划 §2.2/§6.6）：先按实例投影、再聚合到节点——跨并行不把
  // latest 颜色当唯一事实，同一节点后来的 start 不被旧 finish 吞掉。
  running_count: number;
  succeeded_count: number;
  failed_count: number;
  latest: FlowInstanceState | null;
}

/** 事件去重（event_id 幂等键）+ 按 row_id 稳定排序（回放权威，计划 §6.5）。 */
export function dedupeAndOrder(events: FlowEvent[]): FlowEvent[] {
  const seen = new Set<string>();
  const uniq = events.filter((e) => {
    if (seen.has(e.event_id)) return false;
    seen.add(e.event_id);
    return true;
  });
  return uniq.sort((a, b) => a.row_id - b.row_id);
}

/** 实例键（计划 §6.1 instance 合同）：instance_key || span_id，与 attempt
 * 组合。两者都缺（legacy 形状）时归入同一匿名桶——按 event_id 拆会把同一段
 * 连续事实撕成互不相干的"实例"，旧 finish 反过来吞掉后续 start。 */
function instanceKeyOf(ev: FlowEvent): string {
  const base = ev.instance_key || ev.span_id || '__anon__';
  return `${base}#${ev.attempt ?? 0}`;
}

/** 单实例投影：与旧「最近事件定状态」语义一致，只是作用域缩到一个实例
 * （计划 §6.2：start 无 finish 是中断/在途，绝不显示成 skipped/succeeded）。 */
function projectInstance(key: string, events: FlowEvent[]): FlowInstanceState {
  let status = 'not_observed';
  let businessOutcome = '';
  let durationMs: number | null = null;
  let lastTs = '';
  for (const ev of events) {
    lastTs = ev.ts_utc || lastTs;
    if (
      ev.kind === 'finish' ||
      ev.kind === 'decision' ||
      ev.kind === 'trace_end'
    ) {
      status = ev.status || status;
      businessOutcome = ev.reason_code || ev.summary || businessOutcome;
    } else if (ev.kind === 'checkpoint') {
      status = 'succeeded';
      businessOutcome = ev.summary || businessOutcome;
    } else if (ev.kind === 'start' && status === 'not_observed') {
      status = 'running';
    }
    if (ev.duration_ms != null) durationMs = ev.duration_ms;
  }
  return {
    key,
    status,
    businessOutcome,
    firstSeq: events.length ? events[0].seq : 0,
    lastSeq: events.length ? events[events.length - 1].seq : 0,
    lastTs,
    durationMs,
  };
}

const FAILED_STATUSES = new Set(['failed', 'timed_out', 'error']);

/** 单节点投影：先按实例投影（O06），再聚合出节点级计数与 latest。
 * 节点 status：任一实例在跑 → running（新 start 不被旧 finish 吞掉）；
 * 否则取最新实例的状态。businessOutcome 只取 latest 实例自己的事实，
 * 失败 reason 不随新实例延续。 */
export function projectNode(
  nodeId: string,
  events: FlowEvent[],
  label: string,
): FlowNodeState {
  const byInstance = new Map<string, FlowEvent[]>();
  for (const ev of events) {
    const key = instanceKeyOf(ev);
    const list = byInstance.get(key);
    if (list) list.push(ev);
    else byInstance.set(key, [ev]);
  }
  const instanceStates = [...byInstance.entries()].map(([key, evs]) =>
    projectInstance(key, evs),
  );
  const running_count = instanceStates.filter(
    (s) => s.status === 'running',
  ).length;
  const succeeded_count = instanceStates.filter(
    (s) => s.status === 'succeeded',
  ).length;
  const failed_count = instanceStates.filter((s) =>
    FAILED_STATUSES.has(s.status),
  ).length;
  // latest：按实例内最后事件的 seq 取（事件按 encounter 序进入，尾即最新）
  let latest: FlowInstanceState | null = null;
  for (const s of instanceStates) {
    if (!latest || s.lastSeq >= latest.lastSeq) latest = s;
  }
  let durationMs: number | null = null;
  const metrics: Array<Record<string, unknown>> = [];
  let lastTs = '';
  for (const ev of events) {
    lastTs = ev.ts_utc || lastTs;
    if (ev.duration_ms != null) durationMs = ev.duration_ms;
    if (Object.keys(ev.metrics ?? {}).length > 0) metrics.push(ev.metrics);
  }
  return {
    nodeId,
    label,
    status:
      running_count > 0 ? 'running' : latest?.status ?? 'not_observed',
    businessOutcome: latest?.businessOutcome ?? '',
    instances: instanceStates.length,
    firstSeq: events.length ? events[0].seq : 0,
    lastTs,
    durationMs,
    metrics,
    events,
    running_count,
    succeeded_count,
    failed_count,
    latest,
  };
}

/** 事件流 → 节点状态列表（按首次出现顺序）。 */
export function projectNodes(
  events: FlowEvent[],
  labelOf: (nodeId: string) => string,
): FlowNodeState[] {
  const byNode = new Map<string, FlowEvent[]>();
  for (const ev of events) {
    const list = byNode.get(ev.node_id) ?? [];
    list.push(ev);
    byNode.set(ev.node_id, list);
  }
  return [...byNode.entries()]
    .map(([nodeId, evs]) => projectNode(nodeId, evs, labelOf(nodeId)))
    .sort((a, b) => a.firstSeq - b.firstSeq);
}

/** 未知节点的兜底标签（与 Python 侧 flow_catalog.node_label 对齐）。 */
export function fallbackNodeLabel(nodeId: string): string {
  if (nodeId.startsWith('hook.custom:')) {
    return `扩展钩子 ${nodeId.split(':')[1]}`;
  }
  return nodeId;
}

/** 估算字符串渲染宽度（CJK 记全宽，其余半宽）。 */
export function textWidth(text: string): number {
  let w = 0;
  for (const ch of text) {
    w += ch.charCodeAt(0) > 0xff ? 1 : 0.55;
  }
  return w;
}

/**
 * 节点框内文本截断（SVG text 不会自动换行/省略）：超宽按字符截断并加
 * "…"。完整文本始终在浮动详情卡可见。
 */
export function fitNodeText(text: string, maxWidth: number): string {
  if (textWidth(text) <= maxWidth) return text;
  let out = '';
  for (const ch of text) {
    if (textWidth(out + ch) > maxWidth - 1) {
      return `${out}…`;
    }
    out += ch;
  }
  return out;
}
