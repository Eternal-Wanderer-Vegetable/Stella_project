# 跨平台方案的 GitNexus 证据（2026-10-20）

本目录绑定 `main@ba582a922f4d3379b6397c4c0a8d8ef3e7c3e77d`。它记录静态研究与计划，不代表跨平台实现或平台真实收发测试通过。

- [方案正文](../../../plans/2026-10-20-gitnexus-cross-platform-plan.md)：合同、迁移、12个工作包、测试与回滚。
- [执行附录](../../../plans/2026-10-20-cross-platform-inventory.md)：50个运行入口、32个适配器、180个候选文件。
- [命令清单](commands.json)、[消歧与补查](followup-commands.json)、[全量流程与PDG复查](final-audit-commands.json)：LocalBackend与CLI使用同一GitNexus 1.6.11工具实现，均显式绑定Stella_project。
- [原始建库日志](analyze.log)、[运行时安装日志](bootstrap.log)、[初始索引元数据](index-meta-baseline.json)。初始建库为1,249文件、95,747节点、236,981边；不把BasicBlock算作业务函数，也不把推断流程算作运行入口全集。
- [图谱schema](resource-schema.json)、[仓库上下文](resource-context.json)、[全量829个推断流程](graph-processes-all.json)、[节点类型](graph-node-types-fixed.json)、[关系类型](graph-relation-counts.json)。Resource摘要只提供部分流程；全量结果来自Cypher。
- `context-*.json` / `impact-*.json` / `query-*.json`：原始结果，直接调用者、epistemic、boundaries和risk字段保留；[风险汇总](impact-summary.json)便于机器读取。
- [首次查询问题及修正对应](query-resolutions.json)：首次歧义、错误目标或截断不被删去伪装为一次成功。最终使用UID、正确文件/资源label及扩大PDG深度后的结果。
- [PDG最终切片](pdg-evidence-slice-depth64.json)：来源主体校验处的局部依赖，无截断；UNKNOWN风险仍保留，不能当权限证明。
- [运行入口及注册双向核对](runtime-entry-inventory.json)：50声明入口/9流程族，34注册扫描结果，缺失/漏登记均为空。
- [字面量审查](literal-coupling-inventory.json)：599个已跟踪生产/部署/前端/工具文件，1,112条命中，包含注释和生成manifest，不是必改数。
- [动态和跨语言缺边补证](unknown-boundary-supplement.json)、[图与文本合并文件清单](engineering-scope-files.json)：180候选文件及责任包/内容摘要。
- [适配器注册源文件](adapters.json5)、[规范化快照](adapter-registry-snapshot.json)、[验收矩阵](platform-acceptance-matrix.json)：32条商店注册项全部保留，运行测试当前均not_run。
- [机器可读执行清单](execution-backlog.json)：12包全部planned；业务实施not_started。
- [验证结果](verification.json)、[文件摘要清单](SHA256SUMS.json)：本轮文档/状态/清单的一致性检查；不包含业务测试通过声明。

索引数据库和工具缓存不随文档提交：当前工作区 `.gitnexus/lbug`、`.gitnexus/meta.json`、`.gitnexus/run.cjs` 与固定版本便捷入口 `.gitnexus/gn`。该便捷入口不依赖shell默认PATH，示例：

```bash
./.gitnexus/gn list
./.gitnexus/gn status --json
./.gitnexus/gn query 'conversation identity delivery' --repo Stella_project
./.gitnexus/gn context ChatContext --repo Stella_project --file core/context.py
./.gitnexus/gn impact --uid Function:core/conversation.py:conversation_key --direction upstream --repo Stella_project --limit 5000
```

本机launcher依赖当前pnpm缓存位置，缓存清理后按方案中的固定1.6.11安装命令重建；自动生成的run.cjs默认使用latest，所以可重复验证优先使用gn或显式版本命令。没有编辑器MCP设置变更，也没有启动监听服务。

最终索引刷新和当前工作区detect_changes结果保存在被忽略的 `.gitnexus/verification/`，避免验证输出本身反复使源码索引漂移。初始快照统计与最终文档加入后的统计分别记录。图流程的预算截断、动态回调缺边和大型文件跳过已在方案中作为限制列明。
