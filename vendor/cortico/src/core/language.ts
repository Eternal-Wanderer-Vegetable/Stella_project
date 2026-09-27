/**
 * Console text uses the language supplied with each browser request.
 * The initial default uses a recognized config.language, then CORTICO_LANGUAGE,
 * then the system locale. Chinese locales select zh; other nonempty locales select en;
 * an unavailable locale falls back to zh. The environment/locale result is cached once.
 * The browser can override the initial <html lang> value and sends its choice in the
 * console language header or query parameter. Panels receive ConsolePanelContext.language.
 * Owners render request text in that language; missing translations use Chinese.
 * This setting does not select or translate model-facing text.
 */
export type Language = 'zh' | 'en';

export const LANGUAGES: readonly Language[] = ['zh', 'en'];

export function isLanguage(value: unknown): value is Language {
  return value === 'zh' || value === 'en';
}

/** BCP 47 / POSIX tag → language. Empty input is "unknown", not English. */
export function languageOfLocale(tag: string | null | undefined): Language | undefined {
  const t = (tag ?? '').trim().toLowerCase();
  if (!t) return undefined;
  return t === 'zh' || t.startsWith('zh-') || t.startsWith('zh_') ? 'zh' : 'en';
}

/** Pure form of the system read, for tests. */
export function detectLanguage(
  env: Record<string, string | undefined>,
  locale: string | null | undefined,
): Language {
  const forced = env.CORTICO_LANGUAGE;
  if (isLanguage(forced)) return forced;
  return languageOfLocale(locale) ?? 'zh';
}

let systemMemo: Language | undefined;

/** The environment/locale read, performed once and then fixed for the process lifetime. */
export function systemLanguage(): Language {
  if (systemMemo === undefined) {
    // `process` is reached through globalThis so this file also type-checks under the DOM lib.
    const env = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process?.env ?? {};
    let locale: string | undefined;
    try {
      locale = Intl.DateTimeFormat().resolvedOptions().locale;
    } catch {
      locale = undefined;
    }
    systemMemo = detectLanguage(env, locale);
  }
  return systemMemo;
}

/** A configured value wins over the system read; anything unrecognised is ignored. */
export function resolveLanguage(configured: unknown): Language {
  return isLanguage(configured) ? configured : systemLanguage();
}

/** Select a language table; the type requires English to have the same keys as Chinese. */
export function pick<T>(language: Language, table: { readonly zh: T; readonly en: T }): T {
  return language === 'en' ? table.en : table.zh;
}
