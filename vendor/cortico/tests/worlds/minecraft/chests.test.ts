import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';
import {
  ChestBook, chestBlockName, hasItem, hasRoom, matchItemName, matchMaterialName,
} from '../../../src/worlds/minecraft/chests.ts';

const dirs: string[] = [];
afterEach(() => {
  for (const d of dirs.splice(0)) rmSync(d, { recursive: true, force: true });
});

describe('ChestBook', () => {
  it('开过才记得;落盘后再读还在', () => {
    const dir = mkdtempSync(join(tmpdir(), 'mc-chests-'));
    dirs.push(dir);
    const file = join(dir, 'minecraft-chests.json');
    const a = new ChestBook(file);
    expect(a.get('overworld', { x: 1, y: 64, z: 2 })).toBeUndefined();
    a.remember('overworld', { x: 1, y: 64, z: 2 }, [{ name: 'coal', count: 16 }], 1, 27);
    expect(a.get('overworld', { x: 1, y: 64, z: 2 })?.items).toEqual([{ name: 'coal', count: 16 }]);
    const raw = JSON.parse(readFileSync(file, 'utf8'));
    expect(raw['overworld:1,64,2'].items[0].name).toBe('coal');
    const b = new ChestBook(file);
    expect(b.get('overworld', { x: 1, y: 64, z: 2 })?.items).toEqual([{ name: 'coal', count: 16 }]);
  });

  it('clear 清空内存和文件', () => {
    const dir = mkdtempSync(join(tmpdir(), 'mc-chests-'));
    dirs.push(dir);
    const file = join(dir, 'minecraft-chests.json');
    const book = new ChestBook(file);
    book.remember('overworld', { x: 0, y: 64, z: 0 }, [{ name: 'dirt', count: 1 }], 1, 27);
    expect(book.clear()).toContain('1 个');
    expect(book.get('overworld', { x: 0, y: 64, z: 0 })).toBeUndefined();
    expect(JSON.parse(readFileSync(file, 'utf8'))).toEqual({});
  });

  it('hasRoom / hasItem 按账本判断,认类别名', () => {
    expect(matchItemName('log', 'oak_log')).toBe(true);
    // 前缀规则已删:它让 take dirt 捞走 dirt_path、stow iron 捞走全部铁装备
    expect(matchItemName('dirt', 'dirt_path')).toBe(false);
    expect(matchItemName('iron', 'iron_ingot')).toBe(false);
    const full = { x: 0, y: 0, z: 0, dimension: 'overworld', items: [{ name: 'cobblestone', count: 64 }], usedSlots: 27, slots: 27 };
    expect(hasRoom(full, 'dirt', 64)).toBe(false);
    expect(hasRoom({ ...full, usedSlots: 26 }, 'dirt', 64)).toBe(true);
    expect(hasRoom({ ...full, items: [{ name: 'oak_log', count: 10 }] }, 'log', 64)).toBe(true);
    expect(hasItem(full, 'cobblestone')).toBe(true);
    expect(hasItem(full, 'coal')).toBe(false);
  });

  // 堆叠上限是物品自带的属性,不是所有东西都堆到 64。写死 64 的时候一整叠 16 个
  // 鸡蛋算出 16 % 64 = 16 被判成"还有空位",堆叠上限 1 的每一格都判成没满。
  it('hasRoom 按物品自己的堆叠上限判满栈,不是一律 64', () => {
    const at = { x: 0, y: 0, z: 0, dimension: 'overworld', usedSlots: 27, slots: 27 };
    const eggs = { ...at, items: [{ name: 'egg', count: 16 }] };
    expect(hasRoom(eggs, 'egg', 16)).toBe(false);   // 满栈
    expect(hasRoom(eggs, 'egg', 64)).toBe(true);
    expect(hasRoom({ ...eggs, items: [{ name: 'egg', count: 9 }] }, 'egg', 16)).toBe(true);
    // 堆叠上限 1:每一格都是满的
    expect(hasRoom({ ...at, items: [{ name: 'bucket', count: 1 }] }, 'bucket', 1)).toBe(false);
  });
});

