# WP03 实施记录：存储迁移与双后端

- 日期：2026-10-21（Asia/Shanghai）
- 工作分支：`codex/cross-platform-implementation`
- 实现基线：`0254016`；实现提交：`ec5cf65`
- 依赖：WP01、WP02
- 结论：WP03 本地验收项通过；跨项目回归仍 **NOT READY**，见「未关闭项」。

## 交付范围

1. SQLite schema 升到 v21。`group_messages` 新增 `platform_message_id TEXT` 与 `subject_key TEXT NOT NULL DEFAULT ''`，并建立平台回执和主体查询索引。迁移只将旧的非零 INTEGER `msg_id` 原样转成文本回执 ID；保留 `msg_id`，不从裸 `user_id` 或数字会话推断历史 `subject_key`。
2. 群消息写入将原始平台回执和规范主体分别持久化。无回执时平台 ID 为 NULL；旧整数字段继续服务 QQ 兼容读路径。
3. Python 检索边界兼容旧 int 调用，但传给后端前转为字符串。`RetrievalRequest.user_id` 严格为字符串；Python/native API 升为 4，native schema 合同升为 21，旧 schema 20 被拒绝。
4. 修正 flow manifest 漂移门禁：它会扫描不可变归档并寻找任一匹配当前源码的文件，不再遇到按文件名排序的首份历史归档便提前失败。同步修正 Rust 晋升验收脚本：候选通过生产 `MemoryConsolidator` 路径写入 accepted evidence，且验证两后端的晋升、冲突、提交事实和 trace integrity。

## GitNexus 证据

编辑前索引为当前 WP02 提交 `0254016`。重要 upstream impact：

- `memory/schema.py`：HIGH，160 impacted / 24 direct。
- `record_message`：CRITICAL，18 impacted / 4 direct / 9 flows；直接路径包括 `_record_bot_lines`、`handle_private_chat`、`record_group_chat`、`run_turn`，受影响流程包括 `handle_toggle`、`chat`、`handle_reload`、`proactive_speak_job`、`stream`、`handle_addressing`、`handle_chat`、`handle_private_chat`、`record_group_chat`。
- Python `RetrievalRequest`：HIGH，108 impacted / 10 direct；`retrieve_memories`：HIGH，14 impacted / 7 direct，覆盖 benchmark、planner 和 memory replay 入口。
- `migrations.py`：MEDIUM，73 impacted / 3 direct；`run_migrations`：LOW，8 impacted；`_migrate_db`：HIGH，38 impacted / 2 direct。
- Native `ensure_supported`：LOW；`retrieve`：LOW；`promote`：MEDIUM。Rust request 类型图查询 UNKNOWN，已用源码检索确认 serde 输入与测试构造点。
- `migrate_v20` 图结果 UNKNOWN（版本到函数通过动态 `MIGRATIONS` 字典分派）；源码确认 v21 已加入映射且由 `MIGRATIONS.get(version)` 调用。
- generator 文件 UNKNOWN / 0 图边；精确 CLI `main` 为 LOW / 1 direct。源码审计确认 CI 运行 `--check`，并由 `tests/observability/test_message_flow_contract.py` 守护。
- `validate_rust_fullchain.py` 文件 UNKNOWN / 0 图调用者；文本审计仅发现历史计划/报告引用，作为手动验证脚本处理。

提交前 GitNexus 1.6.12：`scope=all` 为 17 files / 58 symbols / 10 flows / HIGH；`scope=compare --base-ref main` 为 202 files / 296 symbols / 28 flows / CRITICAL。新索引 24,709 nodes / 56,333 edges / 1,032 clusters / 811 flows。索引器明确报告跳过 15 个大文件（包括 flow manifests）、候选入口/分支预算截断和 910 个跨语言属性缺边；这些限制没有被视作零调用者。

## 验证证据

