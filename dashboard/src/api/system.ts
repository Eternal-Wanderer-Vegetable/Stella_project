import { api, unwrap } from './http';

export interface CoreStatus {
  desired?: string;
  phase: string;
  instance_id?: string;
  controller_boot_id?: string;
  revision_id?: string;
  generation_id?: string | null;
  pid?: number | null;
  attempt?: number;
  error?: string | null;
  updated_at?: string;
  stale?: boolean;
  stale_age_seconds?: number | null;
}

export interface OperationStatus {
  operation_id: string;
  kind: string;
  phase: string;
  target_revision?: string | null;
  previous_applied_revision?: string | null;
  applied_revision?: string | null;
  restart_scope?: string;
  error_code?: string | null;
  recovery_attempted?: boolean;
  generation_id?: string | null;
  terminal: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface SystemStatus {
  control?: {
    phase: string;
    controller_boot_id?: string;
    instance_id?: string;
    protocol_version?: number;
  };
  core?: CoreStatus;
  desired_revision?: string;
  applied_revision?: string;
  desired_core?: string;
  external_conflict?: boolean;
  last_operation?: OperationStatus | null;
}

export interface ApplyResponse extends OperationStatus {
  ok?: boolean;
}

export function isManagedSystemStatus(value: unknown): value is SystemStatus {
  if (!value || typeof value !== 'object') return false;
  const status = value as SystemStatus;
  return status.control?.phase === 'ready'
    && status.control.protocol_version === 1
    && typeof status.desired_revision === 'string'
    && typeof status.applied_revision === 'string'
    && Boolean(status.core && typeof status.core.phase === 'string');
}

export function idempotencyKey(scope = 'dashboard'): string {
  const uuid = globalThis.crypto?.randomUUID?.()
    ?? `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
  return `${scope}:${uuid}`;
}

export function revisionWriteOptions(revision: string | null | undefined, key: string) {
  const headers: Record<string, string> = { 'Idempotency-Key': key };
  if (revision) headers['If-Match'] = revision;
  return { headers };
}

export const systemApi = {
  async status(): Promise<SystemStatus> {
    return unwrap<SystemStatus>(api.get('/status'));
  },
  async apply(revisionId: string, key: string): Promise<ApplyResponse> {
    return unwrap<ApplyResponse>(
      api.post('/system/apply', { revision_id: revisionId }, {
        headers: { 'Idempotency-Key': key },
      }),
    );
  },
  async operation(operationId: string): Promise<OperationStatus> {
    return unwrap<OperationStatus>(
      api.get(`/system/operations/${encodeURIComponent(operationId)}`),
    );
  },
};
