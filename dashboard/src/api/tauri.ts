// SPDX-License-Identifier: AGPL-3.0
// Copyright (c) 2026 Stella Project Contributors
// 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
/** 桌面壳（Tauri）窄契约的类型化封装（方案 §4 D5 / §11）。

 仅在壳内（tauri:// 源、`window.__TAURI__` 存在）可用；浏览器里 `isTauri`
 为 false，页面走纯 HTTP。命令集 = desktop/src-tauri/src/commands.rs 的
 离线窄契约：启动/等待就绪/自检/迁移/配置/日志。
 */

/* eslint-disable @typescript-eslint/no-explicit-any */
type Invoke = (cmd: string, args?: Record<string, unknown>) => Promise<unknown>;

function tauri(): Invoke | null {
  const w = window as any;
  return w.__TAURI__?.core?.invoke ?? null;
}

export const isTauri = (): boolean => tauri() !== null;

async function invoke<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  const fn = tauri();
  if (!fn) throw new Error("不在桌面壳环境中");
  return (await fn(cmd, args)) as T;
}

export const tauriBridge = {
  /** 启动 Bot（首次会先准备嵌入式运行时，可能耗时数分钟）。 */
  startBot: (force = false) => invoke<string>("start_bot", { force }),
  /** 轮询状态接口直到就绪，返回在线面板基地址。timeoutSecs=0 表示「立即探测一次」。 */
  waitBotReady: (timeoutSecs = 120) =>
    invoke<string>("wait_bot_ready", { timeoutSecs }),
  /** 环境自检（deploy doctor 文本报告）。 */
  runDoctor: () => invoke<string>("run_doctor"),
  /** 读取日志尾部。 */
  logTail: (maxBytes = 65536) => invoke<string>("read_log_tail", { maxBytes }),
};
