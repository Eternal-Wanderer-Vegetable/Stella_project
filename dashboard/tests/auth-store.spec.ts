import { createPinia, setActivePinia } from 'pinia';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  getToken: vi.fn(),
  setToken: vi.fn(),
  clearToken: vi.fn(),
  unwrap: vi.fn(),
  isTauri: vi.fn(),
  desktopSessionSecret: vi.fn(),
}));

vi.mock('@/api/http', () => ({
  api: { get: mocks.get, post: mocks.post },
  getToken: mocks.getToken,
  setToken: mocks.setToken,
  clearToken: mocks.clearToken,
  unwrap: mocks.unwrap,
}));

vi.mock('@/api/tauri', () => ({
  isTauri: mocks.isTauri,
  tauriBridge: { desktopSessionSecret: mocks.desktopSessionSecret },
}));

import { useAuthStore } from '@/stores/auth';

const stored = new Map<string, string>();

function setupStorage(): void {
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => stored.get(key) ?? null,
    setItem: (key: string, value: string) => stored.set(key, value),
    removeItem: (key: string) => stored.delete(key),
    clear: () => stored.clear(),
  });
}

beforeEach(() => {
  setActivePinia(createPinia());
  setupStorage();
  stored.clear();
  vi.clearAllMocks();
  mocks.getToken.mockReturnValue(null);
  mocks.get.mockResolvedValue({});
  mocks.post.mockResolvedValue({});
  mocks.isTauri.mockReturnValue(false);
  mocks.desktopSessionSecret.mockResolvedValue('desktop-capability');
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('auth store desktop session', () => {
  it('exchanges a Corona capability for a JWT in a ready Tauri session', async () => {
    const session = { token: 'jwt-token', expires_at: 'later', username: 'admin' };
    mocks.isTauri.mockReturnValue(true);
    mocks.unwrap
      .mockResolvedValueOnce({ setup_required: false })
      .mockResolvedValueOnce(session);

    const auth = useAuthStore();
    await expect(auth.probe()).resolves.toBe('online');

    expect(mocks.desktopSessionSecret).toHaveBeenCalledOnce();
    expect(mocks.post).toHaveBeenCalledWith('/auth/desktop-session', null, {
      headers: { 'X-Stella-Desktop-Session': 'desktop-capability' },
    });
    expect(auth.token).toBe('jwt-token');
    expect(auth.username).toBe('admin');
    expect(mocks.setToken).toHaveBeenCalledWith('jwt-token');
  });

  it('keeps the login path available when the exchange fails', async () => {
    mocks.isTauri.mockReturnValue(true);
    mocks.unwrap
      .mockResolvedValueOnce({ setup_required: false })
      .mockRejectedValueOnce(new Error('exchange rejected'));

    const auth = useAuthStore();
    await expect(auth.probe()).resolves.toBe('online');

    expect(auth.loggedIn).toBe(false);
    expect(auth.backend).toBe('online');
    expect(mocks.setToken).not.toHaveBeenCalled();
  });

  it('does not request the desktop capability in a browser or before setup', async () => {
    mocks.unwrap.mockResolvedValueOnce({ setup_required: false });
    await useAuthStore().probe();
    expect(mocks.desktopSessionSecret).not.toHaveBeenCalled();

    setActivePinia(createPinia());
    mocks.isTauri.mockReturnValue(true);
    mocks.unwrap.mockResolvedValueOnce({ setup_required: true });
    const setupAuth = useAuthStore();
    await setupAuth.probe();
    expect(setupAuth.setupRequired).toBe(true);
    expect(mocks.desktopSessionSecret).not.toHaveBeenCalled();
  });
});
