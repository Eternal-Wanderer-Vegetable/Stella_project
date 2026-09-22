import { createRouter, createWebHashHistory, type RouteRecordRaw } from 'vue-router';

import BlankLayout from '@/layouts/BlankLayout.vue';
import FullLayout from '@/layouts/FullLayout.vue';
import { useAuthStore } from '@/stores/auth';

// hash 路由（对齐 AstrBot）：静态托管无需服务端 rewrite，桌面壳离线加载
// 也天然兼容（方案 §4 D1）。
const routes: RouteRecordRaw[] = [
  {
    path: '/',
    component: FullLayout,
    children: [
      { path: '', name: 'welcome', component: () => import('@/views/WelcomePage.vue') },
    ],
  },
  {
    path: '/auth',
    component: BlankLayout,
    children: [
      { path: 'login', name: 'login', component: () => import('@/views/auth/LoginPage.vue') },
      { path: 'setup', name: 'setup', component: () => import('@/views/auth/SetupPage.vue') },
    ],
  },
  {
    path: '/offline',
    name: 'offline',
    component: () => import('@/views/BackendOfflinePage.vue'),
  },
];

export const router = createRouter({
  history: createWebHashHistory(),
  routes,
});

const AUTH_PAGES = new Set(['/auth/login', '/auth/setup']);

router.beforeEach(async (to) => {
  const auth = useAuthStore();
  // 后端可达性是路由的前提（方案 §4 D5 的 transport 前提）：探活一次，
  // 之后的跳转沿用结论；/offline 页提供手动重试。
  if (auth.backend === 'unknown') {
    await auth.probe();
  }
  if (auth.backend === 'offline') {
    return to.name === 'offline' ? true : { name: 'offline' };
  }
  if (to.name === 'offline') {
    return { name: 'welcome' };
  }
  if (auth.setupRequired && to.path !== '/auth/setup') {
    return { name: 'setup' };
  }
  if (!auth.setupRequired && to.path === '/auth/setup') {
    return { name: 'login' };
  }
  if (!auth.loggedIn && !AUTH_PAGES.has(to.path)) {
    return { name: 'login' };
  }
  if (auth.loggedIn && AUTH_PAGES.has(to.path)) {
    return { name: 'welcome' };
  }
  return true;
});
