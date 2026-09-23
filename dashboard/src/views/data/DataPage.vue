<script setup lang="ts">
// 数据页 Tab 壳（对齐 AstrBot DataPage：自绘 pill tab + 子路由，方案 §6.9）
import { useRoute } from 'vue-router';

const route = useRoute();

const tabs = [
  { key: 'statistics', label: '统计', to: '/data/statistics' },
  { key: 'conversations', label: '会话', to: '/data/conversations' },
  { key: 'logs', label: '日志', to: '/data/logs' },
  { key: 'trace', label: '追踪', to: '/data/trace' },
];
</script>

<template>
  <v-container fluid class="pa-6">
    <div class="d-flex align-center ga-3 mb-4">
      <div
        v-for="tab in tabs"
        :key="tab.key"
        class="data-tab"
        :class="{ active: route.meta.dataTab === tab.key }"
      >
        <router-link :to="tab.to" class="text-decoration-none text-primary">
          {{ tab.label }}
        </router-link>
      </div>
    </div>
    <router-view />
  </v-container>
</template>

<style scoped>
.data-tab {
  padding: 0.35rem 1.1rem;
  border-radius: 999px;
  background: rgba(var(--v-theme-surface), 0.6);
  font-size: 0.9rem;
}
.data-tab.active {
  background: rgba(var(--v-theme-primary), 0.15);
  font-weight: 600;
}
</style>
