/**
 * B 站直播间 World 的浏览器扩展。
 *
 * `log` 保留直播间入站诊断。Overlay 编辑器由 World 的回环服务独立承载，
 * 控制台只暴露入口链接。
 *
 * 轮询 state,按 total 差值追加事件。服务端响应类型在浏览器端声明,避免导入 Node 模块。
 */

import type { ConsoleClientBundle, ConsolePanelContext, ConsolePanel } from '../../../web/shared/client-panel.ts';

export function errText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

// ---------------------------------------------------------------------------
// 服务端 `BilibiliWorld.console().invoke('log', 'state')` 的返回形状
// ---------------------------------------------------------------------------

interface BilibiliLiveStatus {
  /** `stopped` / `connecting` / `connected` / `retrying` */
  phase: string;
  /** 配置里填的房间号(可能是短号) */
  roomId: number;
  /** 换算出的真实房间号;还没握手完就是 null */
  realRoomId: number | null;
  title: string | null;
  living: boolean;
  /** 登录凭证对应的自己的 uid;匿名接入时为 0 */
  selfUid: number;
  lastError: string | null;
}

/** 待投递的观众统计;计数项累加,其余字段保留最新值。 */
interface BilibiliAggregate {
  enter: number;
  like: number;
  freeGift: number;
  watched: number | null;
  online: number | null;
  popularity: number | null;
  fans: number | null;
  likeTotal: number | null;
}

interface BilibiliLogState {
  status: BilibiliLiveStatus | null;
  /** 最近一窗弹幕均缺少有效 uid。 */
  desensitized: boolean;
  aggregate: BilibiliAggregate;
  /** 最近事件的文本，按时间倒序排列。 */
  recent: string[];
  /** 记过的总条数(含已被上限挤掉的) */
  total: number;
  /** cmd → 条数,按条数降序;没进白名单也没进黑名单的 cmd 也在里面 */
  counts: Array<[string, number]>;
  audienceAdmission: {
    trackedViewers: number;
    qualifiedViewers: number;
    crowd: { onlineRankCount: number | null; signalFresh: boolean; active: boolean };
    totals: { input: number; selected: number; dropped: number; limitedBatches: number };
    lastBatch: { limitingActive: boolean; input: number; selected: number } | null;
    persistenceError: string | null;
  };
}

const DESC = '直播间事件与各 cmd 计数。';

const PHASE_TEXT: Record<string, string> = {
  stopped: '未接入',
  connecting: '连接中',
  connected: '已接入',
  retrying: '重连中',
};

const POLL_MS = 2000;
/** 与服务端 RECENT_CAP 一致。 */
const KEEP = 200;

