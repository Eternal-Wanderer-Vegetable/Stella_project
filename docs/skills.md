# Anthropic 风格 Skills 与受控沙盒

Stella 支持与 Anthropic Skills 同构的任务技能：一个技能就是 `SKILL.md`
正文 + 可选的 `scripts/` 与 `references/` 目录。模型在请求开始时只看到
技能的**名称与描述**；命中技能后才读取正文；脚本与文件操作只在受控
沙盒中执行。

> **整层默认关闭**（`SKILLS_ENABLED=false`）。脚本执行只有 `sandbox`
> 一种受控模式——没有沙盒后端就 fail-closed，**绝不在宿主任意执行代码**。
>
> Skill 不是 Capability：它不进入 `CapabilityRegistry` 的 Provider 图，
> 不参与 Router 的能力竞争，也不占 Comes 的工具预算。

## 目录布局与来源优先级

| 来源层 | 位置 | 信任等级 |
|---|---|---|
| workspace | `<SANDBOX_WORKSPACE_ROOT>/<会话>/skills/<name>/SKILL.md` | untrusted |
| user | `STELLA_HOME/data/skills/<name>/SKILL.md` | managed |
| plugin | `<插件目录>/skills/<name>/SKILL.md` | managed |
| builtin | `assets/skills/<name>/SKILL.md`（随版本发布） | controlled |

同名技能按 **workspace > user > plugin > builtin** 覆盖；同层冲突按
确定性路径排序。目录名即技能名，front matter 里的 `name` 必须与目录
一致。

## SKILL.md 格式

```markdown
---
name: doc-lookup
description: 在项目 docs/ 目录中查找并摘录文档内容。当用户询问……时使用。
license: AGPL-3.0
---

# 正文：给执行器的说明书

按以下步骤……
```

front matter 只有白名单内的**标量**字段会被采纳：`name`、`description`
（必需）、`license`、`compatibility`（可选）。权限类字段（如
`allowed-tools`）一律忽略——信任等级由来源层决定，技能不得自我授权。
解析用 `yaml.safe_load`，复合值（列表/字典）直接丢弃。

`description` 是选择的唯一语义依据（配合技能名），请写成「做什么 +
什么时候用」，控制在千字以内。

## 生命周期（渐进披露）

```
目录扫描（只读 front matter）→ catalog 原子快照
  → 选择（名称/描述匹配，可选 embedding）→ 候选（metadata-only）
  → 命中后才读正文（截断到 SKILLS_BODY_MAX_CHARS）
  → 规划模型产出 JSON 动作计划（白名单校验，逐条把关）
  → 每个动作在独立受限容器内执行
  → 有界摘要 + ArtifactRef 回到主链路
```

不变量：

- 启动与选择阶段**绝不读**正文、scripts、references；
- Skill 正文是**不可信指令**——它指导执行器，但不能改变沙盒策略；
- 规划请求不含 Stella 人格、长期记忆与完整工具表；
- 进 prompt 的只有有界摘要与 workspace 相对产物路径，原始
  stdout/stderr 只进审计日志（`logs/skills_audit.jsonl`）；
- 主链路故障隔离与 Memory/Comes 相同：Skills 任一环节失败，这轮
  没有技能结果，回复照常生成。

## 沙盒执行

抽象动作只有五种：`run_shell`、`run_python`、`read_file`、
`write_file`、`list_files`。文件路径一律是 workspace 相对的 POSIX
路径，禁止 `..`、绝对路径与符号链接。

`SANDBOX_BACKEND=docker` 时，每个动作在**独立容器**内执行：

- 非 root 数字 UID（65532）、只读 rootfs、`no-new-privileges`、
  `CapDrop=ALL`；
- CPU/内存/进程数/墙钟超时/输出大小全部来自 `SandboxLimits`
  （`SANDBOX_*` 配置），调用方的更小预算可以收窄、不可放宽；
- workspace 只挂载为容器 `/workspace`；技能源只读挂载；**绝不**挂载
  项目根、`.env`、记忆库、插件目录、Docker socket 或宿主用户目录；
- 容器用后即删，超时主动终止并审计。

### 网络与远程 runner

- **默认无网络**（`NetworkMode=none`）。进程内 runner 遇到
  `SKILLS_EXECUTION_MODE=sandbox` + 开网络的组合会按策略拒绝——
  域名白名单的强制执行需要外置 runner；
- 部署边界：**不要**把 `/var/run/docker.sock` 挂给 Stella 容器。需要
  Docker runner 时，把 `DOCKER_HOST` 指向 sidecar/代理端点；
- Windows：进程内 runner 不支持命名管道端点，探测会给出明确原因；
  本地开发保持 `SANDBOX_BACKEND=disabled`，需要时把 `DOCKER_HOST`
  指向远程 runner（协议相同，不按 OS 猜测隔离设施）。

## 配置

全部开关见 [配置说明](configuration.md#skills-与沙盒)。常用组合：

| 想要的效果 | 配置 |
|---|---|
| 只浏览技能（默认） | `SKILLS_ENABLED=true`（执行模式保持 `disabled`） |
| 允许技能在沙盒里执行脚本 | `SKILLS_ENABLED=true` + `SKILLS_EXECUTION_MODE=sandbox` + `SANDBOX_BACKEND=docker` |
| 语义匹配（而非仅名称命中） | `SKILLS_EMBEDDING_ENABLED=true`（复用 `MEMORY_EMBEDDING_*` 服务，缓存与 Router 隔离） |

## 编写守则

1. `description` 写清楚触发场景；技能名用小写字母/数字与 `._-`；
2. 正文按「步骤 + 边界」组织：执行器按说明书行动，歧义越少越好；
3. 脚本放 `scripts/`，参考资料放 `references/`——它们在命中后才可见，
   且单文件/总量有字节上限（超限文件不进索引）；
4. **只读示例**（推荐起点）：`assets/skills/doc-lookup/`——只列文件、
   读文档、逐字摘录并注明来源；
5. 反例（会被拒绝或忽略）：在 front matter 写 `allowed-tools` 试图
   自我授权（忽略）；让执行器读 `.env`、记忆库或项目根之外的路径
   （`read_file` 白名单拒绝）；请求白名单外的动作（计划条目被丢弃并
   审计）。

## 状态与排查

- 状态接口（`/stella/status`，回环限制）的 `skills` 段：catalog 版本、
  各层数量、隔离计数、最近错误、沙盒后端状态。只有计数与策略摘要，
  没有正文与路径明细；
- 审计事件（发现、选择、加载、策略拒绝、沙盒启动、超时、输出截断、
  清理）在 `logs/skills_audit.jsonl`，敏感键（环境变量、密钥、命令、
  正文）写入前脱敏；
- 常见现象：
  - 「装了技能但从不出现」→ 技能名不合法、缺 `description`、或
    SKILL.md 超过 `SKILLS_MANIFEST_MAX_BYTES`；隔离原因在状态接口的
    `quarantined` 计数与启动日志；
  - 「执行结果总是沙盒不可用」→ `SANDBOX_BACKEND=disabled` 或 Docker
    daemon 不可达（状态接口 `skills.sandbox.reason` 有原因）；
  - 「插件重载后技能没更新」→ 重载只局部刷新该插件来源；刷新失败会
    保留旧快照并告警，修好后再次重载。
