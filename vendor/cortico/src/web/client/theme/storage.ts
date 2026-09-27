/**
 * 主题记录归部署所有：首屏从服务端注入的 JSON 读，改动回写 `/api/theme`。
 * 这台机器的 localStorage 只在部署还没有记录时读一次，把旧记录交上去。
 */

import { post } from '../core/api.ts';
import {
  DEFAULT_SCHEME_ID,
  THEME_SCRIPT_ID,
  normalizeStoredTheme,
  type InjectedTheme,
  type StoredTheme,
} from '../../shared/theme.ts';

export { THEME_SCRIPT_ID };

/** 搬进部署目录之前，主题记录存在这台机器上的两个键；新的在前。 */
export const LEGACY_THEME_STORAGE_KEYS: readonly string[] = [
  'cortico.theme.v1',
  'xuewu.theme-studio.v1',
];

/** 首页里那段 JSON。`theme` 为 null = 这份部署还没保存过，此时才谈得上迁移本机旧记录。 */
export function readInjectedTheme(doc: Document): InjectedTheme {
  const fallback: InjectedTheme = { defaultScheme: DEFAULT_SCHEME_ID, theme: null };
  const raw = doc.getElementById(THEME_SCRIPT_ID)?.textContent;
  if (raw == null || raw.trim() === '') return fallback;
  try {
    const value = JSON.parse(raw) as Partial<InjectedTheme> | null;
    if (!value || typeof value !== 'object') return fallback;
    return {
      defaultScheme: typeof value.defaultScheme === 'string' && value.defaultScheme !== ''
        ? value.defaultScheme
        : DEFAULT_SCHEME_ID,
      theme: value.theme == null ? null : normalizeStoredTheme(value.theme),
    };
  } catch {
    return fallback;
  }
}

/** 这台机器上的旧记录。两个键都没有内容时给 `null`；旧记录读完不删。 */
export function readLegacyLocalTheme(doc: Document): StoredTheme | null {
  let storage: Pick<Storage, 'getItem'> | null = null;
  try {
    storage = doc.defaultView?.localStorage ?? null;
  } catch {
    // 沙箱 iframe 与无痕模式下访问会被拒。
    return null;
  }
  if (!storage) return null;
  for (const key of LEGACY_THEME_STORAGE_KEYS) {
    let raw: string | null = null;
    try {
      raw = storage.getItem(key);
    } catch {
      return null;
    }
    if (raw == null || raw === '') continue;
    try {
      return normalizeStoredTheme(JSON.parse(raw) as unknown);
    } catch {
      continue;
    }
  }
  return null;
}

/** 回写部署的主题记录。失败由调用方呈现，不吞。 */
export async function saveDeploymentTheme(state: StoredTheme): Promise<void> {
  await post('/api/theme', state);
}
