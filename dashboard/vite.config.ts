import { fileURLToPath, URL } from 'node:url';

import vue from '@vitejs/plugin-vue';
import { defineConfig } from 'vite';

// base './'：同一份 dist 既能被 webui 托管在根路径，也能被桌面壳经 tauri
// 协议从资源目录离线加载（方案 §4 D1 / §11.3）。路由是 hash 模式，相对
// base 不会破坏深链。
export default defineConfig({
  base: './',
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    // 开发期反代到本机 Bot 进程（WEBUI_SERVE_DIST=false 时后端只出 API）
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8080',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    // 首屏分包（M5）：vuetify/apexcharts 体量大且极少变动，独立成块后
    // 业务代码更新不再打穿长缓存
    rollupOptions: {
      output: {
        manualChunks: {
          vuetify: ['vuetify'],
          charts: ['apexcharts', 'vue3-apexcharts'],
        },
      },
    },
  },
});
