# 提交前检查

中文 | [English](testing.en.md) · [文档总览](../README.md)

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
| `test_env_inherit.py` | 继承型配置项：`KEY=`（空值）必须回落父键，而 `_env` 不许跟着改——`MEMORY_EXTRACT_LM_STUDIO_BASE_URL=` 的空值是有意义的 |
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
