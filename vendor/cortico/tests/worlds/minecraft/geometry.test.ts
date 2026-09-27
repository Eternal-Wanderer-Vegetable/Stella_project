import { describe, expect, it } from 'vitest';
import {
  ANCHOR_COUNT, rasterize, resolveAnchors, type Anchor, type Cell,
} from '../../../src/worlds/minecraft/geometry.ts';

const ORIGIN: Cell = { x: 100, y: 64, z: -20 };

function cells(v: ReturnType<typeof rasterize>): Cell[] {
  if (!Array.isArray(v)) throw new Error(`栅格化失败: ${v.error}`);
  return v;
}

function resolved(anchors: Anchor[], origin = ORIGIN): Cell[] {
  const r = resolveAnchors(anchors, origin);
  if (!Array.isArray(r)) throw new Error(r.error);
  return r;
}

describe('锚点解析', () => {
  it('绝对数字、~、~±n 三种写法混用', () => {
    expect(resolved([[1, 2.9, -3], ['~', '~10', '~-3'], ['5', '~', 7]])).toEqual([
      { x: 1, y: 2, z: -3 },
      { x: 100, y: 74, z: -23 },
      { x: 5, y: 64, z: 7 },
    ]);
  });

  it('认不出的坐标报第几个锚点', () => {
    const r = resolveAnchors([['~', '~', '~'], ['abc' as never, 0, 0]], ORIGIN);
    expect(r).toMatchObject({ error: expect.stringContaining('第 2 个锚点') });
  });
});

describe('rasterize', () => {
  it('锚点数量与形状不符直接报错', () => {
    expect(ANCHOR_COUNT.triangle).toBe(3);
    const r = rasterize('triangle', [{ x: 0, y: 0, z: 0 }, { x: 1, y: 0, z: 0 }]);
    expect(r).toMatchObject({ error: expect.stringContaining('triangle 要 3 个锚点') });
  });

  it('line:两端点都在,格数=最长轴+1,连续无重复', () => {
    const got = cells(rasterize('line', [{ x: 0, y: 0, z: 0 }, { x: 0, y: 10, z: 0 }]));
    expect(got).toHaveLength(11);
    expect(got[0]).toEqual({ x: 0, y: 0, z: 0 });
    expect(got[10]).toEqual({ x: 0, y: 10, z: 0 });
  });

  it('line:斜线相邻格最多差 1', () => {
    const got = cells(rasterize('line', [{ x: 0, y: 0, z: 0 }, { x: 7, y: 3, z: -5 }]));
    for (let i = 1; i < got.length; i++) {
      expect(Math.abs(got[i].x - got[i - 1].x)).toBeLessThanOrEqual(1);
      expect(Math.abs(got[i].y - got[i - 1].y)).toBeLessThanOrEqual(1);
      expect(Math.abs(got[i].z - got[i - 1].z)).toBeLessThanOrEqual(1);
    }
  });

  it('rect:一轴相等铺满整面', () => {
    const got = cells(rasterize('rect', [{ x: 0, y: 64, z: 0 }, { x: 3, y: 64, z: 2 }]));
    expect(got).toHaveLength(4 * 3);
    expect(got.every((c) => c.y === 64)).toBe(true);
  });

  it('rect:没有一轴相等报错', () => {
    const r = rasterize('rect', [{ x: 0, y: 0, z: 0 }, { x: 1, y: 1, z: 1 }]);
    expect(r).toMatchObject({ error: expect.stringContaining('一轴相等') });
  });

  it('triangle:三个顶点都在,面被填上', () => {
    const got = cells(rasterize('triangle', [
      { x: 0, y: 0, z: 0 }, { x: 8, y: 0, z: 0 }, { x: 0, y: 0, z: 8 },
    ]));
    const has = (x: number, y: number, z: number) => got.some((c) => c.x === x && c.y === y && c.z === z);
    expect(has(0, 0, 0)).toBe(true);
    expect(has(8, 0, 0)).toBe(true);
    expect(has(0, 0, 8)).toBe(true);
    expect(has(2, 0, 2)).toBe(true); // 内部
    // 面积约为直角边 8×8 的一半,填充数应远超周长
    expect(got.length).toBeGreaterThan(30);
  });

  it('arc:过三点,端点在,中途点在,弯而不是直线', () => {
    // 半圆:(-5,0) 经 (0,5) 到 (5,0),圆心原点半径 5
    const got = cells(rasterize('arc', [
      { x: -5, y: 64, z: 0 }, { x: 0, y: 64, z: 5 }, { x: 5, y: 64, z: 0 },
    ]));
    const has = (x: number, z: number) => got.some((c) => c.x === x && c.z === z && c.y === 64);
    expect(has(-5, 0)).toBe(true);
    expect(has(0, 5)).toBe(true);
    expect(has(5, 0)).toBe(true);
    expect(has(0, 0)).toBe(false); // 不穿圆心:是弧不是弦
    // 所有格都贴着半径 5 的圆周
    for (const c of got) {
      expect(Math.abs(Math.hypot(c.x, c.z) - 5)).toBeLessThan(1.2);
    }
  });

  it('arc:三点共线报错并指路 line', () => {
    const r = rasterize('arc', [{ x: 0, y: 0, z: 0 }, { x: 1, y: 1, z: 1 }, { x: 3, y: 3, z: 3 }]);
    expect(r).toMatchObject({ error: expect.stringContaining('line') });
  });

  // 词取原版 /fill:outline = 只动外壳、内部原样。原版的 hollow 会把内部清成空气,
  // 我们没有那个模式,所以外壳这一档只叫 outline —— 内部那 8 格必须原封不动。
  it('box:solid 全填,outline 只留壳且不碰内部,edges 只留棱', () => {
    const anchors = [{ x: 0, y: 0, z: 0 }, { x: 3, y: 3, z: 3 }];
    expect(cells(rasterize('box', anchors, 'solid'))).toHaveLength(64);
    const shell = cells(rasterize('box', anchors, 'outline'));
    expect(shell).toHaveLength(64 - 8); // 4³ 减内部 2³
    expect(shell.some((c) => c.x === 1 && c.y === 1 && c.z === 1)).toBe(false);
    // edges = 12 条棱:8 角 + 每棱 2 个中段 ×12 = 8 + 24
    expect(cells(rasterize('box', anchors, 'edges'))).toHaveLength(32);
  });
});
