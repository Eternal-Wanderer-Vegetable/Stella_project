import { createVuetify } from 'vuetify';
import * as components from 'vuetify/components';
import * as directives from 'vuetify/directives';
import { StellaTheme, StellaThemeDark } from '../theme';

// 组件默认值对齐 AstrBot 的观感约定（方案 §10.5）：卡片大圆角、snackbar
// 带阴影、tooltip 顶部弹出。M0 全量引入组件（无 treeshaking），体积优化
// 留给 M5（vite-plugin-vuetify + sass）。
export default createVuetify({
  components,
  directives,
  theme: {
    defaultTheme: 'StellaThemeDark',
    themes: { StellaTheme, StellaThemeDark },
  },
  defaults: {
    VCard: { rounded: 'lg' },
    VSnackbar: { elevation: 6 },
    VTooltip: { location: 'top' },
    VBtn: { color: 'primary' },
  },
});
