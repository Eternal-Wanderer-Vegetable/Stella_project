/** 使用提供 /health 的 Node 测试进程验证启动和停止；其他测试检查托管配置与状态。 */
import { afterEach, describe, expect, it } from 'vitest';
import { createServer } from 'node:http';
import { AddressInfo } from 'node:net';
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { LlamaServerManager } from '../../src/providers/llamacpp/server.ts';
import { LlamaRuntime } from '../../src/providers/llamacpp/runtime.ts';
import { LAUNCH_DEFAULTS, PINNED_RELEASE, defaultBackend } from '../../src/providers/llamacpp/options.ts';
import type { LLMProviderEntry } from '../../src/core/types.ts';
import { nullLogger } from '../../src/core/util.ts';

const dirs: string[] = [];
const cleanups: Array<() => Promise<unknown>> = [];
afterEach(async () => {
  for (const cleanup of cleanups.splice(0)) await cleanup();
  for (const dir of dirs.splice(0)) {
    try { rmSync(dir, { recursive: true, force: true }); } catch { /* 测试目录清理失败可忽略。 */ }
  }
});

function tmp(): string {
  const dir = mkdtempSync(join(tmpdir(), 'llamacpp-server-'));
  dirs.push(dir);
  return dir;
}

async function freePort(): Promise<number> {
  const server = createServer();
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  const { port } = server.address() as AddressInfo;
  await new Promise<void>((resolve) => server.close(() => resolve()));
  return port;
}

const reachable = (ok: boolean): typeof fetch =>
  (async () => (ok ? new Response('{"status":"ok"}', { status: 200 }) : Promise.reject(new Error('refused')))) as unknown as typeof fetch;

const launch = LAUNCH_DEFAULTS;

describe('LlamaServerManager', () => {
  it('端点已有服务在跑:不接管,reachable=true', async () => {
    const dir = tmp();
    const manager = new LlamaServerManager({
      name: 'local', baseUrl: 'http://127.0.0.1:8090/v1', runtimeDir: dir, serverExe: 'llama-server.exe',
      cacheDir: join(dir, 'cache'), localModelsDir: join(dir, 'local'), launch, log: nullLogger(), fetchImpl: reachable(true),
    });
    const state = await manager.start();
    expect(state.phase).toBe('stopped');
    expect(state.reachable).toBe(true);
    expect(state.pid).toBeNull();
    expect(state.detail).toMatch(/外部启动/);
    expect((await manager.state('en')).detail).toMatch(/started externally/);
  });

  it('运行时目录里没有可执行文件:error 态指出缺什么;baseUrl 没端口也是 error', async () => {
    const dir = tmp();
    const missing = new LlamaServerManager({
      name: 'local', baseUrl: 'http://127.0.0.1:8090/v1', runtimeDir: dir, serverExe: 'llama-server.exe',
      cacheDir: join(dir, 'cache'), localModelsDir: join(dir, 'local'), launch, log: nullLogger(), fetchImpl: reachable(false),
    });
    expect(await missing.start()).toMatchObject({ phase: 'error', detail: expect.stringContaining('llama-server.exe') });
    const bad = new LlamaServerManager({
      name: 'local', baseUrl: 'nope', runtimeDir: dir, serverExe: 'llama-server.exe',
      cacheDir: join(dir, 'cache'), localModelsDir: join(dir, 'local'), launch, log: nullLogger(), fetchImpl: reachable(false),
    });
    expect((await bad.start()).detail).toMatch(/host\/port/);
  });

  it('真起一个进程:health 通了转 running,stop 结束它', async () => {
    const dir = tmp();
    const port = await freePort();
    const script = `require('http').createServer((q,s)=>{s.setHeader('Content-Type','application/json');s.end('{"status":"ok"}')}).listen(${port},'127.0.0.1')`;
    const manager = new LlamaServerManager({
      name: 'local', baseUrl: `http://127.0.0.1:${port}/v1`, runtimeDir: dir, serverExe: 'llama-server.exe',
      cacheDir: join(dir, 'cache'), localModelsDir: join(dir, 'local'), launch, log: nullLogger(),
      commandOverride: { command: process.execPath, args: ['-e', script] }, healthIntervalMs: 100, healthTimeoutMs: 10_000,
    });
    cleanups.push(() => manager.stop());
    const started = await manager.start();
    expect(started.phase).toBe('starting');
    expect(started.pid).not.toBeNull();
    const deadline = Date.now() + 10_000;
    while ((await manager.state()).phase !== 'running' && Date.now() < deadline) await new Promise((resolve) => setTimeout(resolve, 100));
    expect((await manager.state()).phase).toBe('running');
    const stopped = await manager.stop();
    expect(stopped.phase).toBe('stopped');
    expect(stopped.pid).toBeNull();
  });
});

