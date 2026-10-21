# WP04 实施记录：记忆、权限与社交作用域

- 日期：2026-10-21（Asia/Shanghai）
- 工作分支：`codex/cross-platform-implementation`
- 基线：`main@ba582a922f4d3379b6397c4c0a8d8ef3e7c3e77d`
- 实现提交：`eabec23`（`feat(memory): isolate cross-platform authorization scopes`）
- 状态：WP04 本地实现及定向验收完成；XPLAT-IMPL 整体仍 **NOT READY**。

## 范围和结果

WP04 将个人记忆、证据、分享授权、地址偏好、社交学习资产与知识库授权的主体键改为连接隔离的命名空间身份。底层表保留外部 ID 原文供展示和既有协议读取；遇到未知主体或连接时按不可见/未知处理，不从裸数字 ID 推断平台归属。

- `memory/ownership.py` 从可信 `UserRef` 与 `BotRef` 生成 `person:v2:{connection_id}:{subject_key}`；scope 缺主体或连接时不授予 PERSON 可见性。只对明确的 `qq:client` 和 `legacy-qq:{bot_id}` 提供旧 QQ owner/subject 只读兼容别名。
- `memory/evidence_contract.py` 同时接受旧 `2026-10-08.1` 与当前 `2026-10-21.1` assessment。新来源校验 subject、connection 与可用的 C2 Bot 身份；空的新增身份列不进入旧快照摘要，保持历史证据 digest 有效。候选归属使用审核后的 owner 和 subject，不从 raw ID 重建 QQ 键。
- `memory/personal_sharing.py` 将 grant 查询、复制和撤回限制在 owner、subject、connection、fact 范围；显式 legacy QQ 连接可查旧授权，其他连接无法继承或撤销。schema v22 事务重建授权唯一键时逐列复制旧记录，历史 connection 留空，不猜测映射。
- `memory/addressing.py` 将偏好按空间和主体键存储；读取历史 QQ 偏好必须走显式兼容路径。消息预处理只接受可信 `UserRef`。
- 社交事件、投递、效果和学习资产增加 `connection_id`，唯一索引/检索索引带连接范围。social schema v4 对既有行增加空连接，不把历史聊天绑定到新平台。
- knowledge schema v2 为 owner/grant 写入身份域；ACL 使用命名空间主体，未知裸 ID 不取得旧 QQ 权限。能力工具上下文同样携带受信身份。
- Python/Rust memory schema 同步为 22，backend API 保持 4。主动发言目标继续通过既有 QQ 目标规则校验。
- `ConversationScope.from_context` 优先取上下文或可信 `BotRef.platform_scope`，并从 BotRef 回退 self ID；不把不透明 C2 会话键前缀当平台类型。新增跨平台回归。

## GitNexus upstream impact

编辑前按 `docs/agent/gitnexus.md` 检查。表中数字是 GitNexus 原始 impact；不以 `riskSharedAxes` 抵消风险。HIGH/CRITICAL 项在编辑前已报告并据此审查调用边界。

| 目标 | 直接调用者 / 影响总数 | 原始风险 | 关注流程 |
| --- | ---: | --- | --- |
| `knowledge/acl.py::resolve_role` | 3 / 23 | CRITICAL | KB retrieve/list/add-document/detail/archive/grant/revoke |
| `memory/social_schema.py::ensure_social_schema` | 2 / 47 | CRITICAL | `handle_chat`、`record_group_chat` |
| `ownership.scope_for_conversation` | 1 / 5 | HIGH | 个人记忆范围创建 |
| `ownership.scope_for_chat_context` | 2 / 5 | HIGH | 上下文到检索/记忆范围 |
| `ownership.owner_scope_sql` | 2 / 10 | HIGH | SQL 与 FTS 候选池过滤 |
| `evidence_contract.assess_candidate` | 1 / 3 | HIGH | 候选审核和整合 |
| `evidence_contract.verify_source_snapshot` | 4 / 10 | HIGH | proactive speak 校验链 |
| `retrieval_v2.retrieve_memories` | 7 / 14 | HIGH | Python/native 检索与规划 |
| `retrieval_v2._retrieve_with_optional_backend` | 1 / 11 | HIGH | 双后端选择与回退 |
| `personal_sharing.canonical_owner` | 4 / 5 | HIGH | grant/复制/撤回/缓存版本 |
| `addressing._scope` / preference table | 3 / 7；2 / 7 | HIGH | 地址查询、设置、清除 |
| `core.social.contracts.ConversationScope` | 11 / 21 | MEDIUM | 社交学习/投递/效果存储 |
| `memory_manager._process_new_candidates_python` | 1 / 5 | HIGH | 候选晋升及后台 drain |
| `memory/migrations.py` | 3 / 73 | MEDIUM | 跨版本迁移调用链 |

