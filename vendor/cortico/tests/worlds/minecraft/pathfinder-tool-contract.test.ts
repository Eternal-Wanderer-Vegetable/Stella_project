/**
 * `bestHarvestTool` 的返回值有两个消费者,对 `null` 的解释正好相反:
 *
 * - 规划侧 `Movements.safeOrBreak`(`mineflayer-pathfinder/lib/movements.js:292-297`,
 *   本仓库生效的是 `pathfinder-perf.ts:385-389` 的逐字复刻):
 *   `digTime(tool ? tool.type : null, ...)` —— `null` = **按徒手计价**;
 * - 执行侧 `mineflayer-pathfinder/index.js:502-508`:
 *   `if (!tool) digBlock()` —— `null` = **不换手,继续用手上那把**。
 *
 * 所以"同速不换手"绝不能用 `null` 表达:手持镐子时 A* 会按徒手给每一格挖掘计价
 * (石头 1.9 → 23.5,黑曜石 25 倍),地表宁绕二十格不挖一格,地下直接把搜索预算耗尽。
 *
 * 这一组不 stub digTime:方块与物品都取真 minecraft-data,成本走真 `Movements.safeOrBreak`,
 * 换手走真 `mineflayer/lib/plugins/simple_inventory.js` 的 `equip`。只断言返回值,
 * 或者只断言"返回了 null",都复现不出这条 bug —— 它只在返回值喂进消费者时才显形。
 */
import { describe, expect, it } from 'vitest';
import { createRequire } from 'node:module';
import { installPathfinderToolSelection } from '../../../src/worlds/minecraft/mineflayer-fixes.ts';
import type { Logger } from '../../../src/core/types.ts';

const log = { child() { return this; }, info() {}, warn() {}, error() {}, debug() {}, trace() {}, emit() {} } as unknown as Logger;

const require_ = createRequire(import.meta.url);
// minecraft-data / prismarine-block 不是本仓库的直接依赖,只能顺着 mineflayer 的解析根找;
// require.resolve 返回的是 realpath,pnpm 的 .pnpm 布局下这一跳才接得上
const mfRequire = createRequire(require_.resolve('mineflayer'));

/** 服务端与执行器都钉在这一版;方块硬度与工具等级表随版本变,契约值必须同版取 */
const MC_VERSION = '1.20.6';

const mcData = mfRequire('minecraft-data')(MC_VERSION) as {
  blocksByName: Record<string, { id: number; defaultState: number }>;
  itemsByName: Record<string, { id: number }>;
};
const PBlock = mfRequire('prismarine-block')(MC_VERSION) as {
  fromStateId(stateId: number, biomeId: number): RealBlock;
};
const { Vec3 } = mfRequire('vec3') as { Vec3: new (x: number, y: number, z: number) => Vec3Like };
const Movements = require_('mineflayer-pathfinder/lib/movements.js') as new (bot: unknown) => MovementsLike;
const injectSimpleInventory = require_('mineflayer/lib/plugins/simple_inventory.js') as (bot: unknown) => void;

interface Vec3Like { x: number; y: number; z: number; equals(o: Vec3Like): boolean; clone(): Vec3Like }
interface RealBlock {
  type: number;
  position?: Vec3Like;
  digTime(
    itemType: number | null, creative: boolean, inWater: boolean, notOnGround: boolean,
    enchantments: unknown[], effects: unknown,
  ): number;
}
interface MovementsLike {
  getBlock(pos: Vec3Like, dx: number, dy: number, dz: number): RealBlock;
  safeOrBreak(block: RealBlock, toBreak: unknown[]): number;
}

type Stack = { name: string; type: number; count: number; slot: number };

const pickaxe = (): Stack => ({ name: 'diamond_pickaxe', type: mcData.itemsByName.diamond_pickaxe.id, count: 1, slot: 36 });
const dirt = (): Stack => ({ name: 'dirt', type: mcData.itemsByName.dirt.id, count: 32, slot: 37 });

