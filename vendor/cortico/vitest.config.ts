import { realpathSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vitest/config';

// 将 Windows 8.3 短路径解析为长路径,使临时模块使用一致的文件 URL。
const longTmp = realpathSync.native(tmpdir());

export default defineConfig({
  // 与根 tsconfig 的 paths 同形:仓内 bot 包以 `cortico/<src 下路径>` import 框架。
  resolve: {
    alias: [{ find: /^cortico\//, replacement: fileURLToPath(new URL('./src/', import.meta.url)) }],
  },
  test: {
    include: ['tests/**/*.test.ts', 'templates/extension/*/tests/*.test.ts'],
    // 固定默认语言,避免测试依赖机器区域设置;请求仍可指定语言。
    env: { CORTICO_LANGUAGE: 'zh', TEMP: longTmp, TMP: longTmp, TMPDIR: longTmp },
    testTimeout: 20000,
    pool: 'forks',
    maxWorkers: 2,
    minWorkers: 1,
  },
});
