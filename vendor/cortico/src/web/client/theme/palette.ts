/** 将主题 token 写为 documentElement 的 CSS 变量，并更新明暗标记与 theme-color。 */

import {
  THEME_TOKENS,
  type ThemeAppearance,
  type ThemePalette,
} from './registry.ts';

export interface ApplyPaletteOptions {
  /** 解析之后的明暗，落到 `data-color-mode` 与 `color-scheme`（表单控件、滚动条随之变）。 */
  appearance: ThemeAppearance;
  /** 当前方案 id，落到 `data-theme-scheme`；给 CSS 留一个"某方案单独微调"的口子。 */
  schemeId?: string;
}

/** 按 token 词表顺序映射 CSS 变量，仅包含词表中的键。 */
export function paletteVars(palette: ThemePalette): Array<[string, string]> {
  const out: Array<[string, string]> = [];
  for (const token of THEME_TOKENS) {
    const value = palette[token.key];
    if (typeof value === 'string' && value !== '') out.push(['--' + token.key, value]);
  }
  return out;
}

/**
 * `<meta name="theme-color">` —— 移动端浏览器的地址栏底色。
 * 没有就建一个；页面里已有（`index.html` 静态写的那一个）就改它的 `content`。
 */
function applyThemeColorMeta(doc: Document, color: string | undefined): void {
  const head = doc.head;
  if (!head || !color) return;
  let meta = doc.querySelector('meta[name="theme-color"]') as HTMLMetaElement | null;
  if (!meta) {
    meta = doc.createElement('meta');
    meta.name = 'theme-color';
    head.appendChild(meta);
  }
  meta.content = color;
}

/** 把一份调色板刷到文档根上。**同步、幂等**，重复调用只是把同样的值再写一遍。 */
export function applyPalette(
  doc: Document,
  palette: ThemePalette,
  opts: ApplyPaletteOptions,
): void {
  const root = doc.documentElement;
  if (!root) return;
  for (const [name, value] of paletteVars(palette)) root.style.setProperty(name, value);
  root.dataset.colorMode = opts.appearance;
  if (opts.schemeId) root.dataset.themeScheme = opts.schemeId;
  root.style.colorScheme = opts.appearance;
  applyThemeColorMeta(doc, palette.paper);
}

/** 读取语义色的计算值；缺少合法颜色时回退到 --ink-dim。 */
export function readThemeColor(doc: Document, key: string): string {
  const root = doc.documentElement;
  const view = doc.defaultView;
  if (!root || !view) return '';
  const read = (k: string): string => view.getComputedStyle(root).getPropertyValue('--' + k).trim();
  const value = read(key);
  return /^#[0-9a-f]{6}$/i.test(value) ? value : read('ink-dim');
}

// ---------------------------------------------------------------------------
// 颜色换算
// ---------------------------------------------------------------------------

export interface Hsl {
  /** 0–360 */
  h: number;
  /** 0–100 */
  s: number;
  /** 0–100 */
  l: number;
}

/** 将 #rrggbb 或 #rgb 转为 HSL。 */
export function hexToHsl(hex: string): Hsl {
  let x = String(hex).replace('#', '');
  if (x.length === 3) x = x.split('').map((c) => c + c).join('');
  const r = parseInt(x.slice(0, 2), 16) / 255;
  const g = parseInt(x.slice(2, 4), 16) / 255;
  const b = parseInt(x.slice(4, 6), 16) / 255;
  const mx = Math.max(r, g, b);
  const mn = Math.min(r, g, b);
  let h = 0;
  let s = 0;
  const l = (mx + mn) / 2;
  if (mx !== mn) {
    const d = mx - mn;
    s = l > 0.5 ? d / (2 - mx - mn) : d / (mx + mn);
    h = mx === r ? (g - b) / d + (g < b ? 6 : 0) : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
    h *= 60;
  }
  return { h, s: s * 100, l: l * 100 };
}

/** HSL → `hsl(210,12%,40%)`。三个分量都取整——CSS 不需要那么多小数。 */
export function hslCss(hsl: Hsl): string {
  return `hsl(${Math.round(hsl.h)},${Math.round(hsl.s)}%,${Math.round(hsl.l)}%)`;
}

/** 夹到区间。深浅派生时防止某一族滑到纯黑或纯白（那时候颜色就没有区分度了）。 */
export function clampNumber(value: number, lo: number, hi: number): number {
  return value < lo ? lo : value > hi ? hi : value;
}
