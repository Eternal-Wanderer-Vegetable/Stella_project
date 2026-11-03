# Aoede：主动参与子系统

中文 | [English](aoede.en.md) · [架构导航](README.md)

Aoede 是「是否、何时、对谁开口」的主动参与子系统（2026-11-03 计划 §3）：
机会/时机/预算/一次性求证调度。它与记忆子系统 [Mneme](mneme.md) 通过
`stella_contracts/aoede.py` 的中立端口交互，二者互不导入对方。

## 包布局（S1-02 起，正式实现）

| 模块 | 职责 | 原位置 |
| --- | --- | --- |
| `aoede/controller.py` | 活跃度、近期发言、临时 skip 状态 | `memory/proactive.py` |
| `aoede/gate.py` | 主动硬门禁 `can_speak` / `can_speak_for_scheduled` | `memory/proactive_gate.py` |
| `aoede/storage/legacy_state.py` | 旧 quota/mute/announce 持久状态（schema23 兼容区） | `memory/proactive_state.py` |
| `aoede/verification/target.py` | 主动 @ 选人编排 | `memory/proactive_target.py` |
| `aoede/prompts.py` | 主动表达指令、SKIP 标记 | `memory/proactive_prompt.py` |
| `aoede/contract.py` | 主动验证合同编排 | `memory/proactive_contract.py` |
| `aoede/participation/` | 参与评分决策层（buffer→state→score→decide） | `memory/participation/` |
| `aoede/host.py` | 宿主注入面（bot/发送/观测/引擎适配） | 新增 |
| `aoede/service.py` | 主动插话编排（外移自 ai_gateway） | `ai_gateway` 主动区 |
| `aoede/verification/service.py` | 主动 @ 编排与合同复核 | `ai_gateway` 主动验证区 |

## 装配与兼容

- `ai_gateway` 保留 scheduler 注册、适配器发现（`_sole_timer_qq_bot`）与
  薄委托；job 体在 `aoede.service.proactive_timer_tick`。
- 宿主依赖经 `aoede.host.ProactiveHost` 显式注入：可被测试替换的符号
  （`can_speak`、`get_proactive`、`pick_target`、`DB_PATH` 等）以
  「调用时经 gateway 模块属性转发」的 lambda 注入，既有 monkeypatch
  合同不变。
- `memory.proactive*` / `memory.participation` 是指向本包的显式别名：
  导入时自替换 `sys.modules`，新旧路径得到同一 module 对象
  （单例/缓存/monkeypatch 只有一份）。兼容层保留至少一个可回滚发布
  周期，删除须另设 gate。
- 任务注册表：主动后台任务统一登记（`aoede.service.background_tasks`
  与宿主 `register_task` 钩子），装配层关停时统一 drain，不双跑
  scheduler。

## 阶段二（未实施）

上下文优先的统一机会流程（`ParticipationOpportunity`、debounce、
SPEAK/WAIT/DROP）、一次性求证持久生命周期与 `PROACTIVE_FREQUENCY`
持久预算按 [计划](../plans/2026-11-03-gitnexus-plan-aoede-mneme-proactive-redesign.md)
§6.2–6.5 在阶段二落地；合同类型已在 `stella_contracts/aoede.py` 冻结。
