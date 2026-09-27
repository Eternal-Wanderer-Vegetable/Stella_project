// SPDX-License-Identifier: AGPL-3.0
// Copyright (c) 2026 Stella Project Contributors
// 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
/**
 * 会话宿主：按 conversation_key 懒创建并持有独立 Core 实例（计划假设 A1）。
 *
 * - 每个逻辑对话一个 Core、一个独立 dataDir：会话历史、事件库、用量互不可见；
 * - key 由桥接层给定（QQ: 平台/机器人身份/group_id；WebChat: 独立命名空间），
 *   本层只做文件名安全化（sha256 短摘要），不解释语义；
 * - instance-lock 属 bot 层，Core 不调用 —— 同进程多实例不互斥（M1 实测确认）。
 */
import { createHash } from "node:crypto";
import { join } from "node:path";
import { Core } from "../../../vendor/cortico/src/core/core.ts";
import type { ResponseClient } from "../../../vendor/cortico/src/core/generation.ts";
import type { LoadedConfig } from "../../../vendor/cortico/src/core/config.ts";
import { StellaPersona } from "./stella-persona.ts";
import { TurnAdapter } from "./turn-adapter.ts";

export interface ConversationEntry {
  readonly key: string;
  readonly core: Core;
  readonly adapter: TurnAdapter;
  lastUsedAt: number;
}

export interface ConversationHostOptions {
  /** 各会话 dataDir 的父目录（host 级运行目录）。 */
  dataRoot: string;
  /** LoadedConfig 工厂：host 仅覆写 dataDir，其余字段（config/secret）由装配层给定。 */
  makeLoaded: (dataDir: string) => LoadedConfig;
  /** provider 桥工厂：每会话独立一份（M3 起携带会话身份路由回调）。 */
  makeBridge: () => ResponseClient;
}

export class ConversationHost {
  private readonly entries = new Map<string, ConversationEntry>();

  constructor(private readonly opts: ConversationHostOptions) {}

  /** 已知会话数（诊断面）。 */
  get size(): number {
    return this.entries.size;
  }

  keys(): string[] {
    return [...this.entries.keys()];
  }

  /** 取得（或懒创建）会话条目。 */
  async acquire(key: string): Promise<ConversationEntry> {
    const found = this.entries.get(key);
    if (found) {
      found.lastUsedAt = Date.now();
      return found;
    }
    const dir = join(this.opts.dataRoot, sha12(key));
    const bridge = this.opts.makeBridge();
    const persona = new StellaPersona();
    const core = new Core(this.opts.makeLoaded(dir), { persona, worlds: [], llm: bridge });
    await core.start();
    const entry: ConversationEntry = {
      key,
      core,
      adapter: new TurnAdapter(core),
      lastUsedAt: Date.now(),
    };
    this.entries.set(key, entry);
    return entry;
  }

  /** 回收空闲会话：停止并移除 lastUsedAt 早于 maxIdleMs 的实例。返回被回收的 key。 */
  async reclaimIdle(maxIdleMs: number, now = Date.now()): Promise<string[]> {
    const reclaimed: string[] = [];
    for (const [key, entry] of this.entries) {
      if (now - entry.lastUsedAt >= maxIdleMs) {
        await entry.core.stop();
        this.entries.delete(key);
        reclaimed.push(key);
      }
    }
    return reclaimed;
  }

  /** 停止全部会话（进程关闭路径；drain 由调用方在提交侧先行完成）。 */
  async stopAll(): Promise<void> {
    for (const entry of this.entries.values()) {
      await entry.core.stop();
    }
    this.entries.clear();
  }
}

function sha12(key: string): string {
  return createHash("sha256").update(key).digest("hex").slice(0, 12);
}
