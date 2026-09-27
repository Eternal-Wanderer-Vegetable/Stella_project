/**
 * 面板 `world` —— 存档与玩法。
 *
 * 改动写在 server.properties,而服务器只在**启动时**读一次:停机时改什么都行
 * (下次启动生效),跑着的时候只有**难度**和**默认游戏模式**能当场改(走控制台
 * 指令,只对本轮有效,不落盘)。所以这一屏的禁用规则不是装饰,它就是那条时机规则
 * 的界面形态。
 *
 * 世界生成那几项还多一条时机:它们只在存档**第一次生成**时被读到,对着已有的
 * 世界改毫无作用。所以它们不在"应用"那条路上,而是「开新存档」这个动作的参数。
 *
 * 存档列表按**最近活跃**分组,默认只展开最近的那一组——服务器目录里躺着几十份
 * 存档时,一条长表格里真正要找的永远是最上面那几份。两种版式:网格(一眼扫过
 * 所有存档)与详情(每份摊开 level.dat 自述)。
 */

import type {
  ConsolePanelContext,
  ConsolePanel,
} from '../../../web/shared/client-panel.ts';
import {
  errText,
  msgLine,
  type MinecraftWorldInfo,
  type MinecraftWorldState,
} from './client.ts';

const DESC =
  '换存档、开新世界、调难度与游戏模式。这些写在 server.properties 里,'
  + '而服务器只在启动时读一次:停机时改什么都行(下次启动生效),'
  + '跑着的时候只有难度和默认游戏模式能当场改(走控制台指令,只对本轮有效)。';

const GAMEMODES = [
  { value: 'survival', label: '生存' },
  { value: 'creative', label: '创造' },
  { value: 'adventure', label: '冒险' },
  { value: 'spectator', label: '旁观' },
] as const;

const DIFFICULTIES = [
  { value: 'peaceful', label: '和平' },
  { value: 'easy', label: '简单' },
  { value: 'normal', label: '普通' },
  { value: 'hard', label: '困难' },
] as const;

/** level.dat 里的 GameType / Difficulty 是数字 */
const GAMEMODE_ZH = ['生存', '创造', '冒险', '旁观'];
const DIFFICULTY_ZH = ['和平', '简单', '普通', '困难'];
const GENERATOR_ZH: Record<string, string> = {
  flat: '超平坦',
  amplified: '放大化',
  large_biomes: '大型生物群系',
  normal: '默认',
  overworld: '默认',
};

const DAY_MS = 86_400_000;

/** 分组:按最近活跃分档,顺序即从近到远。 */
const GROUPS: ReadonlyArray<{ id: string; label: string; within: number }> = [
  { id: 'today', label: '今天', within: 1 },
  { id: 'week', label: '最近 7 天', within: 7 },
  { id: 'month', label: '最近 30 天', within: 30 },
  { id: 'older', label: '更早', within: Infinity },
];

/** 本地日历日的差值:23:59 与次日 00:01 是两天,差 2 分钟也算 */
function daysAgo(iso: string, now: Date): number {
  const then = new Date(iso);
  const midnight = (d: Date): number =>
    new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  return Math.floor((midnight(now) - midnight(then)) / DAY_MS);
}

function groupOf(world: MinecraftWorldInfo, now: Date): string {
  if (!world.modified) return 'pending';
  const days = daysAgo(world.modified, now);
  return GROUPS.find((g) => days < g.within)!.id;
}

function fmtBytes(n: number): string {
  if (n <= 0) return '—';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let v = n;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return `${v < 10 && i > 0 ? v.toFixed(1) : Math.round(v)} ${units[i]}`;
}

function fmtWhen(iso: string | null, now: Date): string {
  if (!iso) return '还没生成';
  const days = daysAgo(iso, now);
  const clock = iso.slice(11, 16);
  if (days === 0) return `今天 ${clock}`;
  if (days === 1) return `昨天 ${clock}`;
  if (days < 30) return `${days} 天前`;
  return iso.slice(0, 10);
}

