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
      {
        path: 'platforms',
        name: 'platforms',
        component: () => import('@/views/PlatformsPage.vue'),
      },
      {
        path: 'providers',
        name: 'providers',
        component: () => import('@/views/ProvidersPage.vue'),
      },
      {
        path: 'extension',
        name: 'extension',
        component: () => import('@/views/extension/ExtensionPage.vue'),
      },
      {
        path: 'knowledge-base',
        name: 'knowledge-base',
        component: () => import('@/views/knowledge/KnowledgePage.vue'),
      },
      {
        path: 'persona',
        name: 'persona',
        component: () => import('@/views/PersonaPage.vue'),
      },
      {
        path: 'cron',
        name: 'cron',
        component: () => import('@/views/CronPage.vue'),
      },
      {
        // cometa 外部 Agent 任务（design_docs/Cometa 外部 Agent 任务运行层实施方案 §6.14）
        path: 'cometa',
        name: 'cometa',
        component: () => import('@/views/CometaPage.vue'),
      },
      {
        path: 'groups',
        name: 'groups',
        component: () => import('@/views/GroupsPage.vue'),
      },
      {
        path: 'config',
        name: 'config',
        component: () => import('@/views/ConfigPage.vue'),
      },
      {
        path: 'settings',
        name: 'settings',
        component: () => import('@/views/SettingsPage.vue'),
      },
      {
        path: 'chat',
        name: 'chat',
        component: () => import('@/views/ChatPage.vue'),
      },
      {
        // 数据页：Tab 壳 + 子路由（对齐 AstrBot DataPage 范式，方案 §6.9）
        path: 'data',
        component: () => import('@/views/data/DataPage.vue'),
        children: [
          { path: '', redirect: '/data/statistics' },
          {
            path: 'statistics',
            name: 'data-statistics',
            component: () => import('@/views/data/StatisticsPage.vue'),
            meta: { dataTab: 'statistics' },
          },
          {
            path: 'conversations',
            name: 'data-conversations',
            component: () => import('@/views/data/ConversationsPage.vue'),
            meta: { dataTab: 'conversations' },
          },
          {
            path: 'logs',
            name: 'data-logs',
            component: () => import('@/views/data/LogsPage.vue'),
            meta: { dataTab: 'logs' },
          },
          {
            path: 'trace',
            name: 'data-trace',
            component: () => import('@/views/data/TracePage.vue'),
            meta: { dataTab: 'trace' },
          },
          {
            // 消息流程（源码版本化、真实事件驱动的处理拓扑，计划 §6.7）
            path: 'flow',
            name: 'data-flow',
            component: () => import('@/views/data/FlowPage.vue'),
            meta: { dataTab: 'flow' },
          },
        ],
      },
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
