import { fileURLToPath, URL } from 'node:url';

import { defineConfig } from 'vitest/config';

// 与 vite.config.ts 同一套 '@' 别名；纯 reducer/布局/store 测试跑在 node
// 环境（不开 jsdom——没有组件级 DOM 断言需求，保持依赖最小）。
export default defineConfig({
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  test: {
    environment: 'node',
    include: ['tests/**/*.spec.ts'],
  },
});
