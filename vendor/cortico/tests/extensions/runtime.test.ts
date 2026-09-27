/** 扩展导入 cortico/ 路径时必须解析到框架源码；子进程内验证它与直接导入的模块实例一致。 */
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadExtensions } from '../../src/extensions.ts';
import { RESOLVER_URL, childExecArgv } from '../../src/extensions/runtime.ts';
import { nowIso } from '../../src/core/util.ts';
import { installFixture } from '../fixtures/extensions/install.ts';

const repoRoot = fileURLToPath(new URL('../..', import.meta.url));

let root: string;
beforeEach(() => { root = mkdtempSync(join(tmpdir(), 'extension-runtime-')); });
afterEach(() => rmSync(root, { recursive: true, force: true }));

describe('cortico/* 解析', () => {
  it('装载器 import 扩展时 cortico/core/util.ts 解析得到,拿到的是能用的框架导出', async () => {
    installFixture(root, 'world-imports-framework');
    const set = await loadExtensions(root);
    expect(set.records[0]).toMatchObject({ loaded: true, worldId: 'imports-framework' });
    const borrowed = (set.worlds[0] as unknown as { nowIso: typeof nowIso }).nowIso;
    expect(borrowed('UTC')).toMatch(/^\d{4}-\d{2}-\d{2}T/);
  });

  it('子进程里也解析得到,且与直接 import 是同一个实例', () => {
    // Vite 与 Node 的模块图不同，在独立 Node 子进程中比较模块身份。
    // 不一致时测试进程返回退出码 2。
    const fixture = join(repoRoot, 'tests/fixtures/extensions/child-import.mjs');
    const child = spawnSync(process.execPath, ['--import', 'tsx', '--import', RESOLVER_URL, fixture], {
      cwd: repoRoot,
      encoding: 'utf8',
    });
    expect(child.stderr).toBe('');
    expect(child.status).toBe(0);
    expect(child.stdout.trim()).toBe('function');
  });

  it('childExecArgv:父进程的加载器照抄,末尾挂上解析器本身', () => {
    const argv = childExecArgv();
    expect(argv.slice(-2)).toEqual(['--import', RESOLVER_URL]);
    expect(argv.length).toBeGreaterThanOrEqual(4);
  });
});
