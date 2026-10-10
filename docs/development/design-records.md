# 设计记录

中文 | [English](design-records.en.md) · [文档总览](../README.md)

`design_docs/` 是设计过程的存档，面向开发者自己：

| 目录/文件 | 内容 |
|---|---|
| `Memory *Specification v1.0.md` | 记忆系统的原始规范（Schema / Consolidation / Retrieval / Policy Matrix / Evaluation & Debug） |
| `Migration & Implementation Plan.md` | v1 → v2 的迁移计划 |
| `Memory Verification Loop.md` | 主动获取回路的设计 |
| `check_point/` | 关键决策节点：问题、诊断过程、被否证的假设、实测数据 |
| `bug_report/` | 缺陷分析 |
| `logs/` | 终端输出与运行日志存档 |

与 `docs/` 的区别：`docs/` 的 guides/architecture/reference/development 是当前维护的说明，plans/reports/migration 是日期档案，`design_docs/` 是过程记录，包含被推翻的假设与失败的尝试——那些信息对理解「为什么现在是这样」很重要，但不适合放进使用文档。
