// SPDX-License-Identifier: AGPL-3.0
// Copyright (c) 2026 Stella Project Contributors
// 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
/**
 * Stella Cortico host：随 Python 主进程生命周期的 Node 子进程（计划 §6.4 / M3）。
 *
 * 协议：NDJSON over stdio（stdout 专属协议，其余一切 stdout 写入重定向到
 * stderr——包括 vendor Core 的日志回显）。方法面：
 *   runtime.hello / session.ensure / turn.submit / turn.cancel /
 *   session.reset / runtime.drain / runtime.shutdown
 * 出站：provider.respond —— fork 的 ResponseClient 经它把最终 prompt 投影
 * 交回 Python 侧真实 LLM 后端（薄桥，不调用整个 Pipeline）。
 *
 * 所有权：每个会话一个 owner_epoch；旧 epoch 的 submit/reset 被拒（fence）。
 * 取消/超时：拒绝在途 provider 请求的 future → fork 抛错 → submit 返回
 * E_CANCELLED/E_DEADLINE，不产生任何平台副作用。
 *
 * 配置注入（env）：STELLA_RUNTIME_CONFIG（CoreConfig JSON，providers/
 * activeProvider 必填）、STELLA_RUNTIME_DATA_ROOT（各会话 dataDir 父目录）。
 */
import process from "node:process";
import { createInterface } from "node:readline";
import { randomUUID } from "node:crypto";
import { createResponse } from "../../../vendor/cortico/src/protocol/open-responses/index.ts";
import { message, type ContextRecord } from "../../../vendor/cortico/src/protocol/open-responses/context.ts";
import { Core } from "../../../vendor/cortico/src/core/core.ts";
import type { LoadedConfig } from "../../../vendor/cortico/src/core/config.ts";
import type {
  GenerateOptions,
  Generation,
  ProviderAttempt,
  ResponseClient,
} from "../../../vendor/cortico/src/core/generation.ts";
import type {
  CoreConfig,
  ForkOptions,
  TurnDecision,
} from "../../../vendor/cortico/src/core/types.ts";
import type { ItemOrigin } from "../../../vendor/cortico/src/protocol/open-responses/context.ts";
import { StellaPersona } from "./stella-persona.ts";

const PROTOCOL_VERSION = 1;
const MAX_FRAME_BYTES = 4 * 1024 * 1024;
const HOST_VERSION = 1;
const DRAIN_TIMEOUT_MS = 30_000;

const BRIDGE_ORIGIN: ItemOrigin = {
  instance: "stella-rpc-bridge",
  module: "stella-rpc-bridge",
  model: "python-provider",
  compatibilityDomain: "stella-rpc-bridge",
};

// ---- stdout 独占：协议帧走原生句柄，其余全部改道 stderr ----
const protoWrite = process.stdout.write.bind(process.stdout);
process.stdout.write = ((chunk: unknown, ...rest: unknown[]) => {
  process.stderr.write(chunk as string, ...(rest as []));
  return true;
}) as typeof process.stdout.write;

function send(env: Record<string, unknown>): void {
  const line = JSON.stringify(env);
  if (Buffer.byteLength(line, "utf8") + 1 > MAX_FRAME_BYTES) {
    process.stderr.write(`[host] 出站帧超限被丢弃（有界失败）\n`);
    return;
  }
  protoWrite(line + "\n");
}

function reply(reqId: string, result: Record<string, unknown>): void {
  send({ v: PROTOCOL_VERSION, id: reqId, kind: "response", ts: Date.now() / 1000, result });
}

function replyError(reqId: string, code: string, errMessage: string, retryable = false): void {
  send({
    v: PROTOCOL_VERSION, id: reqId, kind: "response", ts: Date.now() / 1000,
    error: { code, message: errMessage, retryable },
  });
}

// ---- 出站 provider 桥：一次 submit 一个实例（顺序请求，future 按关联 id） ----
type OutboundSender = (method: string, params: Record<string, unknown>) => Promise<Record<string, unknown>>;

class RpcBridge implements ResponseClient {
  private readonly pending = new Map<string, { resolve: (v: Record<string, unknown>) => void; reject: (e: Error) => void }>();

