# Stella 6.1.0 文档索引

中文 | [English](README.en.md)

本目录顶层文档是随仓库维护的使用与开发说明。同步日期：2026-10-08。
版本以 `pyproject.toml` 为准；记忆合同为 schema 18 / backend API 2。

| 文档 | 内容 |
| --- | --- |
| [架构](architecture.md) | 接入、RuntimeFacade、模块与数据边界 |
| [配置](configuration.md) | 环境变量、端点与角色、可选功能默认值 |
| [记忆系统](memory-system.md) | 捕获、晋升、隔离、个人记忆与对话归属 |
| [Rust 记忆后端](memory-rust-backend.md) | 运行模式、合同、资产与排序差异 |
| [能力系统](capability-system.md) | Router、Comes、Provider 与长任务委派 |
| [Cometa](cometa.md) | 外部 Agent 安装、认证、权限与结果回投 |
| [知识库](knowledge-base.md) | 文档导入、ACL、检索与 WebUI 管理 |
| [定时任务](scheduling.md) | 群级 Cron、权限、Agent 与投递语义 |
| [Skills](skills.md) | 渐进披露、来源优先级与受控沙盒 |
| [WebUI](webui.md) | 管理页面、消息流程与桌面壳 |
| [Docker 部署](deployment-docker.md) | 容器配置、数据持久化、升级与备份 |
| [开发](development.md) | 测试、manifest 门禁、评估与发布 |
| [插件规范](plugin-spec.md) | 插件接入、能力声明与失败合同 |
| [迁移报告模板](migration-report-template.md) | 配置与数据导入记录 |
| [模板插件](examples/astrbot_plugin_stella_template/README.md) | 可执行的插件范例 |

每份指南均有对应 `.en.md` 英文版。`plans/`、`reports/`、`migration/cortico/`
及 `reports/evidence/` 保存有日期的计划、调查与验收证据：旧版本号、旧结论和
测试数字表示当时状态，不批量改写为当前版本。后续实施与验收应读最新报告，
不能把计划条目当作已上线功能。项目早期设计资料另在 `design_docs/`。

6.1.0 发布边界：对话归属的真实 QQ 灰度仍需完成；Rust 检索存在 3 个排序
benchmark 差异；归属 guard、主动验证合同、个人记忆写入/分享保持默认关闭。
详见 [P8 验收](reports/2026-10-05-dialogue-attribution-p8-acceptance.md)与
[QQ 灰度清单](reports/2026-10-05-qq-gray-rollout-checklist.md)。
