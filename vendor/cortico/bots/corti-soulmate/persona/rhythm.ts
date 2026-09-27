/**
 * 闹钟(schedule_wake)的全部语义:簿记、投递闸门、到期文案。core 只出持久定时器与闸门原语。
 * 心跳循环在 Cormini;这里只留 tick 文案用的时刻格式。
 */
import type { CoreApi, TimerEntry } from 'cortico/core/types.ts';
import { nowIso } from 'cortico/core/util.ts';

/** tick/闹钟文案里的 "MM-DD HH:MM(周X)" */
export function tickTimeText(timezone: string, d: Date): string {
  const parts = new Intl.DateTimeFormat('zh-CN', {
    timeZone: timezone,
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).formatToParts(d);
  const get = (t: string): string => parts.find((p) => p.type === t)?.value ?? '??';
  const weekday = new Intl.DateTimeFormat('zh-CN', { timeZone: timezone, weekday: 'short' }).format(d);
  return `${get('month')}-${get('day')} ${get('hour')}:${get('minute')}(${weekday})`;
}

/** 闹钟条目的载荷(落在 core 持久定时器的不透明 payload 里) */
interface WakePayload {
  note: string;
  setAt: string;
  blockDelivery?: boolean;
  wakeKeyword?: string;
  overflowLimit?: number;
}

export class WakeManager {
  private activeBlockId: string | null = null;

  constructor(
    private readonly core: CoreApi,
    private readonly timezone: () => string,
  ) {
    core.timers.onDue((entry) => this.onDue(entry));
    this.refreshGate();
  }

  /** Schedules a wake and returns its agent-facing receipt. */
  schedule(args: Record<string, unknown>): string {
    const note = String(args.note ?? '');
    const rawAt = typeof args.at === 'string' ? args.at.trim() : '';
    const afterMinutes = Number(args.after_minutes);
    if (rawAt && Number.isFinite(afterMinutes) && afterMinutes > 0) {
      return '[bad input] use either at or after_minutes, not both';
    }
    let at = rawAt;
    if (!at) {
      if (!Number.isFinite(afterMinutes) || afterMinutes <= 0) {
        return '[bad input] provide at or a positive after_minutes';
      }
      const delayMs = Math.max(10_000, afterMinutes * 60_000);
      at = new Date(Date.now() + delayMs).toISOString();
    }
    const block = args.block === true;
    const wakeKeyword =
      block && typeof args.wake_keyword === 'string' && args.wake_keyword.length > 0
        ? args.wake_keyword
        : undefined;
    const overflowLimit = Number(args.overflow_limit ?? 100);
    if (!Number.isInteger(overflowLimit) || overflowLimit < 1) {
      return '[bad input] overflow_limit must be a positive integer';
    }
    const payload: WakePayload = {
      note,
      setAt: nowIso(this.timezone()),
      ...(block ? { blockDelivery: true, wakeKeyword, overflowLimit } : {}),
    };
    const r = this.core.timers.set(at, payload as unknown as Record<string, unknown>);
    if (!r.ok) {
      return `[bad input] could not parse time "${at}"; use ISO 8601 with timezone, e.g. 2026-07-18T20:00:00+08:00.`;
    }
    this.refreshGate();
    return block
      ? `[system/scheduled] Wake set for ${at} (id: ${r.id}). Live event delivery is blocked until then` +
          `${wakeKeyword ? ` or until literal keyword ${JSON.stringify(wakeKeyword)} matches` : ''}; ` +
          `more than ${overflowLimit} queued external events will release one batch without cancelling the wake.`
      : `[system/scheduled] Wake set for ${at} (id: ${r.id}).`;
  }

  private onDue(entry: TimerEntry): void {
    const p = entry.payload as unknown as WakePayload;
    if (this.activeBlockId === entry.id) {
      // 解闸时暂不投递，使到期通知与积压合并为同一 user 回合。
      this.core.deliveryGate.clear(entry.id, false);
      this.activeBlockId = null;
    }
    this.core.injectInternal(this.dueText(p), 'wake.due');
    this.refreshGate();
    this.core.log.info('schedule_wake到期', {
      id: entry.id,
      note: p.note,
    });
  }

  private dueText(p: WakePayload): string {
    return `[system/wake] My note: "${p.note}" (set at ${p.setAt}).`;
  }

  /** 最早到期的阻断闹钟拥有当前投递闸门;它结束后自动切到下一个。 */
  private refreshGate(): void {
    const next = this.core.timers
      .list()
      .filter((e) => (e.payload as unknown as WakePayload).blockDelivery === true)
      .sort((a, b) => Date.parse(a.atIso) - Date.parse(b.atIso))[0];
    if (next?.id === this.activeBlockId) return;

    if (this.activeBlockId) this.core.deliveryGate.clear(this.activeBlockId, false);
    this.activeBlockId = next?.id ?? null;
    if (!next) return;

    const p = next.payload as unknown as WakePayload;
    const overflowLimit =
      Number.isInteger(p.overflowLimit) && (p.overflowLimit ?? 0) > 0 ? p.overflowLimit! : 100;
    this.core.deliveryGate.set({
      id: next.id,
      keyword: p.wakeKeyword || undefined,
      overflowLimit,
      onKeyword: () => {
        if (this.activeBlockId !== next.id) return;
        this.core.timers.cancel(next.id);
        this.core.deliveryGate.clear(next.id, false);
        this.activeBlockId = null;
        this.core.injectInternal(
          '[system/wake] Woke early because an event matched the literal keyword ' +
            `${JSON.stringify(p.wakeKeyword ?? '')}. My note: "${p.note}" (set at ${p.setAt}).`,
          'wake.due',
        );
        this.refreshGate();
        this.core.log.info('schedule_wake关键词提前唤醒', { id: next.id, note: p.note });
      },
      onOverflow: () => {
        if (this.activeBlockId !== next.id) return;
        this.core.injectInternal(
          `[system/wake-overflow] More than ${overflowLimit} external events accumulated ` +
            'while delivery was blocked. This batch was released once; the scheduled wake remains active.',
          'wake.overflow',
        );
        this.core.log.warn('schedule_wake阻断积压溢出,临时放行一批', {
          id: next.id,
          overflowLimit,
        });
      },
    });
  }
}
