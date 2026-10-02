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
  status: string; // closed | interrupted
  complete: boolean;
  loss: boolean;
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
}

export interface FlowNodeSpec {
  id: string;
  label: string;
  lane: string;
  kind: string;
  derived?: boolean;
  opaque?: boolean;
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
  nodes: Record<string, FlowNodeSpec>;
  edges: FlowEdgeSpec[];
}

export interface MessageQuery {
  platform?: string;
  root_kind?: string;
  outcome?: string;
  limit?: number;
  offset?: number;
}

export async function listMessages(q: MessageQuery = {}): Promise<{
  total: number;
  items: FlowMessageSummary[];
}> {
  return unwrap(
    api.get('/trace/messages', { params: q }),
  ) as Promise<{ total: number; items: FlowMessageSummary[] }>;
}

export async function getMessage(traceId: string): Promise<FlowMessageDetail> {
  return unwrap(api.get(`/trace/messages/${traceId}`)) as Promise<FlowMessageDetail>;
}

export async function getEvents(
  traceId: string,
  after = 0,
  limit = 1000,
): Promise<FlowEvent[]> {
  const data = (await unwrap(
    api.get(`/trace/messages/${traceId}/events`, { params: { after, limit } }),
  )) as { items: FlowEvent[] };
  return data.items;
}

export async function getSpec(version: string): Promise<FlowSpec> {
  return unwrap(
    api.get(`/trace/flow/specs/${encodeURIComponent(version)}`),
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
