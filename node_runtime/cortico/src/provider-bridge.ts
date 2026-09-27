// SPDX-License-Identifier: AGPL-3.0
// Copyright (c) 2026 Stella Project Contributors
// 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
/**
 * Provider 桥：Core 的 ResponseClient 注入点。
 *
 * `ScriptedBridge`（M1 spike）：按脚本返回固定文本、记录每次请求、支持外部取消——
 * 用于固定 provider request 等价与调用次数验收（计划 M1 试验清单）。
 * M3 的 RpcBridge 将以同一接口把 request 投影转发给 Python 侧真实 LLM 后端
 * （薄桥，不调用整个 Pipeline），取消经 options.signal 贯穿。
 */
import { randomUUID } from "node:crypto";
import { createResponse } from "../../../vendor/cortico/src/protocol/open-responses/index.ts";
import { message } from "../../../vendor/cortico/src/protocol/open-responses/context.ts";
import type {
  GenerateOptions,
  Generation,
  ProviderAttempt,
  ResponseClient,
} from "../../../vendor/cortico/src/core/generation.ts";
import type { Request } from "../../../vendor/cortico/src/protocol/open-responses/index.ts";
import type { ItemOrigin } from "../../../vendor/cortico/src/protocol/open-responses/context.ts";

const BRIDGE_ORIGIN: ItemOrigin = {
  instance: "stella-bridge",
  module: "stella-bridge",
  model: "scripted-model",
  compatibilityDomain: "stella-bridge",
};

function completedAttempt(responseId: string): ProviderAttempt {
  return {
    id: randomUUID(),
    generationId: responseId,
    ordinal: 0,
    origin: BRIDGE_ORIGIN,
    startedAt: new Date().toISOString(),
    elapsedMs: 0,
    requestId: null,
    responseId,
    outcome: "completed",
    status: 200,
    serviceTier: "default",
    charges: [],
    meters: { input: null, output: null, total: null, cachedInput: null, uncachedInput: null, reasoning: null, native: null },
  };
}

export interface ScriptedStep {
  /** 本步返回正文。 */
  text?: string;
  /** 本步抛出该错误（provider 异常路径）。 */
  throw?: unknown;
}

export class ScriptedBridge implements ResponseClient {
  /** 每次收到的请求快照（断言 provider request 等价）。 */
  readonly requests: Request[] = [];
  private readonly script: ScriptedStep[];

  constructor(script: ScriptedStep[]) {
    this.script = [...script];
  }

  /** Core 在每次请求前 bind；桥无按请求状态，返回自身。 */
  bind(): ResponseClient {
    return this;
  }

  get calls(): number {
    return this.requests.length;
  }

  async respond(request: Request, _options?: GenerateOptions): Promise<Generation> {
    this.requests.push(request);
    const step = this.script.shift();
    if (!step) throw new Error("ScriptedBridge 脚本耗尽：调用次数超出场景声明");
    if (step.throw !== undefined) throw step.throw;
    const text = step.text ?? "";
    const response = createResponse(randomUUID(), request);
    response.output = [message("assistant", text).item as (typeof response.output)[number]];
    return { response, origin: BRIDGE_ORIGIN, attempts: [completedAttempt(response.id)] };
  }
}
