/**
 * 三份只读读数的渲染:背包、队列、上次没成的几条。
 *
 * 全是**现读现报**,一个字都不改世界、不动队列。放在这里而不是 world.ts 里,是因为
 * 这三份的输入都是纯数据(快照 / 队列状态 / 受阻账),单测直接喂结构就能跑。
 *
 * 措辞与别处同一份来源:背包清单走 `narrateInventory`,队列走 `renderQueue` ——
 * 同一件事两处措辞不同,读起来就像两件事(README「一件事只说一遍」)。
 */
import type { QueueStatus, BlockedRecord } from './executor.ts';
import { renderQueue } from './executor.ts';
import type { GearPiece, GearSlot, WorldSnapshot } from './terrain.ts';
import { enchantSuffix, narrateInventory } from './terrain.ts';
import { zhName } from './names.ts';
import { PLAYER_SLOTS } from './precheck.ts';

const GEAR_SLOT_ZH: Record<GearSlot, string> = {
  head: '头', chest: '胸', legs: '腿', feet: '脚', offhand: '副手',
};
const WORN_ORDER: readonly GearSlot[] = ['head', 'chest', 'legs', 'feet'];

function gearPhrase(p: GearPiece): string {
  const dura = p.durability ? ` ${p.durability.left}/${p.durability.max}` : '';
  return `${GEAR_SLOT_ZH[p.slot]}${zhName(p.name)}${enchantSuffix(p.enchantments)}${dura}`;
}

/**
 * 背包快照包括槽位占用、物品总量、手持和装备。
 * 首次服务端同步前报告未同步，避免将初始空视图当成空背包。
 */
export function renderBagReadout(s: WorldSnapshot): string {
  if (!s.invSynced) return '[背包] 物品栏还在从服务器同步,这份清单还没到。';
  const used = s.inventory.length;
  const held = s.heldItem ? `手里拿着${zhName(s.heldItem)}` : '手里空着';
  const worn = WORN_ORDER
    .map((slot) => s.equipment.find((p) => p.slot === slot))
    .filter((p): p is GearPiece => p !== undefined);
  const off = s.equipment.find((p) => p.slot === 'offhand');
  const lines = [
    `[背包] ${used}/${PLAYER_SLOTS} 格占着,空 ${PLAYER_SLOTS - used} 格。`,
    used > 0 ? `包里:${narrateInventory(s.inventory)}。` : '包里什么都没有。',
    `${held}。`,
    worn.length > 0 ? `穿着:${worn.map(gearPhrase).join('、')}。` : '身上没穿护甲。',
  ];
  if (off) lines.push(`${gearPhrase(off)}。`);
  return lines.join('\n');
}

/** 背包读数的指纹:一轮一答闸按它判「这一份读数变没变」(见 round.ts) */
export function bagStamp(s: WorldSnapshot | null): string {
  if (!s) return 'nobot';
  if (!s.invSynced) return 'nosync';
  return [
    s.inventory.length,
    [...s.inventory].map((i) => `${i.name}${enchantSuffix(i.enchantments)}×${i.count}`).sort().join(','),
    s.heldItem ?? 'bare',
    [...s.equipment].map((p) => `${p.slot}:${p.name}`).sort().join(','),
  ].join('|');
}

/**
 * 队列现状:在做的那件与它跑到第几步、排队的、最近一单的终态。
 *
 * 最近一单的终态是这份读数里唯一"过去时"的东西 —— 它正是「我刚才那一单到底怎么了」
 * 这个问题的答案,而那条终态回执早被交接或后续事件挤出上下文了。
 */
export function renderQueueReadout(
  q: QueueStatus,
  last: { at: string; kind: string; text: string } | null,
): string {
  const lines = [`[队列] ${renderQueue(q)}`];
  lines.push(last ? `[最近一单] ${last.at} ${last.text}` : '[最近一单] 这一场还没有跑完过任何一单。');
  return lines.join('\n');
}

/** 队列读数的指纹。**不含时钟** —— 已跑多少秒每次都在变,进了指纹这道闸等于不存在 */
export function queueStamp(q: QueueStatus, lastAt: number | null): string {
  const r = q.running;
  return [
    r ? `${r.id}:${r.stepIndex}/${r.stepCount}:${r.count ? `${r.count.done}/${r.count.total}` : '-'}` : 'idle',
    q.waiting.map((w) => w.id).join(','),
    q.hold ?? '-',
    lastAt ?? '-',
  ].join('|');
}

/**
 * 最近几条没做成的记录:时刻、任务、步、原文原因。
 *
 * 只搬账本上已有的字,一个字不改写、不归因、不给建议(worlds-report-facts)。
 * 「同一类撞了几次」那件事另有头条在终态回执里报,这里不重复。
 */
export function renderBlockedReadout(records: readonly BlockedRecord[], clock: (ms: number) => string): string {
  if (records.length === 0) return '[上次没成] 这一场还没有记到受阻的步。';
  const lines = records.map((r) => `${clock(r.at)} ${r.task}${r.step ? ` ${r.step}` : ''}:${r.why}`);
  return `[上次没成] 最近 ${records.length} 条(新的在前):\n${lines.join('\n')}`;
}

/** 受阻读数的指纹:最新那一条的时刻 + 条数,两者都没动就是同一份读数 */
export function blockedStamp(records: readonly BlockedRecord[]): string {
  return `${records.length}|${records[0]?.at ?? '-'}`;
}
