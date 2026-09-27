/**
 * 门的 boundingBox 无论开关均为 block，寻路须结合门状态与交互能力；关闭木门可开启，铁门按墙处理。
 * 测试在 prismarine-world 与 1.20.6 方块表上运行真实 A*，检查可达性、useOne 和挖门动作。
 */
import { describe, expect, it } from 'vitest';
import { createRequire } from 'node:module';
import pathfinderPkg, { Movements } from 'mineflayer-pathfinder';
import AStar from 'mineflayer-pathfinder/lib/astar.js';
import Move from 'mineflayer-pathfinder/lib/move.js';
import {
  applyDoorState, doorStateOf, installPathfinderPerf,
} from '../../../src/worlds/minecraft/pathfinder-perf.ts';

const { goals } = pathfinderPkg as unknown as { goals: { GoalNear: new (...a: number[]) => unknown } };

const req = createRequire(createRequire(import.meta.url).resolve('mineflayer/package.json'));
const registry = req('prismarine-registry')('1.20.6');
const World = req('prismarine-world')(registry);
const Chunk = req('prismarine-chunk')(registry);
const PrismarineBlock = req('prismarine-block')(registry);
const { Vec3 } = req('vec3');

const STONE = registry.blocksByName.stone.defaultState as number;
const GRASS = registry.blocksByName.grass_block.defaultState as number;

/** 找某种门的某个具体状态:按属性精确取,免得撞上 defaultState 的开合不确定 */
function doorState(name: string, want: Record<string, string>): number {
  const b = registry.blocksByName[name] as { minStateId: number; maxStateId: number };
  for (let s = b.minStateId; s <= b.maxStateId; s++) {
    const props = PrismarineBlock.fromStateId(s, 0).getProperties() as Record<string, unknown>;
    if (Object.entries(want).every(([k, v]) => String(props[k]) === v)) return s;
  }
  throw new Error(`没有这个状态: ${name} ${JSON.stringify(want)}`);
}

/**
 * 一堵 z=0 的石墙(y=64~65),墙上 x=0 留一个门洞,门洞里放一扇门(上下两半)。
 * 地面 y=63 草方块、可走面 y=64。她从 (0,64,-3) 走到 (0,64,3),门是唯一直路。
 */
const z0 = 0;

function makeDoorWorld(lower: number | null, upper: number | null) {
  const world = new World(null).sync;
  for (let cx = -1; cx <= 1; cx++) {
    for (let cz = -1; cz <= 1; cz++) world.setColumn(cx, cz, new Chunk({ minY: -64, worldHeight: 384 }));
  }
  for (let x = -8; x < 8; x++) {
    for (let z = -8; z < 8; z++) {
      for (let y = 56; y < 63; y++) world.setBlockStateId(new Vec3(x, y, z), STONE);
      world.setBlockStateId(new Vec3(x, 63, z), GRASS);
    }
  }
  // 墙:整条 z=0 两格高,只在 x=0 留洞
  for (let x = -8; x < 8; x++) {
    if (x === 0) continue;
    for (let y = 64; y <= 65; y++) world.setBlockStateId(new Vec3(x, y, z0), STONE);
  }
  if (lower !== null) world.setBlockStateId(new Vec3(0, 64, z0), lower);
  if (upper !== null) world.setBlockStateId(new Vec3(0, 65, z0), upper);
  return world;
}

function makeBot(world: unknown) {
  const items = [
    { type: registry.itemsByName.iron_pickaxe.id as number, count: 1, name: 'iron_pickaxe', nbt: null, metadata: 0 },
  ];
  const bot: Record<string, unknown> = {
    registry,
    version: '1.20.6',
    world,
    blockAt: (p: unknown) => (world as { getBlock(p: unknown): unknown }).getBlock(p),
    inventory: { items: () => items },
    entity: { position: new Vec3(0.5, 64, -2.5), effects: {}, height: 1.8 },
    entities: {} as Record<string, unknown>,
    game: { minY: -64, height: 384 },
  };
  bot.pathfinder = {
    bestHarvestTool: (block: { digTime: (...a: unknown[]) => number }) => {
      let fastest = Number.MAX_VALUE;
      let best: unknown = null;
      for (const tool of items) {
        const t = block.digTime(tool.type, false, false, false, [], {});
        if (t < fastest) { fastest = t; best = tool; }
      }
      return best;
    },
  };
  return bot;
}

interface DoorPath {
  status: string;
  /** 路径里所有「用一下这一格」(开门)的落点 */
  useOne: Array<{ x: number; y: number; z: number }>;
  /** 路径里被排进要挖的格 */
  breaks: Array<{ x: number; y: number; z: number }>;
  /** 落脚点里 z=0(门那一列)的那些 */
  throughDoor: Array<{ x: number; y: number; z: number }>;
}

