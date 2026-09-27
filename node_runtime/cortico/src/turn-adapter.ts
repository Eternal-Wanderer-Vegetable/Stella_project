// SPDX-License-Identifier: AGPL-3.0
// Copyright (c) 2026 Stella Project Contributors
// 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
/**
 * 轮次适配器：把 Stella 的一次「已决策轮次」映射到 Cortico fork 通道。
 *
 * 职责边界（迁移计划 §6.3）：
 * - 输入是 Python prepare 的**最终投影**（messages）与**决策**（generate/direct/silent）；
 * - `generate` 经 `core.spawnFork` 交给真实 Core 执行（fork 单轮硬上限=1，恰好一次调用）；
 * - `direct`/`silent` 由上游 turn-policy 补丁在 provider 调用前结束轮次
 *   （patches/turn-policy.patch，计划 A2 预案）——不调用聊天模型；
 * - 适配器不解释、不重试、不兜底：异常原样上抛，语义归桥接层；
 * - 调用次数的权威记录在 ProviderBridge（provider-bridge.ts），不在本层伪造。
 */
import type { ContextRecord } from "../../../vendor/cortico/src/protocol/open-responses/context.ts";
import type { Core } from "../../../vendor/cortico/src/core/core.ts";

/** 与上游补丁 patches/turn-policy.patch 中的定义保持一致。 */
export type TurnDecision =
  | { kind: "generate" }
  | { kind: "direct"; text: string }
  | { kind: "silent" };

export interface TurnOutcome {
  kind: "generate" | "direct" | "silent";
  /** generate=模型输出；direct=决策携带文本；silent=空串。 */
  text: string;
}

export class TurnAdapter {
  constructor(private readonly core: Core) {}

  async submitTurn(
    projection: readonly ContextRecord[],
    decision: TurnDecision = { kind: "generate" },
  ): Promise<TurnOutcome> {
    // turnPolicy 由上游补丁提供（types.ts ForkOptions.turnPolicy）；
    // 补丁缺失时该字段被 Core 忽略 —— direct/silent 测试在补丁前必然失败（M1 纪律）。
    const text = await this.core.spawnFork({
      id: "turn",
      messages: [...projection],
      ...(decision.kind !== "generate" ? { turnPolicy: () => decision } : {}),
    } as Parameters<Core["spawnFork"]>[0]);
    return { kind: decision.kind, text };
  }
}
