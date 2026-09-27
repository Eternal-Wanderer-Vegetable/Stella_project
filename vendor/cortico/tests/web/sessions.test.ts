import { records } from '../core/fixture-protocol.ts';
/**
 * WebApp session观察通道测试:/api/sessions、/api/sessions/messages、
 * /ws/sessions 实时推送、debug hello携带sessions。真SessionTracker+fake依赖。
 */
import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import WebSocket from 'ws';
import type { ChatMessage } from '../core/fixture-types.ts';
import type { LLMUsage } from '../../src/core/types.ts';
import { SessionTracker } from '../../src/core/sessions.ts';
import { WebApp } from '../../src/web/server.ts';
import { nullLogger } from '../../src/core/util.ts';
import { FakeStore } from './fakes.ts';

const usage = (p: number, c: number, hit = 0, miss = 0): LLMUsage => ({
  promptTokens: p,
  completionTokens: c,
  cacheHitTokens: hit,
  cacheMissTokens: miss,
});

let app: WebApp;
let port: number;
let dir: string;
let tracker: SessionTracker;
const mainMsgs: ChatMessage[] = [{ role: 'system', content: 'sys' }];

const base = () => `http://127.0.0.1:${port}`;
const getJson = async (url: string): Promise<any> => {
  const r = await fetch(url);
  return { status: r.status, body: (await r.json()) as any };
};

/** 收一帧(带超时) */
function nextFrame(ws: WebSocket, timeoutMs = 3000): Promise<any> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('等帧超时')), timeoutMs);
    ws.once('message', (raw) => {
      clearTimeout(timer);
      resolve(JSON.parse(String(raw)));
    });
  });
}

beforeAll(async () => {
  dir = mkdtempSync(join(tmpdir(), 'webtest-sess-'));
  tracker = new SessionTracker('Asia/Shanghai');
  const h = tracker.open('main', '主意识', { id: 'main', messagesRef: () => records(mainMsgs) });
  h.record(usage(1000, 50, 800, 200));

  app = new WebApp({
    store: new FakeStore(),
    memoryDir: dir,
    dataDir: dir,
    getStatus: () => ({}),
    sessions: tracker,
    debug: {
      sessionMessages: () => records(mainMsgs),
      onSessionAppend: () => {},
      onSessionReset: () => {},
      onEvent: () => {},
      onRunlog: () => {},
      toolSchemas: () => [],
    },
    log: nullLogger(),
  });
  port = await app.start(0);
});

afterAll(async () => {
  await app.stop();
  rmSync(dir, { recursive: true, force: true });
});

describe('/api/sessions', () => {
  it('列表含统计与命中率', async () => {
    const { status, body } = await getJson(`${base()}/api/sessions`);
    expect(status).toBe(200);
    const main = body.sessions.find((s: any) => s.id === 'main');
    expect(main).toBeDefined();
    expect(main.label).toBe('主意识');
    expect(main.promptTokens).toBe(1000);
    expect(main.completionTokens).toBe(50);
    expect(main.cacheHitRate).toBeCloseTo(0.8, 5);
    expect(main.endedAt).toBeNull();
    expect(main.messageCount).toBe(mainMsgs.length);
  });

  it('messages端点:返回消息流+估算tokens;未知id→404;缺id→400', async () => {
    const ok = await getJson(`${base()}/api/sessions/messages?id=main`);
    expect(ok.status).toBe(200);
    expect(ok.body.messages).toHaveLength(mainMsgs.length);
    expect(typeof ok.body.estTokens).toBe('number');

    expect((await getJson(`${base()}/api/sessions/messages?id=nope`)).status).toBe(404);
    expect((await getJson(`${base()}/api/sessions/messages`)).status).toBe(400);
  });
});

describe('/ws/sessions 实时推送', () => {
  it('连接即得全量;fork open/record/close各推一帧', async () => {
    const ws = new WebSocket(`ws://127.0.0.1:${port}/ws/sessions`);
    const hello = await nextFrame(ws);
    expect(hello.t).toBe('sessions');
    expect(hello.sessions.some((s: any) => s.id === 'main')).toBe(true);

    const framesP = nextFrame(ws);
    const fork = tracker.open('association', '联想fork');
    const f1 = await framesP;
    expect(f1.t).toBe('sessions');
    expect(f1.sessions.some((s: any) => s.role === 'association' && s.endedAt === null)).toBe(true);

    const f2P = nextFrame(ws);
    fork.record(usage(500, 20, 400, 100));
    const f2 = await f2P;
    const forkStats = f2.sessions.find((s: any) => s.role === 'association');
    expect(forkStats.promptTokens).toBe(500);
    expect(forkStats.cacheHitRate).toBeCloseTo(0.8, 5);

    const f3P = nextFrame(ws);
    fork.close();
    const f3 = await f3P;
    expect(f3.sessions.find((s: any) => s.role === 'association').endedAt).not.toBeNull();

    ws.close();
  });
});

describe('debug通道携带sessions', () => {
  it('hello帧含sessions;tracker变化时也推sessions帧', async () => {
    const ws = new WebSocket(`ws://127.0.0.1:${port}/ws/debug`);
    const hello = await nextFrame(ws);
    expect(hello.t).toBe('hello');
    expect(Array.isArray(hello.sessions)).toBe(true);
    expect(hello.sessions.some((s: any) => s.id === 'main')).toBe(true);

    const fP = nextFrame(ws);
    tracker.open('rumination', '反刍fork').close(); // 快速开关,至少推一帧
    const f = await fP;
    expect(f.t).toBe('sessions');

    ws.close();
  });
});
