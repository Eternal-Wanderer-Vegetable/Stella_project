/**
 * 按物品的显示标签、英文附魔 ID 和数值等级做子串匹配。
 * 同一挑选词可匹配多件物品，操作数量由 count 指定；未匹配时返回候选清单。
 */
import { roman, zhEnchant, zhName } from './names.ts';
import { readEnchants, type EnchantRegistry, type ItemEnchant, type ItemLike } from './item-facts.ts';
import { enchantSuffix } from './terrain.ts';

export interface PickTarget {
  name: string;
  enchantments?: readonly ItemEnchant[];
}

export function pickLabel(it: PickTarget): string {
  return `${zhName(it.name)}${enchantSuffix(it.enchantments)}`;
}

export function pickTargetOf(item: ItemLike, registry?: EnchantRegistry | null): PickTarget {
  return { name: item.name, enchantments: readEnchants(item, registry) };
}

function normalize(s: string): string {
  return s.toLowerCase().replace(/\s+/g, '');
}

function facets(it: PickTarget): string[] {
  const out = [zhName(it.name), it.name, pickLabel(it)];
  for (const e of it.enchantments ?? []) {
    const zh = zhEnchant(e.name);
    out.push(zh, `${zh}${roman(e.level)}`, `${zh}${e.level}`, e.name, `${e.name}${e.level}`);
  }
  return out;
}

/** 空挑选词不筛选。 */
export function matchesPick(pick: string | undefined, it: PickTarget): boolean {
  if (!pick) return true;
  const q = normalize(pick);
  return q.length > 0 && facets(it).some((f) => normalize(f).includes(q));
}

export function itemMatchesPick(
  pick: string | undefined,
  item: ItemLike,
  registry?: EnchantRegistry | null,
): boolean {
  return pick ? matchesPick(pick, pickTargetOf(item, registry)) : true;
}

/** 无附魔时显示“没有附魔”。 */
function pickFacts(it: PickTarget): string {
  return enchantSuffix(it.enchantments).replace(/[（）]/g, '') || '没有附魔';
}

export function pickMissText(
  where: string,
  id: string,
  pick: string,
  sameId: readonly PickTarget[],
): string {
  return `${where}有 ${sameId.length} 件${zhName(id)},没有一件带「${pick}」:`
    + `${sameId.map(pickFacts).join(' / ')}`;
}

export function pickedText(picked: readonly PickTarget[]): string {
  return [...new Set(picked.map(pickLabel))].join('、');
}
