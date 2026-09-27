/** 部署主题记录的读写与那两条路由：写入整份替换、颜色逐个规范化、文件坏了按没有记录算。 */
import { describe, it, expect, afterEach } from 'vitest';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { WebApp } from '../../src/web/server.ts';
import { THEME_FILE, readDeploymentTheme, writeDeploymentTheme } from '../../src/web/theme-store.ts';
import { fallbackPalette, type StoredTheme } from '../../src/web/shared/theme.ts';
import { nullLogger } from '../../src/core/util.ts';
import { FakeStore } from './fakes.ts';

const dirs: string[] = [];
const apps: WebApp[] = [];

function tempDir(): string {
  const dir = mkdtempSync(join(tmpdir(), 'webtest-theme-'));
  dirs.push(dir);
  return dir;
}

afterEach(async () => {
  for (const app of apps.splice(0)) await app.stop();
  for (const dir of dirs.splice(0)) rmSync(dir, { recursive: true, force: true });
});

describe('theme.json', () => {
  it('没有文件时没有记录', () => {
    expect(readDeploymentTheme(tempDir())).toEqual({ state: null });
  });

  it('写进去再读回来,野键丢掉、颜色统一小写、缺格用内置补齐', () => {
    const dir = tempDir();
    const written = writeDeploymentTheme(dir, {
      selectedId: 'navigator',
      mode: 'dark',
      custom: [{ id: 'mine', name: '我的', palettes: { light: { paper: '#ABCDEF', evil: '#000000' } } }],
      野键: 1,
    });
    expect(Object.keys(written).sort()).toEqual(['custom', 'mode', 'selectedId']);
    expect(written.custom[0].palettes.light.paper).toBe('#abcdef');
    expect(written.custom[0].palettes.light.evil).toBeUndefined();
    expect(written.custom[0].palettes.dark).toEqual(fallbackPalette('dark'));
    expect(readDeploymentTheme(dir).state).toEqual(written);
    expect(readFileSync(join(dir, THEME_FILE), 'utf8').endsWith('\n')).toBe(true);
  });

  it('整份替换:上一次写的自定义方案不会留下', () => {
    const dir = tempDir();
    writeDeploymentTheme(dir, { selectedId: 'a', mode: 'light', custom: [{ id: 'a' }] });
    const after = writeDeploymentTheme(dir, { selectedId: 'mint', mode: 'system', custom: [] });
    expect(after.custom).toEqual([]);
    expect(readDeploymentTheme(dir).state?.custom).toEqual([]);
  });

  it('文件坏了:按没有记录算,并给出原因', () => {
    const dir = tempDir();
    writeFileSync(join(dir, THEME_FILE), '{ 这不是 JSON', 'utf8');
    const read = readDeploymentTheme(dir);
    expect(read.state).toBe(null);
    expect(read.error).toBeTruthy();
  });
});

describe('/api/theme', () => {
  async function serve(opts: { botDir?: string; defaultScheme?: string } = {}): Promise<string> {
    const dir = tempDir();
    const app = new WebApp({
      store: new FakeStore(),
      memoryDir: dir,
      dataDir: dir,
      log: nullLogger(),
      getStatus: () => ({}),
      defaultScheme: opts.defaultScheme ?? 'mint',
      ...(opts.botDir === undefined ? { botDir: dir } : {}),
    });
    apps.push(app);
    return `http://127.0.0.1:${await app.start(0)}`;
  }

  it('POST 存下来,GET 连默认方案一起读回来', async () => {
    const base = await serve({ defaultScheme: 'navigator' });
    const body: StoredTheme = { selectedId: 'crab-daisy', mode: 'light', custom: [] };
    const posted = await (await fetch(`${base}/api/theme`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })).json() as { ok: boolean; theme: StoredTheme };
    expect(posted.ok).toBe(true);
    expect(posted.theme).toEqual(body);
    const got = await (await fetch(`${base}/api/theme`)).json() as { defaultScheme: string; theme: StoredTheme };
    expect(got).toEqual({ defaultScheme: 'navigator', theme: body });
  });

  it('正文里的坏颜色不进文件,按内置补齐', async () => {
    const base = await serve();
    const posted = await (await fetch(`${base}/api/theme`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        selectedId: 'mine',
        mode: '不是挡位',
        custom: [{ id: 'mine', palettes: { dark: { paper: 'javascript:alert(1)' } } }],
      }),
    })).json() as { theme: StoredTheme };
    expect(posted.theme.mode).toBe('system');
    expect(posted.theme.custom[0].palettes.dark.paper).toBe(fallbackPalette('dark').paper);
  });

  it('没有部署目录时两条都是 503', async () => {
    const base = await serve({ botDir: '' });
    expect((await fetch(`${base}/api/theme`)).status).toBe(503);
    expect((await fetch(`${base}/api/theme`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
    })).status).toBe(503);
  });
});
