# WP01 身份与注册表实施记录

- 日期：2026-10-21（Asia/Shanghai）
- 分支：`codex/cross-platform-implementation`
- WP00 父提交：`edb8a3d9ae1d90e5eb4246ab4b4ab2a681ca19c4`
- 计划：[GitNexus 跨平台执行方案](../plans/2026-10-20-gitnexus-cross-platform-plan.md)

## 交付

- 新增 `BotRef`、`UserRef`、`SceneRef`、`ConversationRefV2`，外部 ID 均保留为原始字符串。版本化 key 使用 canonical JSON 数组编码后再作 base64url 编码，携带 connection、adapter、platform scope、bot ID、parent path、scene 和 thread；同号但不同 Bot/路径/线程不会合并。
- 新增 V2 会话注册与查询。V2 数据进入独立的 `conversation_registry_v2` 表，多个旧 runtime key 由 `conversation_aliases` 映射；别名无上下文且有多个目标时返回 `None`，带完整 Bot/Scene 时才解析对应目标。
- V1 QQ/WebChat 注册表结构和 API 保持独立。源码搜索发现 `tools/data_repair.py`、`tools/backfill_personal_memory.py` 会直接查询旧表，隔离存储可避免它们把 opaque key 当作旧 bot/user 字段。
- V1 与 V2 分配负存储号时都扫描两张注册表，并在 `BEGIN IMMEDIATE` 事务内分配；WebChat 的 `-1` 继续保留，新的私聊/V2 会话从 `-2` 以下分配。
- 新 V2 会话未显式传入空间时使用 `transport:<canonical_key>`，每会话默认隔离。现有 `config.spaces.resolve_space()` 接收 QQ 整数群号；目前没有通用平台的显式共享配置合同，因此不把不透明 ID 转成整数，也不增加隐式跨平台共享。旧 `ConversationRef` 与 `core/conversation.py` 保持原状，避免在 WP01 中改动仍由旧入口使用的对象合同。
- schema 版本仍为 20。新表通过已有的幂等 `create_conversation_registry_table()` 建立，不迁移生产库；WP03 负责计划中的版本化存储迁移、版本水位与 Python/native 合同。

## GitNexus 与源码补证

使用仓库固定版 GitNexus 1.6.11、Node v24.19.0，命令入口：

```bash
export PATH=/home/vegetable/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:/home/vegetable/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/fallback:$PATH
pnpm --allow-build=@ladybugdb/core,gitnexus,tree-sitter dlx gitnexus@1.6.11 analyze --index-only --workers 1 --pdg --name Stella_project --default-branch main
pnpm --allow-build=@ladybugdb/core,gitnexus,tree-sitter dlx gitnexus@1.6.11 status --json
pnpm --allow-build=@ladybugdb/core,gitnexus,tree-sitter dlx gitnexus@1.6.11 impact lookup --file memory/conversation_registry.py --direction upstream --repo Stella_project
pnpm --allow-build=@ladybugdb/core,gitnexus,tree-sitter dlx gitnexus@1.6.11 impact create_conversation_registry_table --file memory/schema.py --direction upstream --repo Stella_project
pnpm --allow-build=@ladybugdb/core,gitnexus,tree-sitter dlx gitnexus@1.6.11 impact _allocate_negative_storage --file memory/conversation_registry.py --direction upstream --repo Stella_project
pnpm --allow-build=@ladybugdb/core,gitnexus,tree-sitter dlx gitnexus@1.6.11 impact conversation_key --file core/conversation.py --kind Function --direction upstream --repo Stella_project
pnpm --allow-build=@ladybugdb/core,gitnexus,tree-sitter dlx gitnexus@1.6.11 detect-changes --scope all --repo Stella_project
pnpm --allow-build=@ladybugdb/core,gitnexus,tree-sitter dlx gitnexus@1.6.11 detect-changes --scope compare --base-ref main --repo Stella_project
```

