// 时间显示工具：库里统一存 UTC（flow/trace 表是带 +00:00 的 ISO 串，
// SQLite CURRENT_TIMESTAMP 是无时区标记的 "YYYY-MM-DD HH:MM:SS"——语义
// 仍是 UTC），页面一律格式化为**本地时区**显示。2026-10-02 实测：直接
// 截断原始字符串会被用户当成当地时间，造成「记录停在 12 点」的误报
// （实际是 UTC 12 点 = 本地 20 点，数据一直是实时的）。

const SQLITE_UTC_RE = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/;

/** 把库里的 UTC 时间串解析成本地时间；无法解析时原样返回（不猜）。 */
export function parseDbTime(raw: string | null | undefined): Date | null {
  if (!raw) return null;
  let iso = raw.trim();
  if (!iso) return null;
  if (SQLITE_UTC_RE.test(iso)) iso = `${iso.replace(' ', 'T')}Z`;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** "YYYY-MM-DD HH:mm:ss"（本地时区）；解析失败原样返回。 */
export function formatDbTime(raw: string | null | undefined): string {
  const d = parseDbTime(raw);
  if (d === null) return raw ?? '—';
  const pad = (v: number) => String(v).padStart(2, '0');
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ` +
    `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  );
}
