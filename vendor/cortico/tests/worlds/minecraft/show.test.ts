/** 演出节拍:null 无操作、各拍取对值、预算封顶后恢复瞬时、两次开窗之间隔开。 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  ShowPacer, markShowWindowClosed, resetShowScene, type ShowTempo,
} from '../../../src/worlds/minecraft/show.ts';

const TEMPO: ShowTempo = {
  clickMs: 40, dwellOpenMs: 60, dwellResultMs: 80, dwellCloseMs: 50, budgetMs: 130,
  reopenGapMs: 90,
};

beforeEach(() => {
  vi.useFakeTimers();
  resetShowScene();
});

afterEach(() => vi.useRealTimers());

async function timed(fn: () => Promise<void>): Promise<number> {
  const t0 = Date.now();
  await Promise.all([fn(), vi.runAllTimersAsync()]);
  return Date.now() - t0;
}

describe('ShowPacer', () => {
  it('tempo=null 时所有 beat 都是零等待', async () => {
    const p = new ShowPacer(null);
    const ms = await timed(async () => {
      await p.beat('open'); await p.beat('click'); await p.beat('result'); await p.beat('close');
    });
    expect(ms).toBe(0);
  });

  it('各拍按各自的时长等待', async () => {
    const p = new ShowPacer({ ...TEMPO, budgetMs: 10_000 });
    expect(await timed(() => p.beat('open'))).toBe(TEMPO.dwellOpenMs);
    expect(await timed(() => p.beat('click'))).toBe(TEMPO.clickMs);
  });

  it('预算耗尽后剩余 beat 恢复瞬时;最后一拍只吃到剩余预算', async () => {
    const p = new ShowPacer(TEMPO);
    expect(await timed(() => p.beat('open'))).toBe(TEMPO.dwellOpenMs);
    expect(await timed(() => p.beat('result'))).toBe(TEMPO.budgetMs - TEMPO.dwellOpenMs);
    const ms = await timed(async () => {
      await p.beat('click'); await p.beat('close');
    });
    expect(ms).toBe(0);
  });

  it('刚关过窗就要开:把 reopenGapMs 的差额等掉(否则同步屏是闪一下)', async () => {
    markShowWindowClosed(Date.now() - 20);
    const p = new ShowPacer(TEMPO);
    expect(await timed(() => p.openGap())).toBe(TEMPO.reopenGapMs - 20);
  });

  it('上次关窗已经很久了就不等', async () => {
    markShowWindowClosed(Date.now() - 5_000);
    const p = new ShowPacer(TEMPO);
    expect(await timed(() => p.openGap())).toBe(0);
  });

  it('开窗间隔不吃预算:预算耗尽了照样隔开', async () => {
    const p = new ShowPacer(TEMPO);
    expect(await timed(() => p.beat('open'))).toBe(TEMPO.dwellOpenMs);
    expect(await timed(() => p.beat('result'))).toBe(TEMPO.budgetMs - TEMPO.dwellOpenMs);
    markShowWindowClosed();
    expect(await timed(() => p.openGap())).toBe(TEMPO.reopenGapMs);
  });

  it('tempo=null 或 reopenGapMs=0 时 openGap 不等', async () => {
    markShowWindowClosed();
    expect(await timed(() => new ShowPacer(null).openGap())).toBe(0);
    expect(await timed(() => new ShowPacer({ ...TEMPO, reopenGapMs: 0 }).openGap())).toBe(0);
  });

  it('某一拍配 0 毫秒时跳过且不吃预算', async () => {
    const p = new ShowPacer({ ...TEMPO, clickMs: 0 });
    const ms = await timed(async () => {
      for (let i = 0; i < 10; i++) await p.beat('click');
    });
    expect(ms).toBe(0);
    expect(await timed(() => p.beat('open'))).toBe(TEMPO.dwellOpenMs);
  });
});
