// Plugin dependencies.
import '@mdi/font/css/materialdesignicons.css';
import 'vuetify/styles';

// Core plugins.
import { createPinia } from 'pinia';
import { createApp } from 'vue';
import VueApexCharts from 'vue3-apexcharts';
import { installCloseOverlay } from './api/desktopClose';
import vuetify from './plugins/vuetify';
import App from './App.vue';
import { i18n } from './plugins/i18n';
import { router } from './router';

const app = createApp(App);

app.use(createPinia());
app.use(router);
app.use(i18n);
app.use(vuetify);
// <apexchart> 全局组件：不注册则模板里的图表静默渲染为空（数据页统计实测）。
app.use(VueApexCharts);

app.mount('#app');

// 挂载成功，取消 index.html 的启动看门狗（8s 后 #app 仍空会显示缓存自愈卡片）。
if ((window as any).__stellaBootGuard) {
  clearTimeout((window as any).__stellaBootGuard);
}

// 桌面壳内生效：关窗前 Rust 侧会先优雅停止 Bot（可能数十秒），盖遮罩防误判卡死。
installCloseOverlay();
