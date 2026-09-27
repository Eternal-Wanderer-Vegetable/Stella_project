import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { WakeManager } from '../../bots/corti-soulmate/persona/rhythm.ts';
import { TimerStore } from '../../src/core/timers.ts';
import { WakeBus } from '../../src/core/bus.ts';
import type { EventEnvelope, CoreApi, WakeItem } from '../../src/core/types.ts';
import { makeFakeHarnessApi, makeTmpDir } from '../core/helpers.ts';

const TZ = 'Asia/Shanghai';

/** 真 TimerStore + 真 WakeBus 按 core 的接法拼一台观测架 */
function makeRig(tmpDir: string) {
  const bus = new WakeBus({ quietGapMs: 10, minBatchAgeMs: 0, maxBatchAgeMs: 100, maxBatchSize: 100 });
  const timers = new TimerStore(tmpDir);
  const injected: Array<{ text: string; kind: string }> = [];
  const api: CoreApi = makeFakeHarnessApi({
    timers,
    deliveryGate: {
      set: (gate) => bus.setDeliveryGate(gate),
      clear: (id, deliverQueued) => bus.clearDeliveryGate(id, deliverQueued),
      isBlocked: () => bus.isDeliveryBlocked(),
    },
    injectInternal: (text, kind) => {
      injected.push({ text, kind: kind ?? 'notice' });
      bus.push({
        event: {
          cursor: 0,
          type: kind ?? 'notice',
          ts: new Date().toISOString(),
          source: 'persona',
          origin: 'internal',
          text,
        },
      });
    },
  });
  return { bus, timers, api, injected };
}

const evt = (cursor: number, text: string): WakeItem => ({
  event: {
    origin: 'external' as const,
    cursor,
    type: 'qq.message',
    ts: new Date().toISOString(),
    source: 'qq',
    text,
  } as EventEnvelope,
});

