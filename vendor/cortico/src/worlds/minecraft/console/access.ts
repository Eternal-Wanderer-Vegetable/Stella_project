/**
 * 面板 `access` —— 权限与作弊。
 *
 * 专用服务器没有单人存档里那个「开作弊」勾选框。同一件事在这里是两半:**谁在
 * ops.json 里**(能不能下 /tp、/gamemode、/spectate 这类指令),以及
 * `op-permission-level`(op 拿到第几级,4 才够全部指令)。所以这一屏的主体是一份
 * 名单,而不是一个开关。
 *
 * 吃这份名单的是 **bot 与人在游戏里打的命令**:mc_escape 的 /tp、把玩家传送到她
 * 旁边、摄像机附身——服务器由 World 托管时它们走控制台 stdin(天生 4 级,不看名单),
 * 外部起的服务器上就只剩这条退路。
 *
 * 时机与「存档与玩法」同一条规则,只是这里有两份都只在启动时读的文件:停机时改
 * 文件;跑着且是托管的,名单能走控制台 op/deop 当场生效(服务端自己写回文件),
 * server.properties 那几项一概要停机;外部起的跑着时什么都改不了。
 */

import type {
  ConsolePanelContext,
  ConsolePanel,
} from '../../../web/shared/client-panel.ts';
import {
  errText,
  msgLine,
  type MinecraftAccessMember,
  type MinecraftAccessState,
} from './client.ts';

const DESC =
  '专用服没有「开作弊」那个勾选框:能不能下 /tp、/gamemode 全看名字在不在管理员'
  + '名单(ops.json)里。她的 mc_escape、把你传送到她旁边、摄像机附身都吃这份名单'
  + '——服务器由本 World 托管时它们走控制台,不吃;外部起的服务器上就只剩这条路。';

/** 三个有名有姓的身份 + 名单里别的名字 */
const ROLE_ZH: Record<MinecraftAccessMember['role'], { label: string; note: string }> = {
  bot: { label: '她', note: '游戏内账号(worlds.minecraft.username)' },
  camera: { label: '摄像机', note: '观察者客户端账号' },
  player: { label: '玩家', note: '你自己进服那份客户端' },
  other: { label: '其他', note: '名单里已有的名字' },
};

const LEVELS = [
  { value: '1', label: '1 级 · 绕过出生点保护' },
  { value: '2', label: '2 级 · 大部分单人作弊指令' },
  { value: '3', label: '3 级 · 加上封禁踢人' },
  { value: '4', label: '4 级 · 全部(含 /stop)' },
];

