# Stella 文档总览

中文 | [English](README.en.md)

按任务选择入口，再按需展开专题。当前分支事实由源码与目标提交 CI 确认，发布说明与验收保留日期证据。

| 当前任务 | 从这里开始 |
| --- | --- |
| 安装、部署、管理 WebUI、使用可选功能 | [使用指南](guides/README.md) |
| 理解模块、消息链路、记忆和身份 | [架构导航](architecture/README.md) |
| 查配置项、插件合同、迁移报告模板 | [配置与接口参考](reference/README.md) |
| 开发、测试、迁移数据、排查、发布 | [开发导航](development/README.md) |
| 作为编码 Agent 工作、选择门禁、续接任务 | [Agent 工作文档](agent/README.md) |
| 找计划、根因调查、实施与验收证据 | [历史档案导航](history/README.md) |
| 编写 AstrBot 兼容插件 | [模板插件](examples/astrbot_plugin_stella_template/README.md) |

## 目录与正文归属

`guides/`、`architecture/`、`reference/`、`development/` 保存配对的中文/英文正文。`agent/` 保存简短的项目工作规则。旧顶层路径只保留章节导航，新链接直接指向正文；[文档映射](documentation-map.json) 记录迁移和原章节锚点。

`plans/`、`reports/`、`reports/evidence/`、`migration/cortico/` 与根目录 `design_docs/` 保留原日期和结论，从 [档案导航](history/README.md) 查找后续证据。计划不等于已实现，单测不等于真实验收。

## 当前源码与验收边界

应用版本查 `pyproject.toml`，当前分支的记忆/native 合同查 [源码合同](development/contracts.md)。已发布 6.1.0 快照与后续分支变化分别说明；旧报告里的 schema/API 是当时的测试对象。

真实 QQ 归属灰度、Rust 排序 parity、干净 VM / GUI 首启需要各自验收证据；文档整理不关闭这些缺口。有日期的 [P8 报告](reports/2026-10-05-dialogue-attribution-p8-acceptance.md) 和 [QQ 清单](reports/2026-10-05-qq-gray-rollout-checklist.md) 保留原结论。

维护时读 [文档归属与检查规则](agent/documentation.md)。
