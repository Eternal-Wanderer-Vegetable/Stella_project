/**
 * 实体元数据读数的单测。
 *
 * 守的是同一条:元数据下标**随协议版本走 registry 的 metadataKeys**,不写死 1.20.6 的数值。
 * 换版本时 metadataKeys 会整体平移(1.20.6 的狼 owneruuid 在 18 号位),写死就会读到隔壁那格。
 */
import { describe, expect, it } from 'vitest';
import {
  FEED_ITEMS, TAME_ITEMS, dyeColorOf, readSheepColor, readSitting, readTamedBy, tamedByMe,
} from '../../../src/worlds/minecraft/entity-facts.ts';

/**
 * 夹具模拟普通 login 初始化：bot.entity 尚未获得 uuid，bot.player.uuid 可用。
 * 实体类型通过 metadataKeys 声明元数据位置。
 */
function botWith(name: string, keys: string[], me?: string) {
  return {
    entity: {},
    player: me === undefined ? null : { uuid: me },
    registry: { entitiesByName: { [name]: { metadataKeys: keys } } },
  };
}

/** 把值放在 keys 里 key 的下标上,其余位留 undefined */
function metaAt(keys: string[], key: string, value: unknown): unknown[] {
  const meta: unknown[] = [];
  meta[keys.indexOf(key)] = value;
  return meta;
}

const WOLF_KEYS = ['shared_flags', 'health', 'baby', 'flags', 'owneruuid', 'collar_color'];
const SHEEP_KEYS = ['shared_flags', 'health', 'baby', 'wool'];

describe('readTamedBy(主人是谁)', () => {
  it('没有主人时读出 null,而不是空字符串', () => {
    const bot = botWith('wolf', WOLF_KEYS);
    expect(readTamedBy(bot, { name: 'wolf', metadata: metaAt(WOLF_KEYS, 'owneruuid', undefined) })).toBe(null);
    expect(readTamedBy(bot, { name: 'wolf', metadata: metaAt(WOLF_KEYS, 'owneruuid', '') })).toBe(null);
  });

  it('optional 解成 {present:false} 时也算没有主人', () => {
    const bot = botWith('wolf', WOLF_KEYS);
    const meta = metaAt(WOLF_KEYS, 'owneruuid', { present: false, value: 'u-1' });
    expect(readTamedBy(bot, { name: 'wolf', metadata: meta })).toBe(null);
  });

  it('裸字符串与 {value} 两种形状读出同一个 UUID', () => {
    const bot = botWith('wolf', WOLF_KEYS);
    expect(readTamedBy(bot, { name: 'wolf', metadata: metaAt(WOLF_KEYS, 'owneruuid', 'u-1') })).toBe('u-1');
    expect(readTamedBy(bot, { name: 'wolf', metadata: metaAt(WOLF_KEYS, 'owneruuid', { value: 'u-1' }) })).toBe('u-1');
  });

  it('下标按 metadataKeys 走:同一份 metadata 换一份 keys 就读到别的位置', () => {
    const shifted = ['shared_flags', 'health', 'owneruuid', 'baby', 'flags'];
    const meta = metaAt(WOLF_KEYS, 'owneruuid', 'u-1');
    expect(readTamedBy(botWith('wolf', shifted), { name: 'wolf', metadata: meta })).toBe(null);
  });

  it('registry 里没有这一种实体时读 null,不抛', () => {
    expect(readTamedBy({ registry: { entitiesByName: {} } }, { name: 'wolf', metadata: ['u-1'] })).toBe(null);
    expect(readTamedBy({}, { name: 'wolf', metadata: ['u-1'] })).toBe(null);
  });
});

describe('tamedByMe(是不是她自己的)', () => {
  it('主人 UUID 与自己对上才算', () => {
    const bot = botWith('wolf', WOLF_KEYS, 'me-uuid');
    const mine = { name: 'wolf', metadata: metaAt(WOLF_KEYS, 'owneruuid', 'me-uuid') };
    const other = { name: 'wolf', metadata: metaAt(WOLF_KEYS, 'owneruuid', 'someone-else') };
    expect(tamedByMe(bot, mine)).toBe(true);
    expect(tamedByMe(bot, other)).toBe(false);
  });

  it('读不到自己的 UUID 时返回 false —— 这一层不猜', () => {
    const bot = botWith('wolf', WOLF_KEYS);
    expect(tamedByMe(bot, { name: 'wolf', metadata: metaAt(WOLF_KEYS, 'owneruuid', 'me-uuid') })).toBe(false);
  });

  it('player.uuid 缺席时退回 _client.uuid;entity.uuid 从不被 mineflayer 赋值', () => {
    const bot = {
      entity: {},
      _client: { uuid: 'me-uuid' },
      registry: { entitiesByName: { wolf: { metadataKeys: WOLF_KEYS } } },
    };
    expect(tamedByMe(bot, { name: 'wolf', metadata: metaAt(WOLF_KEYS, 'owneruuid', 'me-uuid') })).toBe(true);
  });
});

