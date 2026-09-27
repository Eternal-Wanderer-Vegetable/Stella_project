/**
 * 面板 `skin` —— 皮肤:她和玩家各穿哪一张。
 *
 * 离线服务器的玩家档案里没有材质这一格,所以这一屏做的事全在客户端一侧:选中的
 * PNG 按账号名铺进两份游戏目录,由 CustomSkinLoader 在渲染时读。两份客户端各渲染
 * 各的,所以两个账号的皮肤在两份目录里都要有——这也是"她的皮肤"与"玩家的皮肤"
 * 在这里是同一屏里的两块,而不是分在两个面板的原因。
 *
 * 一个角色一颗按钮,点开就是文件选择器:图从哪儿来是人当场挑的,World 这边不设需要
 * 人自己往里放文件的目录。
 *
 * 预览是把皮肤图上脸那 8x8 块(与帽子层)放大画进 canvas:选皮肤时要认的是哪张脸,
 * 不是那张摊平的材质图。整张材质点开抽屉看。
 */

import type {
  ConsolePanelContext,
  ConsolePanel,
} from '../../../web/shared/client-panel.ts';
import { toDisposable } from '../../../web/shared/client-panel.ts';
import {
  errText,
  msgLine,
  type MinecraftSkinRole,
  type MinecraftSkinState,
} from './client.ts';

const DESC =
  '离线服务器发不出皮肤材质,这里选的 PNG 由客户端侧的 CustomSkinLoader 按账号名'
  + '读——直播画面(摄像机窗口)与你自己那份客户端都看得到,别人的客户端看不到。'
  + '她和玩家各选各的。';

/** 两块的中文名与它们各自是谁 */
const ROLE_ZH: Record<MinecraftSkinRole['role'], { label: string; note: string }> = {
  bot: { label: '她', note: '游戏内账号(worlds.minecraft.username)' },
  player: { label: '玩家', note: '你自己进服那份客户端(worlds.minecraft.player.username)' },
};

const FACE_PX = 72;

