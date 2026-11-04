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

## 阶段二：统一机会流程（S2-02…S2-03 已落地）

- **机会/时机层**（`aoede/opportunity.py`）：每会话唯一在途机会；新消息推进
  context revision、重置静默计时并合并（原 expiry 不顺延）；可取消 debounce
  （内部 3s）+ TTL（内部 15s）到点 DROP。硬预检只含总开关/静音/睡眠/醒来
  缓冲；旧掷骰与 15 条门槛不再前置阻断；600 秒冷却保留为内部安全下限（拦截
  在开火时）。`memory=[]` 不是开口前提：context-only 参与照常进行。
- **一次性求证**（S2-01）：Mneme 持有 attempts + 拒绝 tombstones
  （`mneme/verification.py`，schema24）。预留先于发送；ACK 后 deadline =
  ACK+300s；保守绑定（同会话同主体 + 显式回复问题片段）；DENIED/UNCLEAR/
  UNANSWERED 终态 + tombstone + 候选 CAS 拒绝；写侧（consolidator）与晋升侧
  （memory_manager）都校验旧证据重放，合法新证据可开新 generation；确认只
  记录关系，不自动晋升。用户级 no_reply 退避与自然度 skip 是社交退避，
  不会清除 tombstone。
- **持久预算**（`aoede/budget.py`，S2-03）：唯一用户数值
  `PROACTIVE_FREQUENCY`（0–6 次/小时，默认 1.0；R=0 绝对关闭普通主动参与与
  自发睡眠/苏醒播报）。token bucket 容量 1、初始 0、按 UTC 墙钟补充；同一
  会话的插话/验证 ASK/自发播报共用一桶；ACK commit、确定未发 release、
  UNKNOWN 保守消耗；store 不可用 fail closed。被动回复与用户预约任务不经此桶。
- 定时任务（S2-02 起）只做睡眠播报、机会恢复与验证 ASK 的**公平提交**——
  不再有「主动 @ 优先」。

已知边界（截至本轮）：播报与插话路径的 UNKNOWN 结算为保守消耗，不自动重投；
2026-11-04 本机 Windows `_native.pyd` 已确认导出 API 4/schema 24，Rust selector
可选中该模块；临时数据库 fullchain 通过原生检索冒烟及 Python/native 晋升 parity
（`differ=false`）。旧 wheel 会因合同不匹配而拒绝 schema24，并按模式安全回落或报错。
本机验证不等同于 Release payload、干净 Windows VM 或安装/回滚验收。
阶段验收矩阵见 [计划](../plans/2026-11-03-gitnexus-plan-aoede-mneme-proactive-redesign.md) §8。
