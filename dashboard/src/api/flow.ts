import { api, unwrap } from './http';

// 消息流程 API（计划 §6.6）：types 与后端 webui/services/flow.py 对齐。

export interface FlowMessageSummary {
  trace_id: string;
  root_kind: string;
  platform: string;
  scope: string;
  source_message_key: string;
  started_utc: string;
  ended_utc: string;
  outcome: string;
  // O01 修复后的活跃判定（计划 §6.1）：running=活跃在跑；interrupted=过期化身
  status: string; // running | interrupted | 已知终态
  complete: boolean;
  loss: boolean;
  // 完整性权威账本（M1 后端合同；旧 schema 兼容缺省）
  integrity?: '' | 'complete' | 'partial' | 'unknown';
  lost_events?: number;
  persisted_events?: number;
  producer_ended?: boolean;
  process_kind?: string;
  last_heartbeat_utc?: string;
}

export interface FlowSpanView {
  span_id: string;
  node_id: string;
  instance_key: string;
  parent_span_id: string;
  seq: number;
  started_utc: string;
  ended_utc: string;
  duration_ms: number | null;
  status: string;
  reason_code: string;
  attempt: number; // 同一节点第 N 次尝试（重试/重入，计划 §6.1 instance 合同）
}

export interface FlowRelationView {
  direction: 'in' | 'out';
  trace_id: string;
  kind: string;
  evidence: string;
}

export interface FlowMessageDetail extends FlowMessageSummary {
  topology_version: string;
  process_instance_id: string;
  detail: Record<string, unknown>;
  event_count: number;
  high_watermark: number;
  spans: FlowSpanView[];
  relations: FlowRelationView[];
  // M1 观测合同增量（计划 §6.1 root/run 行；旧 schema 兼容缺省）
  process_kind?: string;
  origin?: string;
  trigger?: string;
  route?: string;
  business_ts?: string;
  spec_digest?: string;
  integrity?: '' | 'complete' | 'partial' | 'unknown';
  lost_events?: number;
  persisted_events?: number;
  producer_ended?: boolean;
  // 修复计划 §6.1/§6.2（M5）：规范身份与 spec 绑定完整性
  conversation_key?: string;
  bot_id?: string;
  conversation_kind?: string;
  peer_id?: string;
  storage_session_id?: number | null;
  source_message_id?: string;
  identity_state?: string;
  spec_binding?: 'exact' | 'legacy_unverified' | 'missing' | 'invalid' | string;
}

export interface FlowEvent {
  row_id: number;
  event_id: string;
  span_id: string;
  parent_span_id: string;
  node_id: string;
  instance_key: string;
  seq: number;
  kind: 'start' | 'finish' | 'decision' | 'link' | 'checkpoint' | 'trace_end';
  status: string;
  reason_code: string;
  ts_utc: string;
  duration_ms: number | null;
  summary: string;
  metrics: Record<string, unknown>;
  // M1 事件合同增量（计划 §6.1 event/transition 行；旧 schema 兼容缺省）
  attempt?: number;
  fact_kind?: '' | 'transition' | 'guard' | 'state' | 'commit' | 'receipt' | string;
  error_code?: string;
}

export interface FlowNodeSpec {
  id: string;
  label: string;
  lane: string;
  kind: string;
  derived?: boolean;
  opaque?: boolean;
  // manifest schema3：真实源码锚点（验收报告 M5 闭包视图）
  source_ref?: { file: string; symbol: string; body_hash: string };
}

export interface FlowClosureItem {
  kind: string;
  line: number;
  target?: string;
  resolved?: string;
  [key: string]: unknown;
}

export interface FlowSourceClosure {
  entry: { items: FlowClosureItem[]; counts: Record<string, number>; truncated?: boolean };
  reachable_symbols: Array<{
    file: string;
    qualname: string;
    body_hash: string;
    resolution: string;
  }>;
  reachable_truncated?: boolean;
  boundaries: Array<{ target: string; resolution: string }>;
}

export interface FlowEdgeSpec {
  src: string;
  dst: string;
  kind: string;
  label: string;
}

