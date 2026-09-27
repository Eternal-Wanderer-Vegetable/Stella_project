/**
 * 成果登记的单测。
 *
 * 守的是**登记只提供事实,不替她拦**这条边界:书本身只会记、查、划掉,
 * 一个「要不要挖」的判据都没有。挖掉了要划掉,不然下一趟拿一格空气冒充她的成果。
 */
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';
import { loadWorks, worksNote, WorksBook } from '../../../src/worlds/minecraft/works.ts';

const dirs: string[] = [];
function tmpFile(): string {
  const d = mkdtempSync(join(tmpdir(), 'works-'));
  dirs.push(d);
  return join(d, 'minecraft-works.json');
}

afterEach(() => {
  for (const d of dirs.splice(0)) rmSync(d, { recursive: true, force: true });
});

const clock = (ms: number): string => new Date(ms).toISOString().slice(11, 19);

describe('WorksBook', () => {
  it('登记按维度+坐标分开:主世界的耕地不会在下界认出来', () => {
    const b = new WorksBook(null);
    b.note('overworld', 10, 64, -3, { kind: 'farmland', block: 'farmland', site: null });
    expect(b.has('overworld', 10, 64, -3)).toBe(true);
    expect(b.has('the_nether', 10, 64, -3)).toBe(false);
  });

  it('同一格重登覆盖旧的,时刻跟着刷新 —— 耕地被踩回去又锄一遍是常态', () => {
    const b = new WorksBook(null);
    b.note('overworld', 0, 64, 0, { kind: 'farmland', block: 'farmland', site: null }, 1000);
    b.note('overworld', 0, 64, 0, { kind: 'farmland', block: 'farmland', site: null }, 9000);
    expect(b.at('overworld', 0, 64, 0)).toEqual({ kind: 'farmland', block: 'farmland', site: null, at: 9000 });
    expect(b.count('overworld')).toBe(1);
  });

  it('挖掉了就划掉:登记不许拿一格空气冒充成果', () => {
    const b = new WorksBook(null);
    b.note('overworld', 1, 64, 1, { kind: 'crop', block: 'wheat', site: null });
    b.forget('overworld', 1, 64, 1);
    expect(b.has('overworld', 1, 64, 1)).toBe(false);
    expect(b.count()).toBe(0);
  });

  it('inCells 按传进来的顺序回命中的那些格', () => {
    const b = new WorksBook(null);
    b.note('overworld', 0, 64, 0, { kind: 'crop', block: 'wheat', site: null }, 5);
    b.note('overworld', 2, 64, 0, { kind: 'farmland', block: 'farmland', site: null }, 7);
    const hits = b.inCells('overworld', [
      { x: 2, y: 64, z: 0 }, { x: 1, y: 64, z: 0 }, { x: 0, y: 64, z: 0 },
    ]);
    expect(hits.map((h) => h.x)).toEqual([2, 0]);
  });

  it('落盘再读回来是同一份;文件坏了当没登记过,不炸', () => {
    const file = tmpFile();
    const b = new WorksBook(file);
    b.noteMany('overworld', [
      { x: 0, y: 64, z: 0, kind: 'blueprint', block: 'oak_planks', site: 'hut' },
      { x: 0, y: 65, z: 0, kind: 'blueprint', block: 'oak_planks', site: 'hut' },
    ], 42);
    expect(JSON.parse(readFileSync(file, 'utf8')).overworld['0,64,0'].site).toBe('hut');
    expect(new WorksBook(file).count()).toBe(2);

    writeFileSync(file, '{ 这不是 json', 'utf8');
    expect(loadWorks(file)).toEqual({});
  });

  it('clear 把文件也写空,报清掉了几格', () => {
    const file = tmpFile();
    const b = new WorksBook(file);
    b.note('overworld', 0, 64, 0, { kind: 'crop', block: 'wheat', site: null });
    expect(b.clear()).toContain('1 格');
    expect(b.count()).toBe(0);
    expect(readFileSync(file, 'utf8').trim()).toBe('{}');
  });
});

describe('worksNote(摆进回执的那一句)', () => {
  it('一格都没有就不出这一行', () => {
    expect(worksNote([], clock)).toBeNull();
  });

  it('按类别合并计数,各报最早那一笔的时刻', () => {
    const text = worksNote([
      { x: 0, y: 64, z: 0, kind: 'crop', block: 'wheat', site: null, at: 9_000 },
      { x: 1, y: 64, z: 0, kind: 'crop', block: 'wheat', site: null, at: 3_000 },
      { x: 2, y: 63, z: 0, kind: 'farmland', block: 'farmland', site: null, at: 5_000 },
    ], clock);
    expect(text).toBe('这一框里有你2 格作物(记于 00:00:03)、1 格耕地(记于 00:00:05)');
  });

  it('只陈述,不出现任何「别挖」「确认」这类替她决定的词', () => {
    const text = worksNote(
      [{ x: 0, y: 64, z: 0, kind: 'blueprint', block: 'oak_planks', site: 'hut', at: 0 }],
      clock,
    ) ?? '';
    for (const word of ['别', '不要', '确认', '建议', '危险']) expect(text).not.toContain(word);
  });
});