  constructor(
    private readonly key: string,
    private readonly sendRequest: OutboundSender,
  ) {}

  bind(): ResponseClient {
    return this;
  }

  /** host 取消/超时/reset 路径：拒绝全部在途 provider 请求。 */
  failAll(reason: Error): void {
    for (const [id, p] of this.pending) {
      this.pending.delete(id);
      p.reject(reason);
    }
  }

  async respond(request: Parameters<ResponseClient["respond"]>[0], _options?: GenerateOptions): Promise<Generation> {
    const reqId = randomUUID();
    const promise = new Promise<Record<string, unknown>>((resolve, reject) => {
      this.pending.set(reqId, { resolve, reject });
    });
    send({
      v: PROTOCOL_VERSION, id: reqId, kind: "request", method: "provider.respond",
      ts: Date.now() / 1000,
      params: { key: this.key, request: { model: request.model, input: request.input, tools: request.tools } },
    });
    const result = await promise;
    const text = String(result.text ?? "");
    const response = createResponse(randomUUID(), request);
    response.output = [message("assistant", text).item as (typeof response.output)[number]];
    const attempt: ProviderAttempt = {
      id: randomUUID(), generationId: response.id, ordinal: 0, origin: BRIDGE_ORIGIN,
      startedAt: new Date().toISOString(), elapsedMs: 0, requestId: null,
      responseId: response.id, outcome: "completed", status: 200, serviceTier: "default",
      charges: [],
      meters: { input: null, output: null, total: null, cachedInput: null, uncachedInput: null, reasoning: null, native: null },
    };
    return { response, origin: BRIDGE_ORIGIN, attempts: [attempt] };
  }

  /** host 读循环派发 provider.respond 的响应；返回是否命中本桥的在途请求。 */
  resolve(reqId: string, result: Record<string, unknown>): boolean;
  resolve(reqId: string, error: Error): boolean;
  resolve(reqId: string, payload: Record<string, unknown> | Error): boolean {
    const p = this.pending.get(reqId);
    if (!p) return false;
    this.pending.delete(reqId);
    if (payload instanceof Error) p.reject(payload);
    else p.resolve(payload);
    return true;
  }
}

// ---- 会话注册表 ----
interface TurnState {
  turnId: string;
  bridge: RpcBridge;
  controller: AbortController;
  deadlineTimer: NodeJS.Timeout | null;
  settled: boolean;
}

class SessionRegistry {
  private readonly epochs = new Map<string, number>();
  private readonly cores = new Map<string, Core>();
  private readonly bridges = new Map<string, RpcBridge>();
  private readonly inflight = new Map<string, TurnState>();
  /** 出站请求（provider.respond 等）的 future 登记表，读循环派发用。 */
  readonly outbound = new Map<string, { resolve: (v: Record<string, unknown>) => void; reject: (e: Error) => void }>();
  private shuttingDown = false;

  outboundSend(method: string, params: Record<string, unknown>): Promise<Record<string, unknown>> {
    return new Promise((resolve, reject) => {
      const id = randomUUID();
      this.outbound.set(id, { resolve, reject });
      send({ v: PROTOCOL_VERSION, id, kind: "request", method, ts: Date.now() / 1000, params });
    });
  }

  private loadConfig(): CoreConfig {
    const cfg = JSON.parse(process.env.STELLA_RUNTIME_CONFIG || "{}") as CoreConfig;
    if (!cfg.providers || !cfg.activeProvider) {
      throw new Error("缺少 STELLA_RUNTIME_CONFIG（providers/activeProvider）");
    }
    return cfg;
  }

  private dataDirFor(key: string): string {
    const dataRoot = process.env.STELLA_RUNTIME_DATA_ROOT || "stella-runtime-data";
    const safe = key.replace(/[^A-Za-z0-9_-]/g, "_").slice(0, 64);
    return `${dataRoot}/${safe}`;
  }