export interface FlowSpec {
  schema_version: number;
  topology_version: string;
  lanes: Array<[string, string]>;
  // 注意：manifest 里 nodes 是数组（scripts/generate_message_flow.py 按序
  // 序列化）；按 ID 查要用 specNodeById。2026-10-02 之前这里误写成 Record，
  // 导致所有目录标签查不到、画布整片显示裸 ID。
  nodes: FlowNodeSpec[];
  edges: FlowEdgeSpec[];
  entry_roots: Record<string, string>;
  // manifest schema3（验收报告 M5）：逐节点源码闭包与边界分类
  source_closure?: Record<string, FlowSourceClosure>;
}

export interface MessageQuery {
  platform?: string;
  root_kind?: string;
  outcome?: string;
  limit?: number;
  offset?: number;
  // 修复计划 §6.6（R8）：keyset 续读游标（started_utc|trace_id）
  cursor?: string;
}

export async function listMessages(q: MessageQuery = {}): Promise<{
  total: number;
  items: FlowMessageSummary[];
  next_cursor?: string | null;
}> {
  return unwrap(
    api.get('/trace/messages', { params: q }),
  ) as Promise<{ total: number; items: FlowMessageSummary[]; next_cursor?: string | null }>;
}

export async function getMessage(traceId: string): Promise<FlowMessageDetail> {
  return unwrap(api.get(`/trace/messages/${traceId}`)) as Promise<FlowMessageDetail>;
}

export async function getEvents(
  traceId: string,
  after = 0,
  limit = 1000,
  until = 0,
): Promise<FlowEvent[]> {
  const data = (await unwrap(
    api.get(`/trace/messages/${traceId}/events`, {
      params: until > 0 ? { after, limit, until } : { after, limit },
    }),
  )) as { items: FlowEvent[] };
  return data.items;
}

export interface FlowMessageIo {
  input: {
    user_id: string;
    content: string;
    msg_id: number;
    // 修复计划 §6.3（M5）：exact=注册表存储键精确命中；legacy_partial=旧兜底
    identity_state?: string;
  } | null;
  output: { lines: string[]; count: number };
  notes: string[];
}

export async function getMessageIo(traceId: string): Promise<FlowMessageIo> {
  return unwrap(
    api.get(`/trace/messages/${traceId}/context`),
  ) as Promise<FlowMessageIo>;
}

export async function getSpec(version: string): Promise<FlowSpec> {
  return unwrap(
    api.get(`/trace/flow/specs/${encodeURIComponent(version)}`),
  ) as Promise<FlowSpec>;
}

/** 按内容 digest 精确读取归档 spec（修复计划 §6.2/M5）：404 不回退。 */
export async function getSpecByDigest(
  version: string,
  digest: string,
): Promise<FlowSpec> {
  return unwrap(
    api.get(`/trace/flow/specs/${encodeURIComponent(version)}`, {
      params: { digest },
    }),
  ) as Promise<FlowSpec>;
}

export async function getSpecVersion(): Promise<string> {
  const data = (await unwrap(api.get('/trace/flow/spec-version'))) as {
    topology_version: string;
  };
  return data.topology_version;
}

/** SSE 事件流 URL（经 sseStream 带 Authorization 拉取）。 */
export function streamUrl(traceId: string, after = 0): string {
  return `/api/v1/trace/messages/${traceId}/stream?after=${after}`;
}

// ============================================================
// 对象履历（计划 §6.6 对象视角；M1 新增 API，运行 ↔ 对象互查）
// ============================================================

export interface FlowEntityChange {
  entity_type: string;
  entity_id: string;
  from_state: string;
  to_state: string;
  ts_utc: string;
  [key: string]: unknown;
}

/** 一次运行触及的全部对象变化（运行视角）。 */
export async function getTraceEntities(traceId: string): Promise<FlowEntityChange[]> {
  const data = (await unwrap(
    api.get(`/trace/messages/${traceId}/entities`),
  )) as { items: FlowEntityChange[] };
  return data.items;
}

/** 单实体履历（对象视角反查：哪些 run 改了它）。 */
export async function getEntityHistory(
  entityType: string,
  entityId: string,
): Promise<FlowEntityChange[]> {
  const data = (await unwrap(
    api.get(`/trace/entities/${encodeURIComponent(entityType)}/${encodeURIComponent(entityId)}`),
  )) as { items: FlowEntityChange[] };
  return data.items;
}