interface Tuning {
  /** bridge.applyTuning 生产值是 true */
  canOpenDoors?: boolean;
  /** bridge.applyTuning 把门钉进 blocksCantBreak;false 用来验"她宁可开门也不挖门" */
  doorsCantBreak?: boolean;
}

/**
 * 与 bridge.applyTuning 同一套门相关设置。
 *
 * 地形(石头/草)一律不许挖:否则 canDig 会让"从墙上刨个洞过去"永远存在,
 * 这张图就问不出"门本身走不走得通"了。
 */
function tunedMovements(bot: unknown, tuning: Tuning): Movements {
  const m = new Movements(bot as never);
  m.canDig = true;
  (m as unknown as { canOpenDoors: boolean }).canOpenDoors = tuning.canOpenDoors ?? true;
  const byName = registry.blocksByName as Record<string, { id: number } | undefined>;
  for (const name of ['stone', 'grass_block', 'dirt']) {
    const b = byName[name];
    if (b) m.blocksCantBreak.add(b.id);
  }
  if (tuning.doorsCantBreak ?? true) {
    for (const name of Object.keys(byName)) {
      if (!name.endsWith('_door') && !name.endsWith('_fence_gate')) continue;
      const b = byName[name];
      if (b) m.blocksCantBreak.add(b.id);
    }
  }
  m.scafoldingBlocks = [];
  return m;
}

function walkThroughDoor(world: unknown, tuning: Tuning = {}): DoorPath {
  const bot = makeBot(world);
  const m = tunedMovements(bot, tuning);
  (m as unknown as { clearCollisionIndex(): void }).clearCollisionIndex();
  (m as unknown as { updateCollisionIndex(): void }).updateCollisionIndex();
  const start = new (Move as never as new (...a: unknown[]) => unknown)(0, 64, -3, 0, 0);
  const astar = new (AStar as never as new (...a: unknown[]) => {
    compute(): {
      status: string;
      path: Array<{
        x: number; y: number; z: number;
        toBreak?: Array<{ x: number; y: number; z: number }>;
        toPlace?: Array<{ x: number; y: number; z: number; useOne?: boolean }>;
      }>;
    };
  })(start, m, new goals.GoalNear(0, 64, 3, 0), 5_000, 60, -1);
  let res = astar.compute();
  while (res.status === 'partial') res = astar.compute();
  const useOne: DoorPath['useOne'] = [];
  const breaks: DoorPath['breaks'] = [];
  const throughDoor: DoorPath['throughDoor'] = [];
  for (const mv of res.path) {
    for (const p of mv.toPlace ?? []) if (p.useOne === true) useOne.push({ x: p.x, y: p.y, z: p.z });
    for (const b of mv.toBreak ?? []) breaks.push({ x: b.x, y: b.y, z: b.z });
    if (mv.z === z0) throughDoor.push({ x: mv.x, y: mv.y, z: mv.z });
  }
  return { status: res.status, useOne, breaks, throughDoor };
}

// 补丁是进程级 prototype 覆写,装上撤不掉:"装之前"的读数必须在任何 it 之前取。
const OPEN_DOOR = {
  lower: doorState('oak_door', { half: 'lower', open: 'true', facing: 'north', hinge: 'left', powered: 'false' }),
  upper: doorState('oak_door', { half: 'upper', open: 'true', facing: 'north', hinge: 'left', powered: 'false' }),
};
const SHUT_DOOR = {
  lower: doorState('oak_door', { half: 'lower', open: 'false', facing: 'north', hinge: 'left', powered: 'false' }),
  upper: doorState('oak_door', { half: 'upper', open: 'false', facing: 'north', hinge: 'left', powered: 'false' }),
};
const SHUT_IRON = {
  lower: doorState('iron_door', { half: 'lower', open: 'false', facing: 'north', hinge: 'left', powered: 'false' }),
  upper: doorState('iron_door', { half: 'upper', open: 'false', facing: 'north', hinge: 'left', powered: 'false' }),
};
const openBeforePatch = walkThroughDoor(makeDoorWorld(OPEN_DOOR.lower, OPEN_DOOR.upper));

