# Agent 工作文档

[文档总览](../README.md) · [根入口](../../AGENTS.md)

根入口承载全局约束、启动顺序和路由。本目录在任务触发时读取；运行时机器人技能见 [Skills 使用指南](../guides/skills.md)。

| 任务 | 正文 | 事实来源 |
| --- | --- | --- |
| 查依赖、编辑或提交 | [GitNexus](gitnexus.md) | 项目既有图分析约束、CLI |
| 改身份、数据、模块和 prompt | [边界规则](boundaries.md) | 架构、配置路径、迁移、RuntimeFacade |
| 选择检查、判断完成 | [验证门禁](verification.md) | 工作流、package scripts、开发指南 |
| 长任务续接或交接 | [任务状态](workflow.md) | feature_list / progress / handoff |
| 新增指令、移动文档 | [文档维护](documentation.md) | 文档映射、来源与复审条件 |

按任务读取一到两份专题，再沿链接读取正文；临时限制进入状态文件或日期报告。
