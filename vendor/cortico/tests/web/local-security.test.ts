import { afterEach, describe, expect, it } from 'vitest';
import { request } from 'node:http';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import WebSocket from 'ws';
import { WebApp } from '../../src/web/server.ts';
import { nullLogger } from '../../src/core/util.ts';
import { FakeStore } from './fakes.ts';

function post(port: number, origin?: string): Promise<{ status: number; body: string }> {
  return new Promise((resolve, reject) => {
    const req = request({
      host: '127.0.0.1', port, path: '/api/run/pause', method: 'POST',
      headers: origin ? { Origin: origin } : undefined,
    }, (res) => {
      let body = '';
      res.setEncoding('utf8');
      res.on('data', (chunk: string) => (body += chunk));
      res.on('end', () => resolve({ status: res.statusCode ?? 0, body }));
    });
    req.on('error', reject);
    req.end();
  });
}

/** 跨站 WS 被 upgrade 闸直接断连(socket.destroy,无 HTTP 响应),体现为连接错误 */
function rejectedWebSocket(url: string, origin: string): Promise<boolean> {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(url, { origin });
    ws.once('error', () => resolve(true));
    ws.once('unexpected-response', (_req, res) => {
      res.resume();
      resolve(true);
    });
    ws.once('open', () => {
      ws.close();
      reject(new Error('跨站 WebSocket 不应连接成功'));
    });
  });
}

describe('WebApp localhost 安全边界', () => {
  let app: WebApp | null = null;
  let dir = '';

  afterEach(async () => {
    if (app) await app.stop();
    app = null;
    if (dir) rmSync(dir, { recursive: true, force: true });
    dir = '';
  });

  async function start() {
    dir = mkdtempSync(join(tmpdir(), 'web-local-security-'));
    let paused = false;
    app = new WebApp({
      store: new FakeStore(), memoryDir: dir, dataDir: dir,
      getStatus: () => ({}), log: nullLogger(),
      run: { pause: () => { paused = true; }, resume: () => { paused = false; }, isPaused: () => paused },
    });
    const port = await app.start(0);
    return { port, paused: () => paused };
  }

  it('无 Origin 的本机客户端保持兼容；外站浏览器写请求被拒绝', async () => {
    const { port, paused } = await start();
    const cli = await post(port);
    expect(cli.status).toBe(200);
    expect(paused()).toBe(true);

    const crossSite = await post(port, 'https://evil.example');
    expect(crossSite.status).toBe(403);
  });

  it('同源(Host 对照)允许写请求，其他端口的 Origin 拒绝', async () => {
    const { port } = await start();
    expect((await post(port, `http://127.0.0.1:${port}`)).status).toBe(200);
    expect((await post(port, 'http://127.0.0.1:9')).status).toBe(403);
  });

  it('WebSocket upgrade 拒绝外站 Origin', async () => {
    const { port } = await start();
    expect(await rejectedWebSocket(`ws://127.0.0.1:${port}/ws/debug`, 'https://evil.example')).toBe(true);
  });
});
