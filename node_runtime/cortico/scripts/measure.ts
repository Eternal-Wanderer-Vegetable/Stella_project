// SPDX-License-Identifier: AGPL-3.0
// Copyright (c) 2026 Stella Project Contributors
// 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
/**
 * M1 资源测量（计划门槛：桥额外延迟 p95 ≤100ms；冷启动增量 ≤3s；RSS 增量 ≤150MiB）。
 *
 * 运行：pnpm --dir node_runtime/cortico measure
 * 排除模型加载/推理（ScriptedBridge 零推理）；场景：冷启动 1/20 个 Core 实例、
 * 每实例 10 次 fork 轮次的提交延迟、Node 进程 RSS。
 * 不引入上游 tests/helpers（其依赖 vitest）；配置取自冻结夹具 fixture-config.json。
 */
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { performance } from "node:perf_hooks";
import { Core } from "../../../vendor/cortico/src/core/core.ts";
import type { LoadedConfig } from "../../../vendor/cortico/src/core/config.ts";
import type { CoreConfig } from "../../../vendor/cortico/src/core/types.ts";
import { message } from "../../../vendor/cortico/src/protocol/open-responses/context.ts";
import type { ResponseClient } from "../../../vendor/cortico/src/core/generation.ts";
import { ScriptedBridge } from "../src/provider-bridge.ts";
import { StellaPersona } from "../src/stella-persona.ts";
import { TurnAdapter } from "../src/turn-adapter.ts";

const FIXTURE_CONFIG = JSON.parse(
  readFileSync(new URL("../tests/fixtures/fixture-config.json", import.meta.url), "utf8"),
) as CoreConfig;

function makeTurnConfig(dataDir: string, rootDir: string): LoadedConfig<CoreConfig> {
  return {
    config: FIXTURE_CONFIG,
    secret: () => "fake-key",
    rootDir,
    memoryDir: `${rootDir}/persona`,
    dataDir,
  };
}

function rssMiB(): number {
  return process.memoryUsage.rss() / (1024 * 1024);
}

function p95(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * 0.95))] ?? NaN;
}

async function startCore(dataDir: string, bridge: ScriptedBridge): Promise<{ core: Core; adapter: TurnAdapter }> {
  const core = new Core(makeTurnConfig(dataDir, join(dataDir, "..", "root")), {
    persona: new StellaPersona(),
    worlds: [],
    llm: bridge as unknown as ResponseClient,
  });
  await core.start();
  return { core, adapter: new TurnAdapter(core) };
}

async function main() {
  const rssBefore = rssMiB();
  console.log(`[measure] Node ${process.version} 基线 RSS=${rssBefore.toFixed(1)}MiB`);

  // 1) 单实例：冷启动 + 10 轮延迟
  {
    const dir = mkdtempSync(join(tmpdir(), "stella-measure-1-"));
    const bridge = new ScriptedBridge(Array.from({ length: 10 }, () => ({ text: "ok" })));
    const t0 = performance.now();
    const { core, adapter } = await startCore(join(dir, "data"), bridge);
    const startMs = performance.now() - t0;
    const latencies: number[] = [];
    for (let i = 0; i < 10; i++) {
      const a = performance.now();
      await adapter.submitTurn([message("user", `延迟样本 ${i}`)]);
      latencies.push(performance.now() - a);
    }
    await core.stop();
    console.log(
      `[measure] 1 实例: 冷启动 ${startMs.toFixed(1)}ms | p50=${latencies[Math.floor(latencies.length / 2)]!.toFixed(1)}ms p95=${p95(latencies).toFixed(1)}ms`,
    );
  }

  // 2) 20 实例：冷启动总耗时 + 200 轮延迟 + RSS
  {
    const dir = mkdtempSync(join(tmpdir(), "stella-measure-20-"));
    const t0 = performance.now();
    const instances = [];
    for (let i = 0; i < 20; i++) {
      const bridge = new ScriptedBridge(Array.from({ length: 10 }, () => ({ text: "ok" })));
      instances.push(await startCore(join(dir, `inst-${i}`), bridge));
    }
    const start20 = performance.now() - t0;
    const latencies: number[] = [];
    for (const { adapter } of instances) {
      for (let i = 0; i < 10; i++) {
        const a = performance.now();
        await adapter.submitTurn([message("user", `20 实例样本 ${i}`)]);
        latencies.push(performance.now() - a);
      }
    }
    for (const { core } of instances) await core.stop();
    const rssAfter = rssMiB();
    console.log(`[measure] 20 实例: 冷启动总 ${start20.toFixed(0)}ms（均 ${(start20 / 20).toFixed(0)}ms/实例）`);
    console.log(`[measure] 20 实例 200 轮: p50=${latencies.sort((a, b) => a - b)[100]!.toFixed(1)}ms p95=${p95(latencies).toFixed(1)}ms`);
    console.log(`[measure] RSS 增量(20 实例在途)=${(rssAfter - rssBefore).toFixed(1)}MiB`);
  }
}

main().then(
  () => process.exit(0),
  (e) => {
    console.error(e);
    process.exit(1);
  },
);