  /** 取得（或懒创建）会话 Core，并递增 owner_epoch。 */
  async ensure(key: string): Promise<number> {
    const epoch = (this.epochs.get(key) ?? 0) + 1;
    this.epochs.set(key, epoch);
    if (!this.cores.has(key)) {
      const cfg = this.loadConfig();
      const dataDir = this.dataDirFor(key);
      // 每会话独立 RPC 桥：Core 只见注入的 ResponseClient（headless，不触碰
      // provider 注册表——bundle 后动态发现不可用，也符合计划薄桥设计）
      const bridge = new RpcBridge(key, (method, p) => this.outboundSend(method, p));
      this.bridges.set(key, bridge);
      const core = new Core(
        {
          config: cfg,
          secret: () => (process.env.STELLA_RUNTIME_SECRET ?? "fake-key"),
          rootDir: dataDir,
          memoryDir: `${dataDir}/persona`,
          dataDir,
        } satisfies LoadedConfig<CoreConfig>,
        { persona: new StellaPersona(), worlds: [], llm: bridge },
      );
      await core.start();
      this.cores.set(key, core);
    }
    return epoch;
  }

  async submit(reqId: string, params: Record<string, unknown>): Promise<void> {
    const key = String(params.key ?? "");
    const turnId = String(params.turn_id ?? "");
    const ownerEpoch = Number(params.owner_epoch ?? 0);
    const deadlineMs = Number(params.deadline_ms ?? 0);
    const decision = (params.decision ?? { kind: "generate" }) as TurnDecision;
    const projection = (params.projection ?? []) as Array<{ role: "user" | "assistant" | "system" | "developer"; text: string }>;
    if (!key || !turnId) {
      replyError(reqId, "E_PROTOCOL", "key/turn_id 缺失");
      return;
    }
    if (this.epochs.get(key) !== ownerEpoch) {
      replyError(reqId, "E_KEY", `owner_epoch 过期（当前 ${this.epochs.get(key) ?? 0}）`);
      return;
    }
    if (this.inflight.has(key)) {
      replyError(reqId, "E_BUSY", "同会话已有在途轮次");
      return;
    }
    if (this.shuttingDown) {
      replyError(reqId, "E_HOST_GONE", "host 正在关闭");
      return;
    }
    const target = this.cores.get(key);
    if (!target) {
      replyError(reqId, "E_KEY", "会话未 ensure（先调 session.ensure）");
      return;
    }

    const bridge = new RpcBridge(key, (method, p) => this.outboundSend(method, p));
    const controller = new AbortController();
    const state: TurnState = { turnId, bridge, controller, deadlineTimer: null, settled: false };
    this.inflight.set(key, state);

    const settleError = (code: string, msg: string) => {
      if (state.settled) return;
      state.settled = true;
      if (state.deadlineTimer) clearTimeout(state.deadlineTimer);
      this.inflight.delete(key);
      bridge.failAll(new Error(msg));
      replyError(reqId, code, msg);
    };
    state.deadlineTimer = deadlineMs > 0
      ? setTimeout(() => settleError("E_DEADLINE", `轮次超过 ${deadlineMs}ms 截止`), deadlineMs)
      : null;

    // fork：messages 由投影构造（Python prepare 的最终 prompt）
    const messages: ContextRecord[] = projection.map((p) => message(p.role, p.text));
    const forkOpts: ForkOptions = {
      id: "turn",
      messages,
      ...(decision.kind !== "generate" ? { turnPolicy: () => decision } : {}),
    };
    try {
      const text = await target.spawnFork(forkOpts);
      if (state.settled) return;
      state.settled = true;
      if (state.deadlineTimer) clearTimeout(state.deadlineTimer);
      this.inflight.delete(key);
      const kind = decision.kind;
      reply(reqId, {
        outcome: kind,
        text: kind === "generate" ? text : kind === "direct" ? decision.text : "",
      });
    } catch (error) {
      const msg = error instanceof Error ? error.message : String(error);
      const code = controller.signal.aborted ? "E_CANCELLED" : "E_PROVIDER";
      settleError(code, msg);
    }
  }

  cancel(key: string, turnId: string): void {
    const state = this.inflight.get(key);
    if (!state || state.turnId !== turnId) return;
    state.controller.abort(new Error("轮次已被取消"));
    state.bridge.failAll(new Error("provider 调用已取消"));
  }

