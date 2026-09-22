import { createI18n } from 'vue-i18n';

import enUS from '../i18n/locales/en-US.json';
import zhCN from '../i18n/locales/zh-CN.json';

// 默认 zh-CN（Stella 现状）；locale 持久化在 localStorage（M2 接设置页）。
export const i18n = createI18n({
  legacy: false,
  locale: localStorage.getItem('stella-locale') ?? 'zh-CN',
  fallbackLocale: 'zh-CN',
  messages: {
    'zh-CN': zhCN,
    'en-US': enUS,
  },
});
