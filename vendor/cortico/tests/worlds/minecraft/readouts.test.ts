import { describe, expect, it } from 'vitest';
import {
  bagStamp, blockedStamp, queueStamp,
  renderBagReadout, renderBlockedReadout, renderQueueReadout,
} from '../../../src/worlds/minecraft/readouts.ts';
import type { BlockedRecord, QueueStatus } from '../../../src/worlds/minecraft/executor.ts';
import type { WorldSnapshot } from '../../../src/worlds/minecraft/terrain.ts';
import { RoundOnceGate, roundTokenOf } from '../../../src/worlds/minecraft/round.ts';

function snap(over: Partial<WorldSnapshot> = {}): WorldSnapshot {
  return {
    position: { x: 0, y: 64, z: 0 },
    dimension: 'overworld',
    health: 20,
    food: 20,
    oxygen: 20,
    inWater: false,
    invSynced: true,
    timeOfDay: 1000,
    realTime: '2026-08-28T12:00:00+08:00',
    light: 15,
    raining: false,
    biome: 'plains',
    gameMode: 'survival',
    heldItem: 'stone_pickaxe',
    inventory: [{ name: 'cobblestone', count: 40 }, { name: 'torch', count: 12 }],
    xpLevel: 5,
    equipment: [{ slot: 'chest', name: 'iron_chestplate', durability: null, enchantments: [] }],
    effects: [],
    entities: [],
    players: [],
    blocks: [],
    standingOn: 'stone',
    ...over,
  } as unknown as WorldSnapshot;
}

describe('背包读数(mc_bag)', () => {
  it('四件事都在:格位分母、聚合清单、手上、身上穿的', () => {
    const text = renderBagReadout(snap());
    expect(text).toContain('2/36 格占着,空 34 格');
    expect(text).toContain('圆石×40');
    expect(text).toContain('手里拿着');
    expect(text).toContain('穿着:');
  });

  it('物品栏还没同步到:照实说没到,不把空栏当「包是空的」报', () => {
    const text = renderBagReadout(snap({ invSynced: false }));
    expect(text).toContain('还在从服务器同步');
    expect(text).not.toContain('0/36');
  });

  it('指纹认物品与手上那件,不认没进读数的东西', () => {
    const a = snap();
    expect(bagStamp(a)).toBe(bagStamp(snap()));
    expect(bagStamp(snap({ heldItem: 'torch' }))).not.toBe(bagStamp(a));
    expect(bagStamp(null)).toBe('nobot');
  });
});

function status(over: Partial<QueueStatus> = {}): QueueStatus {
  return {
    running: {
      id: 7, label: '挖石头', step: '挖 (1, 2, 3)', stepIndex: 0, stepCount: 3,
      elapsedMs: 4_000, taskElapsedMs: 9_000, count: null, pos: { x: 1, y: 64, z: 2 },
    },
    waiting: [{ id: 8, label: '走回家' }],
    ...over,
  };
}

describe('队列读数(mc_queue)', () => {
  it('在做的、排队的、最近一单的下场,三样都报', () => {
    const text = renderQueueReadout(status(), { at: '12:00:01', kind: 'blocked', text: '任务#6:没挖动' });
    expect(text).toContain('[队列]');
    expect(text).toContain('[最近一单] 12:00:01 任务#6:没挖动');
  });

  it('还没跑完过任何一单:照实说,不留空', () => {
    expect(renderQueueReadout(status(), null)).toContain('还没有跑完过任何一单');
  });

  /**
   * 指纹里**不能有时钟**:已跑多少秒每次都在变,进了指纹这道一轮一答的闸等于不存在
   * —— 而拿它轮询正是这三个入口要替掉的那件事。
   */
  it('指纹不含耗时:只是又跑了几秒不算「读数变了」', () => {
    const before = queueStamp(status(), null);
    const later = queueStamp(
      status({ running: { ...status().running!, elapsedMs: 30_000, taskElapsedMs: 60_000 } }),
      null,
    );
    expect(later).toBe(before);
    // 真的走到下一步了才算变
    expect(queueStamp(status({ running: { ...status().running!, stepIndex: 1 } }), null)).not.toBe(before);
    // 最近一单换了也算变
    expect(queueStamp(status(), 123)).not.toBe(before);
  });
});

describe('受阻读数(mc_blocked)', () => {
  const clock = (ms: number): string => new Date(ms).toISOString().slice(11, 19);
  const rec = (at: number, why: string): BlockedRecord => ({ at, task: '任务#3', step: '第 2 步 挖石头', why });

  it('时间、任务、步、原话,一个字不改地摆出来', () => {
    const text = renderBlockedReadout([rec(0, '包里没有能保住砂岩掉落的工具,要木镐及以上')], clock);
    expect(text).toContain('任务#3');
    expect(text).toContain('第 2 步 挖石头');
    expect(text).toContain('包里没有能保住砂岩掉落的工具,要木镐及以上');
  });

  it('一条都没有:照实说没有', () => {
    expect(renderBlockedReadout([], clock)).toContain('还没有记到受阻的步');
  });

  it('指纹看条数与最新那一条的时刻', () => {
    const one = [rec(100, 'a')];
    expect(blockedStamp(one)).toBe(blockedStamp([rec(100, 'a')]));
    expect(blockedStamp([rec(200, 'b'), ...one])).not.toBe(blockedStamp(one));
  });
});

/** 一轮一答闸使用主循环或 IPC 显式提供的轮号。 */
describe('一轮一答闸', () => {
  it('同一轮的几次调用拿到同一个轮号,换一轮换一个', () => {
    const ctx = (round: number) => ({ role: 'x', log: console, round } as never);
    const a1 = roundTokenOf(ctx(1));
    const a2 = roundTokenOf(ctx(1));
    const b1 = roundTokenOf(ctx(2));
    expect(a1).toBe(a2);
    expect(b1).not.toBe(a1);
  });

  it('没有显式轮号时返回 null,闸不生效', () => {
    expect(roundTokenOf({ role: 'x', log: console } as never)).toBeNull();
    const gate = new RoundOnceGate();
    expect(gate.answered('mc_bag', null, 's')).toBe(true);
    expect(gate.answered('mc_bag', null, 's')).toBe(true);
  });

  it('同轮同读数才算重复;读数变了、或换了轮,都照答', () => {
    const gate = new RoundOnceGate();
    expect(gate.answered('mc_bag', 1, 's1')).toBe(true);
    expect(gate.answered('mc_bag', 1, 's1')).toBe(false);
    // 世界真变了:同一轮里也照答,不拿一句过期回执把她挡在外面
    expect(gate.answered('mc_bag', 1, 's2')).toBe(true);
    // 换一轮
    expect(gate.answered('mc_bag', 2, 's2')).toBe(true);
    // 按工具分格,互不影响
    expect(gate.answered('mc_queue', 2, 's2')).toBe(true);
  });

});
