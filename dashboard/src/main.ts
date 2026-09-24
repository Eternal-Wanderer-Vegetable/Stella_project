// Plugin dependencies.
import '@mdi/font/css/materialdesignicons.css';
import 'vuetify/styles';

// Core plugins.
import { createPinia } from 'pinia';
import { createApp } from 'vue';
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

app.mount('#app');

// 桌面壳内生效：关窗前 Rust 侧会先优雅停止 Bot（可能数十秒），盖遮罩防误判卡死。
installCloseOverlay();