- 刷新索引对应 WP00 提交 `edb8a3d`；复核状态为 `up-to-date`，workspace content `current`，覆盖 1,394 个文件；图含 96,237 nodes、237,994 edges、1,012 clusters、829 flows。
- `lookup`：CRITICAL，10 个受影响节点、4 个直接调用者、4 条流程、5 个模块。相关流程包括 WebUI `chat`/`stream` 和 QQ `handle_addressing`/`handle_private_chat`。
- `create_conversation_registry_table`：HIGH，22 个受影响节点、3 个直接调用者；`_allocate_negative_storage`：HIGH，7 个受影响节点、3 个直接调用者。
- 精确到 `Function:core/conversation.py:conversation_key` 为 CRITICAL，14 个受影响节点、6 个直接调用者、4 条流程、5 个模块；同名 `ConversationRef.conversation_key` 属性为 UNKNOWN/0。新增的 `register_conversation_v2` 静态调用边为 UNKNOWN/0；`rg` 确认它目前只被本阶段测试调用，后续由入口工作包接线。
- GitNexus 流程抽取仍有约束：刷新时 12 个大文件（>512 KiB）跳过；流程报告 829 条，但 2,881 个候选入口中 2,681 个没有进入排序，25 条深度截断、753 个 callee 因分支上限跳过、46 次遍历预算截断。索引还报告 910 个跨语言属性读写点不连边及 32 候选 callable-value-flow 上限。不得将缺失图边视为无调用。
- 源码补证：`rg` 检查 `register_conversation_v2`、旧注册表直查及 `core/conversation.py` 引用；维护工具旧表访问已由独立 V2 表隔离。最终暂存后 `GitNexus detect-changes --scope all` 与 `--scope compare --base-ref main` 均退出 0；all 为 13 个文件/83 symbols/low，compare main 为 156 文件/111 symbols/low。暂存前的检查未包含新增文件，故暂存后重跑，将 transport、测试、报告和 message-flow manifest 一并纳入。

## 验收

`STELLA_HOME` 未设置。测试通过仓库 `tests/conftest.py` 使用临时数据目录；没有启动 Bot、访问或迁移生产数据库。

```bash
.venv/bin/python -m pytest tests/test_transport_identity.py tests/test_conversation_registry.py tests/test_conversation_identity.py tests/test_multi_user_identity.py tests/test_private_chat_ingress.py tests/test_context_tail.py tests/test_ai_gateway_deterministic_reply.py tests/test_memory_capture_gate.py tests/test_capture_ingress_gating.py -q
.venv/bin/python -m pytest tests/observability/test_message_flow_contract.py -q
.venv/bin/ruff check core/transport/models.py core/transport/keys.py core/transport/__init__.py memory/conversation_registry.py memory/schema.py tests/test_transport_identity.py tests/test_conversation_registry.py
.venv/bin/python scripts/check_docs.py
.venv/bin/python scripts/generate_message_flow.py --check
git diff --check
```

- pytest：身份/注册表与 QQ/WebChat 定向回归 160 passed；`tests/observability/test_message_flow_contract.py` 另 14 passed（本机 Python 3.12）。覆盖非数字/带冒号/Unicode ID、parent/thread、同号多 Bot、V2/V1 存储号交叉分配、并发注册、重启后 alias、歧义 fail-closed 和旧 QQ/WebChat 回归。
- Ruff：通过；文档检查：119 文件、1204 本地链接、577 anchors、0 errors；message-flow 清单重新生成后拓扑未变，`--check` 通过；`git diff --check` 通过。
- 适配器消息收发、平台 fixture/live、配置界面和发布验收不属于本阶段证据；未认证任何新平台。

## 下一步

开始 WP02 前刷新 GitNexus，并先检查上下文投影、RuntimeFacade、轮次服务、消息 ID 与回复 envelope 的 upstream impact。按计划升级 projection 合同并保留旧 QQ/WebChat 读取路径。
