# 开发指南

[中文](development.md) | [English](development.en.md)

本文覆盖测试、探针脚本、CI 与贡献流程。架构见 [架构说明](architecture.md)，配置见 [配置参考](configuration.md)。

## 环境准备

```bash
git clone https://github.com/Eternal-Wanderer-Vegetable/Stella_project.git
cd Stella_project
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

`requirements-dev.txt` 包含 pytest、ruff、numpy 等开发期依赖。numpy 只被 embedding fixture 的向量计算用到，缺失时相关测试会跳过而非报错。

### 开发机的用户数据放在 `StellaData/`

仓库根目录下的 `StellaData/`（整体 gitignore）是本机的**用户数据目录**（`STELLA_HOME`）：

```text
Stella_project/
  StellaData/          ← 你的 .env、记忆库、空间配置、人格、插件数据、日志
    .env  deploy.answers.toml
    memory/  config/spaces/  system_prompts/  data/  logs/
  bot.py  config/  deploy/  memory/  …   ← 代码
```

`config/home.py` 的第 4 条（便携模式）会命中它，于是**仓库、发布包、运行期的相对布局是同一套**
——都是「数据在 `StellaData/` 里」，区别只在这个目录挂在哪一级。

已有的老工作副本（数据散在仓库根上）不受影响：`config/home.py` 的第 3 条会认出「旧布局」并就地使用。
想迁过来的话，把 `.env`、`deploy.answers.toml`、`memory/`、`config/spaces/`、`system_prompts/`、
`data/`、`logs/` 移进 `StellaData/` 即可，路径常量全部跟着 `STELLA_HOME` 走，不用改代码。
`python -m deploy paths` 会告诉你当前解析到了哪里、走的是哪一条规则。

**不要把数据目录提交进仓库**：`.gitignore` 里有 `StellaData/`，`release.yml` 的 rsync
排除清单里也有，`scripts/check_release_layout.py` 会在发布前再拦一道。三层都是刻意的——
这个目录装着真实的 `.env` 与聊天记录，一旦随发布包出门就收不回来。

## 部署工具

`deploy/` 是「检查逻辑全在 Python 侧、GUI 只是渲染器」的部署工具：doctor 输出结构化 JSON，
桌面安装器（Tauri）调用它并渲染，换 GUI 框架不用重写逻辑。六个子命令：

| 命令 | 用途 |
|---|---|
| `python -m deploy doctor [--json]` | 环境自检；`--json` 输出结构化结果（id/level/title/detail/fix_hint），供 GUI 做图标与本地化映射 |
| `python -m deploy init [--answers PATH] [--force] [--dry-run]` | 交互式生成 `.env`（基于 `.env.example` 逐行替换，模型 ID 从 LM Studio 拉列表选编号）；`--answers` 复用上次的 `deploy.answers.toml`，换机器重装 / CI 冒烟 / GUI（`save_config`）复用同一份答案 |
| `python -m deploy start [--force] [--detach]` | 先跑 doctor，无阻塞问题（或 `--force`）后启动 `bot.py`；`--detach` 后台启动并写 PID 到 `logs/stella.pid`（GUI 用） |
| `python -m deploy status [--json]` | 读 PID 文件报进程是否存活，并从 JSON 日志尾部推断最近状态（`link_status` 在 Bot 进程内，外部读不到） |
| `python -m deploy stop` | 优雅停止：写停止哨兵 → 轮询等待 → 降级信号 → 硬杀兜底（见下）；Tauri 安装器与 `bot.py` 位于同一发布目录 |
| `python -m deploy config-schema --json` | 输出 `settings.py` 的配置 schema（分组、默认值、注释），GUI 的「高级选项」表单据此生成 |
| `python -m deploy migrate [--from 旧目录] [--dry-run] [--fresh-runtime]` | 从旧版本安装目录导入用户数据并升级数据库；只读旧目录，报告写 `migration_report.md` |
| `python -m deploy space-merge --from a,b --to c [--dry-run]` | 合并共享空间（记忆 + 画像 + FTS + 账本），替代过去要用户手搓的一串 UPDATE |
| `python -m deploy paths [--env-file]` | 输出解析后的程序目录 / 用户数据目录等路径；`--env-file` 只打印 `.env` 路径（`start.bat` 用） |
| `python -m deploy manifest [--write]` | 生成发布包清单 `.stella-manifest.json`（升级时据此判断用户是否改过自带文件），release CI 调用 |

分层：`probe` 采集（有副作用）→ `checks` 判断（纯函数，测试重点）→ `report` 渲染。
检查函数的判据与 ai_gateway 的实际行为保持一致（例如人格文件缺失在代码里只是 warning，
doctor 也就报 warn），避免「明明能跑却提示 error」。

**每次改 `checks.py` 或 `report.py`，顺手重新导出一次 mock**（前端/安装器用真实结构预览，
避免结构与后端漂移）：

```bash
python -m deploy doctor --json > stella-installer/src/mock/doctor-clean.json
```

`doctor-mixed.json`（带 items 的场景）需要手工构造，保持字段结构与 `doctor-clean.json` 一致、
`summary.ok = total - error - warn` 自洽。

### 停止链路（哨兵优先）

1. **Windows 下 GUI 与 Bot 不共享控制台**：安装器用 `CREATE_NO_WINDOW(0x08000000)` 启动
   Bot，子进程根本没有控制台，`GenerateConsoleCtrlEvent` 发的 `CTRL_BREAK` 永远送不到
   （实测）。任何依赖控制台事件的停止方案在 GUI 场景必然失效——停止链路的唯一可靠入口是
   文件哨兵（`core/stop_signal.py`，默认路径项目根 `.stella-stop-request`）。
2. **哨兵文件的三方契约**：deploy 写（`deploy/process.py` 的 `stop()`）→ Bot 读并自杀
   （`ai_gateway.watch_stop_request()` 观察到后触发 uvicorn 优雅关闭）→ Bot 启动时先清残留
   （`_start_stop_watcher` 里最早执行）。三者缺一则要么停不了，要么一启动就自杀。
3. **deploy 侧等待 = grace + 缓冲**：Bot 侧 `_graceful_shutdown()` 最长等
   `SHUTDOWN_GRACE_SECONDS(30)`。deploy 的等待窗口必须严格大于它（`STOP_WAIT_BUFFER_SECONDS`，
   与 grace 成比例），否则会在 Bot 收尾的瞬间硬杀，白等一场。

设计取舍：不用 `POST /shutdown`——status_api 只读，加写接口就多一个无鉴权的写接口，
`HOST=0.0.0.0` 时就是局域网可触发的远程关机；哨兵靠文件系统权限天然只限本机用户。
哨兵文件是运行期产物，已加入 `.gitignore` 与 `release.yml` 的排除清单与敏感文件校验。

**前端契约**：`deploy doctor --json`、`deploy config-schema --json` 与 `deploy paths` 是 GUI 的
数据契约，改结构要 bump schema 的 `version` 字段并同步 `stella-installer/src/mock/`。
`deploy migrate` 返回的是 Markdown 报告原文（同一份内容也会写进 `migration_report.md`，
只生成一次就不会两处不一致），GUI 直接以等宽文本渲染。

**GUI 不自己判断用户数据目录在哪**：`python::data_root()` 去问 `deploy paths`。判据只有
`config/home.py` 一份——两处各写一套会出现「一边读旧目录、一边写新目录」，症状是
「保存成功但没生效」。

**GUI 依赖的两处格式约定**：
- `config/spaces/*.toml` 由安装器写入的文件以 `# Managed by Stella installer` 开头，
  改写该头或格式会影响 GUI 的「是否由安装器管理」判断；
- `config/settings.py` 的章节注释（`# ---------- 标题 ----------`）决定配置分组，写新配置
  项时保持该格式，GUI 才能正确归类（`deploy config-schema --json` 是分组结果的唯一事实来源）。

## 提交前检查

```bash
python -m pytest tests -q
ruff check .
```

两条都必须通过。CI 会跑同样的检查（外加 3.10/3.11/3.12 三个版本）。

## 测试

### 运行

```bash
# 全部
python -m pytest tests -q

# 单文件 / 单用例
python -m pytest tests/test_memory_manager.py -v
python -m pytest tests/test_candidate_reinforcement.py::test_gate1_high_confidence_promotes_immediately -v

# 覆盖率
python -m pytest tests --cov=core --cov=memory --cov-branch --cov-report=term -q

# 并行（CI 采用）
python -m pytest tests -n auto --dist loadgroup
```

全部测试使用临时数据库与假 LLM 后端，**不依赖真实机器人、网络或 LM Studio 服务**。

### 测试清单

| 文件 | 覆盖内容 |
|---|---|
| `test_memory_manager.py` | 候选晋升与观察的基础行为 |
| `test_memory_manager_v2.py` | 冲突检测、v2 元字段持久化 |
| `test_memory_manager_fts_sync.py` | FTS 索引与 `memories` 表同步、过期索引自动重建 |
| `test_candidate_reinforcement.py` | 候选强化（累积证据）、Gate 1 三档、超期淘汰、配额竞争 |
| `test_cross_user_isolation.py` | 三条合并路径都不得跨用户（含反向用例） |
| `test_consolidator_core.py` | 整合内部流程、越权候选隔离、JSON 容错解析 |
| `test_consolidation_prompt.py` | 整合 prompt 的防编造条款护栏 |
| `test_source_kind.py` | 来源分级的落库与 prompt 标注 |
| `test_bot_self_source.py` | `BOT_SELF` 标注正确且不进候选白名单 |
| `test_context_tail.py` | 短期上下文：摘要与原始尾巴并存、时间正序 |
| `test_short_term_attribution.py` | 短期记忆的说话人归属 |
| `test_policy.py` | Mode 检测、三层过滤、排序、候选校验 |
| `test_retrieval_v2_and_schema.py` | v2 检索与 Schema 迁移 |
| `test_migrations.py` | 旧库迁移回归：v5（2.2.0）与 v9（3.0.0）两条真实起点必须常绿，`SCHEMA_VERSION` 每 +1 都要在这里加一个起点用例 |
| `test_space_merge.py` | 空间合并：每张归属表都被改写、画像冲突取更活跃的一方、`origin_group_id` 保留以便撤销、FTS 重建 |
| `test_retriever.py` | 检索排序与回退 |
| `test_rag_switches.py` | RAG 开关组合行为 |
| `test_embeddings.py` | embedding 客户端、语义分注入、失败降级 |
| `test_prompt_builder_v2.py` | 分区注入与 token 预算 |
| `test_pipeline_compose.py` | prompt 拼装顺序（指令型 intent 前置、工具结果段落位置） |
| `test_proactive_rules.py` | 活跃度统计、概率曲线 |
| `test_proactive_state.py` | 配额计数、跨日重置、退避 |
| `test_proactive_target.py` | 目标选择、配额算法、冷却判定 |
| `test_proactive_at_flow.py` | 主动 @ 的记账与退避 |
| `test_proactive_prompt.py` | 主动 @ 指令的护栏 |
| `test_text_similarity.py` | 内容相似度与合并的行为基线 |
| `test_compressor.py` | 去重合并、原子化、归档、节流 |
| `test_timeutil.py` | DB 时间戳按 UTC 解析 |
| `test_trace.py` | 决策追踪与统计 |
| `test_benchmark.py` / `test_benchmark_and_log.py` | Benchmark 运行器与整合日志 |
| `test_db_cleaner.py` | 脏数据清理与消息裁剪 |
| `test_lm_studio.py` | LM Studio 客户端（重试、4xx 放弃、空回复） |
| `test_llm_registry.py` | 端点 × 角色注册表：四槽解析、模型三档解析、闸门归属、`describe()` 绝不带出 API key |
| `test_openai_contract.py` | **厂商中立契约**：默认请求体只含最小合规字段（多一个就被替身端点 400）、自适应重试至多一次且不占正常重试预算 |
| `test_llm_compat.py` | 参数差异自适应按**错误措辞关键词**命中，不含任何厂商名——退化成厂商白名单即红；含 `\uXXXX` 转义体那条路 |
| `test_scheduler_concurrency.py` | 闸门并发度：`1` 与改造前的 `asyncio.Lock` 逐字等价、不同端点槽真并行、解析不出来一律退回 `1` |
| `test_full_workflow.py` | 端到端：消息入库 → 上下文 → Pipeline → 输出 → 整合 → 晋升 + FTS |
| `test_spaces.py` | 空间解析：显式配置、隐式分配持久化、冲突处理 |
| `test_session_compact.py` / `test_session_context.py` | 会话压缩的区间不重叠、空结果与失败的区别处理 |
| `test_link_monitor.py` | 链路监测：心跳判活、主动探活、告警节流 |
| `test_deploy_checks.py` | doctor 判断层：健康快照全 ok、非 ok 必有 fix_hint、run_all 排序 |
| `test_deploy_init.py` | 向导校验与渲染（含「模板注释原样保留」反回归） |
| `test_deploy_process.py` | PID 文件读写、进程存活判断、stop 边界（用短命子进程） |
| `test_logging_sink.py` | 结构化 JSON 日志：每行合法 JSON、字段完整、超长消息截断 |
| `test_graceful_shutdown.py` | 优雅停止：等收尾、超时放弃、回应检测任务被取消 |
| `test_log_paths.py` | 日志落点统一：全部在 `LOG_DIR` 下、读写两侧共用同一配置、废弃键仍被 doctor 点名 |
| `test_deploy_probe.py` | doctor 采集层：探测失败一律不抛异常、渲染后端探测 |
| `test_deploy_cli.py` | `python -m deploy` 各子命令的出参结构（GUI 的数据契约） |
| `test_deploy_migrate.py` | 安装器升级：`.env` 是合并而非覆盖、库升到当前 schema、被用户改过的随包文件保留原样、runtime 复用与标记清除 |
| `test_stella_home.py` | 数据目录定位：环境变量优先、旧布局原地不动（也认库文件）、默认取安装目录的同级 `data` 且不预先创建 |
| `test_release_layout.py` | 发布物布局：排除项解析不带多余引号、**任何用户数据路径都不许进包**、`data/` 处处排除、打进包就红 |
| `test_env_schema.py` | `settings.py` → GUI 配置表单 schema 的分组与默认值 |
| `test_env_inherit.py` | 继承型配置项：`KEY=`（空值）必须回落父键，而 `_env` 不许跟着改——`LM_STUDIO_API_KEY=` 的空值是有意义的 |
| `test_env_merge.py` | `.env` 合并：`SUPERSEDED` 换算（`LLM_SCHEDULER_GATE_EMBEDDING` → `MEMORY_EMBEDDING_GATE`）、优先级与重复合并幂等 |
| `test_prompt_cache_prefix.py` | 前缀缓存守卫：三个记忆链路模板的可变占位符必须排在全部固定指令之后 |
| `test_usage_accounting.py` | 用量记账与预算：UPSERT 幂等、日期键跨天翻滚、临界与超额判据、`pause_memory` 只停记忆域而聊天不受影响、`pause_all` 静默返回不抛异常、`warn_only` 从不拦、记账关闭时零写库、**库不存在时 sink 也不抛异常** |
| `test_cost_gates.py` | 前置过滤：跳过路径**绝不推进 checkpoint**、@ 切片保留上下文、词面判据兜住向量不可用、连跳到上限强制整合一次、在线/本地键选择正确 |
| `test_status_api.py` | 本地状态接口：回环判断与 payload 组装 |
| `test_stop_signal.py` | 停止哨兵的写入/清除与残留清理 |
| `test_proactive_gate.py` | 主动发言准入闸门六道条件与原因字符串 |

能力层（`tests/capability/`）：

| 文件 | 覆盖内容 |
|---|---|
| `test_tasks.py` | Task / Result 协议、TaskGraph 成环与悬空依赖必须抛错、拓扑分层 |
| `test_registry.py` | 注册表合并（不覆盖）、工具归属先到先得、版本号失效、单例不被包入口遮蔽 |
| `test_capability_loader.py` | `config/capabilities/*.toml` 解析与容错（坏文件只跳过该文件） |
| `test_router_rules.py` | Level 0：关键词只认显式声明、寒暄整句匹配、工具意图不等于能力已定 |
| `test_router_semantic.py` | Level 1：原型取均值、按注册表版本/模型失效、None 与低分是两种情形 |
| `test_router_cascade.py` | 三级级联与降级：超时/异常/空注册表都回落到 chat+memory |
| `test_router_benchmark.py` | 内置用例集回归、四类错误分开计数、Provider 健康度退避 |
| `test_comes_summarizer.py` | 摘要压缩：失败与「无返回值」条目不进摘要、多工具均分预算 |
| `test_comes_executor.py` | **上下文隔离**（只有命中能力的工具进请求）、status 判定、无参直调、健康度记账 |
| `test_astrbot_adapter.py` | 自动派生、显式声明优先、bootstrap 顺序不可交换 |
| `test_capability_hooks.py` | 记忆门控、两条分支并行且互不拖累、绝不抛异常 |

AstrBot 兼容层（`tests/astrbot_compat/`）：

| 文件 | 覆盖内容 |
|---|---|
| `test_loader.py` | 插件发现与加载、metadata 解析、坏插件只跳过自己 |
| `test_shim_modules.py` / `test_shim_llm.py` | 伪造的 `astrbot.*` 模块树可 import，未实现处抛 NotSupported |
| `test_filters.py` | `@command` / `@regex` / 权限 / 唤醒前缀的判定 |
| `test_events.py` | OneBot 事件 → AstrMessageEvent、唤醒与管理员判定 |
| `test_components.py` | 消息段双向转换（含 `Json` 卡片、合并转发） |
| `test_dispatch.py` | 唤醒模型、handler 执行、**`should_dispatch`**（卡片无纯文本也要进管道、挡自身回显） |
| `test_render.py` | HTML → 图片：options 映射、产物目录上限、渠道回退、按需安装只跑一次且有冷却、失败一律返回 None |
| `test_base.py` | Star 基类、KV 存储、渲染入口不可用时返回空串而非抛异常 |
| `test_llm_provider.py` / `test_llm_tools.py` / `test_llm_hooks.py` / `test_llm_budget.py` | 插件侧 LLM：Provider、函数工具循环、生命周期钩子、预算裁剪 |
| `test_request_llm.py` / `test_conversation.py` / `test_config.py` | `event.request_llm()`、会话历史、插件配置 schema |

> **渲染测试全程给浏览器打桩**（`_FakeBrowser`），不启真 Chromium——CI 里没有内核，而要测的是编排与降级，不是 Chromium 的截图质量。真实出图靠人工验收，见 `design_docs/test_checklist/`。

### 写测试的两个约定

**用 `monkeypatch` 而非 `.env`。** 测试不能依赖环境配置：

```python
monkeypatch.setattr("memory.memory_manager.MEMORY_QUOTA_ENFORCE", True)
monkeypatch.setattr("memory.memory_manager.DB_PATH", tmp_path / "test.db")
```

> 能力层与 astrbot 兼容层的配置要 patch **`config.settings` 的属性**，不能 patch `config.X`：`config/__init__.py` 是 `from .settings import *`，名字在 import 时就绑死了。相应地这些模块内部一律用 `_settings().X` 在调用时取值，而不是 `from config import X`。
>
> 测试文件的 basename 必须全仓唯一（`tests/` 下没有 `__init__.py`），否则 pytest 收集时报模块名冲突——这就是能力层的加载测试叫 `test_capability_loader.py` 而不是 `test_loader.py` 的原因。

**约束型测试必须配反向用例。** 只测「不该发生的没发生」是不够的——把条件写成永假也能通过，功能会静默失效。`test_cross_user_isolation.py` 的每条「不得跨用户合并」都配了一条「同用户仍要合并」。

## 探针脚本

模型侧的验证不走 pytest（需要真实本地模型），用 `scripts/` 下的探针。**它们跑生产链路**：同一份 prompt 模板、同一份解析逻辑、同一份候选校验。

### 整合探针

```bash
# 正例回归基准：验证「该记的时候记得住」
python scripts/probe_consolidation.py --positive --repeat 3

# 真实窗口观察
python scripts/probe_consolidation.py --limit 20

# 只打印 prompt，不调模型（离线比对格式化是否被改动）
python scripts/probe_consolidation.py --positive --print-prompt

# 单窗口稳定性观察
python scripts/probe_consolidation.py --window-index 3 --repeat 3

# 覆盖采样温度
python scripts/probe_consolidation.py --positive --repeat 3 --temperature 0.0

# 两阶段链路（生产行为）：阶段1 出 has_self_disclosure，阶段2 提取候选
python scripts/probe_consolidation.py --positive --two-stage

# 单阶段对照（旧行为，用于确认两阶段的增益）
python scripts/probe_consolidation.py --positive
```

**改动 `memory/consolidation_prompt.py` 后必须跑双向闸门**：

```bash
python scripts/probe_consolidation.py --positive --repeat 3   # 正例必须全绿
python scripts/probe_consolidation.py --limit 20              # 编造率必须 ≈ 0
```

两条都过才算成功。只看一边会漏掉另一边的退化——放宽捕获时正例会变好但可能开始编造，收紧时编造率归零但会漏掉合法事实。

> **两阶段的区分性测试**。`insomnia_breakfast_noisy` 用例把同样的自我披露信息埋在 Bot 寒暄、彼岸花刷屏与单字附和之中，复现生产的失败条件：
>
> | 路径 | 结果 |
> |---|---|
> | 单阶段（整合模型） | ❌ 1/2（漏掉「失眠」） |
> | 两阶段（整合模型 → 主聊天模型） | ✅ 2/2 |
>
> 其余 4 个干净用例两条路径都通过——**只有噪音用例有区分度**。改动 `extraction_prompt.py` 或调整阶段 2 模型后，这个用例必须保持 2/2，否则两阶段就白做了。
>
> 输出里的这两行是失败归因的关键：
>
> ```
> 阶段1 has_self_disclosure=True/False，阶段2 已调用/未调用
> ↳ 该信息出现在原始输出中但未进候选（模型主动弃掉，非未察觉）
> ```
>
> 第一行区分「小模型布尔判错」（阶段 2 根本没被唤醒 → 改 `consolidation_prompt.py`）与「大模型提取失败」（唤醒了但没提出来 → 改 `extraction_prompt.py`）；第二行区分「没看到」与「看到了但主动弃掉」，两者修法完全不同。

### 插件 LLM 探针

`astrbot_compat` 的 LLM 接入面（插件调模型、函数工具、多轮会话）在 pytest 里
`chat_completion` 是打桩的，**「能不能真的问到模型」「小模型会不会真的调工具」只有这个探针能答**：

```bash
python scripts/probe_astrbot_llm.py                     # 全部小节
python scripts/probe_astrbot_llm.py chat tools          # 只跑指定小节
```

| 小节 | 验证什么 |
|---|---|
| `chat` | `provider.text_chat()` 能拿到非空回复，并打印 usage |
| `persona` | 人格三态：插件给了用插件的、没给注入插件专属人格、配置为空串则不发 system |
| `stream` | `text_chat_stream()` 中途是分片、最后一次 yield 是完整文本 |
| `tools` | `run_tool_loop()` 是否真的触发函数调用并把结果复述给用户 |
| `budget` | 超预算的上下文被成对裁掉最早的几条，而不是被服务端拒 |
| `conversation` | `ConversationManager` 落库往返（不需要模型） |

它跑的是生产链路：`core/llm/scheduler` 里 PLUGIN 角色所属端点槽的闸门（纯本地默认 `LOCAL`）→ `core/llm/openai_client.py` →
`StellaChatProvider` → `run_tool_loop`。会话与偏好读写指向临时库，**不会碰 `DB_PATH`
对应的真实数据库**。

`tools` 小节失败时要先分清是链路问题还是模型能力问题：日志里出现
`请求估算 N token（消息 x 条，工具 1 个）` 说明工具已随请求送出，此时模型仍不调用
就是本地小模型 function calling 能力不足，换更大的模型再试。

### 采样真实窗口

```bash
python scripts/sample_windows.py     # 产出 windows_raw.json（含真实数据，已 gitignore）
```

**注意采样偏差**：脚本按 `signal_score`（长句数 − 图片数）降序排列后取「前 12 高信号 + 中间 8 中等 + 末 10 刷屏」。因此 `--limit 20` 实际只跑到高信号与中等层，**其产出率不可外推到生产**。用 `--stratum` 指定分层可使口径显式化。

曾有一次误判源于此：探针 20 窗口产出 3 条候选（10%），而生产 985 条消息产出 0 条，一度被当成缺陷；实际是两者输入分布不同。

### Benchmark

检索层的评估数据集在 `memory/benchmark/`：

```bash
python -m memory.benchmark                        # rule-only
python -m memory.benchmark --verbose              # 每用例明细 + 分数分解
python -m memory.benchmark --embedding-fixture memory/benchmark/_fixtures/embeddings_xxx.json
python -m memory.benchmark --compare              # rule-only vs embedding 对照
```

核心指标：Memory Precision、Recall、Forbidden Activation（目标 ≈ 0）、Pollution Rate、Mode 检测准确率、Behavior Guard Hit。

用例格式见现有 JSON。`_fixtures/` 存放向量数据与整合正例基准，不被当作检索用例加载。

```bash
python scripts/build_embedding_fixture.py    # 构建向量 fixture（需 embedding 服务）
python scripts/probe_embedding.py            # 探测 embedding 服务可用性
```

### 探针的盲区

> 探针**直接把窗口消息拼成文本喂给模型**，不经过 `record_message` / `group_messages`。因此它能验证「模型能不能从消息里提取」，**不能验证「消息有没有被记录进库」**。
>
> 2026-08-17 的缺陷正落在这个盲区里：@ 消息因监听器优先级被 `block=True` 拦截而从未入库，5 个正例探针全绿，线上却一条 `AT_MENTION` 都没有、@ 对话的内容完全学不到。
>
> 入库链路只能靠两件事验证：
>
> ```sql
> -- 启动日志也会输出这个分布
> SELECT source_kind, COUNT(*) FROM group_messages GROUP BY source_kind;
> ```
>
> 以及真实对话后检查整合日志里的 `AT_MENTION 来源 N 条`。若 `AT_MENTION` 长期为 0 而 `BOT_SELF` 大于 0，说明落库被拦截。

## 数据库

```bash
python -m memory.schema --dry-run    # 预览待执行的迁移
python -m memory.schema              # 执行迁移
python -m memory.schema --backup     # 仅备份
```

**迁移原则：Additive Migration** —— 只加字段与索引，绝不删数据。所有 `ALTER` 都经过 `PRAGMA table_info` 探测，幂等可重跑。首次迁移前自动备份为 `stella_memory_backup.db`。

### 加字段的正确做法

1. `memory/schema.py` 的 `SCHEMA_VERSION` +1
2. `_ADDITIVE_COLUMNS` 追加 `(表名, 列名, ALTER 语句)`
3. `_INDEXES` 追加需要的索引
4. **同步更新所有手写该表的 `CREATE TABLE`**

第 4 步是历史踩坑点：`memories` 表的建表语句曾在 `schema.py` / `consolidator.py` / `memory_manager.py` / `compressor.py` 四处各有一份，加 `source_kind` 时漏了 compressor 那份。现在统一走 `schema.create_memories_table(conn)`，新增表也应照此办理。

SQLite 的 `ALTER TABLE ADD COLUMN` **不接受非常量默认值**，`DEFAULT CURRENT_TIMESTAMP` 会失败，需留空由代码写入。

### 改列名/主键的做法

**新规矩（2026-08-27）：`SCHEMA_VERSION` 每 +1，必须同时提交 `memory/migrations.py` 里的
`migrate_vN` 与一个旧库夹具回归测试。禁止再出现「本版不做数据迁移、归档旧库重建」。**

此前 v7（画像分群）与 v8（记忆表改按空间归属）都声明不迁移，理由是「库内数据量很小」。
但公开发布过的 2.x 全是 schema v2/v5（带 `group_id` 列），于是所有存量用户升级即被告知
丢掉全部记忆——这是本项目最贵的一次决策失误。现在 v5 → 最新版全自动。

分工：

| 模块 | 负责 |
|---|---|
| `memory/schema.py` 的 `_migrate()` | 加列 + 建表 + 建索引。幂等、与版本号无关，作为每次迁移的收尾步骤 |
| `memory/migrations.py` | 改结构 + 改数据。每版一个函数、一个事务，成功后才推进 `schema_meta.version` |

写迁移时必须知道的三件事：

1. **逐表判定归属**。v8 的语义变化是归属列的值从「真实 QQ 群号」变成「空间名」，所以
   不能写「凡是 `group_id` 就改名」的脚本。三类表见 `migrations.py` 顶部的常量：
   改名 + 改值的 4 张（`memories` / `memory_candidates` / `atomic_facts` / `user_profiles`，
   外加不能 ALTER、只能 DROP 重建的 `memories_fts`）；**只改值不改名**的
   `long_term_memories`（列名至今仍叫 `group_id`，值早已是空间名）；一个字都不能动的
   6 张按真实群归属的表。
2. **空间名必须与运行时一致**。迁移写进去的名字必须等于 `config.spaces.resolve_space()`
   对该群返回的值，否则检索 `WHERE group_shared_space='casual'` 而行里存着 `'space_1'`
   ——查不到、不报错、不抛异常。判据只能复用 `config/space_map.py`。
3. **事务要真的能回滚 DDL**。Python `sqlite3` 默认只在 DML 前隐式开事务，DDL 走
   autocommit；`run_migrations` 因此把 `isolation_level` 设为 None 自己管 BEGIN/COMMIT。

改主键仍是「建新表 → 拷数据 → 换名」，DDL 从 `schema.py` 的规范常量取（如
`USER_PROFILES_TABLE_DDL`），不要手抄。

### 空间合并

用户把两个群划进同一个 toml 之后，历史记忆还挂在旧空间名下。**不要让用户手搓 UPDATE**：

```bash
python -m deploy space-merge --from space_1,space_2 --to casual --dry-run
python -m deploy space-merge --from space_1,space_2 --to casual
```

它会改写全部按空间归属的表、重建 FTS、更新账本，并处理 `user_profiles` 撞主键
（保留 `interaction_count` 大的那份，冲突进报告）。合并**不可逆**，靠 `origin_group_id`
溯源列与操作前备份兜底。

### 时间处理

`CURRENT_TIMESTAMP` 写入 **UTC**。所有「拿 Python 时间与 DB 时间戳比较」的地方必须走 `memory/timeutil.py`：

```python
from memory.timeutil import parse_db_timestamp, seconds_since, db_timestamp_str
```

直接用 `datetime.now()` 与 DB 时间戳比较会在非 UTC 时区产生固定偏移。这个 bug 曾让 `PROACTIVE_AT_USER_COOLDOWN` 在 UTC+8 下完全失效（永远被判为已过冷却），且只在 CI 的 UTC 环境下才暴露。

SQL 内部的比较（`julianday('now')` vs `julianday(col)`）两侧同为 UTC，无需处理。

### 归档记录

每次大重构后运行时数据库会归档到 `_deprecated/`（已 gitignore）：

| 文件 | 说明 |
|---|---|
| `legacy_agent_memory.db` | 早期版运行库 |
| `legacy_agent_memory_2026.db` | v2 schema 升级前 |
| `legacy_agent_memory_pre_v4.db` | 两层过滤重构（Gate 1 三档 / 候选强化 / 配额）之前 |

启动时会按当前 schema 在 `memory/` 下自动重建新库。

> 封存旧库时**连 `stella_memory_backup.db` 一起移走**。`backup_database()` 见备份已存在即跳过，留着它会导致新库将来迁移时不生成新备份——一个看起来有备份、实际备份错了的状态。
>
> 每次版本化迁移另外会写一份 `agent_memory.db.pre-vN-<时间戳>.bak`（`schema.backup_snapshot`），
> 它才是「这次迁移前的状态」；`stella_memory_backup.db` 是「有史以来第一份原始库」。

## CI

`.github/workflows/ci.yml`，四个 job：

| Job | 内容 |
|---|---|
| `lint` | `ruff check .`（Python 3.11） |
| `security` | `pip-audit -r requirements.txt`（阻塞）+ `bandit`（非阻塞，报告上传为 artifact） |
| `test` | 3.10 / 3.11 / 3.12 三版本矩阵，`pytest tests/ --cov=. --cov-branch -n auto`，覆盖率报告上传为 artifact |
| `notify` | 仅 PR：汇总状态并评论 |

`test` 依赖 `lint` 与 `security` 通过；`fail-fast: false` 保证某个版本失败时其余继续。同一分支的旧工作流会被自动取消。

**本地复现 CI 环境**：

```bash
pip install -r requirements.txt -r requirements-dev.txt pytest pytest-cov pytest-xdist
ruff check .
pytest tests/ --cov=. --cov-branch -n auto --dist loadgroup
```

`pip-audit` 是阻塞的，某个上游依赖爆出 CVE 时 CI 会红。若判断为不可立即修复的上游问题，可临时在该步骤加 `|| true`，但应记录原因。

## 发布流程

打 tag 后 CI（`.github/workflows/release.yml`）自动打包并发布，产出 `Stella-vX.Y.Z-win64.zip`。

### 打 tag 前的检查清单

1. `python -m pytest tests -q` 全绿
2. `ruff check .` 无警告
3. `pyproject.toml` 版本号已更新（CI 会把 tag 与它比对，不一致直接 fail）
4. 改过配置项 → `.env.example` 与 `docs/configuration.md` 已同步
5. `release_assets/RELEASE_NOTES_TEMPLATE.md` 已更新为本版本说明，**破坏性变更必须列明**（例如废弃全部 `NAPCAT_*` 配置）。注意「让用户丢数据」不再是一种合法的升级方式：schema 每 +1 都必须带自动迁移
6. Release 的排除清单独立于 `.gitignore` 维护（见 `release.yml` 的注释）；新增运行期产物或配置文件时，需同时更新排除清单与敏感文件校验的正则
7. **新增顶层目录必须判断该不该进 Release**：开发工具（如 `stella-installer/`，独立分发的 Tauri 安装器）、工具脚本等不能打进用户安装包，需加进 `release.yml` 的 rsync 排除清单与「校验开发目录」的正则，并跑一次手工打包验证
8. `release_assets/start.bat` 里硬编码了 Python 版本与 SHA256；升级 Python patch 版本时需同步更新两处，主次版本变更时还要确认 `python*._pth` 的处理

然后：

```bash
git tag v0.x.0
git push origin v0.x.0
```

CI 会自动：校验版本号 → 构造发布目录（排除 `tests/`、`design_docs/`、`scripts/`、`_deprecated/`、`.github/`、`memory/benchmark/` 等）→ 拷入 `release_assets/` 的四个文件并把 bat/txt 转成 CRLF → 打 zip → 创建 GitHub Release。

### 升级嵌入式 Python 时的注意事项

`release_assets/start.bat` 里**硬编码**了：

- `PY_VER`（如 `3.12.10`）
- `PY_ZIP`（embed-amd64 包文件名，随 `PY_VER` 变）
- `PY_SHA256`（python.org 下载页的官方校验值，写错会导致安装永远失败）
- 段 6 里 `python*._pth` 的通配符（`python312._pth` 里的 `312` 对应主次版本，换 Python 时若文件名不再匹配要同步改）

升级 Python 版本时这四处要一并更新，并在本地完整跑一遍 `start.bat` 验证（会产生 `runtime/` 目录，已加入 `.gitignore`）。

> **注意**：Tauri 安装器的首次安装逻辑在 `stella-installer/src-tauri/src/python.rs`（`runtime_bootstrap`）里用纯 Rust 复刻了同一流程，`PY_VER` / `PY_SHA256` / 下载镜像常量与 `start.bat` 必须同步修改——安装器不依赖 `start.bat`，它只是备用手动安装方式。

> **编码约定**：`release_assets/` 里的 `.bat` 使用纯 ASCII，内部注释与输出统一使用英文；发布时仍统一转换为 CRLF，确保 Windows `cmd` 稳定解析。面向用户的 `README-快速开始.txt` 可继续使用 UTF-8 with BOM。

### 嵌入式 Python 的三处必改

Release 包用 Python Embeddable Package 作运行时，它有三个与常规 Python 不同的行为，
两条 bootstrap 路径（命令行的 `start.bat`、GUI 的 `stella-installer/src-tauri/src/python.rs`）
都必须处理：

1. **`import site` 默认被注释**（`python3xx._pth` 里）。不取消注释则 pip 装到
   `Lib\site-packages` 的依赖全部 import 不到；
2. **`._pth` 存在时 Python 只按该文件构建 `sys.path`**，等价于带上 `-E -s`，
   且其中的相对路径是**相对 `python.exe` 所在目录**解析的。默认的 `.` 指向
   `runtime\` 而非项目根，因此 `runtime\python.exe -m deploy` 会报
   `No module named deploy`（2026-08-18 实测）。需要追加一行 `..`；
3. **只带标准库，没有 `setuptools` / `wheel`**，而现在的 `get-pip.py` 只装 pip
   （setuptools/wheel 早就从它的默认项里去掉了）。于是任何**只发 sdist、不发 wheel**
   的依赖都装不上——pip 要构建它就得 import `setuptools.build_meta`，报
   `BackendUnavailable: Cannot import 'setuptools.build_meta'`，整条依赖安装退出码 2。
   必须在装 `requirements.txt` **之前**先 `pip install setuptools wheel`。

前两处在「启用 site-packages」段处理，用 `python*._pth` 通配匹配文件名，避免升级
Python 主次版本时漏改；第三处是 `start.bat` 的 `Installing build tools` 段与
`python.rs` 的 `ensure_build_tools()`，两边由
`tests::both_bootstrap_paths_install_build_tools` 钉住不许漂移。

> 第 3 条是 2026-08-26 v3.0.0 预发布的真实事故：`qrcode_terminal` 在 PyPI 上只有源码包，
> 全新解压的发布包装依赖必然失败。**开发机完全不复现**——那里的 `runtime/` 早年被老版
> `get-pip.py` 带上过 `setuptools`，一直沿用至今。

**这类问题 CI 挡不住**：ubuntu runner 上的 import 校验只能验证目录完整性，
`._pth` 的路径行为与「缺 setuptools」都只在真实 Windows 的嵌入式运行时里出现。因此每次改动
`start.bat` 或 `python.rs` 后，必须在**全新解压的目录**里实测一遍（不要复用已装好的目录，
它的 `._pth` 可能已被上一次运行修正过、`site-packages` 里也可能早就有 setuptools，
两者都会掩盖问题）。

> 想在开发机上复现「全新运行时」：把 `runtime\Lib\site-packages` 下的 `setuptools*`、
> `wheel*`、`_distutils_hack`、`distutils-precedence.pth` 临时改名，再跑一次装依赖。

## 代码约定

**Lint / 格式**：ruff（配置在 `pyproject.toml`）。未使用 black —— 不要引入 black 格式化，会造成大面积无意义 diff。

**类型检查**：pyright（`pyrightconfig.json`）。CI 不跑类型检查，但新代码应带类型标注。

**注释写「为什么」而不是「做什么」**。项目里大量注释记录了某个阈值的实测依据、某个顺序的必要性、某个 bug 的成因——这类信息删掉之后无法从代码反推。例如：

```python
# confidence / importance 权重刻意压到 0.05：它们描述「记忆本身可靠/重要」，
# 与「当前该不该用这条」关系弱，只适合做 tie-breaker。否则 conf≈0.98 的
# 高质量诱饵会在「该不该用」上作弊。
```

**逻辑不要有第二份副本**。`memory/text_similarity.py` 的存在就是因为相似度判定曾在三个模块各有一份，跨用户合并 bug 需要修三次而漏了两次。

**静默降级必须留痕**。项目里大量 `except sqlite3.OperationalError` 是为了容忍「表还不存在」（惰性建表），这个设计是对的。但它同时会吞掉「列名不匹配」这类致命错误——2026-08-17 的两次故障（记忆表列名遗漏、@ 消息不入库）都因此持续数小时无人察觉。

约定：捕获 SQLite 异常时按消息内容分级。

```python
if "no such table" in str(e):
    logger.debug(...)   # 惰性建表的正常情况
else:
    logger.warning(...)  # 尤其 no such column，必须可见
```

同理，任何「失败时返回空结果继续跑」的路径都要留下 warning。功能静默失效比崩溃难查得多。

**Prompt 改动需要护栏**。`tests/test_consolidation_prompt.py`、`tests/test_proactive_prompt.py` 对关键条款做字符串断言，包括反向断言（确认已移除的条款没被写回来）。这类条款删掉后功能仍「正常工作」但效果立刻变差，只能靠断言锁住。

## 排查问题

**所有运行期日志都在 `logs/`**（由 `LOG_DIR` 决定，见[配置参考](configuration.md#日志)）。排查基本上就是在这个目录里翻。

| 现象 | 查看 |
|---|---|
| 回复内容不对 | `logs/stella_thought_logs.md`（完整 prompt / 原始输出 / 内部思考） |
| 插件没加载 / 能力没注册 | `logs/boot_debug.log`（每次启动清空重写，只反映最近一次启动） |
| 记忆没生成 | `logs/memory_consolidation_log.md`（每批整合的原始输出与候选数） |
| 记忆被误删 | `logs/memory_compressor_log.md` + `compressor_stats` 表 |
| 检索选错记忆 | `memory_traces` 表（候选 / 过滤 / 最终 / 拒绝），或 `python -m memory.benchmark --verbose` |
| 主动发言异常 | 日志里的 `🎯 [主动@]` / `🔇 未回应`；`proactive_state` 表 |
| 链路掉线 / 收不到消息 | 日志里的 `[LinkMonitor]` 告警（含排查步骤）；NapCatQQ Desktop 日志确认账号是否掉线 |
| 整合输出被截断 | 日志里的 `finish_reason=length` 告警 |
| @ 对话完全学不到东西 | `SELECT source_kind, COUNT(*) FROM group_messages GROUP BY source_kind`；`AT_MENTION` 为 0 说明落库监听器被 `block=True` 拦截（priority 必须为 0） |
| 主动 @ 永远走冷启动 | 日志里 `mode=coldstart` 恒定，或 `[ProactiveTarget] 读取候选失败`；说明候选查询的空间列名不匹配 |
| 某个模型排队严重 / 回复变慢 | 日志里 `[Scheduler]` 的等待/持有/队列深度告警；`core.llm.snapshot()` 导出累计统计 |
| 记忆读写静默无效 | 启动日志有无 v8 旧库告警；`PRAGMA table_info(memories)` 是否为 `group_shared_space` |
| GUI 显示不出链路状态 | 检查 `STELLA_STATUS_API_ENABLED`，用 `curl http://127.0.0.1:8080/stella/status` 直接验证；进程在但接口 403 说明路由被误暴露限制、连不上说明 uvicorn 未起来 |

### 常用 SQL

```sql
-- 候选队列状态分布
SELECT status, COUNT(*), AVG(confidence), AVG(occurrence_count)
FROM memory_candidates GROUP BY status;

-- 卡在观察区的候选（被反复提及却晋升不了的）
SELECT user_id, content, confidence, occurrence_count, source_kinds, first_seen_at
FROM memory_candidates WHERE status = 'OBSERVING' ORDER BY occurrence_count DESC;

-- 每用户记忆数（配额观察）
SELECT group_shared_space, user_id, COUNT(*) FROM memories
WHERE status = 'active' GROUP BY group_shared_space, user_id ORDER BY 3 DESC;

-- 记忆的来源分布（审计：哪条路径产生的）
SELECT source_kind, COUNT(*) FROM memories WHERE status = 'active' GROUP BY source_kind;

-- 消息来源分布
SELECT source_kind, COUNT(*) FROM group_messages GROUP BY source_kind;

-- 整合进度
SELECT * FROM consolidation_state;

-- Schema 版本
SELECT * FROM schema_meta;

-- 消息来源分布（AT_MENTION 为 0 而 BOT_SELF > 0 说明落库被拦截）
SELECT group_id, source_kind, COUNT(*) FROM group_messages
GROUP BY group_id, source_kind;

-- 候选的来源构成（AT_MENTION 来源应单次即可晋升）
SELECT source_kind, source_kinds, status, COUNT(*) FROM memory_candidates
GROUP BY source_kind, source_kinds, status;

-- 空间归属核对：QQ 群维度的表应是群号，记忆维度的表应是空间名
SELECT DISTINCT 'consolidation_state' AS t, group_id AS id FROM consolidation_state
UNION ALL SELECT DISTINCT 'memories', group_shared_space FROM memories;

-- 决策追踪：同时看触发群与检索空间
SELECT group_id, group_shared_space, mode, trigger, ts FROM memory_traces
ORDER BY ts DESC LIMIT 20;
```

## 提交与贡献

**提交信息**用简短的英文或中文描述改动实质，避免「fix bug」「update」这类无信息量的描述。

**PR 前确认**：

- `python -m pytest tests -q` 全绿
- `ruff check .` 无警告
- 改了 prompt → 跑过双向闸门（正例回归 + 真实窗口）
- 改了 schema → `python -m memory.schema --dry-run` 输出符合预期
- 改了配置项 → `.env.example` 同步（`deploy init` 基于它渲染，漏改会让新配置项不出现在生成的 `.env` 里），`docs/configuration.md` 同步
- 改了监听器 priority / 新增 block=True 的处理器 → 确认落库监听器仍是最高优先级，且发一条 @ 消息验证 `AT_MENTION` 入库
- 改了记忆表的 SQL → 确认用的是 `group_shared_space` 而非 `group_id`（两层归属见 architecture.md）
- 改了 Router 规则 / 能力声明 → `python -m capability.router.benchmark --rules-only` 的记忆假阴与工具假阳仍为 0
- 打算打开 `ROUTER_GATE_MEMORY` → 跑全链路 benchmark（需 embedding 服务）并确认退出码为 0；这是唯一能验证「不会悄悄丢记忆」的手段
- 新增能力 Provider 类型（MCP / API / native）→ 在 `capability/comes/executor.py::resolve_tools` 里实现对应分支，别让它静默落进 `missing`

**改动涉及以下内容时请在 PR 描述里说明理由**：

- 记忆晋升的阈值或判定逻辑
- prompt 中的防编造条款
- 三条合并路径的归属过滤
- 链路监测的判活 / 告警逻辑（心跳 + 主动探活，只告警不重启）
- 监听器的优先级与 block 关系
- 两层归属（QQ 群 / 共享空间）的划分

这些地方都有过实测依据（记录在 `design_docs/check_point/` 与 `bug_report/`），改动前建议先读相关记录。

## 设计记录

`design_docs/` 是设计过程的存档，面向开发者自己：

| 目录/文件 | 内容 |
|---|---|
| `Memory *Specification v1.0.md` | 记忆系统的原始规范（Schema / Consolidation / Retrieval / Policy Matrix / Evaluation & Debug） |
| `Migration & Implementation Plan.md` | v1 → v2 的迁移计划 |
| `Memory Verification Loop.md` | 主动获取回路的设计 |
| `check_point/` | 关键决策节点：问题、诊断过程、被否证的假设、实测数据 |
| `bug_report/` | 缺陷分析 |
| `logs/` | 终端输出与运行日志存档 |

与 `docs/` 的区别：`docs/` 是面向使用者的成品文档，`design_docs/` 是过程记录，包含被推翻的假设与失败的尝试——那些信息对理解「为什么现在是这样」很重要，但不适合放进使用文档。
