# MBENCH-005 阶段报告：记忆可靠性栈生产化（灰度集成）

- 日期：2026-11-02
- 分支：`codex/memory-benchmark`（PR #127，draft）
- 状态：**集成完成；生产默认行为未变**（两旗标默认 off，灰度由用户执行）
- 前置：MBENCH-004 P4 验收（有条件通过，docs/reports/2026-11-02-mbench004-p4-production-validation.md）

## 交付内容

| 项 | 实现 | 生产默认 |
| --- | --- | --- |
| T3 记忆包表示 | `memory/prompt_builder.py`：`MEMORY_PACK_METADATA_MODE=full` 时聊天素材条目追加 `｜确认 YYYY-MM-DD`（数据来自记忆行既有列，零额外开销） | off（逐字节兼容，测试钉死） |
| 充分性验证器 | `memory/sufficiency_guard.py`（新模块）：ROLE_EXTRACT 对整包判定三态；`MEMORY_SUFFICIENCY_GUARD_MODE=off/shadow/enforce`；turn_service.prepare_turn 接线 | off（不进入该代码路径） |
| 弃答语义（enforce） | INSUFFICIENT 硬短路：固定文案经正常投递链路（`delivery_source_kind=memory-sufficiency-abstention`）；AMBIGUOUS 在记忆分节追加保守作答指令 | — |
| runbook | `docs/guides/memory-tuning.md`（.en 同步）：P4-6 验证栈的 .env 一览、灰度顺序、回退条件（退化 >5pp 即回退） | — |

## 可靠性设计（全部 fail-open）

验证器任何前置不满足都放行正常作答：ROLE_EXTRACT 无后端、每日预算拦截（`budget_blocked`）、
包为空、调用异常/超时、判定不可解析（保守 AMBIGUOUS→仅追加指令）。测试覆盖五条 fail-open
路径与 shadow/enforce/off 三种模式的接线行为（tests/test_memory_reliability_flags.py，13 用例）。

## 兼容性硬门禁

旗标 off 时 `build_v2_named_sections` 输出**逐字节一致**（既有字节兼容/前缀稳定套件
原样通过：test_multi_user_identity 15 passed、test_prompt_cache_prefix 等合计 44 passed）。
memory_eval 评测包零改动。

## 已知事项（如实记录）

1. **既有测试顺序干扰（非本 PR 引入）**：`tests/test_attribution_wiring.py + tests/test_memory_eval.py`
   同进程依序运行会在 message_flow 队列线程上悬挂（最小对复现；暂存本 PR 改动后依然复现；
   单文件与多数组合均绿）。复现命令与根因定位（flow 线程 queue.get 残留）已记录，
   修复属测试基建课题，不在本 PR。
2. 生产 user_id→名字映射不存在（探索确认）：T3 归属标注沿用 `用户(uid)` 惯例；
   `conversation_identity.subject_alias`（自介绍别名）可作后续增强。
3. sufficiency.guard 节点未注册 flow_catalog（未注册节点优雅降级为 UI unmapped），
   避免 manifest 级联；如需 UI 呈现再补。

## 验收对照（P4-6 建议 → 本 PR）

- 每项独立 env 旗标 ✓（权重/检索门/阈值本就是 .env 配置，runbook 给出验证值）
- 默认不改变生产行为 ✓（off 逐字节兼容测试）
- 回退条件文档化 ✓（runbook：退化 >5pp 即回退对应旗标）
- P4-2 judge 人工复核 ✓（2026-11-02 完成：一致率 90.0%、零过宽，见 P4 报告 §P4-2）

## 门禁

tests/test_memory_reliability_flags.py 13 passed；既有回归分组全绿（44+15+32）；
`ruff check .` 全清；`check_docs.py` 123 files / 0 errors。