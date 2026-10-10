# GitNexus 使用门禁

[Agent 导航](README.md)

适用：查调用关系、依赖或执行流程，编辑符号，重命名，提交与回归审查。来源：原根 `AGENTS.md` 的图分析规则。工具升级或仓库绑定变化时复审命令，保留原有门禁。

## 绑定与新鲜度

索引仓库名是 `Stella_project`。先列仓库，检查索引与工作区；多仓库环境每次查询显式指定 repo。符号数和流程数属于索引快照，不在根入口硬编码。

```bash
node .gitnexus/run.cjs list
node .gitnexus/run.cjs status
node .gitnexus/run.cjs query "message ingress" --repo Stella_project
node .gitnexus/run.cjs context RuntimeFacade --repo Stella_project
```

本开发机也可用 Docker 的 `stella-gitnexus`，项目挂载于 `/repo`：

```bash
docker exec stella-gitnexus gitnexus status
docker exec stella-gitnexus gitnexus query "message ingress" --repo Stella_project
```

陈旧索引需要刷新。普通分析用 `analyze --index-only`；已有 PDG 或需要安全/数据依赖分析时保留 `--pdg`。刷新后复查根入口，防止生成上下文引入重复规则。runner 缺失时按 `.claude/skills/gitnexus-cli/SKILL.md` 引导安装。

## 编辑前

```bash
node .gitnexus/run.cjs impact "symbolName" --direction upstream --repo Stella_project
```

MCP：`impact({target: "symbolName", direction: "upstream", repo: "Stella_project"})`。同名结果须用 uid / file 消除歧义。报告直接调用者、受影响流程、risk 与索引限制。

- HIGH / CRITICAL：编辑前提示；`riskSharedAxes` 不能豁免。File 与 symbol 的风险尺度不相同；MCP File 省略部分轴，Graph-RAG 可展开 File。
- UNKNOWN / 零边：补查源码、注册表、动态调用与文本引用。空图不能证明未使用，也不能替代验收。
- 文档移动也先分析文件引用，再检查链接和章节锚点；文本搜索补足空结果、UNKNOWN 或字面量信息。
- 重命名符号使用 GitNexus `rename`，不以文本替换代替语义重命名。
- 安全审查用 `explain({target: "fileOrSymbol"})` 查看 source→sink 发现；索引须含 PDG。

## 提交前

```bash
node .gitnexus/run.cjs detect-changes --scope all --repo Stella_project
# 对 main 的回归审查
node .gitnexus/run.cjs detect-changes --scope compare --base-ref main --repo Stella_project
```

MCP 使用 `detect_changes({scope: "all"})`；compare 增加 `base_ref: "main"`。`partial: true` / `truncated: true` 需重跑补齐，零结果不能代表未扫描的变更不受影响。

资源：`gitnexus://repo/Stella_project/context`、`clusters`、`processes`、`process/{name}`。CLI 专题技能在 `.claude/skills/`：exploring、impact-analysis、debugging、refactoring、guide、cli，按任务加载对应 `SKILL.md`。
