// SPDX-License-Identifier: AGPL-3.0
// Copyright (c) 2026 Stella Project Contributors
// 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
/**
 * Stella 的最小 Persona：只为 Cortico Core 提供轮次执行的承载面。
 *
 * 架构决定（docs/migration/cortico/compatibility-spike.md）：
 * - Stella 轮次走 **fork 通道**（`turn` 声明）：无状态、不持久化、初始 messages
 *   完全由 Python 侧投影提供 —— Core 不向模型上下文追加任何自身历史（BC-7）。
 * - `main` 声明仅满足 Core「恰好一个 persistent+receivesEvents 主会话」的构造
 *   约束（core.ts:163），不用于轮次；事件不注入，主循环空转。
 * - 所有生成语义（提示词、决策、投递）归桥接层；Persona 不携带 Stella 业务规则。
 */
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type {
  BlobStore,
  CoreApi,
  Persona,
  PrefixSegment,
  SessionDecl,
} from "../../../vendor/cortico/src/core/types.ts";

export class StellaPersona implements Persona {
  private core: CoreApi | null = null;

  /** 隔离目录：Persona 自身不落任何数据，仅满足 Core 的路径要求。 */
  readonly memoryDir: string = mkdtempSync(join(tmpdir(), "stella-persona-"));

  readonly blobs: BlobStore = {
    put: (name: string) => `mem:${name}`,
    get: () => null,
    list: () => [],
  };

  attach(core: CoreApi): void {
    this.core = core;
  }

  async systemSegments(): Promise<PrefixSegment[]> {
    // fork 轮次的 system 完全由投影提供；此段只存在于 main 会话（不用于轮次）。
    return [{ title: "STELLA", text: "Stella projection-owned runtime." }];
  }

  declareSessions(): SessionDecl[] {
    const turnRounds = { soft: 1, hard: 1, softHint: () => null };
    return [
      {
        id: "main",
        label: "stella-main",
        rounds: () => turnRounds,
        persistent: true,
        receivesEvents: true,
        tools: () => [],
      },
      {
        // fork 模板：恰好一次 provider 调用、零工具（BC-1/BC-2 的结构保险）。
        id: "turn",
        label: "stella-turn",
        rounds: () => turnRounds,
        persistent: false,
        receivesEvents: false,
        tools: () => [],
      },
    ];
  }
}
