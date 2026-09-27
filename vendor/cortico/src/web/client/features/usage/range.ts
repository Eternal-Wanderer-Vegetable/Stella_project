/**
 * 时间范围：预设天数 ↔ 具体 `from` / `to`。
 *
 * 一律走**本地时区**的年月日：服务端的桶前缀也是本地时区串（`src/core/cost.ts`），
 * 拿 `toISOString().slice(0,10)` 会在 UTC+8 的凌晨八小时里整整差一天。
 */

/** `offsetDays` 天前的本地日期（`YYYY-MM-DD`）。0 = 今天。 */
export function localDate(offsetDays: number, now: number = Date.now()): string {
  const d = new Date(now - offsetDays * 86400000);
  const p = (n: number): string => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

export interface UsageRange {
  from: string | null;
  to: string | null;
}

/**
 * `days === 0` 是"自定义"档：此时取两个日期框里的值（空串 = 不限）。
 * 其余档位是"近 N 天"，含今天，所以起点是 `N-1` 天前。
 */
export function usageRange(days: number, custom: UsageRange, now: number = Date.now()): UsageRange {
  if (days === 0) return { from: custom.from || null, to: custom.to || null };
  return { from: localDate(days - 1, now), to: localDate(0, now) };
}

/** `/api/usage` 的查询串。空的 from/to 不出现在 URL 里。 */
export function usageQuery(bucket: string, range: UsageRange): string {
  const q = new URLSearchParams();
  q.set('bucket', bucket);
  if (range.from) q.set('from', range.from);
  if (range.to) q.set('to', range.to);
  return q.toString();
}
