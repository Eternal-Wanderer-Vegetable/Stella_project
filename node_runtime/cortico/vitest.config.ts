import { realpathSync } from "node:fs";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

// Windows 8.3 短路径会影响临时目录文件 URL（与上游 vitest.config.ts 同法）。
const longTmp = realpathSync.native(tmpdir());
const vendorSrc = fileURLToPath(new URL("../../vendor/cortico/src/", import.meta.url));

export default defineConfig({
  // vendor 内部以 `cortico/<src 下路径>` 自引用（bots/corti-soulmate/assemble.ts 等），
  // 与上游根 tsconfig paths 同形。
  resolve: {
    alias: [{ find: /^cortico\//, replacement: vendorSrc }],
  },
  test: {
    include: ["tests/**/*.test.ts"],
    env: { CORTICO_LANGUAGE: "zh", TEMP: longTmp, TMP: longTmp, TMPDIR: longTmp },
    pool: "forks",
    testTimeout: 30_000,
  },
});
