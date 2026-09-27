/**
 * 同一轮、同一工具且读数指纹相同的重复查询返回简短回执；状态变化时重新完整回答。
 * 指纹排除时钟字段，避免经过时间造成虚假的状态变化。
 * 主循环的 round 经代理 IPC 原样传入子进程的 ctx.round；缺少轮号时每次正常回答。
 */
import type { ToolCallContext } from '../../core/types.ts';

export function roundTokenOf(ctx: ToolCallContext | undefined): number | null {
  if (!ctx) return null;
  if (typeof ctx.round === 'number') return ctx.round;
  return null;
}

export const REPEATED_QUERY_RECEIPT = '这轮已经答过了,答案不会变,先看上一条。';

export class RoundOnceGate {
  private readonly last = new Map<string, { round: number; stamp: string }>();

  answered(tool: string, round: number | null, stamp: string): boolean {
    if (round === null) return true;
    const prev = this.last.get(tool);
    if (prev && prev.round === round && prev.stamp === stamp) return false;
    this.last.set(tool, { round, stamp });
    return true;
  }
}
