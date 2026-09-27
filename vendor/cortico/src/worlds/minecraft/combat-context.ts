/**
 * Context steering 的方向选择实现，算法来源：Andrew Fray，Game AI Pro 2，第 18 章。
 * interest 与 danger 分别合并方向偏好和风险；硬危险通过 masking 排除。
 */

export const SLOTS = 16;

/** 硬危险槽直接排除，不参与最低危险与容差比较。 */
export const HARD = 1e6;

export type Map16 = Float64Array;

export function newMap(): Map16 {
  return new Float64Array(SLOTS);
}

export function slotDir(i: number): { x: number; z: number } {
  const a = (i / SLOTS) * Math.PI * 2;
  return { x: Math.cos(a), z: Math.sin(a) };
}

export function dirSlot(dx: number, dz: number): number {
  const a = Math.atan2(dz, dx);
  const s = (a / (Math.PI * 2)) * SLOTS;
  return ((s % SLOTS) + SLOTS) % SLOTS;
}

/** 各方向强度取 max。sharpness 控制余弦瓣宽度，1 约为 180°，4 更窄。 */
export function write(map: Map16, dx: number, dz: number, strength: number, sharpness = 1): void {
  const len = Math.hypot(dx, dz);
  if (len < 1e-9 || strength <= 0) return;
  const ux = dx / len, uz = dz / len;
  for (let i = 0; i < SLOTS; i++) {
    const d = slotDir(i);
    const dot = d.x * ux + d.z * uz;
    if (dot <= 0) continue;
    const v = strength * Math.pow(dot, sharpness);
    if (v > map[i]) map[i] = v;
  }
}

export function writeSlot(map: Map16, i: number, v: number): void {
  const k = ((i % SLOTS) + SLOTS) % SLOTS;
  if (v > map[k]) map[k] = v;
}

/** 1-2-1 环形平滑。 */
export function blur(map: Map16): void {
  const src = Float64Array.from(map);
  for (let i = 0; i < SLOTS; i++) {
    const a = src[(i - 1 + SLOTS) % SLOTS];
    const b = src[i];
    const c = src[(i + 1) % SLOTS];
    /** 硬危险不参与平滑。 */
    if (b >= HARD) { map[i] = b; continue; }
    const av = a >= HARD ? b : a;
    const cv = c >= HARD ? b : c;
    map[i] = (av + 2 * b + cv) / 4;
  }
}

/** 与上一 tick 的方向图混合，形成滞回。 */
export function blend(prev: Map16, cur: Map16, alpha: number): void {
  for (let i = 0; i < SLOTS; i++) {
    if (cur[i] >= HARD || prev[i] >= HARD) { cur[i] = Math.max(cur[i], prev[i] >= HARD ? 0 : cur[i]); }
    if (cur[i] >= HARD) continue;
    cur[i] = alpha * cur[i] + (1 - alpha) * prev[i];
  }
}

interface Choice {
  x: number;
  z: number;
  strength: number;
  slot: number;
}

/**
 * 排除硬危险和高于最低危险加容差的槽，再选 interest 最大值。
 * 以未排除的相邻槽做抛物线插值；全部排除时返回 null。
 */
export function decide(interest: Map16, danger: Map16, tol = 0.2): Choice | null {
  let min = Infinity;
  for (let i = 0; i < SLOTS; i++) if (danger[i] < HARD && danger[i] < min) min = danger[i];
  if (!Number.isFinite(min)) return null;

  const cut = min + tol;
  let best = -1;
  let bestV = -Infinity;
  for (let i = 0; i < SLOTS; i++) {
    if (danger[i] >= HARD || danger[i] > cut) continue;
    if (interest[i] > bestV) { bestV = interest[i]; best = i; }
  }
  if (best < 0) return null;

  /** 插值仅使用未排除的相邻槽。 */
  const li = (best - 1 + SLOTS) % SLOTS;
  const ri = (best + 1) % SLOTS;
  const ok = (i: number): boolean => danger[i] < HARD && danger[i] <= cut;
  const a = ok(li) ? interest[li] : bestV;
  const c = ok(ri) ? interest[ri] : bestV;
  const denom = a - 2 * bestV + c;
  let off = 0;
  if (Math.abs(denom) > 1e-9) off = (0.5 * (a - c)) / denom;
  if (!Number.isFinite(off) || Math.abs(off) > 1) off = 0;

  const ang = ((best + off) / SLOTS) * Math.PI * 2;
  return { x: Math.cos(ang), z: Math.sin(ang), strength: bestV, slot: best };
}