describe('WakeManager(schedule_wake 全语义在Persona)', () => {
  let tmp: ReturnType<typeof makeTmpDir>;
  beforeEach(() => (tmp = makeTmpDir()));
  afterEach(() => {
    vi.useRealTimers();
    tmp.cleanup();
  });

  it('绝对/相对时间与坏输入;回执文本归这里', () => {
    const { api, timers } = makeRig(tmp.dir);
    const wm = new WakeManager(api, () => TZ);
    const before = Date.now();
    expect(wm.schedule({ at: '2099-07-18T20:00:00+08:00', note: '绝对' }))
      .toContain('[system/scheduled] Wake set for 2099-07-18T20:00:00+08:00');
    const rel = wm.schedule({ after_minutes: 0.001, note: '相对' });
    expect(rel).toContain('[system/scheduled]');
    expect(wm.schedule({ at: 'x', after_minutes: 5, note: '' })).toContain('[bad input] use either');
    expect(wm.schedule({ note: '' })).toContain('[bad input] provide at');
    expect(wm.schedule({ at: '明晚八点', note: '' })).toContain('could not parse time');
    expect(timers.list()).toHaveLength(2);
    const relEntry = timers.list().find((e) => (e.payload as { note?: string }).note === '相对')!;
    // 相对时间被抬到 ≥10 秒地板
    expect(Date.parse(relEntry.atIso) - before).toBeGreaterThanOrEqual(9_000);
  });

  it('到期注入 [system/wake] 文本;阻断闹钟到期先解闸,通知与被扣积压同批', async () => {
    vi.useFakeTimers();
    const { api, timers, bus } = makeRig(tmp.dir);
    const wm = new WakeManager(api, () => TZ);
    timers.start();
    const r = wm.schedule({
      at: new Date(Date.now() + 120).toISOString(),
      note: '睡醒',
      block: true,
    });
    expect(r).toContain('Live event delivery is blocked');
    expect(bus.isDeliveryBlocked()).toBe(true);

    const held = evt(1, '普通消息');
    let delivered = false;
    const waiting = bus.nextBatch();
    void waiting.then(() => { delivered = true; });
    bus.push(held);
    await vi.advanceTimersByTimeAsync(119);
    expect(delivered).toBe(false);
    await vi.advanceTimersByTimeAsync(1);

    const batch = await waiting;
    timers.stop();
    expect(batch).toContainEqual(held);
    expect(batch.some(
      (item) => item.event?.origin === 'internal' && item.event!.text.includes('My note: "睡醒"'),
    )).toBe(true);
    expect(bus.isDeliveryBlocked()).toBe(false);
  });

  it('阻断期间紧急事件同样暂存,不越序穿过;经历序=到达序', async () => {
    vi.useFakeTimers();
    const { api, bus, timers } = makeRig(tmp.dir);
    const wm = new WakeManager(api, () => TZ);
    timers.start();
    wm.schedule({ at: new Date(Date.now() + 3600_000).toISOString(), note: '长睡', block: true });

    const held = evt(1, '先到的普通消息');
    const urgent = evt(2, '后到的紧急消息');
    let delivered = false;
    const waiting = bus.nextBatch();
    void waiting.then(() => { delivered = true; });
    bus.push(held);
    bus.push(urgent, { trigger: 'flush' });
    await vi.advanceTimersByTimeAsync(50);
    expect(delivered).toBe(false);
    expect(bus.isDeliveryBlocked()).toBe(true);
    expect(bus.pending()).toBe(2);

    bus.clearDeliveryGate(api.timers.list()[0].id);
    expect(await waiting).toEqual([held, urgent]);
    timers.stop();
  });

  it('关键词字面命中:取消闹钟、解闸、注入唤醒文本,与积压同批', async () => {
    const { api, bus, timers } = makeRig(tmp.dir);
    const wm = new WakeManager(api, () => TZ);
    timers.start();
    wm.schedule({
      at: new Date(Date.now() + 3600_000).toISOString(),
      note: '等紧急消息',
      block: true,
      wake_keyword: '紧急',
    });
    const trigger = evt(2, '这是一条紧急通知');
    const waiting = bus.nextBatch();
    bus.push(trigger);

    const batch = await waiting;
    timers.stop();
    expect(batch.some(
      (item) => item.event?.origin === 'internal' && item.event!.text.includes('literal keyword "紧急"'),
    )).toBe(true);
    expect(batch).toContainEqual(trigger);
    expect(api.timers.list()).toHaveLength(0);
    expect(bus.isDeliveryBlocked()).toBe(false);
  });

  it('溢出放行一批并保留闹钟与闸门;溢出通知随批同行', async () => {
    const { api, bus, timers } = makeRig(tmp.dir);
    const wm = new WakeManager(api, () => TZ);
    timers.start();
    wm.schedule({
      at: new Date(Date.now() + 3600_000).toISOString(),
      note: '稍后再醒',
      block: true,
      overflow_limit: 2,
    });
    const waiting = bus.nextBatch();
    for (let cursor = 1; cursor <= 3; cursor++) bus.push(evt(cursor, `消息${cursor}`));

    const batch = await waiting;
    timers.stop();
    expect(batch.filter((item) => item.event?.origin === 'external')).toHaveLength(3);
    expect(batch.some(
      (item) => item.event?.origin === 'internal' && item.event!.text.includes('[system/wake-overflow]'),
    )).toBe(true);
    expect(api.timers.list()).toHaveLength(1);
    expect(bus.isDeliveryBlocked()).toBe(true);
  });

  it('重启恢复:attach 时从定时器表重装阻断闸门', () => {
    vi.useFakeTimers();
    const { api: api1, timers: t1 } = makeRig(tmp.dir);
    const wm1 = new WakeManager(api1, () => TZ);
    wm1.schedule({ at: new Date(Date.now() + 3600_000).toISOString(), note: '恢复后继续睡', block: true });
    t1.stop();

    // 同一目录再起一台:构造即读盘,WakeManager 构造时重装闸门
    const rig2 = makeRig(tmp.dir);
    void new WakeManager(rig2.api, () => TZ);
    expect(rig2.bus.isDeliveryBlocked()).toBe(true);
  });
});
