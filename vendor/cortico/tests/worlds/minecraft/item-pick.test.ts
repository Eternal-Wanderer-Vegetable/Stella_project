/**
 * 挑选词用于区分同 id 下具有不同附魔等属性的物品实例。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  matchesPick, pickLabel, pickMissText, pickedText,
} from '../../../src/worlds/minecraft/item-pick.ts';
import { parseSteps } from '../../../src/worlds/minecraft/executor.ts';
import { precheckStep } from '../../../src/worlds/minecraft/precheck.ts';
import { makeExecutorOn, slotChestBot, waitUntil } from './executor-harness.ts';

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date', 'setTimeout', 'clearTimeout', 'setInterval', 'clearInterval'] });
});

afterEach(() => {
  vi.useRealTimers();
});

const INFINITY = { name: 'enchanted_book', enchantments: [{ name: 'infinity', level: 1 }, { name: 'looting', level: 2 }] };
const SILK = { name: 'enchanted_book', enchantments: [{ name: 'silk_touch', level: 1 }] };
const PIERCING = { name: 'enchanted_book', enchantments: [{ name: 'piercing', level: 4 }] };

describe('挑选词的匹配面', () => {
  it('中文附魔名、英文 id、带等级的写法都认', () => {
    for (const q of ['无限', 'infinity', '无限I', '无限1', 'infinity1', '抢夺II']) {
      expect(matchesPick(q, INFINITY), q).toBe(true);
    }
    expect(matchesPick('无限', SILK)).toBe(false);
    expect(matchesPick('精准采集', SILK)).toBe(true);
  });

  it('照清单里那一条整个念也认:她读到什么就写什么', () => {
    expect(pickLabel(INFINITY)).toBe('附魔书（无限I·抢夺II）');
    expect(matchesPick(pickLabel(INFINITY), INFINITY)).toBe(true);
  });

  it('不写挑选词 = 不筛;空字符串同理', () => {
    expect(matchesPick(undefined, SILK)).toBe(true);
    expect(matchesPick('', SILK)).toBe(true);
  });

  /** 位置序号做不到这一点:存掉一件,其余几件的序号全前移,而挑选词一个字不用改 */
  it('挑选词只认内容:同一件东西在包里排第几都是同一个词', () => {
    const before = [INFINITY, SILK, PIERCING];
    const after = before.filter((it) => it !== SILK);
    expect(before.filter((it) => matchesPick('无限', it))).toEqual([INFINITY]);
    expect(after.filter((it) => matchesPick('无限', it))).toEqual([INFINITY]);
  });

  it('一件都没命中时把同 id 的那几件各自是什么摆出来', () => {
    const text = pickMissText('包里', 'enchanted_book', '击退', [INFINITY, SILK, PIERCING]);
    expect(text).toContain('3 件附魔书');
    expect(text).toContain('「击退」');
    expect(text).toContain('无限I·抢夺II');
    expect(text).toContain('穿透IV');
  });

  it('回执点名挑中的是哪几件,重样的只说一遍', () => {
    expect(pickedText([SILK, SILK])).toBe('附魔书（精准采集I）');
  });
});

describe('挑选词的契约面', () => {
  it('stow/take/toss/equip 收 pick,anvil/grindstone 另收 withPick', () => {
    expect(parseSteps([{ skill: 'stow', item: 'enchanted_book', count: 1, pick: '精准采集' }]))
      .toEqual({ steps: [{ skill: 'stow', item: 'enchanted_book', count: 1, pick: '精准采集' }] });
    expect(parseSteps([{
      skill: 'anvil', op: 'combine', item: 'bow', with: 'enchanted_book', withPick: '无限',
    }])).toEqual({
      steps: [{ skill: 'anvil', op: 'combine', item: 'bow', with: 'enchanted_book', withPick: '无限' }],
    });
    expect(parseSteps([{ skill: 'take', item: 'enchanted_book', count: 1, pick: '无限' }]))
      .toEqual({ steps: [{ skill: 'take', item: 'enchanted_book', count: 1, pick: '无限' }] });
    expect(parseSteps([{ skill: 'equip', item: 'bow', pick: '无限' }]))
      .toEqual({ steps: [{ skill: 'equip', item: 'bow', pick: '无限' }] });
  });

  it('挑选词依附于它筛的那一格:没有那件东西可挑就当场驳回', () => {
    expect(parseSteps([{ skill: 'equip', pick: '无限' }])).toHaveProperty('error');
    expect(parseSteps([{ skill: 'anvil', op: 'rename', item: 'bow', name: '弓', withPick: '无限' }]))
      .toHaveProperty('error');
    expect(parseSteps([{ skill: 'take', at: [1, 2, 3], all: true, pick: '无限' }])).toHaveProperty('error');
  });
});

