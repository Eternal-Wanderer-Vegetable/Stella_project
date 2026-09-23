// Plugin dependencies.
import '@mdi/font/css/materialdesignicons.css';
import 'vuetify/styles';

// Core plugins.
import { createPinia } from 'pinia';
import { createApp } from 'vue';
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
