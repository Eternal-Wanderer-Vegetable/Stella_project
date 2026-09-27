# Compatibility Spike（M1 阻断门槛）结论

> 日期：2026-09-27。分支 `feat/cortico-runtime-migration`。
> 结论：**通过 —— 附一个最小通用上游补丁（turn-policy）**。M2 起可以开始迁移领域阶段。
> 全部试验在真实 Cortico Core（vendor 固定快照）上执行，无 mock Core。

## 1. 固定与构建

| 项 | 结果 |
| --- | --- |
| vendor 快照 | `vendor/cortico/` @ `bc47c824d388345f1c13722f4a05a5f745a028f8`（v0.1.4，MIT），793 文件/11MB，`git archive` 导出 |
| 工具链 | pnpm 11.5.0（packageManager 自动委派）+ Node 24.20.0（满足 >=22） |
| 安装 | `pnpm install --ignore-scripts`：跳过 canvas 原生构建；**core 闭包不需要 canvas/mineflainer/express/react 任何一个**（core/protocol/providers 仅依赖纯 JS 的 fflate+tar-stream，见 upstream-lock.json） |
| 上游测试 | `tests/core` **39 文件 / 493 用例全绿**（490 上游原有 + 3 补丁单测），Windows 本机 |
| headless | `new Core(loaded, {persona, worlds: [], llm})` 无端口、无 World 依赖；instance-lock 属 bot 层，Core 不调用（同进程多实例实测无互斥） |

## 2. 架构决定：fork 通道承载 Stella 轮次

Core 常驻主会话全局唯一且历史必然进 prompt —— 直接使用会违反 BC-7（Core 事件历史不得进入模型上下文）。原型采用 **`spawnFork` fork 通道**作为轮次执行器：

- 初始 messages 完全由调用方（Python 投影）提供，**Core 不向模型上下文追加任何内容**（provider request 等价试验证实，`req.input === proj.map(inputItem)`）；
- fork 不持久化、天然按轮隔离 → 每群一个 Core 实例（A1）各自独立 dataDir，互不可见；
- fork 失败**无重试**（异常直接上抛）→ 「恰好一次 provider 调用」在异常路径也成立，无需透传 resubmit；
- `rounds hard=1 + tools=[]` 是调用上限的结构保险（Provider/Planner 计数语义留在 Python 侧，M2 落地）。

## 3. 补丁（计划 A2 预案，最小通用接口）

| 项 | 内容 |
| --- | --- |
| 触及文件 | `src/core/types.ts`（+`ForkOptions.turnPolicy`、`TurnDecision` 类型）、`src/core/fork.ts`（runForkLoop 开头 ~7 行决策点）、`src/core/core.ts`（spawnFork 透传 1 行）、新增 `tests/core/fork-turn-policy.test.ts` |
| 语义 | `direct`：不调用 provider、不产生 assistant 记录，返回决策文本；`silent`：同上返回空串；`generate`/未提供：行为与上游逐字节一致 |
| 维护理由 | 公开 API 无生成前决策点（试验：direct/silent 用例补丁前必然失败——`tests/turn-compat.test.ts` 保留该历史语义注释）；不承载任何 Stella 业务规则 |
| 上游单测 | 3 用例随 `tests/core` 套件运行（direct/silent/generate+异步 policy） |
| 重放检查 | pristine 快照 + `patch -p1 < patches/turn-policy.patch` → 与 vendor 当前文件**逐字节一致**（2026-09-27 验证）；哈希对账：`pnpm --dir node_runtime/cortico verify-patches` |

## 4. 试验结果（计划 M1「试验」清单）

| 试验 | 结果 | 证据 |
| --- | --- | --- |
| 普通 1 次调用 | ✅ | `turn-compat` normal_single_call，bridge.calls===1 |
| direct 0 次 | ✅（补丁后） | `turn-compat` direct 用例，calls===0（补丁前失败，符合预期） |
| silent 0 发送 | ✅（补丁后） | silent 用例，calls===0、返回空串 |
| Planner 受控次数 | ✅ 结构等价 | fork hard=1 + Python Planner 留在 prepare（M2）；Core 侧无第二次调用通道 |
| 固定 provider request 等价 | ✅ | `req.input` 逐条等于投影；`req.tools` 空；无 Core 系统段/历史 |
| 容量检查等价 | ✅（设计等价） | fork 路径无容量门；8K 预算唯一权威是 Python `fit_prompt_to_window`（BC-6），投影即最终 prompt |
| 无额外工具循环 | ✅ | tools=[] + 单轮硬上限；异常路径无重试 |
| 两个群不串历史 | ✅ | 每 Core 独立实例/dataDir；B 的请求不含 A 的投影内容 |
| reset 后不复活 | ✅ | `clearSession` 后新一轮请求只含新投影；fork 本不持久化 |
| 批处理不合并独立轮次 | ✅ | fork 无批处理语义；两轮各自精确投影 |
| 取消与退出 | ✅（桥层模型） | provider 中途失败→spawnFork 拒绝→stopAll 干净收尾；信号贯穿为 M3 RPC 桥实现项 |

## 5. 资源门槛（`pnpm --dir node_runtime/cortico measure`，排除模型推理）

| 指标 | 拟议门槛 | 实测 | 判定 |
| --- | --- | --- | --- |
| 轮次提交延迟 p95 | ≤100ms | **2.2ms**（200 轮/20 实例，纯桥开销） | ✅ |
| RSS 总增量（20 会话在途） | ≤150MiB | **67.1MiB** | ✅ |
| 冷启动增量 | ≤3s | **9ms/实例**（20 实例并发创建 187ms 总） | ✅ |

100 会话为诊断扩展性场景，按线性外推 ~330MiB 留待 M3 host 池化 + idle 回收后复测。

## 6. 发布可行性

- Windows：本机验证通过（安装/构建/测试/补丁重放）；Node 22+ 与 pnpm 11.5.0 为发行依赖，M8 纳入各渠道。
- Docker：现状 Dockerfile 无 Node（记录于 feature-parity.md §I）；core 闭包纯 JS 意味着运行镜像只需 Node 二进制 + 编译产物，无需原生依赖。真实产物验收按计划归 M8。
- `pnpm-workspace.yaml`（allowBuilds esbuild）与本包 lock 独立于 dashboard，符合「锁文件分别固定」。

## 7. 退出条件核对（计划 M1）

行为与发布可行性均通过：direct/silent/普通调用/prompt 等价/隔离/reset/不合并全部成立；补丁最小、有上游单测与重放检查；资源门槛大幅优于预算。**门槛通过，M2 可以开始。**
