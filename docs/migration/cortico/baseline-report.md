# Baseline Report（M0）

> 冻结迁移起点的可验证事实。生成于 2026-09-27，分支 `feat/cortico-runtime-migration`。

## 1. Commit 与证据漂移

| 项 | 值 |
| --- | --- |
| 实施起点（本分支 HEAD / detect-changes `--base-ref`） | `acd5aee4aa21b3202073cf055255ecd71b1f7de9` |
| 计划证据基线 | `390987e37847b5eea57f90f74d42e66b10664b8f`（同分支前身，晚 5 个提交） |
| 漂移文件（390987e..acd5aee） | `astrbot_compat/loader.py`、`cli/Cargo.{lock,toml}`、`deploy/plugin_check.py`、`desktop|stella-installer .../python.rs`、`memory/{memory_manager,retrieval_v2,schema}.py`、`pyproject.toml`、`release_assets/start.bat`、`tests/{astrbot_compat/test_loader,test_release_layout,test_retrieval_v2_and_schema}.py`、`webui/static.py`、本计划文档 |
| 漂移评估 | 五个主符号文件（core/pipeline.py、core/context.py、capability/hooks.py、webui/chat_ingress.py、scheduling/runtime.py）与 ai_gateway.py **均未漂移**，计划 cited 证据继续有效；pyproject.toml digest 失效属预期。每次改符号前仍重跑 impact |
| GitNexus 索引 | 2026-09-27T00:12:46.017Z，v1.6.11，PDG 开；本机 runner：`MSYS_NO_PATHCONV=1 docker exec -w /repo stella-gitnexus gitnexus <cmd> --repo .` |

## 2. 测试基线（M0 实测）

聚焦回归集（计划 §8.3 第一条）：

```
python -m pytest tests/test_pipeline_compose.py tests/test_planner.py tests/capability/test_capability_hooks.py tests/webui/test_webui_chat.py tests/scheduling/test_scheduling_delivery.py -q
→ 87 passed, 47 warnings in 3.82s（Python 3.14.7，Windows 本机）
```

- 已有失败：**无**（聚焦集全绿）。全量 `pytest tests/`（CI 矩阵 3.10/3.11/3.12）在 M9 前的每个提交门禁执行；本机 Python 3.14 与 CI 矩阵的差异记录在案，最终回归以 CI 为准。
- 计划 §8.1 其余范围（session_context/compact、graceful_shutdown、runtime_contract、windows）映射见 feature-parity.md 各行；windows 集在 CI windows-native 跑。
- **全量套件（2026-09-27，M5 证据基线）**：`pytest tests/ -q -n auto --dist loadgroup` → **2658 passed / 14 skipped / 1 failed**。唯一失败 `tests/webui/test_webui_readonly.py::test_query_daily_reads_temp_db` 为 xdist 并发下临时 db 竞争的偶发（单跑 8/8 通过），与迁移改动无关，按 Q1 单列观察。
- M4 后新增回归面：`tests/runtime/`（legacy traces 10 + turn_service 7 + bridge_protocol 8 + session_ownership 4 + restart_recovery 2 + ingress_cortico 3 = 34 例）。

## 3. 性能基线（测量方法冻结；当前未宣称任何压测结果）

| 场景 | 指标 | 测量方法 | M1 门槛（拟议预算） |
| --- | --- | --- | --- |
| 空闲 / 1 / 20 / 100 会话 | 进程 RSS 增量、排队延迟 p95、冷启动增量 | 单进程stub provider 回放 M0 样本；RSS 读 `/proc`（容器）或 `tasklist`（Windows）；100 会话仅诊断扩展性 | 桥额外延迟 p95 ≤100ms；RSS 总增量 ≤150MiB；冷启动 ≤3s（排除模型加载/推理） |
| 日志增长 | 字节/小时 | stub 回放固定时长 | 无门槛，记录基线 |

超出门槛：优化或**明确修订预算依据**，不得不报。

## 4. 固定验收材料（fixture 与 oracle）

- `tests/runtime/fixtures/scenarios.py`：8 个冻结场景（普通1次、工具直回0次、Planner WAIT、Planner 深度、超时、预算静默、QQ 多行、WebChat 轮次），每场景 = ChatContext 参数 + stub 后端脚本（固定响应序列）+ 期望调用数/lines。
- `tests/runtime/fixtures/legacy_traces/*.json`：由当前（提取前）legacy Pipeline 生成并提交的规范化 trace（prompt、调用序列、hooks、lines）；时间戳/随机 ID 规范化为占位符。**旧 oracle 不随实现修改、不被新输出覆盖**（M9 差异回放的比较基准）。
- 再生成命令：`python -m pytest tests/runtime/test_legacy_reference_traces.py --regen`（仅在 M0 执行一次；此后再生成属于破坏 oracle，禁止）。

## 5. 命名与边界决策

| 决策 | 理由 |
| --- | --- |
| `runtime/cortico/` → `node_runtime/cortico/` | `runtime` 是发行链保留名（.gitignore:84、build_release_package FORBIDDEN_PARTS、check_release_archive、release.yml rsync exclude、.dockerignore；语义=嵌入式 Python 运行时目录）。计划 §10 允许文件名微调 |
| `vendor/cortico/` 名称保持 | 无冲突；固定快照 + `runtime/cortico/upstream-lock.json` → `node_runtime/cortico/upstream-lock.json` |
| 上游获取 | 本地参考克隆（E:\stella\_reference\Cortico）无 `bc47c824` 对象；已 `git fetch origin bc47c824d388345f1c13722f4a05a5f745a028f8` 成功，提交主题「扩展包图标与 Coo 默认头像 (#134)」，可导出树 |