  async reset(key: string, ownerEpoch: number): Promise<void> {
    if (this.epochs.get(key) !== ownerEpoch) {
      throw new Error(`owner_epoch 过期（当前 ${this.epochs.get(key) ?? 0}）`);
    }
    const state = this.inflight.get(key);
    if (state) {
      state.controller.abort(new Error("reset 取消在途轮次"));
      state.bridge.failAll(new Error("reset 取消在途轮次"));
      this.inflight.delete(key);
      state.settled = true;
    }
    const core = this.cores.get(key);
    if (core) await core.loop.clearSession();
  }

  async drain(): Promise<number> {
    const deadline = Date.now() + DRAIN_TIMEOUT_MS;
    while (this.inflight.size > 0 && Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, 25));
    }
    return this.inflight.size;
  }

  async shutdown(): Promise<void> {
    this.shuttingDown = true;
    await this.drain();
    for (const core of this.cores.values()) {
      await core.stop();
    }
    this.cores.clear();
  }

  health(): Record<string, unknown> {
    return {
      keys: [...this.epochs.keys()],
      inflight: this.inflight.size,
      cores: this.cores.size,
    };
  }
}

// ---- 读循环 ----
async function main(): Promise<void> {
  const registry = new SessionRegistry();

  const rl = createInterface({ input: process.stdin, crlfDelay: Infinity });
  rl.on("line", (line) => {
    if (!line.trim()) return;
    if (Buffer.byteLength(line, "utf8") > MAX_FRAME_BYTES) {
      process.stderr.write("[host] 入站帧超限，断链（有界失败）\n");
      process.exit(2);
    }
    let env: Record<string, unknown>;
    try {
      env = JSON.parse(line);
    } catch (e) {
      // 单帧损坏不中断进程：记 stderr；请求方超时路径负责有界失败
      process.stderr.write(`[host] 入站帧解析失败: ${e}\n`);
      return;
    }
    void dispatch(env);
  });
  rl.on("close", () => {
    // Python 侧断管：尽快退出（无僵尸）
    process.exit(0);
  });

  async function dispatch(env: Record<string, unknown>): Promise<void> {
    const id = String(env.id ?? "");
    const kind = env.kind;
    try {
      if (kind === "response") {
        const p = registry.outbound.get(id);
        if (p) {
          registry.outbound.delete(id);
          if (env.error) p.reject(new Error(String((env.error as Record<string, unknown>).message)));
          else p.resolve((env.result ?? {}) as Record<string, unknown>);
          return;
        }
        // provider.respond 等桥内出站请求的响应：路由给对应会话桥
        for (const bridge of registry.bridges.values()) {
          if (bridge.resolve(id, env.error ? new Error(String((env.error as Record<string, unknown>).message)) : (env.result ?? {}) as Record<string, unknown>)) {
            return;
          }
        }
        return;
      }
      if (kind !== "request") return;
      const method = String(env.method ?? "");
      const params = (env.params ?? {}) as Record<string, unknown>;
      switch (method) {
        case "runtime.hello":
          reply(id, {
            host_version: HOST_VERSION, protocol_version: PROTOCOL_VERSION,
            node: process.version, ...registry.health(),
          });
          return;
        case "session.ensure": {
          const epoch = await registry.ensure(String(params.key ?? ""));
          reply(id, { owner_epoch: epoch });
          return;
        }
        case "turn.submit":
          await registry.submit(id, params);
          return;
        case "turn.cancel":
          registry.cancel(String(params.key ?? ""), String(params.turn_id ?? ""));
          reply(id, { cancelled: true });
          return;
        case "session.reset":
          await registry.reset(String(params.key ?? ""), Number(params.owner_epoch ?? 0));
          reply(id, { reset: true });
          return;
        case "runtime.drain": {
          const pending = await registry.drain();
          reply(id, { pending });
          return;
        }
        case "runtime.shutdown": {
          const pending = await registry.shutdown();
          reply(id, { pending });
          setTimeout(() => process.exit(0), 50);
          return;
        }
        default:
          replyError(id, "E_UNSUPPORTED", `未知方法: ${method}`);
      }
    } catch (error) {
      replyError(id, "E_PROVIDER", error instanceof Error ? error.message : String(error));
    }
  }

  await new Promise(() => {});
}

void main().catch((e) => {
  process.stderr.write(`[host] fatal: ${e}\n`);
  process.exit(1);
});