/** 试算与执行同一口径:包里有五本而没有一本带「无限」,受理刻就说破 */
describe('挑选词落空:试算当场摆出同 id 的那几件', () => {
  const bookBag = {
    inventory: {
      items: () => [
        { name: 'enchanted_book', count: 1, type: 7, componentMap: ench([[10, 1]]) },
        { name: 'enchanted_book', count: 1, type: 7, componentMap: ench([[11, 4]]) },
      ],
    },
    registry: { enchantments: { 10: { name: 'silk_touch' }, 11: { name: 'piercing' } } },
  };

  it('有同 id 的几件而挑选词一件没中:hard 档,理由里带着那几件是什么', () => {
    const note = precheckStep(
      bookBag as never,
      { skill: 'stow', item: 'enchanted_book', count: 1, pick: '无限' },
      { blockAt: () => null } as never,
    );
    expect(note?.level).toBe('hard');
    expect(note?.text).toContain('没有一件带「无限」');
    expect(note?.text).toContain('精准采集I');
  });

  it('连 id 都没有还是原来那一句,不扯挑选词', () => {
    const note = precheckStep(
      bookBag as never,
      { skill: 'stow', item: 'diamond', count: 1, pick: '无限' },
      { blockAt: () => null } as never,
    );
    expect(note?.text).toBe('包里没有钻石,存不了');
  });
});

function ench(pairs: Array<[number, number]>): Map<string, { data?: unknown }> {
  return new Map([['enchantments', { data: { enchantments: pairs.map(([id, level]) => ({ id, level })) } }]]);
}

/**
 * 真正的那一刀:`deposit`/`withdraw` 按物品类型找第一格,同 id 的几件对它没有分别。
 * 点名挑那一件的实现要是退回按类型搬,下面两条当场变红 —— 而回执照样会说「存了 1 本」。
 */
describe('挑选词落到搬运上:点名的是哪一件,走的就是哪一件', () => {
  const ENCHANTS = { 10: { name: 'silk_touch' }, 11: { name: 'infinity' }, 12: { name: 'piercing' } };
  const threeBooks = [
    { name: 'enchanted_book', type: 7, ench: [[10, 1]] as Array<[number, number]> },
    { name: 'enchanted_book', type: 7, ench: [[11, 1]] as Array<[number, number]> },
    { name: 'enchanted_book', type: 7, ench: [[12, 4]] as Array<[number, number]> },
  ];

  it('stow:点名存精准采集那本,无限那本留在包里', async () => {
    const rig = slotChestBot({ inv: threeBooks, enchants: ENCHANTS });
    const { exec, reports } = makeExecutorOn(rig.bot);
    exec.submit([{ skill: 'stow', item: 'enchanted_book', count: 1, pick: '精准采集' }]);
    await waitUntil(() => reports.length === 1, 8000);
    expect(reports[0].kind).toBe('done');
    expect(rig.boxed()).toEqual(['enchanted_book#10']);
    expect(rig.bag()).toEqual(['enchanted_book#11', 'enchanted_book#12']);
    // 回执念的是挑中的那一本,不是光秃秃一个 id
    expect(reports[0].text).toContain('附魔书（精准采集I）×1');
  });

  it('take:点名从箱子里掏无限那本,别的留在箱里', async () => {
    const rig = slotChestBot({ inv: [], box: threeBooks, enchants: ENCHANTS });
    const { exec, reports } = makeExecutorOn(rig.bot);
    exec.submit([{ skill: 'take', item: 'enchanted_book', count: 1, pick: '无限' }]);
    await waitUntil(() => reports.length === 1, 8000);
    expect(reports[0].kind).toBe('done');
    expect(rig.bag()).toEqual(['enchanted_book#11']);
    expect(rig.boxed()).toEqual(['enchanted_book#10', 'enchanted_book#12']);
  });

  it('stow:挑选词一件没中就受阻,一本也不动', async () => {
    const rig = slotChestBot({ inv: threeBooks, enchants: ENCHANTS });
    const { exec, reports } = makeExecutorOn(rig.bot);
    exec.submit([{ skill: 'stow', item: 'enchanted_book', count: 1, pick: '击退' }]);
    await waitUntil(() => reports.length === 1, 8000);
    expect(reports[0].kind).toBe('blocked');
    expect(reports[0].text).toContain('没有一件带「击退」');
    expect(rig.boxed()).toEqual([]);
  });
});
