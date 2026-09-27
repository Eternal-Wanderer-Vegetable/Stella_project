/** 普通猪灵的条件敌对事实。猪灵蛮兵不走这里，始终按敌对处理。 */

interface NamedStack { name?: string }

interface PiglinLike {
  id?: number;
  name?: string;
  metadata?: unknown[];
}

interface PiglinBotLike {
  inventory?: { slots?: Array<NamedStack | null | undefined> };
  registry?: {
    entitiesByName?: Record<string, { metadataKeys?: string[] } | undefined>;
  };
}

const GOLD_ARMOR = new Set([
  'golden_helmet', 'golden_chestplate', 'golden_leggings', 'golden_boots',
]);

/** 背包里的金甲不算；只读玩家实际穿戴的四个装备槽。 */
export function wearsGoldArmor(bot: PiglinBotLike): boolean {
  const slots = bot.inventory?.slots ?? [];
  return [5, 6, 7, 8].some((slot) => GOLD_ARMOR.has(slots[slot]?.name ?? ''));
}

/** metadata 下标随协议版本走 registry，不把 1.20.6 的数值写死。 */
export function isBabyPiglin(bot: PiglinBotLike, entity: PiglinLike): boolean {
  if (entity.name !== 'piglin') return false;
  const keys = bot.registry?.entitiesByName?.piglin?.metadataKeys ?? [];
  const at = keys.indexOf('baby');
  return at >= 0 && entity.metadata?.[at] === true;
}

/**
 * 是否应把普通猪灵当作当前战斗目标。实际打过玩家是硬事实，优先于金甲；幼体
 * 不会主动攻击，未被实际来源指认时不进入目标池。
 */
export function piglinIsHostile(
  bot: PiglinBotLike,
  entity: PiglinLike,
  provoked = false,
): boolean {
  if (entity.name !== 'piglin') return false;
  if (provoked) return true;
  if (isBabyPiglin(bot, entity)) return false;
  return !wearsGoldArmor(bot);
}
