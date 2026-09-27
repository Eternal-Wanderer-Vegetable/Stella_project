import { afterEach, describe, expect, it } from 'vitest';
import {
  roman, setNameRegistry, zhBiome, zhDimension, zhEffect, zhEnchant, zhEntity, zhName,
} from '../../../src/worlds/minecraft/names.ts';

describe('zhName 组合式拆解', () => {
  it('整词表优先', () => {
    expect(zhName('crafting_table')).toBe('工作台');
    expect(zhName('iron_ore')).toBe('铁矿石');
    expect(zhName('minecraft:cobblestone')).toBe('圆石');
  });

  it('一层组合:前缀词素 + 类别', () => {
    expect(zhName('acacia_log')).toBe('金合欢原木');
    expect(zhName('acacia_planks')).toBe('金合欢木板');
    expect(zhName('stone_pickaxe')).toBe('石镐');
    expect(zhName('diamond_sword')).toBe('钻石剑');
  });

  it('多层组合:一个整词拆不出来就继续往下拆', () => {
    expect(zhName('deepslate_iron_ore')).toBe('深板岩铁矿石');
    expect(zhName('stripped_acacia_log')).toBe('去皮金合欢原木');
    expect(zhName('waxed_weathered_cut_copper')).toBe('涂蜡锈蚀切制铜块');
  });

  it('材质词单用就是那样东西本身', () => {
    expect(zhName('coal')).toBe('煤炭');
    expect(zhName('diamond')).toBe('钻石');
  });

  it('译不出来的退回原 id:那是没给过中文名的诚实信号', () => {
    expect(zhName('some_modded_thing')).toBe('some_modded_thing');
  });
});

describe('实体、群系、维度', () => {
  it('常见生物与群系', () => {
    expect(zhEntity('skeleton')).toBe('骷髅');
    expect(zhEntity('zombie_villager')).toBe('僵尸村民');
    expect(zhEntity('item')).toBe('掉落物');
    expect(zhBiome('savanna')).toBe('热带草原');
    expect(zhBiome('deep_dark')).toBe('深暗之域');
    expect(zhDimension('overworld')).toBe('主世界');
  });
});

describe('附魔、状态效果与罗马数字', () => {
  it('附魔名走原版 id,译不出的退回 id', () => {
    expect(zhEnchant('efficiency')).toBe('效率');
    expect(zhEnchant('minecraft:unbreaking')).toBe('耐久');
    expect(zhEnchant('mending')).toBe('经验修补');
    expect(zhEnchant('some_modded_ench')).toBe('some_modded_ench');
  });

  it('状态效果键是 minecraft-data 的驼峰名', () => {
    expect(zhEffect('FireResistance')).toBe('抗火');
    expect(zhEffect('MiningFatigue')).toBe('挖掘疲劳');
    expect(zhEffect('effect_99')).toBe('effect_99');
  });

  it('罗马数字到 X,再往上原版也写不出,照报阿拉伯数字', () => {
    expect(roman(1)).toBe('I');
    expect(roman(4)).toBe('IV');
    expect(roman(10)).toBe('X');
    expect(roman(11)).toBe('11');
  });
});


describe('拼得出中文名 ≠ 这个 id 存在', () => {
  afterEach(() => { setNameRegistry(null); });

  const REG = {
    itemsByName: { cobbled_deepslate: {}, acacia_log: {}, torch: {}, dirt: {} },
    blocksByName: { cobbled_deepslate: {}, acacia_log: {}, wall_torch: {}, dirt: {} },
  };

  it('拿不到 registry 时一个字都不加(判据答不出就不装作知道)', () => {
    expect(zhName('deepslate_cobblestone')).toBe('深板岩圆石');
    setNameRegistry({});
    expect(zhName('deepslate_cobblestone')).toBe('深板岩圆石');
  });

  it('假 id 拼出真中文名时露馅:带上原始 id', () => {
    setNameRegistry(REG);
    // 真 id 是 cobbled_deepslate,中文名一模一样 —— 两个 id 塌缩到同一个中文名,
    // 「包里没有深板岩圆石」与「[背包] 深板岩圆石×89」于是并排出现
    expect(zhName('deepslate_cobblestone'))
      .toBe('深板岩圆石(deepslate_cobblestone,原版里没有这个 id)');
    expect(zhName('cobbled_deepslate')).toBe('深板岩圆石');
  });

  it('registry 里有的组合词照旧只念中文名', () => {
    setNameRegistry(REG);
    expect(zhName('acacia_log')).toBe('金合欢原木');
    expect(zhName('minecraft:acacia_log')).toBe('金合欢原木');
  });

  it('整词表、单词素与译不出的原样返回都不核 id', () => {
    setNameRegistry(REG);
    expect(zhName('cobblestone')).toBe('圆石');   // WHOLE 命中
    expect(zhName('ore')).toBe('矿石');           // 类别名,本来就不是 id
    expect(zhName('some_modded_thing')).toBe('some_modded_thing');
  });

  it('实体 id 不进这道判据:它不在 itemsByName/blocksByName 里,核了必误报', () => {
    setNameRegistry(REG);
    expect(zhEntity('zombie_villager')).toBe('僵尸村民');
    expect(zhEntity('acacia_boat')).toBe('金合欢船');
  });
});
