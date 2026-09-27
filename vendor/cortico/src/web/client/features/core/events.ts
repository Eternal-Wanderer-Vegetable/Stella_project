/**
 * 事件库翻查界面，按 from/to 游标区间分页：追新使用 latest+1，翻旧使用 earliest−1。边界与来源集合属于本次挂载。
 * 来源选项由数据生成，新来源出现时保留当前选择；调试通道可用时由 event 帧触发追新，不可用时回落轮询。
 */

import type { ConsoleUi, ConsoleTable, Disposable } from '../../../shared/client-panel.ts';
import { get } from '../../core/api.ts';
import type { Lifecycle } from '../../core/lifecycle.ts';
import { shouldStick } from '../../ui/index.ts';
import { S } from './strings.ts';

/** 事件库的一条。字段是服务端 `EventEnvelope` 的子集。 */
export interface EventRow {
  cursor: number;
  ts: string;
  source: string;
  type: string;
  text: string;
}

interface EventPage {
  latest: number;
  events: EventRow[];
}

const PAGE = 100;
/** 没有推送时的轮询间隔。 */
const EVENT_POLL_MS = 3000;
/** 距底多少像素之内仍算贴着底。 */
const STICK_PX = 60;

export interface EventsViewDeps {
  ui: ConsoleUi;
  lifecycle: Lifecycle;
  signal: AbortSignal;
  /** 网络状态回报(与调试通道共用同一处显示) */
  onNet(online: boolean): void;
  onError(err: unknown): void;
}

export interface EventsView {
  el: HTMLElement;
  /** 首次进入/换来源时的全量拉取 */
  init(): Promise<void>;
  /** 追新(推送到了、或轮询到点) */
  poll(): Promise<void>;
  /** 这一页开始/停止自己轮询(没有推送时才需要) */
  setPolling(on: boolean): void;
}

export function createEventsView(deps: EventsViewDeps): EventsView {
  const { ui } = deps;
  const sources = new Set<string>();
  let source = '';
  let archive = false;
  let earliest: number | null = null;
  let latest = 0;
  let inited = false;
  let poller: Disposable | null = null;

  const bar = ui.rowbar();
  const desc = ui.h('span', 'pagedesc grow', S.eventsDesc);
  const sel = ui.select({
    options: [{ value: '', label: S.allSources }],
    onChange: (v) => {
      source = v;
      inited = false;
      earliest = null;
      latest = 0;
      void view.init();
    },
  });
  // 默认过滤 archiveOnly 记录；启用归档选项后同时显示未直接投递的记录。
  const archiveToggle = ui.checkbox(S.showArchive, {
    title: S.showArchiveTitle,
    onChange: (on) => {
      archive = on;
      inited = false;
      earliest = null;
      latest = 0;
      void view.init();
    },
  });
  const more = ui.button(S.loadEarlier, { size: 'sm', onClick: () => void loadEarlier() });
  bar.append(desc, sel, archiveToggle.el, more);

  const table: ConsoleTable = ui.table({
    head: ['#', S.evHeadTime, S.evHeadSource, S.evHeadType, S.evHeadText],
    maxHeight: 'calc(100vh - 300px)',
  });

  const el = ui.h('div');
  el.append(bar, table.el);

  const rowCells = (e: EventRow): Parameters<ConsoleTable['addRow']>[0] => [
    { text: `#${e.cursor}`, cls: 'mono' },
    { text: ui.fmt.clock(e.ts), cls: 'mono' },
    { text: e.source, cls: 'mono' },
    { text: e.type, cls: 'mono' },
    { text: e.text, cls: 'txt' },
  ];

  /** 新来源就补一项;当前选择不动(它可能正指着一个刚被重画掉的 option)。 */
  const noteSources = (events: readonly EventRow[]): void => {
    for (const e of events) {
      if (!e.source || sources.has(e.source)) continue;
      sources.add(e.source);
      const op = ui.h('option', null, e.source);
      op.value = e.source;
      sel.appendChild(op);
    }
  };

  const query = (extra: string): string => {
    const src = source ? `&source=${encodeURIComponent(source)}` : '';
    return `/api/events?${extra}${src}${archive ? '&archive=1' : ''}`;
  };

  const stuck = (): boolean =>
    shouldStick(table.el.scrollTop, table.el.scrollHeight, table.el.clientHeight, STICK_PX);
  const toEnd = (): void => {
    table.el.scrollTop = table.el.scrollHeight;
  };

  const failed = (err: unknown): boolean => {
    if ((err as { name?: string } | null)?.name === 'AbortError') return true;
    deps.onNet(false);
    deps.onError(err);
    return false;
  };

  async function loadEarlier(): Promise<void> {
    if (earliest === null || earliest <= 1) return;
    try {
      const d = await get<EventPage>(query(`to=${earliest - 1}&limit=${PAGE}`), {
        signal: deps.signal,
      });
      const events = d?.events ?? [];
      if (!events.length) return;
      const before = table.el.scrollHeight;
      const first = table.body.children[0] ?? null;
      for (const e of events) {
        const tr = table.addRow(rowCells(e));
        table.body.insertBefore(tr, first);
      }
      // 往上插会把已有内容顶下去,补回同样多的滚动量,视野里的那一行才不动。
      table.el.scrollTop += table.el.scrollHeight - before;
      earliest = events[0].cursor;
      noteSources(events);
    } catch (err) {
      failed(err);
    }
  }

  const view: EventsView = {
    el,
    async init() {
      try {
        const d = await get<EventPage>(query(`limit=${PAGE}`), { signal: deps.signal });
        const events = d?.events ?? [];
        inited = true;
        table.clear(events.length ? undefined : S.noEvents);
        for (const e of events) table.addRow(rowCells(e));
        earliest = events.length ? events[0].cursor : null;
        latest = Math.max(d?.latest ?? 0, events.length ? events[events.length - 1].cursor : 0);
        noteSources(events);
        deps.onNet(true);
        toEnd();
      } catch (err) {
        failed(err);
      }
    },
    async poll() {
      if (!inited) return;
      try {
        const d = await get<EventPage>(query(`from=${latest + 1}`), { signal: deps.signal });
        const events = d?.events ?? [];
        if (events.length) {
          const wasStuck = stuck();
          for (const e of events) table.addRow(rowCells(e));
          if (earliest === null) earliest = events[0].cursor;
          noteSources(events);
          if (wasStuck) toEnd();
        }
        latest = Math.max(d?.latest ?? 0, latest);
      } catch (err) {
        failed(err);
      }
    },
    setPolling(on) {
      poller?.dispose();
      poller = null;
      if (on) poller = deps.lifecycle.interval(() => void view.poll(), EVENT_POLL_MS);
    },
  };
  return view;
}
