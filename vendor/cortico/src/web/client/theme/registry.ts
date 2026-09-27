/** 主题的界面文案：方案名、token 标签与分组。数据与纯函数在 web/shared/theme.ts。 */

import {
  BUILTIN_PALETTES,
  BUILTIN_SCHEME_IDS,
  THEME_TOKEN_GROUPS,
  cloneScheme,
  type ThemeAppearance,
  type ThemeMode,
  type ThemeScheme,
} from '../../shared/theme.ts';
import { S } from './strings.ts';

export {
  BUILTIN_PALETTES,
  BUILTIN_SCHEME_IDS,
  DEFAULT_SCHEME_ID,
  THEME_MODES,
  THEME_TOKEN_KEYS,
  clonePalette,
  cloneScheme,
  defaultStoredTheme,
  fallbackPalette,
  isHexColor,
  normalizeHex,
  normalizePalette,
  normalizeStoredTheme,
  parseStoredTheme,
  resolvePalette,
  schemeSwatches,
} from '../../shared/theme.ts';
export type {
  InjectedTheme,
  StoredTheme,
  ThemeAppearance,
  ThemeMode,
  ThemePalette,
  ThemeScheme,
} from '../../shared/theme.ts';

export interface ThemeToken {
  /** 编辑器里的分组标题 */
  readonly group: string;
  /** CSS 变量名去掉 `--` 前缀，如 `paper` → `--paper` */
  readonly key: string;
  /** 编辑器里的中文标签 */
  readonly label: string;
}

/** 明暗模式的中文挡位名。分段选择器与提示语共用一套措辞。 */
export const THEME_MODE_LABELS: Readonly<Record<ThemeMode, string>> = {
  light: S.modeLight,
  dark: S.modeDark,
  system: S.modeSystem,
};

/** 提示语里的"当前变体"。`light`/`dark` 两个词全站只在这儿定义一次。 */
export const THEME_APPEARANCE_LABELS: Readonly<Record<ThemeAppearance, string>> = {
  light: S.appearanceLight,
  dark: S.appearanceDark,
};

const GROUP_TITLES: Readonly<Record<string, string>> = {
  paper: S.groupPaper,
  ink: S.groupInk,
  state: S.groupState,
  timeline: S.groupTimeline,
  chart: S.groupChart,
};

const SCHEME_TEXT: Readonly<Record<string, { name: string; note: string }>> = {
  mint: { name: S.schemeMint, note: S.schemeMintNote },
  navigator: { name: S.schemeNavigator, note: S.schemeNavigatorNote },
  'crab-daisy': { name: S.schemeCrabDaisy, note: S.schemeCrabDaisyNote },
};

export const THEME_TOKENS: readonly ThemeToken[] = THEME_TOKEN_GROUPS.flatMap((group) =>
  group.keys.map((key): ThemeToken => ({ group: GROUP_TITLES[group.id], key, label: S.token[key] })),
);

/** 内置方案，贴上界面语言的名称与说明。 */
export const BUILTIN_SCHEMES: readonly ThemeScheme[] = BUILTIN_SCHEME_IDS.map((id) => ({
  id,
  name: SCHEME_TEXT[id].name,
  note: SCHEME_TEXT[id].note,
  palettes: BUILTIN_PALETTES[id],
  builtin: true,
}));

/** 方案名与说明：自定义方案没填名字时用通用称呼。 */
export function schemeText(scheme: ThemeScheme): { name: string; note: string } {
  return {
    name: scheme.name || SCHEME_TEXT[scheme.id]?.name || S.customScheme,
    note: scheme.note || SCHEME_TEXT[scheme.id]?.note || S.customNote,
  };
}

/** 全部内置方案的副本。主题记录里没有它们，每次现取。 */
export function builtinSchemes(): ThemeScheme[] {
  return BUILTIN_SCHEMES.map((scheme) => ({ ...cloneScheme(scheme), builtin: true }));
}

/** 部署记录给的方案 id；不是内置方案就落到框架默认方案。 */
export function resolveDefaultSchemeId(value: unknown): string {
  const id = String(value ?? '');
  return BUILTIN_SCHEME_IDS.includes(id) ? id : BUILTIN_SCHEME_IDS[0];
}

/**
 * 词表按 `group` 归并，**保持 `THEME_TOKENS` 里的出现顺序**。
 *
 * 编辑器要的就是这个形状；单独拿出来是因为"分组"是这一页唯一有分量的纯逻辑，
 * 而它写在渲染函数里就只能靠看 DOM 来验。
 */
export function groupedThemeTokens(
  tokens: readonly ThemeToken[] = THEME_TOKENS,
): Array<{ group: string; tokens: ThemeToken[] }> {
  const out: Array<{ group: string; tokens: ThemeToken[] }> = [];
  const index = new Map<string, { group: string; tokens: ThemeToken[] }>();
  for (const token of tokens) {
    let bucket = index.get(token.group);
    if (!bucket) {
      bucket = { group: token.group, tokens: [] };
      index.set(token.group, bucket);
      out.push(bucket);
    }
    bucket.tokens.push(token);
  }
  return out;
}
