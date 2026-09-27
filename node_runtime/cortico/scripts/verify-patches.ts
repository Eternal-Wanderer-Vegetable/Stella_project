// SPDX-License-Identifier: AGPL-3.0
// Copyright (c) 2026 Stella Project Contributors
// 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
/**
 * 补丁完整性检查（M1，计划 §8.3 verify-patches）。
 *
 * 校验 vendor/cortico 中被补丁触碰的文件哈希与 upstream-lock.json 记录一致、
 * 且带有 [STELLA PATCH] 标记 —— 任何未走补丁流程的 vendor 改动都会在此暴露。
 * 完整重放（pristine 快照 + patch → 逐字节一致）的命令记录在 lock 的
 * patches[].replay；CI 侧执行随 M8 接入。
 */
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const pkgRoot = join(dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = join(pkgRoot, "..", "..");
const lock = JSON.parse(readFileSync(join(pkgRoot, "upstream-lock.json"), "utf8"));

let failed = 0;
for (const patch of lock.patches) {
  const patchSha = createHash("sha256")
    .update(readFileSync(join(repoRoot, patch.file)))
    .digest("hex");
  if (patchSha !== patch.sha256) {
    console.error(`[verify-patches] 补丁文件哈希漂移: ${patch.file}`);
    failed++;
  }
  for (const f of patch.touched_files) {
    const abs = join(repoRoot, "vendor", "cortico", f.path);
    const body = readFileSync(abs);
    const sha = createHash("sha256").update(body).digest("hex");
    if (sha !== f.patched_sha256) {
      console.error(`[verify-patches] 文件哈希与 lock 不符: ${f.path}`);
      failed++;
      continue;
    }
    if (f.patched_sha256 !== null && !body.includes("[STELLA PATCH]")) {
      console.error(`[verify-patches] 缺少补丁标记: ${f.path}`);
      failed++;
    }
  }
}

if (failed > 0) {
  console.error(`[verify-patches] ${failed} 项不一致 —— vendor 改动必须经补丁流程`);
  process.exit(1);
}
console.log("[verify-patches] 全部一致:", lock.patches.length, "个补丁");