授权 grant/revoke 的精确目标为 LOW，均沿 `handle_private_chat → _maybe_personal_sharing` 单一入口；高风险来自它们调用的身份、来源和迁移合同。`ConversationScope.from_context` 的精确方法名查图返回 UNKNOWN；`rg` 补查发现唯一生产调用位于 `core/social/context_builder.py`，其类级影响为 MEDIUM。schema 常量的 UNKNOWN/零边通过 `rg` 核对 Python/Rust 声明和拒载用例。生成 flow archive 的 File impact 未命中图节点；脚本 `scripts/generate_message_flow.py` 和运行时 archive glob 的源码引用确认它是重新生成的不可变产物。

实施期间对 `MemoryManager._process_new_candidates_python`（HIGH，5 impacted / 1 direct）复核时发现晋升后关联查询硬编码 `qq:{user_id}`。审核来源已按 subject/connection 验证，因此移除该过滤条件，避免 U2 主体被旧 QQ 表达式误拒绝；增补的 v2 管理器用例通过。

提交前 GitNexus 1.6.12 `detect-changes`：

- `scope=all`：49 files / 215 symbols / 48 affected processes / CRITICAL。
- `scope=compare, base_ref=main`：241 files / 496 symbols / 71 affected processes / CRITICAL，包含 WP00–WP03。
- CLI 的人类可读输出只列一部分符号/流程名；用 `--limit=1000` 重跑后仍显示相同摘要统计和明确的其余项数。图谱刷新到 `eabec23` 后为 97,099 nodes、240,838 edges、1,037 clusters、816 flows。
- 文档/状态提交前再次运行 `detect-changes` all/compare，原始风险均为 CRITICAL；结果将文档章节关联到大量流程，按原始风险记录，不据此改动源码。新报告与 JSON 状态文件不在本次索引快照中，另以文件差异、JSON 解析和 `check_docs.py` 校验。
- 图谱仍是下界：本次分析跳过 16 个大文件，入口候选预算丢弃 2,656 项，21 条 trace 达深度上限，742 个 callee 被分支预算跳过，44 次遍历受预算限制；910 个跨语言属性读写站点无法连边。空结果与 UNKNOWN 不作未使用证明。

## 验收证据

| 命令/范围 | 结果 |
| --- | --- |
| `.venv/bin/python -m pytest tests/test_memory_evidence_contract.py tests/test_multi_user_identity.py tests/test_personal_memory_scope.py tests/test_personal_memory_backfill.py tests/test_personal_memory_concurrency.py tests/test_memory_manager_v2.py tests/test_migrations.py tests/test_addressing.py tests/test_addressing_handler.py tests/test_proactive_at_flow.py tests/test_attribution_wiring.py tests/test_personal_memory_sharing.py -q` | 135 passed |
| `.venv/bin/python -m pytest tests/knowledge tests/test_social_migrations.py tests/test_expression_learning.py tests/test_expression_selector.py tests/test_expression_store.py tests/test_jargon_service.py tests/test_reply_effect_service.py tests/test_social_contracts.py tests/test_social_delivery.py -q` | 203 passed |
| `.venv/bin/python -m pytest tests/test_proactive_target.py tests/test_retrieval_v2_and_schema.py tests/test_retriever.py tests/test_retrieval_cache_topic.py tests/test_social_migrations.py -q` | 45 passed（与上组有重复覆盖） |
| `.venv/bin/python -m pytest tests/test_memory_rust_selector.py tests/test_memory_rust_promotion.py tests/test_memory_rust_benchmark.py -q` | 29 passed / 1 skipped |
| `cargo test --locked --manifest-path memory_rust/native/Cargo.toml`（临时 Rust/Cargo home） | 25 passed；0 failed |
| 隔离 maturin release wheel，安装至临时目标并从 repo 外导入 | 成功；报告 backend API 4 / schema 22 |
| 改动 Python Ruff；`python scripts/check_docs.py`；`python scripts/generate_message_flow.py --check`；`git diff --check`；`cargo fmt --manifest-path memory_rust/native/Cargo.toml --all --check` | 全部通过；文档 119 files / 1209 local links / 577 anchors / 0 errors；flow archive `message-flow.f716810e9756.json` 与当前源码匹配 |

pytest 组之间存在重叠，结果不相加。这里没有运行全量 Python suite；WP02/WP03 已记录的全量 Cometa/WebUI 缺陷仍未关闭，集成验收保持 NOT READY。

## 数据边界与未完成验收

`STELLA_HOME` 未设置。测试只使用 pytest 临时目录和隔离 wheel 目录；没有读取或迁移用户/生产数据库，没有启动 Bot，没有调用真实模型，也没有平台 fixture/live、QQ 灰度或 clean VM 发布验收。迁移回归证明临时旧 schema 的升级、保留和重跑行为，不代表生产备份、迁移窗口或运行期升级已验收。WP05–WP11 和上述外部验收仍是后续工作。
