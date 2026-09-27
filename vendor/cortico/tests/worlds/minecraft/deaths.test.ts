/**
 * 死亡账本按 06:00 换日计数，换世界重开，并支持跨进程读盘。
 */
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import {
  DeathBook, dayKey, loadDeaths, tollOn,
} from '../../../src/worlds/minecraft/deaths.ts';

const TZ = 'Asia/Shanghai';

describe('死亡账本', () => {
  let dir: string;
  let file: string;
  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), 'mc-deaths-'));
    file = join(dir, 'minecraft-deaths.json');
  });
  afterEach(() => rmSync(dir, { recursive: true, force: true }));

  /**
   * 直播时段(19:00→次日 00:12)必然骑着上海午夜。按自然日切,她刚播完
   * 「今天第 49 次」下一次死亡就当着观众报第 1 次。
   */
  it('一场直播落在同一个「今天」里:跨过午夜不归零', () => {
    const book = new DeathBook(file, TZ);
    book.record('世界一', new Date('2026-08-23T11:00:00Z')); // 北京 19:00 开播
    expect(book.record('世界一', new Date('2026-08-23T15:59:00Z'))).toMatchObject({ today: 2, total: 2 }); // 23:59
    expect(book.record('世界一', new Date('2026-08-23T16:04:00Z'))).toMatchObject({ today: 3, total: 3 }); // 次日 00:04
    expect(book.count(new Date('2026-08-23T21:59:00Z'))).toEqual({ today: 3, total: 3 }); // 次日 05:59
    // 换日点之后才是新的一天:今天归零,累计不动
    expect(book.record('世界一', new Date('2026-08-23T23:00:00Z'))).toMatchObject({ today: 1, total: 4 }); // 次日 07:00
  });

  it('换日点在部署时区的 06:00', () => {
    const night = dayKey(TZ, new Date('2026-08-23T15:59:00Z')); // 北京 23:59
    expect(night).toBe('2026-08-23');
    expect(dayKey(TZ, new Date('2026-08-23T16:04:00Z'))).toBe(night); // 次日 00:04
    expect(dayKey(TZ, new Date('2026-08-23T21:59:00Z'))).toBe(night); // 次日 05:59
    expect(dayKey(TZ, new Date('2026-08-23T22:00:00Z'))).toBe('2026-08-24'); // 次日 06:00
    expect(dayKey(TZ, new Date('2026-08-23T23:00:00Z'))).toBe('2026-08-24'); // 次日 07:00
  });

  it('日界属于部署时区,不是跑机器的本地时区', () => {
    // 北京 08-23 05:00 与 07:00;两者在 UTC-5 的机器上属于同一个本地日
    expect(dayKey(TZ, new Date('2026-08-22T21:00:00Z'))).toBe('2026-08-22');
    expect(dayKey(TZ, new Date('2026-08-22T23:00:00Z'))).toBe('2026-08-23');
  });

  it('换世界整本重开:位置类记忆在那一刻作废,死亡账同理', () => {
    const book = new DeathBook(file, TZ);
    book.record('恶地存档');
    book.record('恶地存档');
    expect(book.record('平原存档')).toMatchObject({ today: 1, total: 1 });
  });

  it('读盘方跨过午夜自己滚,不必等下一次死亡', () => {
    const book = new DeathBook(file, TZ);
    book.record('世界一', new Date('2026-08-22T14:00:00Z'));
    const onDisk = loadDeaths(file);
    expect(tollOn(onDisk, dayKey(TZ, new Date('2026-08-22T14:00:00Z')))).toEqual({ today: 1, total: 1 });
    expect(tollOn(onDisk, dayKey(TZ, new Date('2026-08-23T14:00:00Z')))).toEqual({ today: 0, total: 1 });
  });

  it('落盘后另开一本读得到——引擎子进程崩溃重启不清零', () => {
    const first = new DeathBook(file, TZ);
    first.record('世界一');
    first.record('世界一');
    expect(new DeathBook(file, TZ).count()).toEqual({ today: 2, total: 2 });
  });

  it('文件缺损当没死过,不抛', () => {
    writeFileSync(file, '{ 半截', 'utf8');
    expect(loadDeaths(file)).toEqual({ world: '', day: '', today: 0, total: 0, lastCauses: [] });
    expect(loadDeaths(null)).toEqual({ world: '', day: '', today: 0, total: 0, lastCauses: [] });
  });

  /**
   * 死因与死亡格进入 lastCauses，归档后仍可读取。
   */
  it('死因与死亡格记进 lastCauses,归档读得回来', () => {
    const book = new DeathBook(file, TZ);
    const r = book.record('世界一', new Date('2026-08-29T14:07:03Z'), {
      cause: 'CortiV burned to death',
      cell: 'minecraft:overworld:-145,-42,101',
    });
    expect(r).toMatchObject({ today: 1, total: 1, hereToday: 1 });
    const onDisk = loadDeaths(file);
    expect(onDisk.lastCauses).toHaveLength(1);
    expect(onDisk.lastCauses[0].cause).toBe('CortiV burned to death');
    expect(onDisk.lastCauses[0].cell).toBe('minecraft:overworld:-145,-42,101');
  });

  it('同格死亡计数:同一格今天第 N 次,换格与换日各自另算', () => {
    const book = new DeathBook(file, TZ);
    const cell = 'minecraft:overworld:-150,70,100';
    expect(book.record('世界一', new Date('2026-08-29T11:00:00Z'), { cell }).hereToday).toBe(1);
    expect(book.record('世界一', new Date('2026-08-29T12:00:00Z'), { cell }).hereToday).toBe(2);
    // 别的格不沾这本账
    expect(book.record('世界一', new Date('2026-08-29T13:00:00Z'), { cell: 'minecraft:overworld:0,64,0' }).hereToday).toBe(1);
    // 没有格读数时不数(0 = 说不出「这一格」这句话)
    expect(book.record('世界一', new Date('2026-08-29T13:30:00Z')).hereToday).toBe(0);
    // 换日(06:00 界)之后同一格重新从 1 数
    expect(book.record('世界一', new Date('2026-08-29T23:00:00Z'), { cell }).hereToday).toBe(1);
  });

  it('死因晚到:15 秒内补进最近一条,过窗或已有死因不动', () => {
    const book = new DeathBook(file, TZ);
    const at = new Date('2026-08-29T14:00:00Z');
    book.record('世界一', at, { cell: 'minecraft:overworld:1,2,3' });
    // 死亡广播晚一拍到:补进去
    book.noteCause('CortiV suffocated in a wall', new Date(at.getTime() + 3_000));
    expect(loadDeaths(file).lastCauses[0].cause).toBe('CortiV suffocated in a wall');
    // 已有死因的不覆盖
    book.noteCause('CortiV drowned', new Date(at.getTime() + 4_000));
    expect(loadDeaths(file).lastCauses[0].cause).toBe('CortiV suffocated in a wall');
    // 过窗的宁可丢,不错挂到上一次死亡上
    const book2 = new DeathBook(join(dir, 'b2.json'), TZ);
    book2.record('世界一', at);
    book2.noteCause('CortiV fell from a high place', new Date(at.getTime() + 60_000));
    expect(loadDeaths(join(dir, 'b2.json')).lastCauses[0].cause).toBeNull();
  });

  it('清空只抹计数,保留世界身份', () => {
    const book = new DeathBook(file, TZ);
    book.record('世界一');
    expect(book.clear()).toContain('1');
    expect(book.count()).toEqual({ today: 0, total: 0 });
    expect((JSON.parse(readFileSync(file, 'utf8')) as { world: string }).world).toBe('世界一');
    expect(book.clear()).toBe('死亡账本本来就是空的');
  });
});
