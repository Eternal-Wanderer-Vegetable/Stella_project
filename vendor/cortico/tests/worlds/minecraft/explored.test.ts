import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';
import {
  ExploreBook, loadExplored, renderExploredLedger, renderExploredSummary,
} from '../../../src/worlds/minecraft/explored.ts';

const dirs: string[] = [];
afterEach(() => {
  for (const d of dirs.splice(0)) rmSync(d, { recursive: true, force: true });
});

function tmpFile(): string {
  const dir = mkdtempSync(join(tmpdir(), 'mc-explored-'));
  dirs.push(dir);
  return join(dir, 'minecraft-explored.json');
}

describe('ExploreBook', () => {
  it('收工按世界与维度落账;落盘后再读还在', () => {
    const file = tmpFile();
    const a = new ExploreBook(file);
    a.useRealm('realm-a');
    a.record('overworld', 'north', 460.4, 'plains', 1000);
    const raw = JSON.parse(readFileSync(file, 'utf8'));
    expect(raw).toMatchObject({
      version: 2,
      currentRealm: 'realm-a',
      realms: {
        'realm-a': {
          'minecraft:overworld': {
            north: { distance: 460, biome: 'plains', at: 1000 },
          },
        },
      },
    });
    const b = new ExploreBook(file);
    expect(b.summary('minecraft:overworld')).toContain('北460(平原)');
  });

  it('同一世界同一维度的更远记录覆盖;更近只刷新时间', () => {
    const file = tmpFile();
    const book = new ExploreBook(file);
    book.useRealm('realm-a');
    book.record('overworld', 'east', 80, 'forest', 1000);
    book.record('overworld', 'east', 300, 'desert', 2000);
    const east = () => JSON.parse(readFileSync(file, 'utf8'))
      .realms['realm-a']['minecraft:overworld'].east;
    expect(east()).toEqual({ distance: 300, biome: 'desert', at: 2000 });
    book.record('overworld', 'east', 40, 'plains', 3000);
    expect(east()).toEqual({ distance: 300, biome: 'desert', at: 3000 });
  });

  it('同一方向在不同世界与维度各有一份账', () => {
    const file = tmpFile();
    const book = new ExploreBook(file);
    book.useRealm('realm-a');
    book.record('overworld', 'north', 120, 'plains', 1000);
    book.record('the_nether', 'north', 45, 'nether_wastes', 2000);

    expect(book.summary('overworld')).toContain('北120(平原)');
    expect(book.summary('overworld')).not.toContain('45');
    expect(book.summary('minecraft:the_nether')).toContain('北45(下界荒地)');
    expect(book.summary('minecraft:the_nether')).not.toContain('120');

    book.useRealm('realm-b');
    expect(book.summary('overworld')).toBe('');
    book.record('overworld', 'north', 30, 'forest', 3000);
    expect(book.summary('overworld')).toContain('北30(森林)');
    book.useRealm('realm-a');
    expect(book.summary('overworld')).toContain('北120(平原)');
  });

  it('原地命中不落账', () => {
    const file = tmpFile();
    const book = new ExploreBook(file);
    book.useRealm('realm-a');
    book.record('overworld', 'south', 0, 'plains');
    book.record('overworld', 'south', 0.4, 'plains');
    expect(book.summary('overworld')).toBe('');
  });

  it('清空移除全部已归属记录', () => {
    const file = tmpFile();
    const book = new ExploreBook(file);
    book.useRealm('realm-a');
    book.record('overworld', 'west', 120, 'jungle');
    expect(book.clear()).toContain('1 个方向');
    expect(book.summary('overworld')).toBe('');
    expect(JSON.parse(readFileSync(file, 'utf8'))).toEqual({
      version: 2, currentRealm: 'realm-a', realms: {},
    });
    expect(book.clear()).toContain('空的');
  });
});

describe('探索摘要', () => {
  it('探过的按罗盘序列写距离与群系,没去过的点名', () => {
    expect(renderExploredSummary({})).toBe('');
    const line = renderExploredSummary({
      north: { distance: 460, biome: 'plains', at: 1 },
      east: { distance: 80, biome: 'forest', at: 2 },
    });
    expect(line).toBe('探过:北460(平原)/东80(森林);东北、东南、南、西南、西、西北没去过');
  });

  it('冷代理摘要逐维度标明归属,不合并方向', () => {
    const line = renderExploredLedger({
      version: 2,
      currentRealm: 'realm-a',
      realms: {
        'realm-a': {
          'minecraft:overworld': { north: { distance: 120, biome: 'plains', at: 1 } },
          'minecraft:the_nether': { east: { distance: 40, biome: 'nether_wastes', at: 2 } },
        },
      },
    });
    expect(line).toContain('[主世界] 探过:北120(平原)');
    expect(line).toContain('[下界] 探过:东40(下界荒地)');
  });

  it('八方向全探过就没有“没去过”尾巴;unknown 群系不带括注', () => {
    const rec = { distance: 32, biome: 'plains', at: 1 };
    const line = renderExploredSummary({
      north: rec, northeast: rec, east: rec, southeast: rec,
      south: rec, southwest: rec, west: rec,
      northwest: { distance: 48, biome: 'unknown', at: 2 },
    });
    expect(line).not.toContain('没去过');
    expect(line.endsWith('西北48')).toBe(true);
  });

  it('loadExplored 对坏文件与非 v2 形状都返回空账本', () => {
    const file = tmpFile();
    const empty = { version: 2, currentRealm: '', realms: {} };
    expect(loadExplored(null)).toEqual(empty);
    expect(loadExplored(file)).toEqual(empty);
    writeFileSync(file, 'not json', 'utf8');
    expect(loadExplored(file)).toEqual(empty);
    writeFileSync(file, JSON.stringify({ north: { distance: 0 }, east: { distance: 30 } }), 'utf8');
    expect(loadExplored(file)).toEqual(empty);
  });
});