export const skinPanel: ConsolePanel = {
  mount(ctx: ConsolePanelContext) {
    const { ui, root } = ctx;

    const card = ui.sheet({ title: '皮肤', en: 'skins', desc: DESC });
    const s = card.body;
    root.appendChild(card.el);

    const msg = msgLine(ctx);
    s.appendChild(msg.el);

    const roleBox = ui.h('div', 'mc-skins');
    s.append(
      ui.section('谁穿哪一张', '选中即铺进两份游戏目录;客户端正跑着的话,要它重进一次服务器才换得过来'),
      roleBox,
    );

    const premise = ui.h('div');
    s.append(ui.section('前提', '皮肤由客户端 mod 读;它不在游戏目录里就一切照旧'), premise);

    /** 一个角色一个隐藏的 file input:点的是卡里那颗钮 */
    const pickers = new Map<MinecraftSkinRole['role'], HTMLInputElement>();
    for (const role of ['bot', 'player'] as const) {
      const input = ui.h('input', 'mc-hidden');
      input.type = 'file';
      input.accept = 'image/png';
      input.addEventListener('change', () => {
        const file = input.files?.[0];
        input.value = '';
        if (!file) return;
        void act(async () => {
          const base64 = await toBase64(file);
          return ctx.invoke<MinecraftSkinState>('set', [role, base64]);
        }, `读取 ${file.name}…`);
      }, { signal: ctx.signal });
      pickers.set(role, input);
      s.appendChild(input);
    }

    // -----------------------------------------------------------------------
    // 材质:每换一张重取一次,面板活着期间同一张只取一次
    // -----------------------------------------------------------------------

    const urls = new Map<string, Promise<string>>();

    /** key 带上选中时刻:换了图就是另一个 key,不会拿旧的 ObjectURL 画新皮肤 */
    function skinUrl(role: MinecraftSkinRole['role'], key: string): Promise<string> {
      let pending = urls.get(key);
      if (!pending) {
        pending = ctx.invokeBinary('file', [role]).then((blob) => {
          const url = URL.createObjectURL(blob);
          ctx.own(toDisposable(() => URL.revokeObjectURL(url)));
          return url;
        });
        urls.set(key, pending);
      }
      return pending;
    }

    /** 脸那 8x8 块放大,帽子层叠上去;点一下进抽屉看整张材质 */
    function face(role: MinecraftSkinRole['role'], key: string): HTMLCanvasElement {
      const cv = ui.h('canvas', 'mc-face');
      cv.width = FACE_PX;
      cv.height = FACE_PX;
      void skinUrl(role, key).then((url) => {
        if (ctx.signal.aborted) return;
        const img = ui.h('img');
        img.addEventListener('load', () => {
          const cx = cv.getContext('2d');
          if (!cx) return;
          cx.imageSmoothingEnabled = false;
          cx.drawImage(img, 8, 8, 8, 8, 0, 0, FACE_PX, FACE_PX);
          cx.drawImage(img, 40, 8, 8, 8, 0, 0, FACE_PX, FACE_PX);
        }, { signal: ctx.signal });
        img.src = url;
        cv.addEventListener('click', () => {
          const big = ui.h('img', 'mc-shot-big');
          big.src = url;
          big.alt = `${ROLE_ZH[role].label}的皮肤`;
          ui.drawer(`${ROLE_ZH[role].label}的皮肤`, big);
        }, { signal: ctx.signal });
      }, () => { /* 取不到就留一块空 canvas */ });
      return cv;
    }

    // -----------------------------------------------------------------------

    let cur: MinecraftSkinState | null = null;

    function roleCard(role: MinecraftSkinRole, st: MinecraftSkinState): HTMLDivElement {
      const zh = ROLE_ZH[role.role];
      const el = ui.h('div', 'mc-skin');
      if (role.skin) el.classList.add('cur');

      const head = ui.h('div', 'mc-skinhead');
      head.appendChild(role.skin
        ? face(role.role, `${role.role}:${role.skin.at}`)
        : ui.h('div', 'mc-face mc-facenone'));

      const meta = ui.h('div');
      const title = ui.h('div', 'mc-worldname', zh.label);
      title.title = zh.note;
      meta.appendChild(title);
      meta.appendChild(ui.h('div', 'mc-worldmeta', role.username || '(没配账号名)'));
      if (role.skin) {
        const shared = st.dirs.camera === st.dirs.player;
        const laid = role.installed.camera && (shared || role.installed.player);
        const line = ui.h('div', 'mc-worldmeta');
        line.append(
          ui.h('span', null, `${role.skin.width}×${role.skin.height} · ${ui.fmt.bytes(role.skin.bytes)}`),
          ui.h('span', null, `选于 ${ui.fmt.clock(role.skin.at)}`),
          laid ? ui.pill('已铺好', 'on') : ui.pill('未铺到位', 'off'),
        );
        meta.appendChild(line);
      } else {
        meta.appendChild(ui.h('div', 'mc-worldmeta', '没选 · 原版随机皮肤'));
      }
      head.appendChild(meta);
      el.appendChild(head);

      const acts = ui.actions();
      const btnPick = ui.button(role.skin ? '换一张…' : '选一张…', {
        size: 'sm',
        variant: role.skin ? 'plain' : 'primary',
      });
      btnPick.addEventListener(
        'click',
        () => pickers.get(role.role)?.click(),
        { signal: ctx.signal },
      );
      acts.append(btnPick, ui.h('span', 'grow'));
      if (role.skin) {
        const btnClear = ui.button('撤回', { size: 'sm', variant: 'danger' });
        btnClear.addEventListener('click', () => {
          void (async () => {
            const ok = await ui.confirm({
              title: `撤回${zh.label}的皮肤?`,
              body: '那个账号回到原版随机皮肤。',
              danger: true,
            });
            if (!ok) return;
            await act(() => ctx.invoke<MinecraftSkinState>('clear', [role.role]), '撤回中…');
          })();
        }, { signal: ctx.signal });
        acts.appendChild(btnClear);
      }
      el.appendChild(acts);
      return el;
    }

    function renderPremise(st: MinecraftSkinState): void {
      const shared = st.dirs.camera === st.dirs.player;
      const modPill = (ok: boolean): HTMLSpanElement =>
        ok ? ui.pill('已装', 'on') : ui.pill('没装 · 皮肤不会生效', 'off');
      const rows = [
        { k: shared ? '客户端目录' : '摄像机目录', v: ui.h('span', null, st.dirs.camera) },
        { k: 'CustomSkinLoader', v: modPill(st.mod.camera) },
      ];
      if (!shared) {
        rows.push(
          { k: '玩家目录', v: ui.h('span', null, st.dirs.player) },
          { k: 'CustomSkinLoader(玩家)', v: modPill(st.mod.player) },
        );
      }
      premise.replaceChildren(ui.kv(rows));
      if (!st.mod.camera || (!shared && !st.mod.player)) {
        premise.appendChild(ui.h(
          'div',
          'pagedesc',
          '把 CustomSkinLoader 的 jar 放进该目录的 mods/ 再启动客户端。它是纯客户端 mod,'
          + '服务器不用装,也不影响 mineflayer 那条连接。',
        ));
      }
    }

    function render(st: MinecraftSkinState | null): void {
      if (ctx.signal.aborted) return;
      cur = st;
      if (!st) {
        msg.say('皮肤设置不可用', true);
        roleBox.replaceChildren(ui.placeholder('读不到皮肤设置'));
        premise.replaceChildren();
        return;
      }
      roleBox.replaceChildren(...st.roles.map((role) => roleCard(role, st)));
      renderPremise(st);
      msg.say(st.detail ?? '');
    }

    const refresh = (): Promise<void> =>
      ctx.invoke<MinecraftSkinState>('state').then(render, () => render(null));

    /** 一次动作:调服务端 → 拿回来的新状态重画。失败时重画旧状态,错误话留在最后一行 */
    async function act(fn: () => Promise<MinecraftSkinState>, working: string): Promise<void> {
      msg.say(working);
      try {
        render(await fn());
      } catch (err) {
        if (ctx.signal.aborted) return;
        if (cur) render(cur);
        msg.say(`操作失败: ${errText(err)}`, true);
      }
    }

    /** 原样上传:皮肤材质一个像素都不能重编码,浏览器这一侧只做搬运 */
    function toBase64(file: File): Promise<string> {
      return file.arrayBuffer().then((buf) => {
        const bytes = new Uint8Array(buf);
        let bin = '';
        for (const b of bytes) bin += String.fromCharCode(b);
        return btoa(bin);
      });
    }

    void refresh();
  },
};
