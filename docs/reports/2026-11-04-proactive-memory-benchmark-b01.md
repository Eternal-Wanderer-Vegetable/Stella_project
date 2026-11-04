# 主动参与与记忆 Benchmark — B01 数据合同与隔离运行器

- 日期：2026-11-04
- 工作包：B01；证据等级：L0 合同/合成夹具
- 状态：评测合同、隔离执行与恢复检查完成；真实公开数据适配及产品效果仍 **NOT READY**。
- 计划：[主计划](../plans/2026-11-04-proactive-memory-benchmark-plan.md)；前置：[B00 报告](2026-11-04-proactive-memory-benchmark-b00.md)

## 交付

- proactive_eval/adapters.py 验证锁定 registry、actor scenario 与 scorer gold 的 JSONL 合同、文件 SHA-256、样本 ID、事件引用和 episode/split 一致性。空 actor/gold、错误 hash、跨 split episode 与不匹配 gold 引用被拒绝。B01 建立通用已适配 JSONL 接口；When2Speak、Social AI 等源格式转换在 B02。
- proactive_eval/cli.py、plugins.py 与 worker.py 提供 validate/run 命令。actor 与 scorer 分别在独立子进程执行；actor 接收单个 actor-only scenario，完成退出后才启动 scorer。父进程在 actor 阶段只计算 gold 文件摘要，不解析或发送 gold 内容。worker 使用最小环境变量 allowlist、隔离且标记的 STELLA_HOME；run 输出要求在仓库外或被 gitignore。
- runner.py 把运行指纹、actor 输入摘要、checkpoint 与逐样本结果绑定。每条结果先 fsync 到 JSONL，再原子替换 checkpoint；恢复时只截去不完整尾行、计入恢复重试，并拒绝不同指纹/输入、重复或意外样本和不守恒计数。scorer 有独立指纹、gold 摘要和样本数检查。
- fingerprint.py 对 registry、协议、代码提交、允许范围内的工作树差异、actor 输入、解析后的非秘密配置与随机种子生成规范化 SHA-256；gold 通过 scorer 指纹单独绑定。无关的日志、扩展与操作脚本不纳入未跟踪文件摘要。
- core/evaluation/events.py 为虚拟时钟回放定义稳定顺序：同刻 timer 先于 message，再用源 sequence 和 event ID 解同类事件平局；拒绝无时区/重复/无效事件。不改生产定时器。
- metrics.py 提供有明确分母的二分类参与指标、Macro-F1、FIR/MIR 与空分母状态；report.py 做 schema 验证和原子写入；legacy.py 只读接入既有 memory-eval-report/1，不回写历史报告。

没有改动 memory_eval/runner.py、memory_eval/scenarios.py 或 memory_eval/report.py。GitNexus 对旧 memory_eval.runner.run 的调用关系是下界（21 个调用点因动态接收者未解析）；因此 B01 以新合同和只读兼容适配器承接，不将旧 runner 的零/少量图边当作安全删除依据，也不改写历史证据。

## 验证

- Python 3.12.14 隔离环境，STELLA_HOME 指向临时路径。执行：
  pytest tests/evaluation/test_proactive_eval_contracts.py tests/evaluation/test_virtual_clock.py tests/evaluation/test_pipeline_replay.py tests/evaluation/test_evaluation_isolation.py tests/evaluation/test_stability_report.py -q
  — **40 passed**（6.18s）；pytest-asyncio 发出 fixture loop scope 未显式设置的弃用警告。
- ruff check core/evaluation/events.py proactive_eval tests/evaluation/test_proactive_eval_contracts.py — **PASS**。
- 临时目录合成 CLI E2E — validate PASS；错误 gold hash 在启动 worker 前被拒绝；有效样本通过 actor 子进程、actor 退出后再通过 scorer 子进程；actor/scorer 各 1/1 完成，fixture score 正确。运行产物仅在系统临时目录。
- 自动测试覆盖异指纹与异输入续跑拒绝、crash 后不完整尾行恢复/重试计数、两次事件轨迹一致、gold 不能进入 actor、虚拟时间同刻排序、指标边界、报告原子写入与旧报告只读。
- python scripts/check_docs.py — **127 files / 1361 local links / 577 anchors / 0 errors**。
- git diff --cached --check 与 git diff --check — PASS。
- GitNexus pre-edit：VirtualClock upstream LOW（7 impacted / 3 direct / 0 processes）；core/evaluation/runner.py File MEDIUM（5 direct / 0 processes，未改）；memory_eval/scenarios.py File MEDIUM（6 direct / 0 processes，未改）；memory_eval.runner.py File LOW，但 run exact context 显示21个未解析调用点下界，未改。提交前 detect-changes scope=all：18 files / 6 indexed symbols / 0 processes / LOW；索引报告的6个符号都来自已跟踪 README 与状态文档，新加源码文件在当前索引中还没有符号，因此不将图中空结果解释为无调用者。scope=compare base_ref=main：338 files / 2649 symbols / 113 processes / CRITICAL；changed-symbol 列表 capped，为分支累计风险且保留不豁免。

## 限制与后续

B01 的输入为本地合成夹具；没有下载/解析公开测试集，没有启动模型、Bot、服务或平台，也没有读写生产聊天、数据库或用户配置。CLI 的临时 E2E 只证明合同与隔离边界可运行，不证明公开数据转换准确、真实组件决策正确或产品效果提升。

B00 的检索基线仍 PARTIAL；embedding/hybrid 与新 LoCoMo judge 未运行。B02 才实现 When2Speak/Social 源格式适配并建立无记忆原样基线；B03–B07 的时机、写入、记忆使用、中文双标、盲测与统计门禁未完成。B06 标注员尚未安排，B08 用户目标范围、明确授权与七天观察条件未满足。benchmark 全体效果、产品行为与 QQ/WebChat/Windows 发布验收保持 **NOT READY**。

## 恢复点

当前提交只涵盖 B01。回滚本包可 revert 英文提交 feat(eval): add isolated proactive evaluation runner；B00 协议/来源冻结提交独立保留。原有未跟踪 .zcode/、debug.log、extensions/ligamina_bridge/、scripts/start_managed_stella.ps1 不属于本包。
