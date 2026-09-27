/**
 * 附魔与耐久读数的单测。
 *
 * 这里守两件事:①1.20.5+ 的组件路与旧 NBT 路读出来是同一份事实;
 * ②耐久上限走原版公式表而**不是** minecraft-data —— 1.20.6 那份表里每件的
 * maxDurability 都是 1(diamond_pickaxe=1,1.20.4 同一字段是 1561),照它报等于报假话。
 */
import { describe, expect, it } from 'vitest';
import {
  maxDurabilityOf, readDamage, readDurability, readEnchants, readPotionId,
} from '../../../src/worlds/minecraft/item-facts.ts';

const REGISTRY = { enchantments: { 20: { name: 'efficiency' }, 22: { name: 'unbreaking' } } };

/** 1.20.5+ 服务端发来的形状 */
function componentItem(name: string, comps: Record<string, unknown>) {
  return { name, componentMap: new Map(Object.entries(comps).map(([k, data]) => [k, { data }])) };
}

/** 旧版 NBT 形状(台架假件与低版本走这条) */
function nbtItem(name: string, nbt: unknown) {
  return { name, nbt };
}

describe('maxDurabilityOf(原版公式表)', () => {
  it('工具按材质,盔甲按材质×部位', () => {
    expect(maxDurabilityOf('diamond_pickaxe')).toBe(1561);
    expect(maxDurabilityOf('netherite_sword')).toBe(2031);
    expect(maxDurabilityOf('golden_hoe')).toBe(32);
    expect(maxDurabilityOf('iron_chestplate')).toBe(240);
    expect(maxDurabilityOf('leather_boots')).toBe(65);
    expect(maxDurabilityOf('turtle_helmet')).toBe(275);
  });

  it('不按材质×部位算的那几件单列', () => {
    expect(maxDurabilityOf('shield')).toBe(336);
    expect(maxDurabilityOf('elytra')).toBe(432);
    expect(maxDurabilityOf('minecraft:shears')).toBe(238);
  });

  it('不带耐久的东西返回 null,不硬凑一个数', () => {
    expect(maxDurabilityOf('cobblestone')).toBeNull();
    expect(maxDurabilityOf('bread')).toBeNull();
    expect(maxDurabilityOf('turtle_boots')).toBeNull(); // 海龟壳只有头盔一件
  });
});

describe('readDamage / readDurability', () => {
  it('组件路:damage 组件就是已损耗点数', () => {
    expect(readDamage(componentItem('iron_chestplate', { damage: 22 }))).toBe(22);
    expect(readDurability(componentItem('iron_chestplate', { damage: 22 })))
      .toEqual({ left: 218, max: 240 });
  });

  it('NBT 路:Damage 键同义', () => {
    const it0 = nbtItem('diamond_pickaxe', { type: 'compound', value: { Damage: { type: 'int', value: 61 } } });
    expect(readDamage(it0)).toBe(61);
    expect(readDurability(it0)).toEqual({ left: 1500, max: 1561 });
  });

  it('没损耗过的东西身上没有 damage 组件:那是原版的零,不是读不到', () => {
    expect(readDamage(componentItem('shield', {}))).toBeNull();
    expect(readDurability(componentItem('shield', {}))).toEqual({ left: 336, max: 336 });
  });

  it('损耗超过上限也不报负数', () => {
    expect(readDurability(componentItem('golden_hoe', { damage: 99 }))).toEqual({ left: 0, max: 32 });
  });
});

describe('readEnchants', () => {
  it('组件路:id 是注册表序号,靠 registry 译名', () => {
    const pick = componentItem('diamond_pickaxe', {
      enchantments: { enchantments: [{ id: 20, level: 4 }, { id: 22, level: 3 }], showTooltip: true },
    });
    expect(readEnchants(pick, REGISTRY)).toEqual([
      { name: 'efficiency', level: 4 }, { name: 'unbreaking', level: 3 },
    ]);
  });

  it('附魔书走 stored_enchantments', () => {
    const book = componentItem('enchanted_book', {
      stored_enchantments: { enchantments: [{ id: 22, level: 1 }], showTooltip: true },
    });
    expect(readEnchants(book, REGISTRY)).toEqual([{ name: 'unbreaking', level: 1 }]);
  });

  it('译不出名字的那一条不报:编一个名字比少报一条更坏', () => {
    const odd = componentItem('diamond_axe', { enchantments: { enchantments: [{ id: 999, level: 1 }] } });
    expect(readEnchants(odd, REGISTRY)).toEqual([]);
  });

  it('NBT 路:id 是字符串,去掉 minecraft: 前缀', () => {
    const pick = nbtItem('diamond_pickaxe', {
      type: 'compound',
      value: {
        Enchantments: {
          type: 'list',
          value: {
            type: 'compound',
            value: [{ id: { value: 'minecraft:efficiency' }, lvl: { value: 5 } }],
          },
        },
      },
    });
    expect(readEnchants(pick)).toEqual([{ name: 'efficiency', level: 5 }]);
  });

  it('没附魔就是空数组', () => {
    expect(readEnchants(componentItem('stone', {}))).toEqual([]);
  });
});

describe('readPotionId', () => {
  it('水瓶与药水物品 id 同名,只有内容序号分得开', () => {
    expect(readPotionId(componentItem('potion', { potion_contents: { potionId: 0 } }))).toBe(0);
    expect(readPotionId(componentItem('potion', { potion_contents: { potionId: 3 } }))).toBe(3);
    expect(readPotionId(componentItem('potion', {}))).toBeNull();
  });
});