const logPanel: ConsolePanel = {
  mount(ctx: ConsolePanelContext) {
    const { ui, root } = ctx;
    const card = ui.sheet({ title: '直播间事件', en: 'bilibili live', desc: DESC });
    root.appendChild(card.el);

    const err = ui.msgline();
    const info = ui.h('div');
    const gauges = ui.statgrid();
    const view = ui.log({ max: KEEP, maxHeight: '320px', empty: '(等待直播间消息…)' });
    const counts = ui.table({ head: ['cmd', '条数'] });
    const btnEnd = ui.button('回到底部', { size: 'sm', onClick: () => view.scrollToEnd() });
    const bar = ui.rowbar();
    bar.append(ui.h('span', 'grow'), btnEnd);
    card.body.append(err, info, gauges, bar, view.el, counts.el);

    let shown = 0;

    const setError = (text: string | null): void => {
      err.textContent = text ?? '';
      err.className = text ? 'msgline bad' : 'msgline';
      err.hidden = !text;
    };
    setError(null);

    const drawInfo = (st: BilibiliLogState): void => {
      const s = st.status;
      const room = s?.realRoomId
        ? `${s.realRoomId}${s.roomId && s.roomId !== s.realRoomId ? `(短号 ${s.roomId})` : ''}`
        : s?.roomId
          ? `${s.roomId}(还没换算出真实房间号)`
          : '未配置';
      info.replaceChildren(ui.kv([
        { k: '接入', v: PHASE_TEXT[s?.phase ?? 'stopped'] ?? s?.phase ?? '未接入' },
        { k: '直播间', v: room },
        { k: '标题', v: s?.title || '—' },
        { k: '开播', v: ui.pill(s?.living ? '直播中' : '未开播', s?.living ? 'on' : 'off') },
        {
          k: '身份',
          v: st.desensitized
            ? ui.pill('近期弹幕缺少观众 uid', 'off')
            : ui.pill(s?.selfUid ? `已登录(uid ${s.selfUid})` : '待观察', s?.selfUid ? 'on' : 'plain'),
        },
        ...(s?.lastError ? [{ k: '最近错误', v: s.lastError }] : []),
      ]));
    };

    /** 服务端在生成投递正文后清零聚合计数。 */
    const drawGauges = (agg: BilibiliAggregate, admission: BilibiliLogState['audienceAdmission']): void => {
      const num = (v: number | null): string => (v === null ? '—' : ui.fmt.count(v));
      const last = admission.lastBatch;
      const limiter = admission.crowd.active
        ? last?.limitingActive
          ? `拥挤（上批保留 ${last.selected}/${last.input}）`
          : '拥挤'
        : last?.limitingActive
          ? `未限流（上批保留 ${last.selected}/${last.input}）`
          : '未限流';
      gauges.replaceChildren(
        ui.stat({ k: '待投递 · 进场', v: agg.enter, unit: '人' }),
        ui.stat({ k: '待投递 · 点赞', v: agg.like, unit: '次' }),
        ui.stat({ k: '待投递 · 免费礼物', v: agg.freeGift, unit: '个' }),
        ui.stat({ k: '高能榜', v: num(admission.crowd.onlineRankCount ?? agg.online), unit: '人' }),
        ui.stat({ k: '事件筛选', v: limiter }),
        ui.stat({ k: '重要观众', v: admission.qualifiedViewers, unit: '人' }),
        ui.stat({ k: '累计过滤', v: admission.totals.dropped, unit: '条' }),
        ui.stat({ k: '看过', v: num(agg.watched) }),
        ui.stat({ k: '人气', v: num(agg.popularity) }),
        ui.stat({ k: '粉丝', v: num(agg.fans) }),
      );
    };

    const drawCounts = (rows: BilibiliLogState['counts']): void => {
      counts.clear(rows.length ? undefined : '(还没收到任何 cmd)');
      for (const [cmd, n] of rows) counts.addRow([cmd, n]);
    };

    const appendNew = (st: BilibiliLogState): void => {
      const fresh = Math.min(st.total - shown, st.recent.length);
      if (fresh <= 0) {
        shown = st.total;
        return;
      }
      const chronological = [...st.recent].reverse();
      for (const line of chronological.slice(chronological.length - fresh)) view.append(line);
      shown = st.total;
    };

    let polling = false;
    const poll = (): void => {
      if (polling) return;
      polling = true;
      void ctx.invoke<BilibiliLogState>('state').then(
        (st) => {
          polling = false;
          if (ctx.signal.aborted) return;
          setError(null);
          drawInfo(st);
          drawGauges(st.aggregate, st.audienceAdmission);
          drawCounts(st.counts);
          appendNew(st);
        },
        (e: unknown) => {
          polling = false;
          if (ctx.signal.aborted) return;
          setError(`读取直播间状态失败: ${errText(e)}`);
        },
      );
    };

    ctx.interval(poll, POLL_MS);
    poll();
  },
};

const bundle: ConsoleClientBundle = {
  // 键是**局部** panel id,与服务端 `console().panels[].id` 一一对应。
  panels: {
    log: logPanel,
  },
};

export default bundle;
