// SPDX-License-Identifier: AGPL-3.0
// Copyright (c) 2026 Stella Project Contributors
// 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
/**
 * M1 兼容性原型验收：真实 Cortico Core（vendor 固定快照）上的轮次契约。
 *
 * 场景清单来自迁移计划 §7 M1「试验」：
 * 普通1次 / direct0次 / silent0发送 / 固定 provider request 等价 / 无额外工具循环 /
 * 两个群不串历史 / reset 后不复活 / 批处理不合并独立轮次 / provider 异常恰好一次。
 *
 * direct/silent 两个用例是 **A2 最小失败测试**：公开 API 没有 provider 调用前的
 * 决策点 —— 补丁（patches/turn-policy.patch）落地前它们必然失败。
 */
import { expect } from "vitest";
import { describe, it } from "vitest";
import { Core } from "../../../vendor/cortico/src/core/core.ts";
import { message, inputItem, type ContextRecord } from "../../../vendor/cortico/src/protocol/open-responses/context.ts";
import { makeCfg, makeLoaded, makeTmpDir } from "../../../vendor/cortico/tests/core/helpers.ts";
import { ScriptedBridge } from "../src/provider-bridge.ts";
import { StellaPersona } from "../src/stella-persona.ts";
import { TurnAdapter, type TurnDecision } from "../src/turn-adapter.ts";

function projection(text: string): ContextRecord[] {
  // 模拟 Python 侧最终投影：单条 user 消息即完整 prompt（BC-6/BC-7）。
  return [message("user", text)];
}

async function makeTurn(bridge: ScriptedBridge) {
  const tmp = makeTmpDir();
  const core = new Core(
    makeLoaded({
      config: makeCfg(),
      rootDir: tmp.dir,
      memoryDir: `${tmp.dir}/persona`,
      dataDir: `${tmp.dir}/data`,
    }),
    { persona: new StellaPersona(), worlds: [], llm: bridge },
  );
  await core.start();
  const adapter = new TurnAdapter(core);
  const cleanup = async () => {
    await core.stop();
    tmp.cleanup();
  };
  return { core, adapter, cleanup };
}

describe("turn-compat: generate 路径（公开 API）", () => {
  it("普通回复：恰好一次 provider 调用，返回脚本正文", async () => {
    const bridge = new ScriptedBridge([{ text: "在的呀" }]);
    const { adapter, cleanup } = await makeTurn(bridge);
    try {
      const out = await adapter.submitTurn(projection("【投影】在吗"));
      expect(out).toEqual({ kind: "generate", text: "在的呀" });
      expect(bridge.calls).toBe(1);
    } finally {
      await cleanup();
    }
  });

  it("固定 provider request 等价：input 恰为投影，Core 不附加任何历史/系统段", async () => {
    const bridge = new ScriptedBridge([{ text: "好" }]);
    const { adapter, cleanup } = await makeTurn(bridge);
    try {
      const proj = projection("【投影】现在是 <normalized-time>。\n用户(1001): 讲个笑话");
      await adapter.submitTurn(proj);
      expect(bridge.calls).toBe(1);
      const req = bridge.requests[0]!;
      // inputItem = 协议线上格式（剥 version 包装）；逐条对应投影、无任何附加记录
      expect(req.input).toEqual(proj.map(inputItem));
      expect(req.tools).toEqual([]);
    } finally {
      await cleanup();
    }
  });

  it("无额外工具循环：tools 为空且单轮硬上限，一次调用即结束", async () => {
    const bridge = new ScriptedBridge([{ text: "一次就好" }]);
    const { adapter, cleanup } = await makeTurn(bridge);
    try {
      await adapter.submitTurn(projection("投影A"));
      expect(bridge.calls).toBe(1);
      expect(bridge.requests[0]!.tools ?? []).toEqual([]);
    } finally {
      await cleanup();
    }
  });

  it("provider 异常：fork 通道无重试，恰好一次调用后原样上抛", async () => {
    const bridge = new ScriptedBridge([{ throw: new Error("boom") }]);
    const { adapter, cleanup } = await makeTurn(bridge);
    try {
      await expect(adapter.submitTurn(projection("投影"))).rejects.toThrow("boom");
      expect(bridge.calls).toBe(1);
    } finally {
      await cleanup();
    }
  });

  it("批处理不合并：同 Core 两次独立轮次各自精确投影", async () => {
    const bridge = new ScriptedBridge([{ text: "一" }, { text: "二" }]);
    const { adapter, cleanup } = await makeTurn(bridge);
    try {
      const proj1 = projection("第一轮投影");
      const proj2 = projection("第二轮投影");
      const out1 = await adapter.submitTurn(proj1);
      const out2 = await adapter.submitTurn(proj2);
      expect([out1.text, out2.text]).toEqual(["一", "二"]);
      expect(bridge.calls).toBe(2);
      expect(bridge.requests[0]!.input).toEqual(proj1.map(inputItem));
      expect(bridge.requests[1]!.input).toEqual(proj2.map(inputItem));
    } finally {
      await cleanup();
    }
  });
});

describe("turn-compat: 决策路径（A2 补丁面）", () => {
  const decisionCases: Array<{ name: string; decision: TurnDecision; text: string }> = [
    { name: "direct", decision: { kind: "direct", text: "东京明天 27℃，晴。" }, text: "东京明天 27℃，晴。" },
    { name: "silent", decision: { kind: "silent" }, text: "" },
  ];

  for (const c of decisionCases) {
    it(`${c.name}：provider 零调用（补丁前必然失败——公开 API 无生成前决策点）`, async () => {
      const bridge = new ScriptedBridge([{ text: "不应被消费" }]);
      const { adapter, cleanup } = await makeTurn(bridge);
      try {
        const out = await adapter.submitTurn(projection("【投影】查天气"), c.decision);
        expect(out).toEqual({ kind: c.decision.kind, text: c.text });
        expect(bridge.calls).toBe(0);
      } finally {
        await cleanup();
      }
    });
  }
});

describe("turn-compat: 隔离与复位", () => {
  it("两个群不串历史：独立 Core 实例互不可见（A1：每会话一实例）", async () => {
    const bridgeA = new ScriptedBridge([{ text: "A 回复" }]);
    const bridgeB = new ScriptedBridge([{ text: "B 回复" }]);
    const a = await makeTurn(bridgeA);
    const b = await makeTurn(bridgeB);
    try {
      await a.adapter.submitTurn(projection("群A的私密话题"));
      expect(bridgeB.calls).toBe(0);
      await b.adapter.submitTurn(projection("群B的话题"));
      expect(bridgeB.calls).toBe(1);
      // B 的请求里没有 A 的任何投影内容
      expect(JSON.stringify(bridgeB.requests[0])).not.toContain("群A的私密话题");
    } finally {
      await a.cleanup();
      await b.cleanup();
    }
  });

  it("reset 后不复活：清会话后新一轮请求只含新投影", async () => {
    const bridge = new ScriptedBridge([{ text: "第一轮" }, { text: "第二轮" }]);
    const { core, adapter, cleanup } = await makeTurn(bridge);
    try {
      await adapter.submitTurn(projection("会被清掉的话题"));
      // WebChat reset 的 Core 侧语义：清主会话上下文（fork 本就不持久化）
      await core.loop.clearSession();
      const proj2 = projection("清空后的新话题");
      await adapter.submitTurn(proj2);
      const second = bridge.requests[1]!;
      expect(second.input).toEqual(proj2.map(inputItem));
      expect(JSON.stringify(second.input)).not.toContain("会被清掉的话题");
    } finally {
      await cleanup();
    }
  });
});
