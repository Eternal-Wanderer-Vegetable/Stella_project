/** 从本地 HTTP 服务下载测试 zip/tar.gz，检查解压、标记与失败清理；不访问外部网络。 */
import { afterEach, describe, expect, it } from 'vitest';
import { createServer } from 'node:http';
import { AddressInfo } from 'node:net';
import { existsSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { gzipSync } from 'node:zlib';
import { randomBytes } from 'node:crypto';
import { zipSync } from 'fflate';
import { pack } from 'tar-stream';
import { RUNTIME_MARKER, RuntimeStore } from '../../src/providers/llamacpp/runtime-store.ts';
import { launchArgs, launchEnv, parseEndpoint, parseRegDword } from '../../src/providers/llamacpp/server.ts';
import { LAUNCH_DEFAULTS, type ReleasePlan } from '../../src/providers/llamacpp/options.ts';
import { nullLogger } from '../../src/core/util.ts';

const dirs: string[] = [];
const closers: Array<() => Promise<void>> = [];
afterEach(async () => {
  for (const close of closers.splice(0)) await close();
  for (const dir of dirs.splice(0)) rmSync(dir, { recursive: true, force: true });
});

function tmp(): string {
  const dir = mkdtempSync(join(tmpdir(), 'llamacpp-runtime-'));
  dirs.push(dir);
  return dir;
}

async function tarball(files: Record<string, string>): Promise<Buffer> {
  const tar = pack();
  const chunks: Buffer[] = [];
  const done = new Promise<void>((resolve) => tar.on('end', resolve));
  tar.on('data', (chunk) => chunks.push(chunk as Buffer));
  tar.entry({ name: 'llama-b1/', type: 'directory' });
  for (const [name, body] of Object.entries(files)) tar.entry({ name: `llama-b1/${name}`, mode: 0o755 }, body);
  tar.finalize();
  await done;
  return gzipSync(Buffer.concat(chunks));
}

async function serve(files: Record<string, Buffer>): Promise<string> {
  const server = createServer((req, res) => {
    const body = files[(req.url ?? '').slice(1)];
    if (!body) { res.statusCode = 404; res.end('missing'); return; }
    res.setHeader('Content-Length', String(body.length));
    res.end(body);
  });
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  closers.push(() => new Promise((resolve) => server.close(() => resolve())));
  return `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
}

describe('RuntimeStore', () => {
  it('两个 zip 与一个 tar.gz 装进同一个版本目录,标记落地后才算安装', async () => {
    const zip = Buffer.from(zipSync({ 'llama-server.exe': new TextEncoder().encode('server'), 'ggml.dll': new TextEncoder().encode('lib') }));
    const cudart = Buffer.from(zipSync({ 'cublas64_13.dll': new TextEncoder().encode('cuda') }));
    const tgz = await tarball({ 'llama-server': 'server', 'libllama.so': 'lib' });
    const base = await serve({ 'a.zip': zip, 'cudart.zip': cudart, 'a.tar.gz': tgz });
    const root = tmp();
    const store = new RuntimeStore(root, nullLogger());
    const plan: ReleasePlan = {
      key: 'mixed',
      serverExe: 'llama-server.exe',
      archives: [
        { url: `${base}/a.zip`, file: 'a.zip', format: 'zip', stripComponents: 0 },
        { url: `${base}/cudart.zip`, file: 'cudart.zip', format: 'zip', stripComponents: 0 },
        { url: `${base}/a.tar.gz`, file: 'a.tar.gz', format: 'tgz', stripComponents: 1 },
      ],
    };
    const dir = store.dir('b1', plan);
    expect(dir).toBe(join(root, 'llama.cpp', 'b1', 'mixed'));
    expect(store.state(dir).phase).toBe('absent');
    await store.install('b1', plan);
    expect(store.state(dir).phase).toBe('installed');
    expect(readdirSync(dir).sort()).toEqual(['cortico-runtime.json', 'cublas64_13.dll', 'ggml.dll', 'libllama.so', 'llama-server', 'llama-server.exe']);
    expect(readFileSync(join(dir, 'llama-server'), 'utf8')).toBe('server');
    expect(store.marker(dir)).toMatchObject({ runtime: 'llama.cpp', release: 'b1', key: 'mixed', archives: ['a.zip', 'cudart.zip', 'a.tar.gz'] });
    expect(existsSync(`${dir}.partial`)).toBe(false);
    expect(RUNTIME_MARKER).toBe('cortico-runtime.json');
  });

  it("大压缩包和高压缩比条目完成安装，进度字节数达到总量", async () => {
    const payload = randomBytes(3 * 1024 * 1024);
    const zeros = new Uint8Array(24 * 1024 * 1024);
    const zip = Buffer.from(zipSync({ 'blob.bin': new Uint8Array(payload), 'zeros.bin': zeros }, { level: 6 }));
    const base = await serve({ 'big.zip': zip });
    const store = new RuntimeStore(tmp(), nullLogger());
    const plan: ReleasePlan = { key: 'big', serverExe: 'llama-server', archives: [{ url: `${base}/big.zip`, file: 'big.zip', format: 'zip', stripComponents: 0 }] };
    const seen: number[] = [];
    const ticker = setInterval(() => seen.push(store.state(store.dir('b1', plan)).done), 5);
    try {
      await store.install('b1', plan);
    } finally {
      clearInterval(ticker);
    }
    expect(readFileSync(join(store.dir('b1', plan), 'blob.bin')).equals(payload)).toBe(true);
    expect(statSync(join(store.dir('b1', plan), 'zeros.bin')).size).toBe(zeros.length);
    expect(Math.max(0, ...seen)).toBeLessThanOrEqual(zip.length);
  });

  it('下载 404:error 态说清哪个文件,半成品目录清掉', async () => {
    const base = await serve({});
    const root = tmp();
    const store = new RuntimeStore(root, nullLogger());
    const plan: ReleasePlan = { key: 'k', serverExe: 'llama-server', archives: [{ url: `${base}/gone.zip`, file: 'gone.zip', format: 'zip', stripComponents: 0 }] };
    await expect(store.install('b1', plan)).rejects.toThrow('gone.zip');
    const dir = store.dir('b1', plan);
    expect(store.state(dir)).toMatchObject({ phase: 'error', detail: expect.stringContaining('gone.zip') });
    expect(store.state(dir, 'en').detail).toContain('Download of gone.zip failed');
    expect(existsSync(dir)).toBe(false);
    expect(existsSync(`${dir}.partial`)).toBe(false);
  });

  it('归档里带 .. 的条目拒绝解压', async () => {
    const zip = Buffer.from(zipSync({ '../escape.txt': new TextEncoder().encode('x') }));
    const base = await serve({ 'bad.zip': zip });
    const store = new RuntimeStore(tmp(), nullLogger());
    const plan: ReleasePlan = { key: 'k', serverExe: 'llama-server', archives: [{ url: `${base}/bad.zip`, file: 'bad.zip', format: 'zip', stripComponents: 0 }] };
    await expect(store.install('b1', plan)).rejects.toThrow('unsafe archive entry');
  });
});

describe('llama-server 启动契约', () => {
  it('router 模式:没有 -m,模型目录与缓存分开给,附加参数按空格拆', () => {
    const args = launchArgs({ localModelsDir: 'D:/models/local', launch: { ...LAUNCH_DEFAULTS, extraArgs: '--flash-attn on  --no-webui' } }, '127.0.0.1', 8090);
    expect(args).not.toContain('-m');
    expect(args.slice(0, 6)).toEqual(['--host', '127.0.0.1', '--port', '8090', '--models-dir', 'D:/models/local']);
    expect(args).toContain('--jinja');
    expect(args.slice(-3)).toEqual(['--flash-attn', 'on', '--no-webui']);
    const env = launchEnv('/rt', '/models/cache', 'secret', { PATH: 'p', LD_LIBRARY_PATH: '/usr/lib' }, 'linux');
    expect(env.LLAMA_CACHE).toBe('/models/cache');
    expect(env.LLAMA_API_KEY).toBe('secret');
    expect(env.LD_LIBRARY_PATH).toBe('/rt:/usr/lib');
    expect(launchEnv('C:\\rt', 'C:\\cache', undefined, { PATH: 'p' }, 'win32').PATH).toBe('C:\\rt;p');
    expect(parseEndpoint('http://127.0.0.1:8090/v1')).toEqual({ host: '127.0.0.1', port: 8090, origin: 'http://127.0.0.1:8090' });
    expect(parseEndpoint('not a url')).toBeNull();
  });

  it('智能应用控制的注册表值:0 关 1 强制 2 评估,读不到是 null', () => {
    expect(parseRegDword('\r\nHKEY_LOCAL_MACHINE\\...\\Policy\r\n    VerifiedAndReputablePolicyState    REG_DWORD    0x1\r\n')).toBe(1);
    expect(parseRegDword('    VerifiedAndReputablePolicyState    REG_DWORD    0x0')).toBe(0);
    expect(parseRegDword('    VerifiedAndReputablePolicyState    REG_DWORD    0x2')).toBe(2);
    expect(parseRegDword('ERROR: The system was unable to find the specified registry key or value.')).toBeNull();
    expect(parseRegDword('REG_DWORD 0x7')).toBeNull();
  });
});
