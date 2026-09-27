/**
 * BoatItem 通过使用物品按玩家视线射线生成船，不处理 use_item_on 方块放置。
 * precheck 拒绝将船作为 build 材料；执行器也检查未经 precheck 的调用。
 */
import { Vec3 as V } from 'vec3';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { precheckStep } from '../../../src/worlds/minecraft/precheck.ts';
import type { SkillCall } from '../../../src/worlds/minecraft/executor.ts';
import { makeExecutorOn, waitUntil } from './executor-harness.ts';

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date', 'setTimeout', 'clearTimeout', 'setInterval', 'clearInterval'] });
});

afterEach(() => {
  vi.useRealTimers();
});

/** 水面上一格空气:放船该去的地方 */
function boatBot(bagName: string) {
  const bag = new Map([[bagName, 1], ['cobblestone', 8]]);
  const bot = {
    entity: { id: 9, position: new V(0.5, 64, 0.5), height: 1.8 },
    entities: {} as Record<string, unknown>,
    game: { dimension: 'overworld' },
    health: 20,
    players: {},
    registry: { blocksByName: {}, itemsByName: {} },
    heldItem: null as { name: string } | null,
    inventory: {
      items: () => [...bag].filter(([, n]) => n > 0).map(([name, n]) => ({ name, count: n, type: 1, metadata: 0 })),
    },
    equip: async (it: { name: string }) => { bot.heldItem = it; },
    lookAt: async () => {},
    activateItem: () => {},
    deactivateItem: () => {},
    activateBlock: async () => {},
    placeBlock: async () => { throw new Error('服务端不认'); },
    waitForTicks: async () => {},
    blockAt: (p: V) => {
      const f = p.floored();
      return f.y < 64
        ? { name: 'water', position: p, boundingBox: 'empty', stateId: 0 }
        : { name: 'air', position: p, boundingBox: 'empty', stateId: 1 };
    },
    pathfinder: { stop() {}, setGoal() {}, goto: async () => {} },
  };
  return bot;
}

const deps = (bot: ReturnType<typeof boatBot>) => ({
  resolve: (a: unknown) => {
    const t = a as [number, number, number];
    return Array.isArray(t) ? { x: t[0], y: t[1], z: t[2] } : null;
  },
  cellsOf: () => [{ x: 1, y: 64, z: 0 }],
  blockAt: (c: { x: number; y: number; z: number }) => bot.blockAt(new V(c.x, c.y, c.z)),
});

describe('build 放船', () => {
  it('受理刻就是 hard,并指名改用 use + at', () => {
    const bot = boatBot('acacia_boat');
    const note = precheckStep(
      bot as never,
      { skill: 'build', material: 'acacia_boat', anchors: [[1, 64, 0]] } as unknown as SkillCall,
      deps(bot) as never,
    );
    expect(note?.level).toBe('hard');
    expect(note?.rule).toBe('build.notBlock');
    expect(note?.text).toContain('不是方块');
    expect(note?.text).toContain('"skill":"use"');
  });

  it('执行器也挡:一个面都不试,回执直接给该用的姿势', async () => {
    const bot = boatBot('acacia_boat');
    const { exec, reports } = makeExecutorOn(bot);
    exec.submit([{ skill: 'build', material: 'acacia_boat', anchors: [[1, 64, 0]] } as unknown as SkillCall]);
    await waitUntil(() => reports.length === 1, 5000);
    expect(reports[0].kind).toBe('blocked');
    expect(reports[0].text).toContain('不是方块');
    expect(reports[0].text).not.toContain('六个面');
  });

  it('运输船与竹筏同判', () => {
    const bot = boatBot('bamboo_raft');
    for (const material of ['bamboo_raft', 'oak_chest_boat']) {
      const note = precheckStep(
        bot as never,
        { skill: 'build', material, anchors: [[1, 64, 0]] } as unknown as SkillCall,
        deps(bot) as never,
      );
      expect(note?.rule).toBe('build.notBlock');
    }
  });

  it('真方块不受影响:圆石照旧走 build 的判据', () => {
    const bot = boatBot('acacia_boat');
    const note = precheckStep(
      bot as never,
      { skill: 'build', material: 'cobblestone', anchors: [[1, 64, 0]] } as unknown as SkillCall,
      deps(bot) as never,
    );
    expect(note?.rule).not.toBe('build.notBlock');
  });
});
