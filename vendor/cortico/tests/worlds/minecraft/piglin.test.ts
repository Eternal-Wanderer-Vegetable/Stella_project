import { describe, expect, it } from 'vitest';
import { isBabyPiglin, piglinIsHostile, wearsGoldArmor } from '../../../src/worlds/minecraft/piglin.ts';

function piglinBot() {
  return {
    inventory: { slots: [] as Array<{ name: string } | null | undefined> },
    registry: {
      entitiesByName: {
        piglin: { metadataKeys: ['flags', 'baby', 'immune_to_zombification'] },
      },
    },
  };
}

describe('猪灵条件敌对', () => {
  it('只认实际穿在装备槽里的金甲，背包里带着不算', () => {
    const bot = piglinBot();
    const withBagOnly = {
      ...bot,
      inventory: {
        ...bot.inventory,
        items: () => [{ name: 'golden_boots' }],
      },
    };
    expect(wearsGoldArmor(withBagOnly)).toBe(false);

    for (const [slot, name] of [
      [5, 'golden_helmet'],
      [6, 'golden_chestplate'],
      [7, 'golden_leggings'],
      [8, 'golden_boots'],
    ] as const) {
      bot.inventory.slots.fill(null);
      bot.inventory.slots[slot] = { name };
      expect(wearsGoldArmor(bot)).toBe(true);
    }

    bot.inventory.slots[5] = { name: 'iron_helmet' };
    bot.inventory.slots[8] = { name: 'leather_boots' };
    expect(wearsGoldArmor(bot)).toBe(false);
  });

  it('幼体下标从注册表读取，不把协议元数据位置写死', () => {
    const bot = piglinBot();
    expect(isBabyPiglin(bot, { name: 'piglin', metadata: [false, true, false] })).toBe(true);
    expect(isBabyPiglin(bot, { name: 'piglin', metadata: [false, false, true] })).toBe(false);
    expect(isBabyPiglin(bot, { name: 'piglin_brute', metadata: [false, true, false] })).toBe(false);
  });

  it('成年普通猪灵按金甲决定是否主动敌对，实际受击来源仍会把它标成敌人', () => {
    const bot = piglinBot();
    const adult = { id: 7, name: 'piglin', metadata: [false, false, false] };
    expect(piglinIsHostile(bot, adult)).toBe(true);

    bot.inventory.slots[8] = { name: 'golden_boots' };
    expect(piglinIsHostile(bot, adult)).toBe(false);
    expect(piglinIsHostile(bot, adult, true)).toBe(true);
  });

  it('未被指认为实际攻击源的幼年猪灵不进入敌对目标池', () => {
    const bot = piglinBot();
    const baby = { id: 8, name: 'piglin', metadata: [false, true, false] };
    expect(piglinIsHostile(bot, baby)).toBe(false);
  });
});
