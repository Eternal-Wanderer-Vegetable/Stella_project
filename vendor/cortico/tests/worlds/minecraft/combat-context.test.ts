import { describe, expect, it } from 'vitest';
import {
  HARD, SLOTS, blend, blur, decide, dirSlot, newMap, slotDir, write, writeSlot,
} from '../../../src/worlds/minecraft/combat-context.ts';

/**
 * 上下文图纯逻辑的断言,从台架的 context-check.ts 原样搬入。
 *
 * 为什么单独钉这一层:方向数学里的符号错误不会报错,只会让 bot 朝反方向走,
 * 在战斗数据里表现为「这条战术没用」——台架按键坐标系那次就是这么坑的,
 * 图里的合成方向连真机探针都看不见,只能靠断言。
 */
describe('上下文图:槽与方向', () => {
  it('slotDir/dirSlot 往返一致', () => {
    for (let i = 0; i < SLOTS; i++) {
      const d = slotDir(i);
      expect(dirSlot(d.x, d.z)).toBeCloseTo(i, 6);
    }
  });

  it('write:峰值落在目标方向上,反方向为 0', () => {
    const m = newMap();
    write(m, 1, 0, 1, 1);
    let best = 0;
    for (let i = 1; i < SLOTS; i++) if (m[i] > m[best]) best = i;
    expect(best).toBe(dirSlot(1, 0));
    expect(m[(best + SLOTS / 2) % SLOTS]).toBeCloseTo(0, 6);
  });

  it('write:合并取 max,不是求和;更弱的一次不降低已有值', () => {
    const m = newMap();
    write(m, 1, 0, 0.4, 1);
    write(m, 1, 0, 0.9, 1);
    const i = dirSlot(1, 0);
    expect(m[i]).toBeCloseTo(0.9, 6);
    write(m, 1, 0, 0.5, 1);
    expect(m[i]).toBeCloseTo(0.9, 6);
  });

  it('write:sharpness 越大瓣越窄', () => {
    const wide = newMap();
    write(wide, 1, 0, 1, 1);
    const narrow = newMap();
    write(narrow, 1, 0, 1, 4);
    const side = (dirSlot(1, 0) + 3) % SLOTS; // 偏离约 67°
    expect(narrow[side]).toBeLessThan(wide[side]);
  });
});

describe('上下文图:裁决', () => {
  it('危险方向被排除,选次优的 interest', () => {
    const I = newMap();
    const D = newMap();
    write(I, 1, 0, 1.0, 1);   // 最想去 +x
    write(I, -1, 0, 0.6, 1);  // 次想去 -x
    write(D, 1, 0, 5.0, 1);   // 但 +x 很危险
    const c = decide(I, D);
    expect(c).not.toBeNull();
    expect(c!.x).toBeLessThan(0.5);
  });

  it('硬危险永远排除,即使它是最想去的', () => {
    const I = newMap();
    const D = newMap();
    write(I, 1, 0, 1.0, 1);
    const bad = dirSlot(1, 0);
    writeSlot(D, bad, HARD);
    const c = decide(I, D);
    expect(c).not.toBeNull();
    expect(c!.slot).not.toBe(bad);
  });

  it('四面全硬 → null(调用方自己决定站住还是硬闯)', () => {
    const I = newMap();
    const D = newMap();
    for (let i = 0; i < SLOTS; i++) {
      I[i] = 1;
      writeSlot(D, i, HARD);
    }
    expect(decide(I, D)).toBeNull();
  });

  it('次槽插值把方向拉向更强的一侧', () => {
    const I = newMap();
    const D = newMap();
    const b = 4;
    I[b] = 1.0;
    I[b + 1] = 0.9;
    I[b - 1] = 0.2;
    const c = decide(I, D);
    expect(c).not.toBeNull();
    const s = dirSlot(c!.x, c!.z);
    expect(s).toBeGreaterThan(b);
    expect(s).toBeLessThan(b + 1);
  });

  it('端到端:被三只怪从西/北/南围住,唯一空档在东', () => {
    const I = newMap();
    const D = newMap();
    write(I, -1, 0, 1.0, 1);  // 目标(最近那只)在西,仍然想朝它
    write(D, -1, 0, 2.0, 2);
    write(D, 0, 1, 2.0, 2);
    write(D, 0, -1, 2.0, 2);
    const c = decide(I, D, 0.2);
    expect(c).not.toBeNull();
    expect(c!.x).toBeGreaterThan(0.5); // 往东边空档走
  });
});

describe('上下文图:模糊与滞回', () => {
  it('blur:抹平尖刺但不动硬危险,也不把硬危险渗到邻槽', () => {
    const m = newMap();
    m[5] = 1;
    writeSlot(m, 10, HARD);
    blur(m);
    expect(m[4]).toBeGreaterThan(0);
    expect(m[6]).toBeGreaterThan(0);
    expect(m[5]).toBeLessThan(1);
    expect(m[10]).toBeGreaterThanOrEqual(HARD);
    expect(m[9]).toBeLessThan(HARD);
    expect(m[11]).toBeLessThan(HARD);
  });

  it('blend:全局滞回——新图不会一步跳到位;硬危险不被稀释', () => {
    const prev = newMap();
    const cur = newMap();
    prev[3] = 1;
    cur[3] = 0;
    blend(prev, cur, 0.5);
    expect(cur[3]).toBeCloseTo(0.5, 6);

    const prev2 = newMap();
    const cur2 = newMap();
    writeSlot(cur2, 7, HARD);
    blend(prev2, cur2, 0.3);
    expect(cur2[7]).toBeGreaterThanOrEqual(HARD);
  });
});
