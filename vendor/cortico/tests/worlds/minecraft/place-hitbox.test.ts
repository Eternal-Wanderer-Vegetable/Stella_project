/**
 * 放置夹具按原版 isUnobstructed 拒绝与玩家碰撞箱重叠的落点，覆盖擦边放置和寻路停滞。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  V, log, makeExecutorOn, nextTaskId, waitUntil,
} from './executor-harness.ts';
import { Executor, type TaskReport } from '../../../src/worlds/minecraft/executor.ts';

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date', 'setTimeout', 'clearTimeout', 'setInterval', 'clearInterval'] });
});

afterEach(() => {
  vi.useRealTimers();
});

const PLAYER_HALF_WIDTH = 0.3;
const PLAYER_HEIGHT = 1.8;
const NON_SOLID = new Set(['air', 'water', 'lava', 'torch']);

/**
 * 会拒绝擦身放置的假世界。
 *
 * `goto` 落在格子正中(真寻路器的 GoalBlock 语义),不是格子角上:落在角上时
 * 半宽 0.3 的碰撞箱会探进邻格,退半步这件事在台架里就永远退不干净。
 */
function placeBot(cells: Record<string, string>, at: { x: number; y: number; z: number }) {
  const world = new Map(Object.entries(cells));
  const names = new Set(['air', 'stone', 'lava', 'cobblestone', ...world.values()]);
  const blocksByName: Record<string, { id: number; name: string }> = {};
  let nextId = 1;
  for (const n of names) blocksByName[n] = { id: nextId++, name: n };
  const keyOf = (x: number, y: number, z: number) => `${x},${y},${z}`;
  const bag = [{ name: 'cobblestone', count: 64, type: blocksByName.cobblestone.id }];
  /** 服务端拒了哪些落点:测试据此断言"这一包根本没发出去"与"发了被拒"的区别 */
  const refused: Array<{ x: number; y: number; z: number }> = [];
  const keys: string[] = [];
  /**
   * 假寻路器照上游的取消语义:`setGoal(null)` / `stop()` 让在跑的那次 goto reject。
   * 缺了这一条,零位移看门狗撤掉目标之后 goto 仍挂着,受阻句永远出不来。
   */
  let rejectGoto: ((e: Error) => void) | null = null;
  const cancel = (why: string): void => {
    const r = rejectGoto;
    rejectGoto = null;
    r?.(new Error(why));
  };
  const pathfinder = {
    /** true = 收下目标却一步不挪,只有撤目标能把它掐掉(钉死的现场) */
    stall: false,
    stop: () => cancel('PathStopped'),
    setGoal: (goal: unknown) => { if (goal === null) cancel('GoalChanged'); },
    goto: async (goal: { x?: number; y?: number; z?: number }) => {
      if (pathfinder.stall) {
        await new Promise<void>((_res, rej) => { rejectGoto = rej; });
        return;
      }
      const p = bot.entity.position;
      bot.entity.position = new V(
        goal.x === undefined ? p.x : goal.x + 0.5,
        goal.y ?? p.y,
        goal.z === undefined ? p.z : goal.z + 0.5,
      );
    },
  };
  const bot = {
    world,
    refused,
    keys,
    entity: { id: 9, position: new V(at.x, at.y, at.z), onGround: true, velocity: new V(0, 0, 0) },
    entities: {},
    players: {},
    health: 20,
    food: 20,
    game: { minY: -64, height: 384, dimension: 'minecraft:the_nether' },
    inventory: { items: () => bag },
    registry: { blocksByName, itemsByName: {}, items: {} },
    heldItem: bag[0],
    equip: async () => {},
    lookAt: async () => {},
    clearControlStates: () => { keys.push('clear'); },
    setControlState: (name: string, on: boolean) => { if (on) keys.push(name); },
    blockAt: (p: V) => {
      const [x, y, z] = [Math.floor(p.x), Math.floor(p.y), Math.floor(p.z)];
      const name = world.get(keyOf(x, y, z)) ?? 'air';
      return {
        name,
        position: new V(x, y, z),
        boundingBox: NON_SOLID.has(name) ? 'empty' : 'block',
        diggable: true,
        canHarvest: () => true,
      };
    },
    /** 原版 isUnobstructed:落点与玩家碰撞箱有重叠就拒,包发了也不生效 */
    placeBlock: async (ref: { position: V }, face: V) => {
      const dest = { x: ref.position.x + face.x, y: ref.position.y + face.y, z: ref.position.z + face.z };
      const p = bot.entity.position;
      const w = PLAYER_HALF_WIDTH;
      const hits = p.x - w < dest.x + 1 && p.x + w > dest.x
        && p.z - w < dest.z + 1 && p.z + w > dest.z
        && p.y < dest.y + 1 && p.y + PLAYER_HEIGHT > dest.y;
      if (hits) { refused.push(dest); return; }
      world.set(keyOf(dest.x, dest.y, dest.z), 'cobblestone');
      bag[0].count--;
    },
    canDigBlock: () => true,
    digTime: () => 10,
    stopDigging: () => {},
    dig: async (b: { position: V }) => { world.delete(keyOf(b.position.x, b.position.y, b.position.z)); },
    findBlocks: () => [],
    pathfinder,
  };
  return bot;
}

