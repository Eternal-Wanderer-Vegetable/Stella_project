import type { FlowEvent } from '@/api/flow';

// 消息流程投影 reducer（计划 §6.7）：纯函数、无副作用——回放/实时共用
// 同一份投影逻辑，任何动作都不发消息、不写业务（历史播放零副作用）。

export interface FlowNodeState {
  nodeId: string;
  label: string;
  status: string; // 投影出的展示状态
  businessOutcome: string; // reason/summary 携带的业务事实
  instances: number; // 事件实例数（重试/多段/多轮）
  firstSeq: number;
  lastTs: string;
  durationMs: number | null;
  metrics: Array<Record<string, unknown>>;
  events: FlowEvent[];
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

/** 单节点投影：以「最近事件」为展示状态；finish 缺失即 running（计划 §6.2：
 * start 无 finish 是中断/在途，绝不显示成 skipped/succeeded）。 */
export function projectNode(
  nodeId: string,
  events: FlowEvent[],
  label: string,
): FlowNodeState {
  let status = 'not_observed';
  let businessOutcome = '';
  let durationMs: number | null = null;
  let lastTs = '';
  const metrics: Array<Record<string, unknown>> = [];
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
    if (Object.keys(ev.metrics ?? {}).length > 0) metrics.push(ev.metrics);
  }
  return {
    nodeId,
    label,
    status,
    businessOutcome,
    instances: new Set(
      events.map((e) => e.instance_key || e.span_id || e.event_id),
    ).size,
    firstSeq: events.length ? events[0].seq : 0,
    lastTs,
    durationMs,
    metrics,
    events,
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
