import { defineStore } from 'pinia';

export type ThemeMode = 'light' | 'dark' | 'system';

const MODE_KEY = 'stella-theme-mode';

export const useCustomizerStore = defineStore('customizer', {
  state: () => ({
    themeMode: (localStorage.getItem(MODE_KEY) ?? 'dark') as ThemeMode,
    miniSidebar: false,
  }),
  getters: {
    /** 应用到 Vuetify 的具体主题名（system 跟随系统偏好，方案 §10.5）。 */
    resolvedTheme(state): string {
      const dark =
        state.themeMode === 'dark' ||
        (state.themeMode === 'system' &&
          window.matchMedia('(prefers-color-scheme: dark)').matches);
      return dark ? 'StellaThemeDark' : 'StellaTheme';
    },
  },
  actions: {
    setThemeMode(mode: ThemeMode): void {
      this.themeMode = mode;
      localStorage.setItem(MODE_KEY, mode);
    },
  },
});