/** 石头地板 + 上方空气的一小片下界,外加点名的几格 */
function flatWorld(extra: Record<string, string> = {}): Record<string, string> {
  const cells: Record<string, string> = {};
  for (let x = -3; x <= 4; x++) {
    for (let z = -3; z <= 4; z++) {
      for (let y = 60; y <= 63; y++) cells[`${x},${y},${z}`] = 'stone';
    }
  }
  return { ...cells, ...extra };
}

describe('放置:碰撞箱擦边', () => {
  /**
   * 第一级台阶支撑格与玩家碰撞箱重叠，其他井筒朝向被岩浆阻挡；须后退腾出放置空间。
   */
  it('螺旋第一级的支撑格被自己身子压着:退半步再垫,不是报「服务端不认」', async () => {
    const bot = placeBot(
      // 另外三种井筒摆法的第一级要挖到岩浆(在头顶再上一格,不挡退半步的落脚)
      flatWorld({ '0,66,1': 'lava', '0,66,-1': 'lava', '-1,66,0': 'lava' }),
      // x 小数 0.85:脚下格是 (0,64,0),碰撞箱右边缘 1.15 探进 (1,64,0)
      { x: 0.85, y: 64, z: 0.5 },
    );
    const { exec, reports } = makeExecutorOn(bot);
    exec.submit([{ skill: 'tunnel', at: ['~', '~1', '~'], spiral: true }]);
    await waitUntil(() => reports.length === 1, 15_000);
    expect(reports[0].kind).toBe('done');
    expect(reports[0].text).toContain('到顶了');
    expect(reports[0].text).not.toContain('服务端不认');
    // 支撑格真放上了,而且一个被拒的包都没发出去
    expect(bot.world.get('1,64,0')).toBe('cobblestone');
    expect(bot.refused).toEqual([]);
  });

  /**
   * 垫脚失败的两种归因不许混成一句:一包都没发出去(六个面没有参照)与
   * 发了三包被服务端拒,她换的招不一样。
   */
  it('垫脚格六个面都没有参照面时说「这一包没发出去」,不说服务端不认', async () => {
    // 站在虚空里的一格柱子上:第一级台阶的支撑格四周全空,四种井筒摆法都一样
    const bot = placeBot({ '0,63,0': 'stone' }, { x: 0.5, y: 64, z: 0.5 });
    const { exec, reports } = makeExecutorOn(bot);
    // 升 5 格:近到 2 格内的终点会被步骤核验判成达成,盖过受阻句
    exec.submit([{ skill: 'tunnel', at: ['~', '~5', '~'], spiral: true }]);
    await waitUntil(() => reports.length === 1, 15_000);
    expect(reports[0].kind).toBe('blocked');
    expect(reports[0].text).toContain('(1, 64, 0) 六个面都没有能贴着放的实心方块,这一包没发出去');
    expect(reports[0].text).not.toContain('服务端不认');
    // 悬空里上行只有塔走得通:它垫的是自己脚下那一格,不吃邻格的参照面
    expect(reports[0].text).toContain('走塔(at 放正上方、不带 spiral)');
    expect(bot.refused).toEqual([]);
  });

  it('build 落点被身子擦着:退半步再放,不算一次服务端没认', async () => {
    const bot = placeBot(flatWorld(), { x: 0.85, y: 64, z: 0.5 });
    const { exec, reports } = makeExecutorOn(bot);
    exec.submit([{ skill: 'build', material: 'cobblestone', on: [{ at: [1, 63, 0], face: 'up' }] }]);
    await waitUntil(() => reports.length === 1, 15_000);
    expect(reports[0].kind).toBe('done');
    expect(bot.world.get('1,64,0')).toBe('cobblestone');
    expect(bot.refused).toEqual([]);
  });
});

