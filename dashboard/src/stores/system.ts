import { computed, ref } from 'vue';
import { defineStore } from 'pinia';

import { SseAuthError, sseStream } from '@/api/sse';
import {
  idempotencyKey,
  isManagedSystemStatus,
  systemApi,
  type OperationStatus,
  type SystemStatus,
} from '@/api/system';

interface PendingApply {
  revisionId: string;
  key: string;
}

const PENDING_APPLY_KEY = 'stella-system-pending-apply-v1';
const TERMINAL_PHASES = new Set(['succeeded', 'rolled_back', 'failed']);

function readPendingApply(): PendingApply | null {
  try {
    const value = sessionStorage.getItem(PENDING_APPLY_KEY);
    if (!value) return null;
    const parsed = JSON.parse(value) as Partial<PendingApply>;
    return typeof parsed.revisionId === 'string' && typeof parsed.key === 'string'
      ? { revisionId: parsed.revisionId, key: parsed.key }
      : null;
  } catch {
    return null;
  }
}

function writePendingApply(value: PendingApply | null): void {
  try {
    if (value) sessionStorage.setItem(PENDING_APPLY_KEY, JSON.stringify(value));
    else sessionStorage.removeItem(PENDING_APPLY_KEY);
  } catch {
    // Storage can be disabled in embedded browsers; status polling still recovers accepted work.
  }
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

export const useSystemStore = defineStore('system', () => {
  const status = ref<SystemStatus | null>(null);
  const operation = ref<OperationStatus | null>(null);
  const managed = ref(false);
  const controlAvailable = ref(true);
  const statusError = ref('');
  const operationError = ref('');
  const lastEventId = ref(0);

  const coreGeneration = computed(() => status.value?.core?.generation_id ?? null);
  const coreReady = computed(() =>
    managed.value
    && controlAvailable.value
    && status.value?.core?.phase === 'ready'
    && status.value.core.stale !== true,
  );
  const coreUnavailable = computed(() => managed.value && !coreReady.value);
  const revisionsMatch = computed(() =>
    managed.value
    && Boolean(status.value?.desired_revision)
    && status.value?.desired_revision === status.value?.applied_revision,
  );
  const operationPending = computed(() => Boolean(operation.value && !operation.value.terminal));

  let monitorTimer: number | null = null;
  let statusInFlight = false;
  let trackingOperationId: string | null = null;
  let streamController: AbortController | null = null;
  let pendingApplyInFlight = false;
  let nextPendingRetryAt = 0;
  let pendingRetryDelay = 1000;

  function noteDesiredRevision(revisionId: string): void {
    if (!status.value) return;
    status.value = { ...status.value, desired_revision: revisionId };
  }

  function setOperation(value: OperationStatus): void {
    operation.value = {
      ...value,
      terminal: value.terminal || TERMINAL_PHASES.has(value.phase),
    };
    operationError.value = value.error_code ?? '';
    if (operation.value.terminal) {
      const pending = readPendingApply();
      if (pending && pending.revisionId === value.target_revision) writePendingApply(null);
      if (status.value) {
        status.value = { ...status.value, last_operation: operation.value };
      }
    }
  }

  async function refreshStatus(): Promise<SystemStatus | null> {
    if (statusInFlight) return status.value;
    statusInFlight = true;
    try {
      const next = await systemApi.status();
      status.value = next;
      controlAvailable.value = true;
      statusError.value = '';
      managed.value = isManagedSystemStatus(next);
      if (managed.value && next.last_operation) {
        setOperation(next.last_operation);
        if (!next.last_operation.terminal) void followOperation(next.last_operation.operation_id);
      }
      return next;
    } catch (error) {
      // A failed core does not evict the browser session or send the user to the whole-backend
      // offline page. Only the auth client's genuine 401 policy may clear a JWT.
      controlAvailable.value = false;
      statusError.value = errorMessage(error);
      return null;
    } finally {
      statusInFlight = false;
    }
  }

  async function refreshOperation(operationId: string): Promise<OperationStatus | null> {
    try {
      const current = await systemApi.operation(operationId);
      setOperation(current);
      return current;
    } catch (error) {
      operationError.value = errorMessage(error);
      return null;
    }
  }

  async function followOperation(operationId: string): Promise<void> {
    if (trackingOperationId === operationId) return;
    trackingOperationId = operationId;
    let reconnectDelay = 400;
    try {
      while (trackingOperationId === operationId) {
        const controller = new AbortController();
        streamController = controller;
        try {
          await sseStream(
            `/api/v1/system/operations/${encodeURIComponent(operationId)}/events`,
            (eventId, data) => {
              if (eventId) lastEventId.value = Math.max(lastEventId.value, Number(eventId) || 0);
              try {
                const payload = JSON.parse(data) as Partial<OperationStatus> & {
                  id?: number;
                  phase?: string;
                  data?: { error_code?: string | null; recovery_attempted?: boolean | null };
                };
                if (payload.operation_id) {
                  setOperation(payload as OperationStatus);
                } else if (payload.phase) {
                  const previous = operation.value;
                  if (previous?.operation_id === operationId) {
                    setOperation({
                      ...previous,
                      phase: payload.phase,
                      terminal: TERMINAL_PHASES.has(payload.phase),
                      error_code: payload.data?.error_code ?? previous.error_code,
                      recovery_attempted: payload.data?.recovery_attempted ?? previous.recovery_attempted,
                    });
                  }
                }
              } catch {
                // Ignore malformed or forward-compatible event payloads; snapshot polling recovers.
              }
            },
            {
              signal: controller.signal,
              lastEventId: lastEventId.value ? String(lastEventId.value) : undefined,
            },
          );
        } catch (error) {
          if (controller.signal.aborted || error instanceof SseAuthError) return;
          operationError.value = errorMessage(error);
        } finally {
          if (streamController === controller) streamController = null;
        }

        if (trackingOperationId !== operationId || operation.value?.terminal) break;
        const snapshot = await refreshOperation(operationId);
        if (snapshot?.terminal) break;
        await delay(reconnectDelay);
        reconnectDelay = Math.min(4000, reconnectDelay * 2);
      }
    } finally {
      if (trackingOperationId === operationId) trackingOperationId = null;
      if (operation.value?.terminal) {
        void refreshStatus();
      }
    }
  }

  async function recoverPendingApply(): Promise<void> {
    if (!managed.value || pendingApplyInFlight || Date.now() < nextPendingRetryAt) return;
    const pending = readPendingApply();
    if (!pending) return;
    const last = status.value?.last_operation;
    if (last?.kind === 'apply' && last.target_revision === pending.revisionId) {
      setOperation(last);
      if (!last.terminal) void followOperation(last.operation_id);
      else writePendingApply(null);
      return;
    }
    if (status.value?.desired_revision !== pending.revisionId) {
      writePendingApply(null);
      return;
    }
    pendingApplyInFlight = true;
    try {
      const accepted = await systemApi.apply(pending.revisionId, pending.key);
      setOperation(accepted);
      void followOperation(accepted.operation_id);
      nextPendingRetryAt = 0;
      pendingRetryDelay = 1000;
    } catch (error) {
      const code = (error as { response?: { status?: number } }).response?.status;
      if (code === 400 || code === 409) writePendingApply(null);
      nextPendingRetryAt = Date.now() + pendingRetryDelay;
      pendingRetryDelay = Math.min(10000, pendingRetryDelay * 2);
    } finally {
      pendingApplyInFlight = false;
    }
  }

  async function applyRevision(revisionId: string): Promise<OperationStatus> {
    if (!managed.value) throw new Error('当前运行模式不支持受管配置应用');
    if (!revisionId) throw new Error('配置 revision 缺失，无法应用');
    if (operationPending.value && operation.value?.target_revision !== revisionId) {
      throw new Error('另一个配置操作正在执行，请等待完成后重试');
    }
    const key = idempotencyKey('apply');
    const pending = { revisionId, key };
    writePendingApply(pending);
    try {
      const accepted = await systemApi.apply(revisionId, key);
      setOperation(accepted);
      void followOperation(accepted.operation_id);
      return accepted;
    } catch (error) {
      await refreshStatus();
      const last = status.value?.last_operation;
      if (last?.kind === 'apply' && last.target_revision === revisionId) {
        setOperation(last);
        if (!last.terminal) void followOperation(last.operation_id);
        else writePendingApply(null);
        return last;
      }
      throw error;
    }
  }

  async function startMonitoring(): Promise<void> {
    if (monitorTimer !== null) return;
    await refreshStatus();
    if (managed.value || !status.value) {
      monitorTimer = window.setInterval(() => {
        void refreshStatus().then(() => recoverPendingApply());
      }, 2500);
    }
    if (managed.value) void recoverPendingApply();
  }

  function stopMonitoring(): void {
    if (monitorTimer !== null) {
      window.clearInterval(monitorTimer);
      monitorTimer = null;
    }
    trackingOperationId = null;
    streamController?.abort();
    streamController = null;
  }

  return {
    status,
    operation,
    managed,
    controlAvailable,
    statusError,
    operationError,
    coreGeneration,
    coreReady,
    coreUnavailable,
    revisionsMatch,
    operationPending,
    noteDesiredRevision,
    refreshStatus,
    applyRevision,
    startMonitoring,
    stopMonitoring,
  };
});
