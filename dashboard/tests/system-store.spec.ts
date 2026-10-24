import { createPinia, setActivePinia } from 'pinia';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { idempotencyKey, isManagedSystemStatus, revisionWriteOptions, systemApi, type OperationStatus, type SystemStatus } from '@/api/system';
import { isControlPlaneEndpoint } from '@/api/http';
import { sseStream } from '@/api/sse';
import { useSystemStore } from '@/stores/system';

vi.mock('@/api/sse', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/sse')>();
  return { ...actual, sseStream: vi.fn() };
});

const managedStatus: SystemStatus = {
  control: { phase: 'ready', protocol_version: 1 },
  core: { phase: 'ready', stale: false, generation_id: 'generation-1' },
  desired_revision: 'revision-1',
  applied_revision: 'revision-1',
  last_operation: null,
};

function operation(overrides: Partial<OperationStatus> = {}): OperationStatus {
  return {
    operation_id: 'operation-1',
    kind: 'apply',
    phase: 'accepted',
    target_revision: 'revision-2',
    terminal: false,
    ...overrides,
  };
}

beforeEach(() => {
  setActivePinia(createPinia());
  vi.spyOn(systemApi, 'status').mockResolvedValue(managedStatus);
  vi.spyOn(systemApi, 'apply').mockResolvedValue(operation());
  vi.spyOn(systemApi, 'operation').mockResolvedValue(operation());
  vi.mocked(sseStream).mockResolvedValue();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('system API contracts', () => {
  it('distinguishes Corona managed status from the legacy status payload', () => {
    expect(isManagedSystemStatus(managedStatus)).toBe(true);
    expect(isManagedSystemStatus({ pid: 123, uptime_seconds: 5 })).toBe(false);
  });

  it('adds a revision CAS and unique idempotency key to managed writes', () => {
    const options = revisionWriteOptions('revision-1', idempotencyKey('config'));
    expect(options.headers['If-Match']).toBe('revision-1');
    expect(options.headers['Idempotency-Key']).toMatch(/^config:/);
  });

  it('only classifies controller endpoints as session-authentication authority', () => {
    for (const url of [
      '/api/v1/status',
      '/api/v1/config',
      '/api/v1/system/operations/op-1/events',
      '/api/v1/providers/endpoints',
      'https://localhost/api/v1/platform/onebot',
    ]) {
      expect(isControlPlaneEndpoint(url)).toBe(true);
    }
    for (const url of [
      '/api/v1/chat',
      '/api/v1/providers/models',
      '/api/v1/groups/allowed',
      '/api/v1/platform/link',
      '/api/v1/flow/trace/run-1/events',
    ]) {
      expect(isControlPlaneEndpoint(url)).toBe(false);
    }
  });
});

describe('system store', () => {
  it('accepts one apply and completes from the SSE phase event', async () => {
    vi.mocked(sseStream).mockImplementation(async (_url, onMessage) => {
      onMessage('1', JSON.stringify({
        id: 1,
        phase: 'succeeded',
        data: { error_code: null, recovery_attempted: false },
      }));
    });
    const store = useSystemStore();
    await store.refreshStatus();

    const accepted = await store.applyRevision('revision-2');
    expect(accepted.operation_id).toBe('operation-1');
    expect(systemApi.apply).toHaveBeenCalledTimes(1);
    expect(systemApi.apply).toHaveBeenCalledWith('revision-2', expect.stringMatching(/^apply:/));
    await vi.waitFor(() => expect(store.operation?.phase).toBe('succeeded'));
  });

  it('recovers a lost apply response from the durable latest operation', async () => {
    vi.mocked(systemApi.apply).mockRejectedValueOnce(new Error('connection reset'));
    vi.mocked(systemApi.status)
      .mockResolvedValueOnce(managedStatus)
      .mockResolvedValueOnce({
        ...managedStatus,
        last_operation: operation({ phase: 'starting', target_revision: 'revision-2' }),
      });
    vi.mocked(sseStream).mockImplementation(async (_url, onMessage) => {
      onMessage('2', JSON.stringify({
        id: 2,
        phase: 'rolled_back',
        data: { error_code: 'core_start_failed', recovery_attempted: true },
      }));
    });
    const store = useSystemStore();
    await store.refreshStatus();

    const recovered = await store.applyRevision('revision-2');
    expect(recovered.operation_id).toBe('operation-1');
    await vi.waitFor(() => expect(store.operation?.phase).toBe('rolled_back'));
    expect(store.operation?.recovery_attempted).toBe(true);
    expect(systemApi.apply).toHaveBeenCalledTimes(1);
  });

  it('keeps legacy mode outside Corona apply and leaves status errors separate from auth', async () => {
    vi.mocked(systemApi.status).mockResolvedValue({ pid: 123 } as unknown as SystemStatus);
    const store = useSystemStore();
    await store.refreshStatus();
    expect(store.managed).toBe(false);
    await expect(store.applyRevision('legacy')).rejects.toThrow('不支持受管配置应用');

    vi.mocked(systemApi.status).mockRejectedValueOnce(new Error('control unavailable'));
    await store.refreshStatus();
    expect(store.controlAvailable).toBe(false);
    expect(store.statusError).toBe('control unavailable');
    expect(store.operation).toBeNull();
  });
});
