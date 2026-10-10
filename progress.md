# Session Progress Log

## Current State

**Last Updated:** 2026-10-10 (Asia/Shanghai)
**Active Feature:** none; CI-001 and DOC-001 done
**Scope:** PR #105 的 CI 修复：源码闭包预算、生成清单、回归与在线 CI；基线 f8b2dce。此前 DOC-001 仅修改文档与门禁。

## What's Done

- 58 份双语正文按主题归类；架构和开发长文拆分；28 个原路径和 577 个原章节锚点保留。
- AGENTS 为 45 行任务入口，CLAUDE 引用共同规则；专题标明来源和复审条件。
- 当前源码合同与发布快照区分，补齐 CI 与数据目录优先级说明。
- 建立任务状态、Windows/Git Bash 初始化、文档 CI 门禁；根状态文件排除出发布包。

## Verification Evidence

- `python scripts/check_docs.py`：通过；路径、双语、迁移锚点和状态检查无错误。
- 独立 unittest 6/6；新增 Python 文件 Ruff 通过；`git diff --check` 通过。
- 246 个迁移前历史文件 SHA256 完全一致，原章节锚点集合无缺失。
- PowerShell/Git Bash docs 模式通过；非法模式退出码 1/2，空仓库文档检查退出码 1。
- GitNexus scope=all：120 文件/859 符号，low；用独立 index 纳入本轮 83 个新增文件，真实 index 未改。
- harness-creator：28/100 → 100/100，仅结构评分。详见 [整理报告](docs/reports/2026-10-10-documentation-restructure.md)。

## Files

- AGENTS/CLAUDE、README、docs 分类正文/兼容入口/映射、Agent 专题、根状态三文件。
- scripts/check_docs.py、tests/documentation、init.ps1/init.sh、CI 和 release 排除项。

## Blockers / Risks

- 本次文档验收已完成。模型、QQ、native parity、VM/GUI 与实际 Agent 会话效果仍需各自证据，不在本次结论中关闭。
- 保留原有未跟踪技能、日志、计划、报告、证据及 native 备份，不纳入本轮提交。用户已审核文档重整并授权提交上传，最终提交与远端状态以 Git 记录为准。

## What's Next

1. 新任务从 AGENTS 与主题导航进入，核对 Git／PR 最新状态和工作区。
2. CI-001 已完成；没有新用户任务时不自动执行历史计划。

## PR #105 CI Repair — 2026-10-10

- CI-001 done；scope：闭包预算、生成清单、回归与在线 CI。
- 基线 f8b2dce；本地复现两项合同失败：manifest 漂移、四个 ingress 截断。
- record_group_chat 实际闭包 257 个辅助符号，旧上限 256；显式 cap=512 完整展开。
- 修复：默认 cap 256 → 512，保留小预算截断与零核心截断门禁；按仓库惯例替换随包清单。
- 验证：40 项专项通过；全量 Python 3669 passed / 17 skipped（Windows Python 3.14、隔离 STELLA_HOME）；623 个已跟踪 Python 文件 Ruff 通过；清单漂移、文档门禁通过。
- 修复提交：3b31931，已推送 PR #105；[主 CI](https://github.com/Eternal-Wanderer-Vegetable/Stella_project/actions/runs/38043343651) 全部 11 项通过，[Dashboard CI](https://github.com/Eternal-Wanderer-Vegetable/Stella_project/actions/runs/38043343680) 通过。
- 提交前 GitNexus：6 文件、11 符号、low，无 partial/truncated；提交后索引刷新到修复提交并保留 PDG。
- CI-001 验收完成。完成记录的后续提交与 CI 以 Git／PR 最新状态为准；新任务由用户授权。

### Final-head Dashboard follow-up

- 2906569 的 Dashboard CI 暴露既有大数据功能用例超时（5.17s > 默认 5s）；原修复提交的主 CI 与 Dashboard 全部通过记录仍有效。
- 保留 100 页／100000 事件、全部水位断言、性能专项预算；仅该功能用例超时设为 15s。
- c7751f6 已修复该超时；本地 Dashboard 100 项测试、类型检查、生产构建通过。
- [主 CI](https://github.com/Eternal-Wanderer-Vegetable/Stella_project/actions/runs/38044052769) 全部 11 项通过，[Dashboard CI](https://github.com/Eternal-Wanderer-Vegetable/Stella_project/actions/runs/38044052792) 通过；CI-001 done，无活动任务。
- 完成记录提交的最终 SHA／检查结果以 Git 和 PR 最新状态为准。