/** 一格实心方块,四周与头顶都是空气(safeToBreak 要回读这五格) */
function rig(blockName: string, held: Stack | null, bag: Stack[]) {
  const solid = PBlock.fromStateId(mcData.blocksByName[blockName].defaultState, 0);
  const air = PBlock.fromStateId(mcData.blocksByName.air.defaultState, 0);
  const target = new Vec3(0, 64, 0);
  const bot = {
    registry: mcData,
    entity: { effects: {}, position: new Vec3(0, 65, 0) },
    heldItem: held,
    inventory: { hotbarStart: 36, items: () => bag },
    blockAt(pos: Vec3Like): RealBlock {
      const src = pos.equals(target) ? solid : air;
      // Movements.getBlock 会往回读的 block 上挂 safe/physical 等字段,共享实例会被互相污染
      const copy = Object.assign(Object.create(Object.getPrototypeOf(src)) as RealBlock, src);
      copy.position = pos.clone();
      return copy;
    },
    pathfinder: { bestHarvestTool: (_b: RealBlock): Stack | null => null },
  };
  installPathfinderToolSelection(bot as never, log);
  const movements = new Movements(bot);
  return {
    bot,
    /** 规划侧真实成本:`this.bot.pathfinder.bestHarvestTool` 由上游自己调 */
    laborCost: (): number => movements.safeOrBreak(movements.getBlock(target, 0, 0, 0), []),
    /** 规划侧实际用来计价的 itemType(`tool ? tool.type : null`)对应的挖掘毫秒 */
    plannedDigMs: (): number => {
      const tool = bot.pathfinder.bestHarvestTool(movements.getBlock(target, 0, 0, 0));
      return solid.digTime(tool ? tool.type : null, false, false, false, [], bot.entity.effects);
    },
    tool: (): Stack | null => bot.pathfinder.bestHarvestTool(movements.getBlock(target, 0, 0, 0)),
  };
}

describe('寻路选工具:返回值必须同时对规划侧与执行侧成立', () => {
  it('手持钻石镐挖石头:计价按镐算,不按徒手', () => {
    const bag = [pickaxe(), dirt()];
    const held = bag[0];
    const r = rig('stone', held, bag);

    // 手上那把就是最快的一把;返回 null 会被规划侧读成"徒手"
    expect(r.tool()).toBe(held);

    // 真 minecraft-data:钻石镐 300ms / 徒手 7500ms
    expect(r.plannedDigMs()).toBe(300);
    expect(r.laborCost()).toBeCloseTo(1.9, 6);
  });

  it('黑曜石同理:徒手计价把一格挖掘抬到 25 倍', () => {
    const bag = [pickaxe(), dirt()];
    const r = rig('obsidian', bag[0], bag);
    expect(r.plannedDigMs()).toBe(75_000);
    expect(r.laborCost()).toBeCloseTo(226, 6);
  });

  it('同一格石头,手持镐与手持泥土算出来的成本必须相等', () => {
    // 刚垫完脚手持泥土时镐子"严格更快"会被返回,手持镐时却返回 null —— 同一段路
    // 两次重算差 10 倍,路径在两种走法之间来回跳
    const withPick = rig('stone', pickaxe(), [pickaxe(), dirt()]);
    const bagAfterScaffold = [pickaxe(), dirt()];
    const withDirt = rig('stone', bagAfterScaffold[1], bagAfterScaffold);

    expect(withPick.plannedDigMs()).toBe(withDirt.plannedDigMs());
    expect(withPick.laborCost()).toBe(withDirt.laborCost());
  });

  it('空手且包里也没有更快的:返回 null,规划侧读成徒手,语义正确', () => {
    const r = rig('stone', null, [dirt()]);
    expect(r.tool()).toBeNull();
    expect(r.plannedDigMs()).toBe(7_500);
  });
});

describe('执行侧:返回手上那把时 equip 不动槽位', () => {
  /** 真 simple_inventory 插件;线路与槽位动作全部记账(插件自己会盖掉 bot.setQuickBarSlot) */
  function equipBot() {
    const moves: string[] = [];
    const bot = {
      quickBarSlot: 0,
      supportFeature: (): boolean => false,
      inventory: {
        slots: [] as Array<Stack | null>,
        findInventoryItem: (): Stack | null => null,
        firstEmptySlotRange: (): number | null => null,
      },
      _client: { write: (name: string, params: { slotId?: number }): void => { moves.push(`packet:${name}:${params.slotId}`); } },
      updateHeldItem: (): void => {},
      clickWindow: async (slot: number): Promise<void> => { moves.push(`click:${slot}`); },
      moveSlotItem: async (from: number, to: number): Promise<void> => { moves.push(`move:${from}->${to}`); },
      equip: (async (): Promise<void> => {}) as (item: unknown, dest: string) => Promise<void>,
    };
    injectSimpleInventory(bot);
    return { bot, moves };
  }

  it('equip 手上那把是彻底的空动作,换别的才发包', async () => {
    const { bot, moves } = equipBot();
    // heldItem 定义为 inventory.slots[QUICK_BAR_START + quickBarSlot](inventory.js:49-53),
    // equip 的 destSlot 同式;两者相等时 simple_inventory.js:101-104 直接 return
    await bot.equip(pickaxe(), 'hand');
    expect(moves).toEqual([]);

    // 记账层本身是活的:换快捷栏里的另一格确实发 held_item_slot
    await bot.equip(dirt(), 'hand');
    expect(moves).toEqual(['packet:held_item_slot:1']);
  });
});
