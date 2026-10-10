# 文档维护规则

[Agent 导航](README.md) · [文档总览](../README.md)

适用：新增/移动文档、修改指令、同步源码事实。依据：[第四讲：把指令拆分到不同文件里](https://walkinglabs.github.io/learn-harness-engineering/zh/lectures/lecture-04-why-one-giant-instruction-file-fails/)、harness-creator 和 writing-for-agents。

## 内容归属

| 位置 | 内容 | 更新触发 |
| --- | --- | --- |
| 根 AGENTS / CLAUDE | 全局约束、启动、路由、完成、交接 | 工作流程或路由变化；CLAUDE 只引用共同入口 |
| `docs/agent/` | 工具、边界、验证、状态、文档规则 | 对应来源变化 |
| `docs/guides/` | 部署、管理、使用步骤 | 用户可见行为或命令变化 |
| `docs/architecture/` | 模块、流程、身份/数据、设计理由 | 源码合同或运行接线变化 |
| `docs/reference/` | 配置、插件合同、模板 | 配置项或接口变化 |
| `docs/development/` | 环境、测试、探针、数据库、CI、发布、排查 | package scripts、CI 或开发流程变化 |
| plans / reports / migration / design_docs | 日期计划、实施、调查、验收、证据 | 增加后续记录，保留原日期和结论 |
| 根任务状态三文件 | 当前任务与恢复动作 | 会话结束或范围变化 |

## 单一正文与渐进展开

根入口控制在 200 行以内；这是维护预算，不是效果保证。专题围绕任务触发条件；长配置表和测试清单作为参考按需读取，避免为凑行数拆散同一合同。

规则只有一个权威正文，入口用“触发条件 + 链接”路由。参数/版本从源码查，不复制到所有入口。新增规则标明来源、适用条件、复审/移除条件；临时故障进入状态或报告。

| 规则正文 | 来源 | 复审 / 移除条件 |
| --- | --- | --- |
| [GitNexus](gitnexus.md) | 既有项目指令、CLI | runner / 图接口升级；替代流程保留原门禁 |
| [边界](boundaries.md) | home、runtime、schema、prompt 与架构 | 合同改变，退役边界补迁移记录后移除 |
| [验证](verification.md) | CI / manifests / 开发正文 | 测试、构建、发布门禁改变 |
| [状态](workflow.md) | harness-creator、状态三文件 | 生命周期替换，旧记录封存后移除旧规则 |
| 本页 | 第四讲、当前布局 | 分类或兼容策略变化 |

## 移动与双语同步

1. impact 检查文件及引用；按主题迁移，保留章节内容，事实更新另作记录。
2. `.md` / `.en.md` 配对同步，修正相对链接和跨章节链接；新导航直接指向正文。
3. 旧公开路径保留导航和原锚点，不维护第二份正文；登记 [documentation-map.json](../documentation-map.json)。
4. 历史正文和相对路径稳定；旧结论增加后续记录，不批量改成当前版本或“已完成”。
5. 跑 `python scripts/check_docs.py`、`git diff --check`，校验路径、配对、映射与根入口预算。

当前分支合同见 [源码合同](../development/contracts.md)；已发布合同和验收属于日期证据。代码存在、部署加载和效果分开陈述。结构检查不证明 Agent 实际运行可靠性提高，需后续代表性会话验证。