describe('LlamaRuntime', () => {
  const roots = () => {
    const base = tmp();
    return { runtimes: join(base, 'runtimes'), models: join(base, 'models') };
  };
  const make = (entry: LLMProviderEntry, patch: Partial<ConstructorParameters<typeof LlamaRuntime>[0]> = {}) => {
    const current = { entry };
    const runtime = new LlamaRuntime({
      name: 'local', entry: () => current.entry, secret: () => '', log: nullLogger(), roots: roots(), fetchImpl: reachable(false), ...patch,
    });
    return { runtime, set: (next: LLMProviderEntry) => { current.entry = next; } };
  };

  it('外部端点:managed=false,只报模型目录与后端候选', async () => {
    const { runtime } = make({ kind: 'llamacpp', baseUrl: 'http://127.0.0.1:8090/v1' });
    const state = await runtime.state();
    expect(state.managed).toBe(false);
    expect(state.server).toBeNull();
    expect(state.backendChoices.length).toBeGreaterThan(0);
    expect(state.localModelsDir).toMatch(/llamacpp[\\/]local$/);
    expect(state.cacheDir).toMatch(/llamacpp[\\/]cache$/);
    await expect(runtime.start()).rejects.toThrow('没有开启托管');
  });

  it('托管但还没装:start 拒绝;自备目录不需要安装', async () => {
    const managed: LLMProviderEntry = {
      kind: 'llamacpp', baseUrl: 'http://127.0.0.1:8090/v1',
      options: { runtime: { release: PINNED_RELEASE, backend: defaultBackend() }, launch: LAUNCH_DEFAULTS },
    };
    const { runtime } = make(managed);
    const state = await runtime.state();
    expect(state.managed).toBe(true);
    expect(state.install.phase).toBe('absent');
    expect(state.runtimeDir).toContain(join('llama.cpp', PINNED_RELEASE));
    await expect(runtime.start()).rejects.toThrow('没装好');

    const own = tmp();
    const { runtime: withOwn } = make({ ...managed, options: { ...managed.options, runtime: { release: PINNED_RELEASE, backend: 'anything', runtimeDir: own } } });
    const ownState = await withOwn.state();
    expect(ownState.own).toBe(true);
    expect(ownState.install.phase).toBe('installed');
    expect(ownState.runtimeDir).toBe(own);
    // 目录里没有可执行文件:错误来自进程管理器,不是安装状态
    expect((await withOwn.start())!.phase).toBe('error');
  });

  it('改启动参数不动正在跑的进程,状态标 configurationPending;下一次启动换新参数', async () => {
    const own = tmp();
    mkdirSync(own, { recursive: true });
    writeFileSync(join(own, 'llama-server.exe'), '');
    const port = await freePort();
    const script = `require('http').createServer((q,s)=>{s.end('{"status":"ok"}')}).listen(${port},'127.0.0.1')`;
    const base: LLMProviderEntry = {
      kind: 'llamacpp', baseUrl: `http://127.0.0.1:${port}/v1`,
      options: { runtime: { release: PINNED_RELEASE, backend: defaultBackend(), runtimeDir: own }, launch: LAUNCH_DEFAULTS },
    };
    const { runtime, set } = make(base, { fetchImpl: undefined, commandOverride: { command: process.execPath, args: ['-e', script] } });
    cleanups.push(() => runtime.stop());
    const started = await runtime.start();
    expect(started!.phase).toBe('starting');
    expect((await runtime.state()).server!.configurationPending).toBe(false);
    set({ ...base, options: { ...base.options, launch: { ...LAUNCH_DEFAULTS, contextSize: 4096 } } });
    const pending = await runtime.state();
    expect(pending.server!.configurationPending).toBe(true);
    expect(pending.launch!.contextSize).toBe(4096);
    expect(pending.server!.phase).not.toBe('stopped');
  });
});