| 命令 / 检查 | 结果 |
| --- | --- |
| `.venv/bin/python -m pytest -q -rs tests/test_migrations.py tests/test_memory_rust_selector.py tests/test_message_relations.py::test_record_message_persists_opaque_id_and_subject_separately tests/test_retrieval_v2_and_schema.py tests/test_memory_rust_benchmark.py tests/observability/test_message_flow_contract.py` | 77 passed, 1 skipped。skip 是原 pytest 进程未加载 native wheel；wheel 单独安装后另做了真实验证。 |
| `cargo test --locked --manifest-path memory_rust/native/Cargo.toml` | 25 passed，0 failed；包括 schema 21 接受、schema 20 拒绝和不透明字符串 user ID 检索。 |
| `cargo fmt --manifest-path memory_rust/native/Cargo.toml --all --check` | 通过。 |
| 项目锁定 `maturin==1.15.0` 的 release wheel 构建 | Python 3.12.14，生成 `stella_memory_rust-0.1.0-cp310-abi3-manylinux_2_34_x86_64.whl`。安装后真实扩展报告 API 4 / schema 21。工具链和 wheel 均放在 `/tmp`，未改项目依赖。 |
| `scripts/validate_rust_fullchain.py --output /tmp/stella-wp03-native-parity.json`（通过隔离 wheel 加载） | PASS。native 检索冒烟成功；Python/native 均晋升强候选为 CONFIRMED、弱冲突保持 OBSERVING、旧记忆保持 active；两侧 backend decision 与 commit fact succeeded，trace integrity complete。 |
| `run_compare_benchmark(retrieval_mode="embedding", embedding_fixture=memory/benchmark/_fixtures/embeddings_text-embedding-qwen3-embedding-0.6b.json)`（隔离 wheel） | PASS；101/101 cases expected-correct，Python/native 101/101 match，0 mismatches，fixture skipped 0。 |
| `run_compare_benchmark(retrieval_mode="rule")`（隔离 wheel） | 两后端 101/101 完全一致、0 parity mismatch；但整体质量结果 100/101。唯一共享失败 `rank-casual-001` 期望 C01/C02/C03，实际 C01/C03/C04；这是既有 rule benchmark 夹具/排名缺口，需在基准课题单独处理。 |
| `.venv/bin/ruff check .`；`python scripts/check_docs.py`；`python scripts/generate_message_flow.py --check`；`git diff --check` | Ruff、diff 和 flow gate 通过；文档 119 files / 1,206 local links / 577 anchors / 0 errors；manifest `f4aca9357166` 与源码匹配。 |
| 全量 `.venv/bin/python -m pytest tests -q` | 为诊断 451.87 秒无进展后以 SIGINT 中止：876 passed / 7 skipped，卡在 `tests/cometa/test_worker.py::TestSingleOwner::test_second_worker_rejected`。该测试仍期待第二 worker 立即报 `StoreBusyError`，而当前 worker 实现会按租约合同重试；单测加 30 秒 timeout 后复现超时（配置重试上限 70 秒）。属于本包之外的既有合同不一致，不能记为全量通过。 |

WP03 状态文档收尾在实现提交之后另行检查：`.venv/bin/python scripts/check_docs.py` 为 119 files / 1,209 local links / 577 anchors / 0 errors；`feature_list.json` JSON 解析及 `git diff --check` 通过。提交前 GitNexus `scope=all` 汇总为 4 files / 12 symbols / 0 flows / LOW；`scope=compare --base-ref main` 汇总为 203 files / 295 symbols / 28 flows / CRITICAL。比较命令重跑并提高 `--limit 500` 后仍以省略号展示部分 symbol/flow 名称；聚合计数与风险级别完整显示，CLI 未给出 `partial` / `truncated` 标记。

项目 `STELLA_HOME` 未设置。迁移、晋升和 parity 使用临时 SQLite；未启动 Bot、未读取或改写生产库，未运行真实模型、QQ 灰度或 clean VM 验收。

## 未关闭项与后续

- 全量 Python 回归仍 NOT READY：本轮被 Cometa 单 worker 过时测试卡住；WP02 报告中列出的其他全量失败也尚未关闭。
- Rule benchmark 有一个两后端共有的 expected-ranking mismatch；embedding fixture 模式 parity 和质量均全绿。
- QQ/WebChat 行为、外部适配器、真实平台、发布包和 clean VM 仍须按 WP11 分别验收。本地 wheel 只证明当前 Linux/Python ABI3 构建，不代表 Windows 发布 wheel 或线上 native 安装验收。
- 下一包 WP04（记忆/权限/社交作用域）：从 `ec5cf65` 刷新 GitNexus 后，对 ownership、evidence contract、personal sharing、addressing、social 与 knowledge ACL/store 入口重新跑 upstream impact，再按依赖顺序实施。