describe('readSitting(坐着还是站着)', () => {
  it('flags 的 0x01 位是 sitting', () => {
    const bot = botWith('wolf', WOLF_KEYS);
    expect(readSitting(bot, { name: 'wolf', metadata: metaAt(WOLF_KEYS, 'flags', 0x01) })).toBe(true);
    expect(readSitting(bot, { name: 'wolf', metadata: metaAt(WOLF_KEYS, 'flags', 0x04) })).toBe(false);
    expect(readSitting(bot, { name: 'wolf', metadata: metaAt(WOLF_KEYS, 'flags', 0x05) })).toBe(true);
  });

  it('读不到就 null,不猜', () => {
    const bot = botWith('wolf', WOLF_KEYS);
    expect(readSitting(bot, { name: 'wolf', metadata: [] })).toBe(null);
    expect(readSitting(bot, { name: 'creeper', metadata: [0x01] })).toBe(null);
  });
});

describe('羊毛颜色', () => {
  it('低四位是颜色', () => {
    const bot = botWith('sheep', SHEEP_KEYS);
    expect(readSheepColor(bot, { name: 'sheep', metadata: metaAt(SHEEP_KEYS, 'wool', 0) })).toBe('white');
    expect(readSheepColor(bot, { name: 'sheep', metadata: metaAt(SHEEP_KEYS, 'wool', 11) })).toBe('blue');
    expect(readSheepColor(bot, { name: 'sheep', metadata: metaAt(SHEEP_KEYS, 'wool', 15) })).toBe('black');
  });

  it('第五位是"剪过了",不能把它算进颜色', () => {
    const bot = botWith('sheep', SHEEP_KEYS);
    // 0x10 | 11 = 27:剪过的蓝羊,颜色仍是蓝
    expect(readSheepColor(bot, { name: 'sheep', metadata: metaAt(SHEEP_KEYS, 'wool', 0x10 | 11) })).toBe('blue');
  });

  it('读不到就返回 null', () => {
    const bot = botWith('sheep', SHEEP_KEYS);
    expect(readSheepColor(bot, { name: 'sheep', metadata: [] })).toBe(null);
  });
});

describe('dyeColorOf', () => {
  it('十六种染料认出颜色名', () => {
    expect(dyeColorOf('blue_dye')).toBe('blue');
    expect(dyeColorOf('light_gray_dye')).toBe('light_gray');
  });

  it('不是染料的一律 null(名字里带 dye 也不算)', () => {
    expect(dyeColorOf('bone_meal')).toBe(null);
    expect(dyeColorOf('rainbow_dye')).toBe(null);
    expect(dyeColorOf(null)).toBe(null);
  });
});

describe('道具表', () => {
  it('驯服与喂食是两张表:狼的骨头只在驯服表里,肉只在喂食表里', () => {
    expect(TAME_ITEMS.wolf).toContain('bone');
    expect(FEED_ITEMS.wolf).not.toContain('bone');
    expect(FEED_ITEMS.wolf).toContain('cooked_beef');
  });

  it('猪吃胡萝卜土豆甜菜根,不吃小麦(原版如此)', () => {
    expect(FEED_ITEMS.pig).toEqual(expect.arrayContaining(['carrot', 'potato', 'beetroot']));
    expect(FEED_ITEMS.pig).not.toContain('wheat');
  });

  it('1.20.5 起狼吃腐肉与生熟鱼类;猫也吃热带鱼/河豚', () => {
    expect(FEED_ITEMS.wolf).toEqual(expect.arrayContaining(['rotten_flesh', 'cod', 'cooked_salmon', 'tropical_fish', 'pufferfish']));
    expect(FEED_ITEMS.cat).toEqual(expect.arrayContaining(['tropical_fish', 'pufferfish']));
  });
});