export const accessPanel: ConsolePanel = {
  mount(ctx: ConsolePanelContext) {
    const { ui, root } = ctx;

    // -----------------------------------------------------------------------
    // 卡一:管理员名单
    // -----------------------------------------------------------------------
    const card = ui.sheet({ title: '权限与作弊', en: 'cheats & permissions', desc: DESC });
    const s = card.body;
    root.appendChild(card.el);

    const msg = msgLine(ctx);
    s.appendChild(msg.el);

    const stateBox = ui.h('div');
    s.append(ui.section('当前'), stateBox);

    const list = ui.table({ head: ['名字', '身份', '作弊权限', ''] });
    s.append(ui.section('管理员名单', 'ops.json;服务器只在启动时读它'), list.el);

    const addName = ui.input({ placeholder: '游戏名' });
    const btnAdd = ui.button('授权', { size: 'sm' });
    const addBar = ui.actions();
    addBar.append(ui.field('另外授权一个名字', addName), ui.h('span', 'grow'), btnAdd);
    s.append(addBar);

    // -----------------------------------------------------------------------
    // 卡二:服务器权限项(server.properties)
    // -----------------------------------------------------------------------
    const propCard = ui.sheet({
      title: '服务器权限项',
      en: 'permission properties',
      desc: '写在 server.properties 里,服务器只在启动时读一次——这几项都要停机改,下次启动生效。',
    });
    const p = propCard.body;
    root.appendChild(propCard.el);

    const levelSel = ui.select({ options: LEVELS });
    const cmdBlockIn = ui.checkbox('命令方块可用');
    const flightIn = ui.checkbox('允许飞行(不踢)');
    const onlineIn = ui.checkbox('正版验证');
    const whiteIn = ui.checkbox('白名单');
    const btnApply = ui.button('应用', { size: 'sm', variant: 'primary' });
    const propForm = ui.h('div', 'mc-form');
    propForm.append(ui.field('op 权限等级', levelSel));
    const propBar = ui.actions();
    propBar.append(cmdBlockIn.el, flightIn.el, onlineIn.el, whiteIn.el, ui.h('span', 'grow'), btnApply);
    const propNote = ui.h('div', 'pagedesc',
      '正版验证开着时她、摄像机、玩家这三个离线账号都进不来;白名单开着则名单外的进不来。');
    p.append(propForm, propBar, propNote);

    // -----------------------------------------------------------------------

    let cur: MinecraftAccessState | null = null;

    function memberRow(m: MinecraftAccessMember, st: MinecraftAccessState): void {
      const role = ROLE_ZH[m.role];
      const who = ui.h('span', null, role.label);
      who.title = role.note;
      const btn = ui.button(m.op ? '收回' : '授权', { size: 'sm', variant: m.op ? 'plain' : 'primary' });
      btn.disabled = !st.configured || (st.live && !st.hosted);
      btn.addEventListener('click', () => {
        void act(() => ctx.invoke<MinecraftAccessState>('setOp', [m.name, !m.op]), m.op ? '收回中…' : '授权中…');
      }, { signal: ctx.signal });
      list.addRow([
        { text: m.name, cls: 'mono' },
        who,
        m.op ? ui.pill(`有 · ${m.level} 级`, 'on') : ui.pill('没有', 'off'),
        btn,
      ]);
    }

    function render(st: MinecraftAccessState | null): void {
      if (ctx.signal.aborted) return;
      cur = st;
      if (!st) {
        msg.say('权限设置不可用', true);
        stateBox.replaceChildren(ui.placeholder('读不到服务器目录里的 ops.json'));
        list.clear('—');
        return;
      }
      stateBox.replaceChildren(ui.kv([
        {
          k: '服务器',
          v: ui.pill(
            st.live ? (st.hosted ? '运行中(本 World 托管)' : '运行中(外部)') : '已停机',
            st.live ? 'on' : 'plain',
          ),
        },
        {
          k: '自动授权',
          v: st.autoOp
            ? ui.pill('开 · 每次启动前补齐名单', 'on')
            : ui.pill('关 · 只按名单现状来', 'off'),
        },
        { k: '服务器目录', v: st.serverDir || '(未配置)' },
      ]));

      list.clear();
      if (!st.members.length) list.clear('名单是空的');
      else for (const m of st.members) memberRow(m, st);

      levelSel.value = String(st.settings.opPermissionLevel);
      cmdBlockIn.setChecked(st.settings.enableCommandBlock);
      flightIn.setChecked(st.settings.allowFlight);
      onlineIn.setChecked(st.settings.onlineMode);
      whiteIn.setChecked(st.settings.whiteList);

      const stopped = !st.live;
      const off = !st.configured;
      addName.disabled = btnAdd.disabled = off || (st.live && !st.hosted);
      levelSel.disabled = cmdBlockIn.input.disabled = off || !stopped;
      flightIn.input.disabled = onlineIn.input.disabled = off || !stopped;
      whiteIn.input.disabled = btnApply.disabled = off || !stopped;

      msg.say(st.detail || (st.live && !st.hosted
        ? '服务器是外部起的,没有控制台可用:名单与这几项都要先停机才改得了'
        : st.live
          ? '服务器跑着:名单走控制台当场生效,下面那几项要先停机'
          : ''));
    }

    const refresh = (): Promise<void> =>
      ctx.invoke<MinecraftAccessState>('state').then(render, () => render(null));

    /** 一次动作:置灰两颗钮 → 调服务端 → 拿回来的新状态重画(先解锁再重画)。 */
    async function act(fn: () => Promise<MinecraftAccessState>, working: string): Promise<void> {
      msg.say(working);
      const lock = ui.disable(btnAdd, btnApply);
      let next: MinecraftAccessState | null = null;
      try {
        next = await fn();
      } catch (err) {
        if (!ctx.signal.aborted) msg.say(`操作失败: ${errText(err)}`, true);
      } finally {
        lock.dispose();
      }
      if (next) render(next);
    }

    btnAdd.addEventListener('click', () => {
      const name = addName.value.trim();
      if (!name) {
        msg.say('先写个游戏名', true);
        return;
      }
      void act(async () => {
        const next = await ctx.invoke<MinecraftAccessState>('setOp', [name, true]);
        addName.value = '';
        return next;
      }, '授权中…');
    }, { signal: ctx.signal });

    btnApply.addEventListener('click', () => {
      if (cur?.live) {
        msg.say('这几项服务器只在启动时读,要先把它停下来', true);
        return;
      }
      void act(() => ctx.invoke<MinecraftAccessState>('apply', [{
        opPermissionLevel: Number(levelSel.value),
        enableCommandBlock: cmdBlockIn.checked,
        allowFlight: flightIn.checked,
        onlineMode: onlineIn.checked,
        whiteList: whiteIn.checked,
      }]), '应用中…');
    }, { signal: ctx.signal });

    void refresh();
  },
};