describe('容器账本:炉子族与工作站', () => {
  const P = { x: 3, y: 64, z: -5 };

  it('炉子三槽位入账并落盘;due 只在到点且没报过时命中,markNotified 落盘存活', () => {
    const dir = mkdtempSync(join(tmpdir(), 'mc-chests-'));
    dirs.push(dir);
    const file = join(dir, 'minecraft-chests.json');
    const a = new ChestBook(file);
    const t0 = 1_000_000;
    a.rememberFurnace('overworld', P, 'furnace',
      { input: { name: 'raw_iron', count: 8 }, fuel: { name: 'coal', count: 2 }, output: null },
      t0, t0 + 80_000);
    const rec = a.get('overworld', P)!;
    expect(rec.name).toBe('furnace');
    // items 同步成非空槽清单:快照「近处」那行照读
    expect(rec.items).toEqual([{ name: 'raw_iron', count: 8 }, { name: 'coal', count: 2 }]);
    expect(a.due(t0 + 79_999)).toHaveLength(0);
    expect(a.due(t0 + 80_000)).toHaveLength(1);
    a.markNotified('overworld', P);
    expect(a.due(t0 + 80_000)).toHaveLength(0);
    // 落盘后再读:notified 也存活,重启不重复报
    const b = new ChestBook(file);
    expect(b.due(t0 + 80_000)).toHaveLength(0);
    expect(b.get('overworld', P)?.furnace?.input?.count).toBe(8);
  });

  it('loadedFurnaces 只回本维度、槽里有料/有成品的;取空之后不再点名', () => {
    const a = new ChestBook(null);
    a.rememberFurnace('overworld', P, 'furnace',
      { input: { name: 'raw_iron', count: 3 }, fuel: null, output: null }, 0, 30_000);
    a.rememberFurnace('the_nether', { x: 0, y: 64, z: 0 }, 'furnace',
      { input: { name: 'gold_ore', count: 1 }, fuel: null, output: null }, 0, 10_000);
    expect(a.loadedFurnaces('overworld')).toHaveLength(1);
    expect(a.loadedFurnaces('overworld')[0].furnace?.input?.name).toBe('raw_iron');
    // 取货之后槽位清空重记:不再压着料
    a.rememberFurnace('overworld', P, 'furnace', { input: null, fuel: null, output: null }, 1, null);
    expect(a.loadedFurnaces('overworld')).toHaveLength(0);
  });

  it('自备工作站带 placedAt 入账;重开箱子刷新内容不冲掉来历', () => {
    const a = new ChestBook(null);
    a.rememberStation('overworld', P, 'crafting_table', 1234);
    expect(a.get('overworld', P)?.placedAt).toBe(1234);
    // 后来当箱子开过一样的位置(比如放的是箱子):内容更新,placedAt 还在
    a.remember('overworld', P, [{ name: 'melon_slice', count: 32 }], 1, 27);
    const rec = a.get('overworld', P)!;
    expect(rec.items[0].name).toBe('melon_slice');
    expect(rec.placedAt).toBe(1234);
    expect(rec.name).toBe('crafting_table');
  });

  it('inCells 只回落在格子清单里的;forget 划账,没记过的不写盘', () => {
    const a = new ChestBook(null);
    a.rememberStation('overworld', P, 'crafting_table', 1);
    a.rememberStation('overworld', { x: 9, y: 64, z: 9 }, 'furnace', 2);
    const cells = [{ x: 3, y: 64, z: -5 }, { x: 4, y: 64, z: -5 }];
    expect(a.inCells('overworld', cells).map((r) => r.name)).toEqual(['crafting_table']);
    // 别的维度同坐标不算命中
    expect(a.inCells('the_nether', cells)).toHaveLength(0);
    expect(a.forget('overworld', P)).toBe(true);
    expect(a.forget('overworld', P)).toBe(false);
    expect(a.inCells('overworld', cells)).toHaveLength(0);
  });

  /**
   * 箱子账本提供已知容器的精确位置，供附近未扫描到容器时的回执补充事实。
   */
  it('chestsIn 只回本维度的箱子族:炉子与工作台不算,开箱记的没 name 也算', () => {
    const a = new ChestBook(null);
    // 开箱记下的那份不带 name:按 chest 兜底,照样算箱子
    a.remember('overworld', { x: 10, y: 64, z: 0 }, [{ name: 'coal', count: 4 }], 1, 27);
    a.rememberStation('overworld', { x: 11, y: 64, z: 0 }, 'barrel', 5);
    a.rememberStation('overworld', { x: 12, y: 64, z: 0 }, 'crafting_table', 6);
    a.rememberFurnace('overworld', { x: 13, y: 64, z: 0 }, 'furnace',
      { input: null, fuel: null, output: null }, 0, null);
    a.remember('the_nether', { x: 1, y: 64, z: 1 }, [], 0, 27);
    expect(a.chestsIn('overworld').map((r) => r.x)).toEqual([10, 11]);
    expect(a.chestsIn('the_nether').map((r) => r.x)).toEqual([1]);
    expect(a.chestsIn('the_end')).toHaveLength(0);
  });

  it('chestBlockName:开箱记的那份没 name 就按 chest 兜底,自备的按自己的名字', () => {
    const a = new ChestBook(null);
    a.remember('overworld', P, [], 0, 27);
    expect(chestBlockName(a.get('overworld', P)!)).toBe('chest');
    a.rememberStation('overworld', P, 'barrel', 1);
    expect(chestBlockName(a.get('overworld', P)!)).toBe('barrel');
  });
});


describe('matchMaterialName:真实 id 只认自己,裸类别名才走后缀', () => {
  const reg = {
    itemsByName: { obsidian: {}, crying_obsidian: {}, torch: {}, soul_torch: {}, oak_planks: {}, dirt: {} },
    blocksByName: { obsidian: {}, crying_obsidian: {}, torch: {}, soul_torch: {}, oak_planks: {}, dirt: {} },
  };

  it('真实 id 只认自己:同族的近亲一律不顶', () => {
    expect(matchMaterialName(reg, 'obsidian', 'obsidian')).toBe(true);
    expect(matchMaterialName(reg, 'obsidian', 'crying_obsidian')).toBe(false);
    expect(matchMaterialName(reg, 'torch', 'soul_torch')).toBe(false);
  });

  it('裸类别名(本身不是 id)照旧走后缀', () => {
    expect(matchMaterialName(reg, 'planks', 'oak_planks')).toBe(true);
    expect(matchMaterialName(reg, 'log', 'birch_log')).toBe(true);
  });

  it('没有 registry 时退回后缀口径:判据要的是「是不是真 id」,拿不到就别装作知道', () => {
    expect(matchMaterialName(null, 'obsidian', 'crying_obsidian')).toBe(true);
  });

  it('前缀不再是匹配的一部分:dirt 不捞 dirt_path', () => {
    expect(matchMaterialName(reg, 'dirt', 'dirt_path')).toBe(false);
  });
});