/** 存档自述里能读出多少写多少;一项都读不出来就不摆这一行 */
function infoRows(w: MinecraftWorldInfo, now: Date): Array<{ k: string; v: string }> {
  const rows: Array<{ k: string; v: string }> = [
    { k: '最后活跃', v: `${fmtWhen(w.modified, now)}${w.modified ? `(${w.modified.slice(0, 16).replace('T', ' ')})` : ''}` },
    { k: '占盘', v: fmtBytes(w.sizeBytes) },
  ];
  const info = w.info;
  if (info) {
    if (info.generator) rows.push({ k: '世界类型', v: GENERATOR_ZH[info.generator] ?? info.generator });
    if (info.seed) rows.push({ k: '种子', v: info.seed });
    if (info.gameType !== null) rows.push({ k: '游戏模式', v: GAMEMODE_ZH[info.gameType] ?? String(info.gameType) });
    if (info.difficulty !== null) {
      rows.push({
        k: '难度',
        v: `${DIFFICULTY_ZH[info.difficulty] ?? info.difficulty}${info.hardcore ? ' · 极限' : ''}`,
      });
    }
    if (info.version) rows.push({ k: '版本', v: info.version });
    if (info.dayTime !== null) rows.push({ k: '世界天数', v: `第 ${Math.floor(info.dayTime / 24_000) + 1} 天` });
    if (info.levelName && info.levelName !== w.name) rows.push({ k: '存档自述名', v: info.levelName });
  }
  if (w.dimensions.length) {
    rows.push({ k: '已生成维度', v: w.dimensions.map((d) => (d === 'nether' ? '下界' : '末地')).join('、') });
  }
  return rows;
}