describe('build:竖直单列', () => {
  it('搭完人不在那一列上时点名,并指向 tunnel 的塔', async () => {
    const bot = placeBot(flatWorld(), { x: 0.5, y: 64, z: 0.5 });
    const { exec, reports } = makeExecutorOn(bot);
    exec.submit([{
      skill: 'build', material: 'cobblestone', shape: 'line',
      anchors: [[2, 64, 2], [2, 66, 2]],
    }]);
    await waitUntil(() => reports.length === 1, 15_000);
    expect(reports[0].text).toContain('那一列,人不在它上面');
    expect(reports[0].text).toContain('用 tunnel 的塔');
  });

  it('横着一排不报这一句', async () => {
    const bot = placeBot(flatWorld(), { x: 0.5, y: 64, z: 0.5 });
    const { exec, reports } = makeExecutorOn(bot);
    exec.submit([{
      skill: 'build', material: 'cobblestone', shape: 'line',
      anchors: [[2, 64, 2], [4, 64, 2]],
    }]);
    await waitUntil(() => reports.length === 1, 15_000);
    expect(reports[0].text).not.toContain('人不在它上面');
  });
});

describe('寻路:钉在原地', () => {
  /**
   * 首次静止窗口到期后尝试解卡；解卡也没有位移时直接报告钉在原地，不再等待第二个静止窗口。
   */
  it('零位移跳闸先解卡;解卡也动不了就报「钉在原地」,不再赔一轮', async () => {
    const bot = placeBot(flatWorld(), { x: 0.5, y: 64, z: 0.5 });
    bot.pathfinder.stall = true;
    const reports: TaskReport[] = [];
    const exec = new Executor({
      getBot: () => bot as never,
      report: (r: TaskReport) => reports.push(r),
      log,
      nextId: nextTaskId(),
    });
    const t0 = Date.now();
    exec.submit([{ skill: 'goto', at: [20, 64, 20] }]);
    await waitUntil(() => reports.length === 1, 30_000);
    expect(reports[0].kind).toBe('blocked');
    expect(reports[0].text).toContain('钉在原地');
    expect(reports[0].text).toContain('跳/退解卡也没能动一下');
    expect(reports[0].text).toContain('这不是路难走,是人动不了');
    // 解卡真按了键:跳 + 后退、跳 + 侧移各一次
    expect(bot.keys).toContain('jump');
    expect(bot.keys).toContain('back');
    expect(bot.keys).toContain('left');
    // 一个静止档 + 解卡,不是两个静止档
    expect(Date.now() - t0).toBeLessThan(18_000);
  }, 35_000);
});