describe('寻路器与门', () => {
  it('装补丁前:开着的门就是一堵墙,门不许挖时一步都过不去', () => {
    // 这一条钉的是**被修掉的那个行为**:boundingBox 按类型给,开着的门 safe=false。
    expect(openBeforePatch.status).toBe('noPath');
  });

  it('开着的门:直接走过去,不用开、不挖', () => {
    installPathfinderPerf();
    const path = walkThroughDoor(makeDoorWorld(OPEN_DOOR.lower, OPEN_DOOR.upper));
    expect(path.status).toBe('success');
    // 门那一列确实是路线的一部分(不是从旁边绕过去的 —— 墙上只有这一个洞)
    expect(path.throughDoor.some((c) => c.x === 0 && c.y === 64)).toBe(true);
    // 开着的门不能再「用一下」:那一下是把门关上
    expect(path.useOne).toHaveLength(0);
    expect(path.breaks).toHaveLength(0);
  });

  it('关着的木门:生成「用一下下半扇再过去」,不挖门', () => {
    installPathfinderPerf();
    const path = walkThroughDoor(makeDoorWorld(SHUT_DOOR.lower, SHUT_DOOR.upper));
    expect(path.status).toBe('success');
    expect(path.useOne).toEqual([{ x: 0, y: 64, z: 0 }]);
    expect(path.breaks).toHaveLength(0);
    // 落脚点只在下半扇那一格,上半扇(y=65)永远不当落脚格
    expect(path.throughDoor.every((c) => c.y === 64)).toBe(true);
  });

  it('canOpenDoors 关着时,关着的木门照旧是墙(开关仍然管事)', () => {
    installPathfinderPerf();
    const path = walkThroughDoor(makeDoorWorld(SHUT_DOOR.lower, SHUT_DOOR.upper), { canOpenDoors: false });
    expect(path.status).toBe('noPath');
  });

  it('关着的木门允许挖时也不挖:开一下比刨一块便宜', () => {
    installPathfinderPerf();
    const path = walkThroughDoor(
      makeDoorWorld(SHUT_DOOR.lower, SHUT_DOOR.upper),
      { doorsCantBreak: false },
    );
    expect(path.status).toBe('success');
    expect(path.useOne).toEqual([{ x: 0, y: 64, z: 0 }]);
    expect(path.breaks).toHaveLength(0);
  });

  it('关着的铁门:手上没有开它的办法,当墙,不假装能过', () => {
    installPathfinderPerf();
    const path = walkThroughDoor(makeDoorWorld(SHUT_IRON.lower, SHUT_IRON.upper));
    expect(path.status).toBe('noPath');
    expect(path.useOne).toHaveLength(0);
  });

  it('门洞空着当基线:同一张图不放门就是一条直路', () => {
    installPathfinderPerf();
    const path = walkThroughDoor(makeDoorWorld(null, null));
    expect(path.status).toBe('success');
    expect(path.useOne).toHaveLength(0);
    expect(path.breaks).toHaveLength(0);
  });
});

describe('门的逐状态判词', () => {
  it('开着=可穿过、关着的木门=用一下、铁门=锁着;上半扇带标记', () => {
    // 1 = DOOR_OPEN,2 = DOOR_SHUT_HAND,3 = DOOR_SHUT_LOCKED,+4 = 上半扇
    expect(doorStateOf('oak_door', { open: true, half: 'lower' })).toBe(1);
    expect(doorStateOf('oak_door', { open: 'true', half: 'upper' })).toBe(1 + 4);
    expect(doorStateOf('oak_door', { open: false, half: 'lower' })).toBe(2);
    expect(doorStateOf('oak_door', { open: false, half: 'upper' })).toBe(2 + 4);
    expect(doorStateOf('iron_door', { open: false, half: 'lower' })).toBe(3);
    expect(doorStateOf('iron_door', { open: true, half: 'lower' })).toBe(1);
    // 栅栏门没有上下半扇
    expect(doorStateOf('oak_fence_gate', { open: false })).toBe(2);
    expect(doorStateOf('oak_fence_gate', { open: true })).toBe(1);
    // 活板门不在这一族(它是横着的地板,「开一下再过去」等于把脚下打开)
    expect(doorStateOf('oak_trapdoor', { open: true, half: 'bottom' })).toBe(0);
    expect(doorStateOf('stone', {})).toBe(0);
  });

  it('落到读块结果上:开着的门撤掉 openable,关着的木门反过来', () => {
    const shut = { safe: false, physical: true, openable: false, height: 65 };
    applyDoorState(shut, 2, 64, true);
    expect(shut).toEqual({ safe: true, physical: false, openable: true, height: 64 });

    const open = { safe: false, physical: true, openable: true, height: 65 };
    applyDoorState(open, 1, 64, true);
    expect(open).toEqual({ safe: true, physical: false, openable: false, height: 64 });

    // canOpenDoors 关着:关着的门一个字不改
    const shutNoOpen = { safe: false, physical: true, openable: false, height: 65 };
    applyDoorState(shutNoOpen, 2, 64, false);
    expect(shutNoOpen).toEqual({ safe: false, physical: true, openable: false, height: 65 });

    // 铁门任何时候都不改
    const iron = { safe: false, physical: true, openable: false, height: 65 };
    applyDoorState(iron, 3, 64, true);
    expect(iron).toEqual({ safe: false, physical: true, openable: false, height: 65 });
  });
});
