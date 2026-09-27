// SPDX-License-Identifier: AGPL-3.0
// Copyright (c) 2026 Stella Project Contributors
// 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
/**
 * M1 宿主生命周期验收（计划 §8.2 host-lifecycle）：多 Core 实例隔离、idle 回收、
 * 关闭无泄漏、provider 中断后进程仍可干净退出。
 */
import { createHash } from "node:crypto";
import { existsSync } from "node:fs";
import { expect } from "vitest";
import { describe, it } from "vitest";
import { makeCfg, makeLoaded, makeTmpDir } from "../../../vendor/cortico/tests/core/helpers.ts";
import { ConversationHost } from "../src/host.ts";
import { ScriptedBridge } from "../src/provider-bridge.ts";
import { message } from "../../../vendor/cortico/src/protocol/open-responses/context.ts";

function makeHost(dataRoot: string, bridgeFactory: () => ScriptedBridge): ConversationHost {
  return new ConversationHost({
    dataRoot,
    makeLoaded: (dataDir) =>
      makeLoaded({
        config: makeCfg(),
        rootDir: `${dataRoot}/root`,
        memoryDir: `${dataRoot}/persona`,
        dataDir,
      }),
    makeBridge: bridgeFactory,
  });
}

describe("host-lifecycle", () => {
  it("多实例隔离：两个会话两个 dataDir，轮次互不可见", async () => {
    const tmp = makeTmpDir();
    const bridges = [new ScriptedBridge([{ text: "A" }]), new ScriptedBridge([{ text: "B" }])];
    let next = 0;
    const host = makeHost(tmp.dir, () => bridges[next++]!);
    try {
      const a = await host.acquire("qq:bot1:group_a");
      const b = await host.acquire("qq:bot1:group_b");
      expect(host.size).toBe(2);
      await a.adapter.submitTurn([message("user", "群A话题")]);
      await b.adapter.submitTurn([message("user", "群B话题")]);
      expect(JSON.stringify(bridges[1]!.requests[0])).not.toContain("群A话题");
      expect(existsSync(`${tmp.dir}/${sha12("qq:bot1:group_a")}`)).toBe(true);
      expect(existsSync(`${tmp.dir}/${sha12("qq:bot1:group_b")}`)).toBe(true);
    } finally {
      await host.stopAll();
      tmp.cleanup();
    }
  });

  it("idle 回收：reclaimIdle 移除空闲实例并释放；再次 acquire 重建", async () => {
    const tmp = makeTmpDir();
    const host = makeHost(tmp.dir, () => new ScriptedBridge([{ text: "x" }]));
    try {
      const entry = await host.acquire("qq:bot1:group_c");
      await entry.adapter.submitTurn([message("user", "投影")]);
      const reclaimed = await host.reclaimIdle(0);
      expect(reclaimed).toEqual(["qq:bot1:group_c"]);
      expect(host.size).toBe(0);
      const again = await host.acquire("qq:bot1:group_c");
      expect(again).not.toBe(entry);
      expect(host.size).toBe(1);
    } finally {
      await host.stopAll();
      tmp.cleanup();
    }
  });

  it("provider 中断：submitTurn 拒绝后 stopAll 仍干净收尾（无僵尸轮次）", async () => {
    const tmp = makeTmpDir();
    const host = makeHost(tmp.dir, () => new ScriptedBridge([{ throw: new Error("aborted-mid-call") }]));
    try {
      const entry = await host.acquire("qq:bot1:group_d");
      await expect(entry.adapter.submitTurn([message("user", "投影")])).rejects.toThrow("aborted-mid-call");
      await expect(host.stopAll()).resolves.toBeUndefined();
      expect(host.size).toBe(0);
    } finally {
      tmp.cleanup();
    }
  });
});

function sha12(key: string): string {
  return createHash("sha256").update(key).digest("hex").slice(0, 12);
}
