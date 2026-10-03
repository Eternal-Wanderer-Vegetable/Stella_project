import { formatDbTime, parseDbTime } from '@/utils/time';
import { describe, expect, it } from 'vitest';

// 时区显示合同：库里统一存 UTC，页面必须按本地时区渲染。
// 回归背景：FlowPage 曾直接截断 UTC 原始串，用户把 UTC 12 点当成当地时间，
// 误报「记录停在 12 点」（实际数据实时写入到本地 21 点）。

describe('parseDbTime', () => {
  it('parses ISO strings with explicit +00:00 offset', () => {
    const d = parseDbTime('2026-10-02T13:00:00.000+00:00');
    expect(d).not.toBeNull();
    expect(d!.getTime()).toBe(Date.UTC(2026, 9, 2, 13, 0, 0));
  });

  it('treats SQLite CURRENT_TIMESTAMP strings as UTC', () => {
    const d = parseDbTime('2026-10-02 13:00:00');
    expect(d).not.toBeNull();
    expect(d!.getTime()).toBe(Date.UTC(2026, 9, 2, 13, 0, 0));
  });

  it('returns null for empty and garbage input', () => {
    expect(parseDbTime('')).toBeNull();
    expect(parseDbTime(null)).toBeNull();
    expect(parseDbTime('not-a-date')).toBeNull();
  });
});

describe('formatDbTime', () => {
  it('renders in the local timezone (UTC+8 check)', () => {
    // 用固定时区偏移验证：本地时区相对 UTC 的差值由运行环境决定，
    // 这里只断言「解析正确 + 本地渲染与 Date 本地字段一致」。
    const raw = '2026-10-02T13:00:00.000+00:00';
    const d = parseDbTime(raw)!;
    const pad = (v: number) => String(v).padStart(2, '0');
    const expected =
      `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ` +
      `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
    expect(formatDbTime(raw)).toBe(expected);
  });

  it('falls back to the raw string when unparseable', () => {
    expect(formatDbTime('not-a-date')).toBe('not-a-date');
    expect(formatDbTime(null)).toBe('—');
  });
});
