import { describe, expect, it } from 'vitest';
import { LANE_ZH, MinecraftLog, laneLevel } from '../../../src/worlds/minecraft/log.ts';
import type { LogEmitOptions, Logger, LogLevel } from '../../../src/core/types.ts';

/** 记下每条 emit 落到的区域、级别与选项。 */
function recorder(): { log: Logger; records: Array<{ area: string; level: LogLevel; msg: string; opts?: LogEmitOptions }> } {
  const records: Array<{ area: string; level: LogLevel; msg: string; opts?: LogEmitOptions }> = [];
  const make = (area: string): Logger => {
    const emit = (level: LogLevel, msg: string, opts?: LogEmitOptions) => { records.push({ area, level, msg, opts }); };
    return {
      trace: (m, d) => emit('trace', m, { data: d }),
      debug: (m, d) => emit('debug', m, { data: d }),
      info: (m, d) => emit('info', m, { data: d }),
      warn: (m, d) => emit('warn', m, { data: d }),
      error: (m, d) => emit('error', m, { data: d }),
      emit,
      child: (sub) => make(area ? `${area}.${sub}` : sub),
    };
  };
  return { log: make('worlds.minecraft'), records };
}

describe('MinecraftLog', () => {
  it('物品与身体泳道有稳定标识和面板标签', () => {
    const log = new MinecraftLog();
    log.write({ lane: 'inventory', event: 'item-broke', msg: '铁镐损坏' });
    expect(log.after(0)[0]).toMatchObject({ lane: 'inventory', event: 'item-broke', seq: 1 });
    expect(LANE_ZH.inventory).toBe('物品');
    expect(LANE_ZH.body).toBe('身体');
  });

  it('每条记录落到 worlds.minecraft.<泳道>,小类、任务号、耗时、读数进契约字段', () => {
    const rec = recorder();
    const log = new MinecraftLog({ log: rec.log });
    log.write({ lane: 'task', event: 'enqueue', taskId: 3, msg: '受理任务#3' });
    log.write({ lane: 'craft', event: 'gain', msg: '入包 1 个', data: { got: 1 }, durMs: 40 });
    expect(rec.records).toEqual([
      { area: 'worlds.minecraft.task', level: 'info', msg: '受理任务#3', opts: { event: 'enqueue', task: 3 } },
      { area: 'worlds.minecraft.craft', level: 'debug', msg: '入包 1 个', opts: { event: 'gain', durMs: 40, data: { got: 1 } } },
    ]);
  });

  it('级别按泳道默认,每次点击与每帧寻路的机械回声降到 trace,显式级别优先', () => {
    expect(laneLevel('tool', 'mc_do')).toBe('info');
    expect(laneLevel('body', 'heartbeat')).toBe('trace');
    expect(laneLevel('craft', 'slot-in')).toBe('trace');
    expect(laneLevel('craft', 'confirmed')).toBe('debug');
    expect(laneLevel('path', 'update')).toBe('trace');
    expect(laneLevel('path', 'goal')).toBe('debug');
    expect(laneLevel('reflex', 'lava')).toBe('info');
    expect(laneLevel('reflex', 'drown-submerged')).toBe('trace');
    const rec = recorder();
    const log = new MinecraftLog({ log: rec.log });
    log.write({ lane: 'skill', event: 'blocked', msg: '走不过去', level: 'warn' });
    expect(rec.records[0]).toMatchObject({ area: 'worlds.minecraft.skill', level: 'warn' });
  });

  it('面板环形缓冲按 after 游标增量取,清空不回退序号', () => {
    const log = new MinecraftLog({ ring: 3 });
    for (let i = 1; i <= 5; i++) log.write({ lane: 'body', event: 'decision', msg: `第 ${i} 条` });
    expect(log.after(0).map((e) => e.seq)).toEqual([3, 4, 5]);
    expect(log.after(4).map((e) => e.msg)).toEqual(['第 5 条']);
    expect(log.clear()).toContain('3 条');
    expect(log.after(0)).toEqual([]);
    log.write({ lane: 'body', event: 'decision', msg: '第 6 条' });
    expect(log.after(5).map((e) => e.seq)).toEqual([6]);
  });
});
