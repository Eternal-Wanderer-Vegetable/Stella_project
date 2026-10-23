# Corona / Nucleus 规划证据

日期：2026-10-23，Asia/Shanghai。基线 `c1713e3dfb0854e1a7b746e0ef1e5c82ed9a8485`。本目录仅含代码图、公开源码接线、合成配置和隔离测试结果，不含用户凭据、聊天、生产配置内容或业务数据库。

入口：[工程计划](../../../plans/2026-10-23-corona-nucleus-engineering-plan.md) · [机器清单](../../../plans/2026-10-23-corona-nucleus-inventory.json)。业务实施尚未开始；新架构运行、QQ、真实模型、clean VM 和发布均 NOT READY。

## 图绑定与使用方式

- [仓库绑定](repos.txt)、[新鲜度](status.txt)、[索引摘要](index-snapshot.json)：GitNexus 1.6.12、PDG、目标 HEAD 内容一致；索引时分支名仍是原 Dashboard 分支，新计划分支的源码 HEAD 相同。
- [命令、退出码、输出与替代记录](graph-commands.json)：6 组主题 query、12 组 context、文件和符号 upstream impact、814 条流程总表及关键流程步骤。
- [完整 settings 影响](impact-00-config_settings.py-output-retry.txt)：CRITICAL，278 impacted / 76 direct；[config 入口影响](impact-01-config___init__.py.txt)：CRITICAL，205 / 69。
- [空间 reload 影响](impact-symbol-reload-spaces.txt)：CRITICAL，13 impacted / 2 direct / 7 flows。业务代码未修改；实施前仍须重新跑 upstream impact 并提示 HIGH/CRITICAL。
- [重启主题](query-restart.txt)、[启动重跑](query-startup-retry.txt)、[WebUI](query-webui.txt)、[后台](query-background.txt)、[配置](query-configuration.txt)、[Runtime](query-runtime.txt)。
- [完整流程快照](processes-output-retry.txt)、[关键流程步骤](selected-process-steps.txt)。流程为有预算的推断图，不能作为运行入口覆盖分母。
- [源码与动态接线补证](source-reference-audit.txt)：bot.py 的 Popen/启动器、Tauri 宏/invoke、Cometa 动态 runtime stop。新计划文件在索引中不存在，UNKNOWN 是预期结果；创建前现有状态/历史导航无对应字面引用。

文件级影响没有流程/社区归属，所以 flows=0 不代表执行路径不存在。UNKNOWN 不降级为低风险。前一轮同 HEAD 刷新时观察到 2,889 个入口候选遗漏、804 条 callee 分支遗漏、41 次预算截断、21 次深度截断；本轮明确保留限制，不作全图完备性声明。`index-snapshot.json` 含 receiver/coverage 能力摘要，详细接线仍以源码补证为准。

## 失败与输出完整性

- `query-startup.txt` 首次返回 partial，已串行重跑为 `query-startup-retry.txt`；不能使用初次结果作为通过证据。
- `impact-00-config_settings.py.txt`、`processes.txt` 初次通过子进程 pipe 捕获时在约 64 KiB 中断，JSON 不完整。重跑将 stdout 直接写普通文件，完整输出分别为 `*-output-retry.txt`，含 278 个影响项/814 流程；旧记录保留诊断用途。
- 新计划 path impact 返回 not found/UNKNOWN 是新文件尚无图节点的预期，不作为“无引用”证明；历史导航和新归档链接另由文档/归档检查核验。
- 不依据 raw 文本中出现 `truncation` 一词判断所有查询失败；区分分析器流程抽取限制、工具 partial/truncated 标志与 CLI 输出完整性。

证据脚本格式整理前另跑了 upstream impact：`framework_probe.py` 和 `verify_plan.py` 为 CRITICAL（各含 179 个推断受影响流程），`config_probe.py` 和 `build_inventory.py` 为 LOW。已先提示原始风险，补查文档链接与显式 shell 入口，再仅整理格式/import 并重跑探针、清单复现和 Ruff；原始结果见 `impact-evidence-*.json`。不以 riskSharedAxes 豁免，也不把图中的宽泛关系当成这些脚本参与生产业务的证明。

最终增量刷新曾出现已知有变更但文档符号映射归零，工具未报 partial/truncated；该结果未作为干净检查。强制全量重建后，结构化 all 为 5 files / 10 symbols / LOW，compare main 为 26 / 47 / LOW，列表完整且无 partial/truncated。原始前后结果见 `detect-incremental-zero-*.json` 与 `detect-final-*.json`；compare 包含继承的分支变更。

## 隔离验证

| 内容 | 证据 | 结果与边界 |
| --- | --- | --- |
| 数据路径边界 | [data-boundary.json](data-boundary.json) | STELLA_HOME 外部未设置；只解析 home 来源，没有打开生产配置/库；测试全部临时 home |
| 配置继承、删除和覆盖 | [探针](config_probe.py)、[结果](config-probe-result.json) | 真实 config.settings：复制旧环境 11，改盘 22 仍读 11；fresh=22，删除=90，外部覆盖=44，prod overlay=33 |
| NoneBot 文件源 | [探针](framework_probe.py)、[结果](framework-probe-result.json) | 本机 2.5.0：init(None) 不是禁读；显式 Env/Config(_env_file=None) 不读临时合成 .env；未启动 Driver/server |
| 既有专项基线 | [baseline-pytest.txt](baseline-pytest.txt) | 83 passed / 37.20s；八个既有文件，非新架构测试 |
| 文档基线 | [baseline-docs.txt](baseline-docs.txt) | 119 files / 1247 links / 577 anchors / 0 errors；尚未计入新导航 |
| 清单构造与复核 | [构造脚本](build_inventory.py)、[复核脚本](verify_plan.py) | 12 工作包 DAG、199 源码指纹、133 静态路由双向核对、426 配置键、34 场景、归档链接、证据 hash；含拒绝依赖环负例；证据脚本 Ruff 及格式整理后复现通过 |

实际 pytest 命令（独立 `mktemp` 目录，未启动 Bot）：

```bash
STELLA_HOME="$(mktemp -d /tmp/stella-corona-baseline-XXXXXX)" .venv/bin/python -m pytest -q tests/test_self_restart.py tests/test_stop_signal.py tests/test_instance.py tests/test_deploy_process.py tests/test_graceful_shutdown.py tests/webui/test_webui_config.py tests/webui/test_webui_mount.py tests/webui/test_webui_chat.py
```

配置键清单包含字面量 `_env*`、端点槽拼接与 legacy fallback，以及显式补登记的框架/身份键。它不枚举所有插件动态键；源码/运行时登记仍需 CN00 补齐。路由清单的 proposed_owner 是设计决策，不是已经完成的迁移。

## 复核命令与校验范围

从仓库根执行：

```bash
python3 docs/reports/evidence/corona-nucleus-20261023/verify_plan.py
python3 scripts/check_docs.py
git diff --check
```

[manifest.json](manifest.json) 固定本目录原始证据与工具的 SHA256；不自哈希，也不把本 README、后续 verification 摘要或本地最终图检查输出纳入循环校验。`verify_plan.py` 同时核验正文归档链接，补足 `check_docs.py` 默认不 lint 日期归档的边界。

本轮最终图变更输出留在忽略目录 `.gitnexus/verification/corona-nucleus-20261023/`，摘要写入任务状态；detect_changes 主要扫描已跟踪变更，新归档的链接、清单、源指纹和原始证据由上述复核单独覆盖。最终检查不代表业务实现、完整 Python suite、模型/QQ 或安装发布已通过。
