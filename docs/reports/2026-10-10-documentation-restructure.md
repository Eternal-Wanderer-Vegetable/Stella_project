# 项目文档结构整理记录

日期：2026-10-10（Asia/Shanghai）。源码基线：`952007e`，分支 `codex/compact-8192-batching`。范围为文档结构、Agent 工作入口与文档校验；不包含业务功能修复或真实 QQ/模型/VM 验收。

## 依据与问题

依据 [第四讲：把指令拆分到不同文件里](https://walkinglabs.github.io/learn-harness-engineering/zh/lectures/lecture-04-why-one-giant-instruction-file-fails/)、本项目 harness-creator 和 writing-for-agents。采用短根入口、任务触发的专题规则、单一正文、按需展开与明确验证门禁；行数预算是维护约束，不是模型效果保证。

原 AGENTS/CLAUDE 只有重复的 GitNexus 上下文；开发长文混合了环境、测试清单、模型探针、迁移、CI 与发布。索引仍写 schema 18/API 2，而当前分支源码已为 schema 19/API 3。

## 交付结构

| 位置 | 职责 |
| --- | --- |
| [AGENTS](../../AGENTS.md) / [CLAUDE](../../CLAUDE.md) | 共同约束、启动顺序、按任务加载、完成标准和交接；Claude 引用共同入口 |
| [文档总览](../README.md) | 面向使用、架构、参考、开发、Agent 与历史的任务导航 |
| [使用指南](../guides/README.md) | 部署、WebUI、Cometa、定时任务、运行技能 |
| [架构](../architecture/README.md) | 模块、消息链路、数据归属、预算、扩展与子系统 |
| [参考](../reference/README.md) | 配置、插件合同、迁移模板 |
| [开发](../development/README.md) | 环境、测试、探针、迁移、CI、发布、排查和源码合同 |
| [Agent 专题](../agent/README.md) | 工具门禁、模块边界、验证、任务状态与文档维护 |
| [历史导航](../history/README.md) | 原计划、调查、实施、验收与迁移记录，保留原路径和日期 |

迁移了 24 份完整双语子系统/使用/参考正文，把原架构与开发的 4 份长文拆成 34 份专题正文；合计 58 份维护正文。28 个旧公开路径保留导航，577 个原章节锚点由 [映射](../documentation-map.json) 绑定目标页。兼容页不维护第二份正文。

根 `feature_list.json` / `progress.md` / `session-handoff.md` 只跟踪登记任务；没有把旧计划导入成“已实现功能”。`init.ps1` / `init.sh` 以 docs/python/dashboard 区分验证范围；默认 docs 不启动服务或写生产库。CI 增加独立 documentation 门禁，发布工作流排除根状态和初始化文件。

## 源码核对与图分析

- Docker `stella-gitnexus` 绑定 `/repo` 的 `Stella_project`，刷新后恢复原 PDG 模式。
- `query` 查接入/运行/能力/记忆流，`context RuntimeFacade` 确认 gateway、状态 API 和 WebChat 接线；源码核对 facade、turn_service、home、schema 与 native 常量。
- 编辑前文档文件 impact 为 LOW/MEDIUM。架构/开发中文版各 26 个上游文件（7/5 个直接引用），英文架构 27 个。文件节点不提供完整执行流程归属，不能据此宣布运行链路没有影响。
- AGENTS/CLAUDE 与新校验工具没有解析调用者，workflow 文件不在图中：UNKNOWN 通过文本引用及实际文件检查补证，不视为低风险。
- 全图过程提取存在预算警告；其缺失流程不作为不存在的证据。文档兼容由独立路径/锚点检查验证。

## 事实修正

[源码合同](../development/contracts.md) 明确当前分支 schema 19/API 3 与已发布 6.1.0/P8 的 schema 18/API 2 快照。现行指南同步此区别，历史报告原结论保留。环境正文的便携目录优先级修正为 `config/home.py` 的第 2 条；CI 正文补齐原先遗漏的 flow-manifest / flow-closure 和新 documentation job。

## 验证证据

| 检查 | 结果 |
| --- | --- |
| `python scripts/check_docs.py` | 119 份维护文档、1187 条本地链接、577 个迁移锚点；0 错误 |
| `python -m unittest discover -s tests/documentation -v` | 6/6 正反例通过 |
| 新增校验器/合同测试的 `python -m ruff check` | 通过 |
| `git diff --check` 与新增文件空白检查 | 通过 |
| 历史保真 SHA256 | 迁移前 246 文件均存在且哈希一致；原章节锚点集合无遗漏 |
| Windows / Git Bash docs 初始化 | 均通过；非法模式分别退出 1/2，空仓库校验退出 1 |
| CI / release YAML | 解析通过，documentation 接入门禁/通知，开发状态文件排除出发布包 |
| harness-creator 结构评分 | 28/100 → 100/100，五子系统均 5/5；不是运行 benchmark |
| GitNexus scope=all | 120 文件/859 符号，risk low，未置 partial/truncated；全量结构结果已核对 |

GitNexus CLI 只展示前 15 项，另用同一 LocalBackend 的 detect_changes 读取完整结构结果。为纳入尚未跟踪的本轮 83 个新增文件，使用独立 Git index 的 intent-to-add；真实 index 哈希未变，暂存区未更改。0 个 affected processes 受文件节点与流程预算限制，不证明运行路径没有影响。

检查器只校验当前 Markdown 的本地链接、锚点、双语配对、迁移映射和状态；不联网检查外链，也不批量检查/改写历史档案。完整任务摘要见 [progress](../../progress.md)。

## 验收范围

文档链接、双语配对、迁移锚点、状态结构和历史保真属于本次验收。harness-creator 评分只衡量结构与关键词，不是 Agent 可靠性 benchmark。真实效果需要后续代表性任务会话；原 QQ、Rust parity、VM/GUI 首启缺口不因整理文档关闭。
