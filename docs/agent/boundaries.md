# 数据与模块边界

[Agent 导航](README.md) · [架构导航](../architecture/README.md)

适用：改数据路径、会话身份、记忆、prompt、接入与模块职责。来源为下表源码和开发正文；对应合同变化时复审。

| 边界 | 改动要求 | 来源 |
| --- | --- | --- |
| 用户数据与程序 | 用 `config/home.py` / `python -m deploy paths` 解析数据根；验证用临时库、隔离 workdir，保留升级前备份 | [环境](../development/environment.md)、[数据库](../development/database.md) |
| prompt 优先级 | 用户数据中的 `system_prompts/` 可覆盖仓库默认值；检查实际加载源，记录协议迁移是否需更新用户配置 | `config/settings.py`、[配置](../reference/configuration.md) |
| 身份与受众 | QQ 群、ConversationRef、平台用户、共享空间、owner / subject / audience 分别校验，不按旧表 ID 正负推导权限 | [数据边界](../architecture/data-boundaries.md)、[记忆](../architecture/memory-system.md) |
| schema 与 native | 每次升级同时维护迁移与旧库回归，Python/native 常量对齐；wheel 版本不能代替合同核验 | [源码合同](../development/contracts.md) |
| 执行入口 | 接入经 RuntimeFacade，单轮服务负责 prepare / generate / finalize；检查接线与回执后再报告运行结果 | `core/runtime/facade.py`、[消息链路](../architecture/message-lifecycle.md) |
| WebUI | 叶子包通过 host injection 取得状态；新增包检查发布 payload，GUI 复用 Python 配置与路径合同 | `webui/status_source.py`、[环境](../development/environment.md) |
| 能力与记忆 | Router、Comes、记忆和独立知识库保持各自职责；新 provider 同步工具解析和失败合同 | [能力](../architecture/capability-system.md)、[知识库](../architecture/knowledge-base.md) |
| Compact | 保持 8192 tokens 上限；完整来源单元预规划批次，失败、无效引用或 length 输出不推进成功水位 | `stella_project/plugins/bot_main/session_compact.py`、[预算](../architecture/llm-budget.md) |

凭据、原始聊天、生产库和本机配置不进入提交或公开证据。约束回归同时覆盖允许与禁止路径；语义问题增加 [模型探针](../development/probes.md) 和真实链路验收。
