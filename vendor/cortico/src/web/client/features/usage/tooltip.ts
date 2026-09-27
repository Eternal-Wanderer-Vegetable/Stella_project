/**
 * 随鼠标移动的 tooltip 与当前色块高亮。tooltip 位于本页 root，使用 fixed 定位并随卸载移除。
 * 移出色块、重画图表与卸载统一通过 setHi/clearHi 更新高亮，避免残留描边。
 */

import type { Disposable } from '../../../shared/client-panel.ts';

/** 鼠标与浮层之间留的空隙，也是碰到视口边缘时翻转的余量。 */
const TIP_PAD = 14;
/** 贴边时离视口边缘至少留这么多。 */
const TIP_EDGE = 8;

export interface UsageTip extends Disposable {
  /** 浮层节点本身（`.u-tip`）。 */
  readonly el: HTMLElement;
  /**
   * 显示一段正文。`key` 相同就**不重写 innerHTML**——鼠标在同一个段里移动会每帧
   * 触发一次，重写等于每帧重建一棵子树（也会打断文本选取）。
   */
  show(html: string, key: string): void;
  /** 跟着鼠标走，碰到视口边缘翻到另一侧。 */
  move(ev: { clientX: number; clientY: number }): void;
  /** 收起，并顺手清掉高亮。 */
  hide(): void;
  setHi(rect: Element): void;
  clearHi(): void;
}

/** host 通常为 feature 的 root。HTML 来自 uTipHtml，所有外部文本必须经过 escaping。 */
export function createUsageTip(doc: Document, host: HTMLElement): UsageTip {
  const el = doc.createElement('div');
  el.className = 'u-tip viewport-overlay hidden';
  host.appendChild(el);
  let hi: Element | null = null;
  let curKey: string | undefined;
  let disposed = false;

  const clearHi = (): void => {
    if (hi) {
      hi.classList.remove('seghi');
      hi = null;
    }
  };

  return {
    el,
    show(html, key) {
      if (disposed) return;
      if (curKey !== key) {
        el.innerHTML = html;
        curKey = key;
      }
      el.classList.remove('hidden');
    },
    move(ev) {
      if (disposed) return;
      const view = doc.defaultView;
      const r = el.getBoundingClientRect();
      let x = ev.clientX + TIP_PAD;
      let y = ev.clientY + TIP_PAD;
      const vw = view?.innerWidth ?? 0;
      const vh = view?.innerHeight ?? 0;
      if (vw && x + r.width > vw - TIP_EDGE) x = ev.clientX - r.width - TIP_PAD;
      if (vh && y + r.height > vh - TIP_EDGE) y = ev.clientY - r.height - TIP_PAD;
      el.style.left = Math.max(4, x) + 'px';
      el.style.top = Math.max(4, y) + 'px';
    },
    hide() {
      el.classList.add('hidden');
      clearHi();
    },
    setHi(rect) {
      if (hi === rect) return;
      clearHi();
      rect.classList.add('seghi');
      hi = rect;
    },
    clearHi,
    dispose() {
      if (disposed) return;
      disposed = true;
      clearHi();
      el.remove();
    },
  };
}
