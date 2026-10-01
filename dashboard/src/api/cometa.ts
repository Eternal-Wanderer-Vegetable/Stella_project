// SPDX-License-Identifier: AGPL-3.0
// Copyright (c) 2026 Stella Project Contributors
// cometa 外部 Agent 任务 API 客户端（design_docs/Cometa 外部 Agent 任务运行层
// 实施方案 v1.0 §6.14）。envelope 约定见 webui/responses.py（{status,message,data}），
// unwrap 在 http.ts；本文件只做形状转换，不持有业务状态。
import { api, unwrap } from '@/api/http';

export interface CometaTask {
  task_id: string;
  short_id: string;
  state: string;
  backend_id: string;
  attempt_no: number;
  phase: string;
  last_activity_at: string | null;
  heartbeat_at: string | null;
  deadline_at: string | null;
  waiting_request_id: string;
  waiting_question?: string;
  waiting_kind?: string;
  waiting_revision?: number;
  delivery_state: string;
  created_at: string | null;
  updated_at: string | null;
}

export interface CometaEvent {
  sequence: number;
  kind: string;
  occurred_at: string | null;
  payload: Record<string, unknown>;
}

export interface CometaResult {
  outcome: string;
  summary: string;
  final_text_ref: string;
  verification_status: string;
  artifacts: {
    artifact_id: string;
    display_name: string;
    sha256: string;
    size: number;
    mime: string;
  }[];
  limitations: string[];
  error: string;
  usage: Record<string, unknown>;
}

export interface CometaBackend {
  backend_id: string;
  type: string;
  capabilities: string[];
}

export interface CometaHealth {
  state: string;
  message?: string;
  reason?: string;
  config_hash?: string;
  backends?: string[];
}

export function getHealth(): Promise<CometaHealth> {
  return unwrap(api.get('/cometa/health'));
}

export function listTasks(cursor = 0): Promise<{ tasks: CometaTask[]; next_cursor: number }> {
  return unwrap(api.get('/cometa/tasks', { params: { cursor } }));
}

export function getTask(taskId: string): Promise<CometaTask> {
  return unwrap(api.get(`/cometa/tasks/${taskId}`));
}

export function listEvents(taskId: string, afterSequence = 0): Promise<{ events: CometaEvent[]; next_sequence: number }> {
  return unwrap(api.get(`/cometa/tasks/${taskId}/events`, { params: { after_sequence: afterSequence } }));
}

export function getResult(taskId: string): Promise<CometaResult> {
  return unwrap(api.get(`/cometa/tasks/${taskId}/result`));
}

export function listBackends(): Promise<{ backends: CometaBackend[] }> {
  return unwrap(api.get('/cometa/backends'));
}

export function submitTask(payload: { objective: string; idempotency_key: string; request_id?: string }): Promise<{ task_id: string }> {
  return unwrap(api.post('/cometa/tasks', payload));
}

export function cancelTask(taskId: string, idempotencyKey: string): Promise<{ status: string; state: string }> {
  return unwrap(api.post(`/cometa/tasks/${taskId}/cancel`, { idempotency_key: idempotencyKey }));
}

export function respondInput(taskId: string, requestId: string, answer: string, expectedRevision: number): Promise<{ status: string }> {
  return unwrap(api.post(`/cometa/tasks/${taskId}/inputs/${requestId}`, { answer, expected_revision: expectedRevision }));
}

export function artifactDownloadUrl(taskId: string, artifactId: string): string {
  return `/api/v1/cometa/tasks/${taskId}/artifacts/${artifactId}`;
}

// ── 后端认证管理（codex_auth；秘密零回显：状态只含 has_api_key 布尔）──

export interface CometaAuthStatus {
  backend_id: string;
  mode: string; // ready_custom | ready_chatgpt | ready_api_key | legacy | none
  ready: boolean;
  reason: string;
  has_api_key: boolean;
  has_custom_endpoint: boolean;
  legacy_available: boolean;
  account: Record<string, string> | null;
}

export interface CometaDeviceLogin {
  session_id: string;
  state: string; // pending | completed | failed
  user_code: string;
  verification_url: string;
  account: Record<string, string> | null;
  error: string;
}

export function getAuthStatus(backendId: string): Promise<CometaAuthStatus> {
  return unwrap(api.get(`/cometa/backends/${backendId}/auth/status`));
}

export function applyApiKey(backendId: string, apiKey: string): Promise<CometaAuthStatus> {
  return unwrap(api.post(`/cometa/backends/${backendId}/auth/api-key`, { api_key: apiKey }));
}

export function applyCustomEndpoint(
  backendId: string,
  payload: { base_url: string; api_key: string; model: string; wire_api?: string },
): Promise<CometaAuthStatus> {
  return unwrap(api.post(`/cometa/backends/${backendId}/auth/custom-endpoint`, payload));
}

export function startDeviceLogin(backendId: string): Promise<CometaDeviceLogin> {
  return unwrap(api.post(`/cometa/backends/${backendId}/auth/device-login`, {}));
}

export function getDeviceLogin(backendId: string, sessionId: string): Promise<CometaDeviceLogin> {
  return unwrap(api.get(`/cometa/backends/${backendId}/auth/device-login/${sessionId}`));
}

export function migrateLegacyAuth(backendId: string): Promise<CometaAuthStatus> {
  return unwrap(api.post(`/cometa/backends/${backendId}/auth/migrate-legacy`, {}));
}

export function logoutBackend(backendId: string): Promise<CometaAuthStatus> {
  return unwrap(api.post(`/cometa/backends/${backendId}/auth/logout`, {}));
}

export function testAuthEndpoint(
  backendId: string,
  payload: { base_url: string; api_key: string },
): Promise<{ models: string[]; error: string }> {
  return unwrap(api.post(`/cometa/backends/${backendId}/auth/test`, payload));
}
