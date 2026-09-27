/**
 * World 日志面板，按泳道筛选增量记录。
 * 日志滚动与裁剪由 ui.log 管理，轮询随 ctx.interval 的面板生命周期结束。
 * WorldConsoleDecl 仅提供 invoke；按序号每两秒拉取新增条目。
 */

import type {
  ConsolePanelContext,
  ConsolePanel,
} from '../../../web/shared/client-panel.ts';
import type { MinecraftLogEntry } from './client.ts';

const DESC =
  '一场试玩里下过的每一道令、投递出去的每一句、每一步的结局与耗时。'
  + '同一份进运行日志(data/runs/<run>/log.jsonl,区域 worlds.minecraft.<泳道>,事后 logq 查),这里只留最近 2000 条。';

/**
 * 泳道表。与 `src/worlds/minecraft/log.ts` 的 `LANE_ZH` 同一份词表——那边是 Node
 * 模块(读写文件),浏览器 bundle 不能 import 它,所以这里抄一份。
 */
const LANES: ReadonlyArray<readonly [string, string]> = [
  ['tool', '工具'], ['event', '投递'], ['task', '任务'], ['skill', '技能'], ['craft', '合成'],
  ['inventory', '物品'], ['path', '寻路'], ['body', '身体'], ['reflex', '反射'], ['combat', '战斗'],
  ['link', '连接'], ['world', '世界'],
];

const LANE_ZH: Record<string, string> = Object.fromEntries(LANES);

/** 内存里留多少条(与落盘那份无关;那边是完整的)。 */
const KEEP = 2000;
const POLL_MS = 2000;

export const logPanel: ConsolePanel = {
  mount(ctx: ConsolePanelContext) {
    const { ui, root } = ctx;
    const card = ui.foldSheet('log', { title: 'World 日志', en: 'module log', desc: DESC });
    const s = card.body;
    root.appendChild(card.el);

    /** 关掉的泳道。默认一个都不关。 */
    const off = new Set<string>();
    const bar = ui.rowbar();
    for (const [lane, label] of LANES) {
      const box = ui.checkbox(label, {
        checked: true,
        title: `不看${label}这一类记录时把它取消勾选`,
        onChange: (on) => {
          if (on) off.delete(lane); else off.add(lane);
          redraw();
        },
      });
      bar.appendChild(box.el);
    }
    const btnEnd = ui.button('回到底部', { size: 'sm' });
    bar.append(ui.h('span', 'grow'), btnEnd);
    s.appendChild(bar);

    const view = ui.log({ max: KEEP, maxHeight: '320px', empty: '(等待日志…)' });
    s.appendChild(view.el);
    btnEnd.addEventListener('click', () => view.scrollToEnd(), { signal: ctx.signal });

    /** 收到过的条目(未过滤)。切泳道时按它整份重铺。 */
    let entries: MinecraftLogEntry[] = [];
    let lastSeq = 0;

    const lineOf = (e: MinecraftLogEntry): string => {
      const t = ctx.ui.fmt.clock(e.ts);
      const task = e.taskId ? ` #${e.taskId}` : '';
      const dur = e.durMs === undefined ? '' : ` (${e.durMs}ms)`;
      return `[${t}] ${LANE_ZH[e.lane] ?? e.lane}${task} | ${e.msg}${dur}`;
    };

    const shownCount = (): number => entries.filter((e) => !off.has(e.lane)).length;

    const noteCount = (): void => {
      card.note.textContent = `${shownCount()} 条${off.size ? `(关了 ${off.size} 条泳道)` : ''}`;
    };

    /** 切泳道:整份重铺(这是唯一会重画已有行的路径,日志本身只往末尾长)。 */
    const redraw = (): void => {
      view.clear();
      for (const e of entries) if (!off.has(e.lane)) view.append(lineOf(e));
      noteCount();
      view.scrollToEnd();
    };

    let polling = false;
    const poll = (): void => {
      if (polling) return;
      polling = true;
      void ctx.invoke<{ entries?: MinecraftLogEntry[] }>('entries', [lastSeq]).then(
        (out) => {
          polling = false;
          if (ctx.signal.aborted) return;
          const fresh = out?.entries ?? [];
          if (fresh.length === 0) return;
          for (const e of fresh) lastSeq = Math.max(lastSeq, e.seq);
          entries = entries.concat(fresh).slice(-KEEP);
          for (const e of fresh) if (!off.has(e.lane)) view.append(lineOf(e));
          noteCount();
        },
        () => { polling = false; /* 下一拍再试 */ },
      );
    };

    noteCount();
    ctx.interval(poll, POLL_MS);
    poll();
  },
};
