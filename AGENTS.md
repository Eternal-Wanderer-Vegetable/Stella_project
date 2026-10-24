# Stella — Agent 工作入口

Stella 是 Python / NoneBot 的 QQ 与 WebChat 机器人，使用 SQLite 记忆、能力路由和 WebUI；Dashboard 为 Vue，CLI 和桌面组件为 Rust。事实从源码与目标提交的验证结果确认。

## 全局约束

1. 编辑前运行 GitNexus **upstream impact**，报告调用者、流程与 risk；HIGH / CRITICAL 编辑前提示，不能用 riskSharedAxes 豁免。UNKNOWN / 零调用者补查源码与引用。详见 [图分析门禁](docs/agent/gitnexus.md)。
2. 查调用关系、依赖与执行流程时先用 query / context / impact；空结果、UNKNOWN 和字面量才用文本搜索补证。符号重命名使用 GitNexus rename。
3. 提交前运行 detect_changes(scope=all)；partial / truncated 须重跑，不能把零当作干净检查。回归审查用 scope=compare, base_ref=main。
4. 凭据、聊天、生产库和本机配置属于用户数据；先确认 STELLA_HOME，验证用临时/隔离目录。见 [数据与模块边界](docs/agent/boundaries.md)。
5. 结论绑定命令、结果与验收范围。计划、单测、真实模型、QQ 灰度和干净 VM 分开记录；缺必要验收保留 NOT READY。

## Startup Workflow

1. 读用户任务，运行 `git status --short`，确认分支与已有修改。
2. 读 [feature_list.json](feature_list.json) 和 [progress.md](progress.md)；续接未完成任务时读 [session-handoff.md](session-handoff.md)。状态可能落后，先核对证据。
3. 按下表加载专题，启动时不通读完整文档库与全部历史报告。
4. 登记本轮 scope 与完成条件。**One feature at a time**：依赖与额外发现写入状态，独立并行工作须有明确所有权。
5. 按 [验证门禁](docs/agent/verification.md) 执行基线；文档可用 `python scripts/check_docs.py`，代码按模块追加检查。

## 按任务加载

| 触发条件 | 必读入口 |
| --- | --- |
| 查文档、配置、使用方法 | [文档总览](docs/README.md) |
| 改模块、接入、消息链路 | [架构](docs/architecture/README.md)、[边界](docs/agent/boundaries.md) |
| 改 Python / Dashboard / Rust 或选择测试 | [开发](docs/development/README.md)、[验证](docs/agent/verification.md) |
| 改记忆、归属、schema、native 合同 | [数据库](docs/development/database.md)、[源码合同](docs/development/contracts.md) |
| 改 prompt、Compact、人格加载 | [边界](docs/agent/boundaries.md)、[模型探针](docs/development/probes.md) |
| 改部署、安装、升级、发布 | [部署开发](docs/development/deployment.md)、[发布](docs/development/release.md) |
| 长任务续接、记录状态、结束会话 | [任务与交接](docs/agent/workflow.md) |
| 新增、移动、更新文档或指令 | [文档维护](docs/agent/documentation.md) |

## Definition of Done

- scope 内交付物和必要检查完成，每个 done criterion 有证据。
- 代码、测试、正文同步；`python scripts/check_docs.py` 和对应 test / lint / build 门禁结果已记录。
- 失败、跳过、未运行与外部验收缺口明确说明；只改文档不宣告运行问题修复。

## End of Session

- 更新任务 status、[progress.md](progress.md) 的结果与 Next、未完成任务的 [交接](session-handoff.md)。
- 列出 Files、Evidence、Blockers 和下一步；确认没有混入已有无关修改，使下一会话可恢复（restartable）。

规则来源、适用范围、复审条件见 [文档维护](docs/agent/documentation.md)。

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **Stella_project** (28983 symbols, 100820 relationships, 796 execution flows).

> Index stale? Run `node .gitnexus/run.cjs analyze --index-only` from the project root — it auto-selects an available runner. No `.gitnexus/run.cjs` yet? Bootstrap with `npx`, `bunx`, or `pnpm dlx` — e.g. `bunx gitnexus@latest analyze` (npm 11 npx crash; #1939).

## Always Do

- **MUST run impact before editing.** Use `impact({target: "symbolName", direction: "upstream"})` or `node .gitnexus/run.cjs impact "symbolName" --direction upstream --repo .`; report callers, processes, and risk. Never substitute grep for graph analysis.
- **MUST analyze graph changes before committing.** Use `detect_changes({scope: "all"})` (MCP) or `node .gitnexus/run.cjs detect-changes --scope all --repo .` (CLI fallback). `partial: true` or `truncated: true` is not a clean check — a zero means unseen, not unaffected; re-run it. For regression review: `detect_changes({scope: "compare", base_ref: "main"})` or `node .gitnexus/run.cjs detect-changes --scope compare --base-ref "main" --repo .`.
- MUST warn on HIGH/CRITICAL `risk` pre-edit; never use `riskSharedAxes` to waive a HIGH/CRITICAL `risk` warning. Compare File/symbol: MCP File omits axes; Graph-RAG expands File.
- **MUST treat `risk: UNKNOWN` as unresolved, not as low.** An empty caller set is not evidence the symbol is unused — it can also mean the callers are not resolvable by the index (plain-object property access, dynamic dispatch, cross-language calls). `impact` pairs `UNKNOWN` with a `riskNote` saying so. Confirm with a text search before treating the symbol as safe to change or delete; do not proceed on the strength of a zero.
- **MUST use `query({search_query: "concept"})` for concepts/flows, `context({name: "symbolName"})` for a named symbol, or `impact` for blast radius, on read-only callers, dependencies, imports, or execution flow.** Graph first; text search only for empty/`UNKNOWN`/literals.
- For security review, `explain({target: "fileOrSymbol"})` lists taint findings (source→sink flows; needs `analyze --pdg`).

## Never Do

- NEVER edit a function, class, or method before MCP/CLI impact analysis.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis, and never read `UNKNOWN` as an all-clear — it means the walk could not answer, which is the one verdict that requires confirming by other means.
- NEVER rename symbols with find-and-replace — use `rename` which understands the call graph.
- NEVER commit before MCP/CLI graph change analysis.

## Resources

| Resource | Use for |
| --- | --- |
| `gitnexus://repo/Stella_project/context` | Codebase overview, check index freshness |
| `gitnexus://repo/Stella_project/clusters` | All functional areas |
| `gitnexus://repo/Stella_project/processes` | All execution flows |
| `gitnexus://repo/Stella_project/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
| --- | --- |
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->