export const worldPanel: ConsolePanel = {
  mount(ctx: ConsolePanelContext) {
    const { ui, root } = ctx;

    // -----------------------------------------------------------------------
    // 卡一:存档
    // -----------------------------------------------------------------------
    const card = ui.sheet({ title: '存档与玩法', en: 'world & rules', desc: DESC });
    const s = card.body;
    root.appendChild(card.el);

    const msg = msgLine(ctx);
    s.appendChild(msg.el);

    const stateBox = ui.h('div');
    s.append(ui.section('当前世界'), stateBox);

    const layout = ui.segmented(
      [{ value: 'grid', label: '网格' }, { value: 'detail', label: '详情' }],
      {
        value: ctx.memo.get<string>('layout', 'grid'),
        size: 'sm',
        onSelect: (v) => { ctx.memo.set('layout', v); render(cur); },
      },
    );
    const listBar = ui.rowbar();
    listBar.append(ui.h('span', 'grow'), layout.el);
    const listBox = ui.h('div');
    s.append(ui.section('存档', '按最近活跃分组,默认只展开最近的一组'), listBar, listBox);

    // ---- 玩法 ----
    const gmSel = ui.select({ options: GAMEMODES });
    const diffSel = ui.select({ options: DIFFICULTIES });
    const hardcoreIn = ui.checkbox('极限模式');
    const pvpIn = ui.checkbox('PVP');
    const monstersIn = ui.checkbox('刷怪');
    const btnApply = ui.button('应用', { size: 'sm', variant: 'primary' });
    const ruleForm = ui.h('div', 'mc-form');
    ruleForm.append(ui.field('游戏模式', gmSel), ui.field('难度', diffSel));
    const ruleBar = ui.actions();
    ruleBar.append(hardcoreIn.el, pvpIn.el, monstersIn.el, ui.h('span', 'grow'), btnApply);
    s.append(ui.section('玩法'), ruleForm, ruleBar);

    // ---- 世界规则(收起来的那些) ----
    const netherIn = ui.checkbox('允许下界');
    const spawnProtIn = ui.input({ type: 'number', value: '16' });
    const viewIn = ui.input({ type: 'number', value: '10' });
    const simIn = ui.input({ type: 'number', value: '10' });
    const borderIn = ui.input({ type: 'number', value: '29999984' });
    const rulesForm = ui.h('div', 'mc-form');
    rulesForm.append(
      ui.field('出生点保护(格)', spawnProtIn),
      ui.field('视距(区块)', viewIn),
      ui.field('模拟距离(区块)', simIn),
      ui.field('世界边界(格)', borderIn),
    );
    const rulesBar = ui.actions();
    rulesBar.append(netherIn.el, ui.h('span', 'grow'));
    const moreRules = fold(ctx, '更多世界规则', '这几项都要停机改,下次启动生效。');
    moreRules.body.append(rulesForm, rulesBar);
    s.append(moreRules.el);

    // -----------------------------------------------------------------------
    // 卡二:开新存档
    // -----------------------------------------------------------------------
    const newCard = ui.sheet({
      title: '开新存档',
      en: 'new world',
      desc: '这里的生成参数只在世界第一次生成时被读到;开出来之后再改不会重塑地形。'
        + '服务器停机时登记,下次启动按它生成。',
    });
    const n = newCard.body;
    root.appendChild(newCard.el);

    const newName = ui.input({ placeholder: '新存档名' });
    const newSeed = ui.input({ placeholder: '留空 = 随机' });
    const typeSel = ui.select();
    const structIn = ui.checkbox('生成村庄、神殿这些结构', { checked: true });
    const typeNote = ui.h('div', 'pagedesc');
    const newForm = ui.h('div', 'mc-form');
    newForm.append(ui.field('存档名', newName), ui.field('种子', newSeed), ui.field('世界类型', typeSel));

    const presetSel = ui.select();
    const genText = ui.textarea({ placeholder: '留空 = 该世界类型的默认生成', cls: 'mono' });
    const presetNote = ui.h('div', 'pagedesc');
    const moreGen = fold(ctx, '更多世界生成', '超平坦的层配方、单一群系的群系名都写在这份 JSON 里。');
    const presetForm = ui.h('div', 'mc-form');
    presetForm.append(ui.field('超平坦预设', presetSel));
    moreGen.body.append(presetForm, presetNote, ui.field('生成器细则(generator-settings)', genText));

    const btnCreate = ui.button('登记新存档', { size: 'sm', variant: 'primary' });
    const newBar = ui.actions();
    newBar.append(structIn.el, ui.h('span', 'grow'), btnCreate);
    n.append(newForm, typeNote, moreGen.el, newBar);

    // -----------------------------------------------------------------------

    /** 服务端那份权威状态。应用玩法时要看它决定提交哪几项。 */
    let cur: MinecraftWorldState | null = null;
    /** 展开着的分组;首次渲染时钉在最近的那一组上,之后跟着用户开合走 */
    let opened: Set<string> | null = null;

    function fillPresets(st: MinecraftWorldState): void {
      if (presetSel.options.length) return;
      const custom = ui.h('option', null, '自定义');
      custom.value = '';
      presetSel.appendChild(custom);
      for (const p of st.flatPresets) {
        const op = ui.h('option', null, p.label);
        op.value = p.id;
        presetSel.appendChild(op);
      }
      presetSel.addEventListener('change', () => {
        const hit = st.flatPresets.find((p) => p.id === presetSel.value);
        presetNote.textContent = hit ? hit.note : '';
        if (!hit) return;
        // 选了平坦预设就是想开一个平坦世界,类型跟着走,免得配方写好了却是默认地形
        genText.value = hit.json;
        typeSel.value = 'minecraft:flat';
        typeSel.dispatchEvent(new Event('change'));
      }, { signal: ctx.signal });
    }

    function fillLevelTypes(st: MinecraftWorldState): void {
      if (typeSel.options.length) return;
      for (const t of st.levelTypes) {
        const op = ui.h('option', null, t.label);
        op.value = t.value;
        typeSel.appendChild(op);
      }
      const note = (): void => {
        typeNote.textContent = st.levelTypes.find((t) => t.value === typeSel.value)?.note ?? '';
      };
      typeSel.addEventListener('change', note, { signal: ctx.signal });
      note();
    }

    /** 一份存档一张卡片。两种版式的差别只在卡片里摆什么。 */
    function worldCard(w: MinecraftWorldInfo, st: MinecraftWorldState, now: Date, detail: boolean): HTMLElement {
      const isCur = w.name === st.settings.levelName;
      const el = ui.h('div', `mc-world${isCur ? ' cur' : ''}`);
      const head = ui.h('div', 'mc-worldhead');
      head.append(ui.h('span', 'mc-worldname', w.name));
      if (isCur) head.append(ui.pill('当前', 'on'));
      if (!w.generated) head.append(ui.pill('还没生成', 'plain'));
      el.append(head);

      if (detail) {
        el.append(ui.kv(infoRows(w, now)));
      } else {
        const meta = ui.h('div', 'mc-worldmeta');
        meta.append(ui.h('span', null, fmtWhen(w.modified, now)));
        if (w.sizeBytes > 0) meta.append(ui.h('span', null, fmtBytes(w.sizeBytes)));
        if (w.info?.version) meta.append(ui.h('span', null, w.info.version));
        if (w.info?.generator) {
          meta.append(ui.h('span', null, GENERATOR_ZH[w.info.generator] ?? w.info.generator));
        }
        el.append(meta);
      }

      const acts = ui.h('div', 'mc-worldacts');
      const pick = ui.button('换到这个存档', { size: 'sm' });
      pick.disabled = isCur || !st.configured || st.live;
      pick.addEventListener('click', () => {
        void act(() => ctx.invoke<MinecraftWorldState>('select', [w.name]), '切换中…');
      }, { signal: ctx.signal });
      acts.append(pick);
      el.append(acts);
      return el;
    }

    function renderWorlds(st: MinecraftWorldState): void {
      const now = new Date();
      const detail = layout.value === 'detail';
      const buckets = new Map<string, MinecraftWorldInfo[]>();
      for (const w of st.worlds) {
        const id = groupOf(w, now);
        (buckets.get(id) ?? buckets.set(id, []).get(id)!).push(w);
      }
      const order = [...GROUPS.map((g) => ({ id: g.id, label: g.label })), { id: 'pending', label: '还没生成' }]
        .filter((g) => buckets.has(g.id));
      if (opened === null) opened = new Set(order.length ? [order[0].id] : []);

      listBox.replaceChildren();
      if (!order.length) {
        listBox.append(ui.placeholder('还没有存档(下次启动会按当前存档名生成一个)'));
        return;
      }
      for (const g of order) {
        const items = buckets.get(g.id)!;
        const box = ui.h('details', 'mc-group');
        box.open = opened.has(g.id);
        const sum = ui.h('summary');
        sum.append(ui.h('span', null, g.label), ui.h('span', 'mc-groupcount', `${items.length} 份`));
        box.append(sum);
        const grid = ui.h('div', `mc-worlds ${detail ? 'detail' : 'grid'}`);
        for (const w of items) grid.append(worldCard(w, st, now, detail));
        box.append(grid);
        box.addEventListener('toggle', () => {
          if (box.open) opened!.add(g.id);
          else opened!.delete(g.id);
        }, { signal: ctx.signal });
        listBox.append(box);
      }
    }

    function render(st: MinecraftWorldState | null): void {
      if (ctx.signal.aborted) return;
      cur = st;
      if (!st) {
        msg.say('存档设置不可用', true);
        stateBox.replaceChildren(ui.placeholder('读不到服务器目录里的 server.properties'));
        listBox.replaceChildren(ui.placeholder('—'));
        return;
      }
      const stopped = !st.live;
      fillLevelTypes(st);
      fillPresets(st);

      const genZh = st.levelTypes.find((t) => t.value === st.settings.levelType)?.label ?? st.settings.levelType;
      stateBox.replaceChildren(ui.kv([
        { k: '当前存档', v: st.settings.levelName },
        { k: '种子', v: st.settings.levelSeed || '(随机)' },
        { k: '世界类型', v: `${genZh}${st.settings.generatorSettings ? ' · 带生成器细则' : ''}` },
        { k: '服务器', v: ui.pill(
          st.live ? (st.hosted ? '运行中(本 World 托管)' : '运行中(外部)') : '已停机',
          st.live ? 'on' : 'plain',
        ) },
        { k: '服务器目录', v: st.serverDir || '(未配置)' },
      ]));

      renderWorlds(st);

      gmSel.value = st.settings.gamemode;
      diffSel.value = st.settings.difficulty;
      hardcoreIn.setChecked(st.settings.hardcore);
      pvpIn.setChecked(st.settings.pvp);
      monstersIn.setChecked(st.settings.spawnMonsters);
      netherIn.setChecked(st.settings.allowNether);
      spawnProtIn.value = String(st.settings.spawnProtection);
      viewIn.value = String(st.settings.viewDistance);
      simIn.value = String(st.settings.simulationDistance);
      borderIn.value = String(st.settings.maxWorldSize);

      const off = !st.configured;
      newName.disabled = newSeed.disabled = typeSel.disabled = presetSel.disabled = off || !stopped;
      genText.disabled = structIn.input.disabled = btnCreate.disabled = off || !stopped;
      hardcoreIn.input.disabled = pvpIn.input.disabled = monstersIn.input.disabled = off || !stopped;
      netherIn.input.disabled = spawnProtIn.disabled = viewIn.disabled = off || !stopped;
      simIn.disabled = borderIn.disabled = off || !stopped;
      gmSel.disabled = diffSel.disabled = btnApply.disabled = off;
      msg.say(st.detail || (st.live ? '服务器跑着:只有难度和默认游戏模式能当场改' : ''));
    }

    const refresh = (): Promise<void> =>
      ctx.invoke<MinecraftWorldState>('state').then(render, () => render(null));

    /**
     * 一次动作:置灰两颗钮 → 调服务端 → 拿回来的新状态重画。
     *
     * **先解锁再重画。** `ui.disable` 恢复的是各自调用前的原值,而重画本身要按
     * 新状态重设这些钮的可用性——顺序反了的话,刚算出来的禁用规则会被恢复动作
     * 原样抹掉。
     */
    async function act(fn: () => Promise<MinecraftWorldState>, working: string): Promise<void> {
      msg.say(working);
      const lock = ui.disable(btnCreate, btnApply);
      let next: MinecraftWorldState | null = null;
      try {
        next = await fn();
      } catch (err) {
        if (!ctx.signal.aborted) msg.say(`操作失败: ${errText(err)}`, true);
      } finally {
        lock.dispose();
      }
      if (next) render(next);
    }

    btnCreate.addEventListener('click', () => {
      void act(() => ctx.invoke<MinecraftWorldState>('create', [newName.value, {
        seed: newSeed.value,
        levelType: typeSel.value,
        generatorSettings: genText.value,
        generateStructures: structIn.checked,
      }]), '登记中…');
    }, { signal: ctx.signal });

    btnApply.addEventListener('click', () => {
      // 运行期间仅提交支持热更新的字段。
      const patch = cur?.live
        ? { gamemode: gmSel.value, difficulty: diffSel.value }
        : {
          gamemode: gmSel.value,
          difficulty: diffSel.value,
          hardcore: hardcoreIn.checked,
          pvp: pvpIn.checked,
          spawnMonsters: monstersIn.checked,
          allowNether: netherIn.checked,
          spawnProtection: Number(spawnProtIn.value),
          viewDistance: Number(viewIn.value),
          simulationDistance: Number(simIn.value),
          maxWorldSize: Number(borderIn.value),
        };
      void act(() => ctx.invoke<MinecraftWorldState>('apply', [patch]), '应用中…');
    }, { signal: ctx.signal });

    void refresh();
  },
};

/**
 * 卡片内的折叠块。`ui.foldSheet` 折的是整张卡,而这里要的是"卡里那几项平时收着"
 * ——把次要参数摊在主表单里,主表单就没有主次可言了。
 */
function fold(ctx: ConsolePanelContext, title: string, note: string): { el: HTMLElement; body: HTMLElement } {
  const el = ctx.ui.h('details', 'mc-fold');
  const sum = ctx.ui.h('summary', null, title);
  const body = ctx.ui.h('div', 'mc-foldbody');
  if (note) body.append(ctx.ui.h('div', 'pagedesc', note));
  el.append(sum, body);
  return { el, body };
}
