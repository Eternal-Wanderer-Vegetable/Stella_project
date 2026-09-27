/**
 * level.dat 解析。夹具在这里现编:一份真 level.dat 是二进制的 gzip NBT,
 * 拿真存档当夹具既进不了库(第三方素材),也没法覆盖"字段缺一半"这类形态。
 */
import { gzipSync } from 'node:zlib';
import { describe, expect, it } from 'vitest';
import { parseLevelDat } from '../../../src/worlds/minecraft/level-dat.ts';

const TAG_BYTE = 1;
const TAG_INT = 3;
const TAG_LONG = 4;
const TAG_STRING = 8;
const TAG_COMPOUND = 10;

function name(s: string): Buffer {
  const body = Buffer.from(s, 'utf8');
  const head = Buffer.alloc(2);
  head.writeUInt16BE(body.length);
  return Buffer.concat([head, body]);
}

const tag = {
  byte: (key: string, v: number): Buffer => Buffer.concat([Buffer.from([TAG_BYTE]), name(key), Buffer.from([v])]),
  int: (key: string, v: number): Buffer => {
    const body = Buffer.alloc(4);
    body.writeInt32BE(v);
    return Buffer.concat([Buffer.from([TAG_INT]), name(key), body]);
  },
  long: (key: string, v: bigint): Buffer => {
    const body = Buffer.alloc(8);
    body.writeBigInt64BE(v);
    return Buffer.concat([Buffer.from([TAG_LONG]), name(key), body]);
  },
  str: (key: string, v: string): Buffer =>
    Buffer.concat([Buffer.from([TAG_STRING]), name(key), name(v)]),
  compound: (key: string, ...children: Buffer[]): Buffer =>
    Buffer.concat([Buffer.from([TAG_COMPOUND]), name(key), ...children, Buffer.from([0])]),
};

/** root(无名) → Data{…} */
function levelDat(...data: Buffer[]): Buffer {
  return gzipSync(Buffer.concat([
    Buffer.from([TAG_COMPOUND]), name(''), tag.compound('Data', ...data), Buffer.from([0]),
  ]));
}

const FULL = levelDat(
  tag.str('LevelName', '试玩世界'),
  tag.long('LastPlayed', 1_755_000_000_000n),
  tag.int('GameType', 1),
  tag.byte('Difficulty', 3),
  tag.byte('hardcore', 1),
  tag.long('DayTime', 24_000n),
  tag.compound('Version', tag.str('Name', '1.20.6'), tag.int('Id', 3839)),
  tag.compound(
    'WorldGenSettings',
    tag.long('seed', -8_601_234_567_890_123n),
    tag.byte('generate_features', 1),
    tag.compound(
      'dimensions',
      tag.compound(
        'minecraft:overworld',
        tag.compound('generator', tag.str('type', 'minecraft:flat')),
      ),
    ),
  ),
  tag.compound(
    'GameRules',
    tag.str('keepInventory', 'true'),
    tag.str('doInsomnia', 'false'),
  ),
);

describe('level.dat 自述', () => {
  it('存档名、上次游玩、模式、版本都读得出', () => {
    expect(parseLevelDat(FULL)).toMatchObject({
      levelName: '试玩世界',
      lastPlayed: 1_755_000_000_000,
      gameType: 1,
      difficulty: 3,
      hardcore: true,
      version: '1.20.6',
      dayTime: 24_000,
    });
  });

  it('种子是 64 位的,按字符串带出来才不会掉精度', () => {
    expect(parseLevelDat(FULL)?.seed).toBe('-8601234567890123');
  });

  it('主世界生成器认得出超平坦', () => {
    expect(parseLevelDat(FULL)?.generator).toBe('flat');
  });

  it('噪声生成器报的是它的 settings(放大化/大群系都在这儿)', () => {
    const dat = levelDat(tag.compound(
      'WorldGenSettings',
      tag.compound('dimensions', tag.compound('minecraft:overworld', tag.compound(
        'generator',
        tag.str('type', 'minecraft:noise'),
        tag.str('settings', 'minecraft:amplified'),
      ))),
    ));
    expect(parseLevelDat(dat)?.generator).toBe('amplified');
  });

  it('GameRules 原样带出来(原版连布尔也存成字符串)', () => {
    expect(parseLevelDat(FULL)?.gameRules).toEqual({ keepInventory: 'true', doInsomnia: 'false' });
  });

  it('没有 GameRules 那一节 = null;有那一节但空着 = 空对象(两者不是一回事)', () => {
    // 「读不到」与「读到了、这条没写」要分得开:前者不能拿来跨维度对齐(见 mc-server
    // 的 planGameRuleAlignment),后者说明主世界确实没设过这条规则。
    expect(parseLevelDat(levelDat(tag.str('LevelName', 'x')))?.gameRules).toBeNull();
    expect(parseLevelDat(levelDat(tag.compound('GameRules')))?.gameRules).toEqual({});
  });

  it('字段缺一半照样给出一份,缺的是 null', () => {
    expect(parseLevelDat(levelDat(tag.str('LevelName', 'x')))).toEqual({
      levelName: 'x',
      lastPlayed: null,
      seed: null,
      gameType: null,
      difficulty: null,
      hardcore: null,
      version: null,
      generator: null,
      dayTime: null,
      gameRules: null,
    });
  });

  it('不是 NBT、gzip 坏了、没有 Data 的都当作没有自述', () => {
    expect(parseLevelDat(Buffer.from('这不是 level.dat'))).toBeNull();
    expect(parseLevelDat(gzipSync(Buffer.from([0x1f, 0x8b, 0x00])))).toBeNull();
    expect(parseLevelDat(gzipSync(Buffer.concat([
      Buffer.from([TAG_COMPOUND]), name(''), Buffer.from([0]),
    ])))).toBeNull();
  });

  it('未压缩的 level.dat 也读(有的服务端不压)', () => {
    const raw = Buffer.concat([
      Buffer.from([TAG_COMPOUND]), name(''), tag.compound('Data', tag.str('LevelName', 'raw')), Buffer.from([0]),
    ]);
    expect(parseLevelDat(raw)?.levelName).toBe('raw');
  });
});
