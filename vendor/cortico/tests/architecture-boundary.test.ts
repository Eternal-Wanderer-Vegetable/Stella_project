import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

/** 统一入口仅负责接线，不得依赖任何具体 bot 的概念。 */
// corti 靠词边界匹配,盖不住 cortiv/cormini(后缀连着字母),必须单列。
const LATIN = ['qq', 'websearch', 'vtuber', 'minecraft', 'dream', 'checkpoint', 'corti', 'cortiv', 'cormini', 'end_turn', 'xuewu'];
const CJK = ['宪法', '联想', '反刍', '做梦', '雪午'];

function offenders(text: string): string[] {
  const lower = text.toLowerCase();
  return [
    // 词边界避免将框架名 Cortico 误判为具体实现 Corti。
    ...LATIN.filter((w) => new RegExp(`\\b${w}\\b`).test(lower)),
    ...CJK.filter((w) => lower.includes(w)),
  ];
}

describe('架构边界', () => {
  it('src/bot.ts 不认识任何具体实现的概念', () => {
    const text = readFileSync(join(import.meta.dirname, '../src/bot.ts'), 'utf8');
    expect(offenders(text)).toEqual([]);
  });

  it('src/core 不认识任何 World 或人格实现的词', () => {
    for (const file of ['core.ts', 'loop.ts', 'bus.ts', 'timers.ts', 'prefix.ts', 'fork.ts']) {
      const text = readFileSync(join(import.meta.dirname, '../src/core', file), 'utf8');
      expect(offenders(text), file).toEqual([]);
    }
  });
});
