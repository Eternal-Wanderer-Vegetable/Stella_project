# Dashboard 消息工作流完整性修复实施报告

日期：2026-10-04。分支：`feat/dashboard-flow-completeness-repair`（自 `feat/multi-user-identity-repair` @ 6d73b9f 切出）。
依据：`docs/plans/2026-10-04-gitnexus-plan-dashboard-flow-completeness-repair.md`（M0–M6）。
交付状态：**代码验证完成；真实账号/发行包现场验收待执行**（计划 §12 允许的交付形态）。

## 提交结构（8 个分段提交，全部英文说明）

| 提交 | 里程碑 | 内容 |
| --- | --- | --- |
| 021882c | — | 复核报告 + 修复计划入库（Laya 计划保持未跟踪，未动） |
| 541fbbf | M0 | 六类隔离探针固化为**按设计失败**的回归（R1/R2/R3/R4/R5/R9 目标合同） |
| a25203d | M1 | 完整事件身份 + schema3 + spec 精确归档 + owned root bundle + exact spec API |
| 43768e7 | M2 | 中立回执 + social v1→v2 迁移 + 群学习守卫 + 私聊精确 IO |
| b054a26 | M3 | 显式 transition 事实 + span/attempt 生命周期 + transition-only 连线 |
| e902cfb | M4 | 跨文件源码闭包 + 入口发现对账门禁 + 目录固定节点 + lifecycle 真实锚点 |
| 4c744dd | M5 | bundle 刷新 + keyset 分页/水位 + 缺 spec 回退 + 关系/对象导航 |
| 2767689 | M6 | 一次正式 manifest 重生成 + CI 发现对账门禁 + 路径触发覆盖 |

## R1–R9 逐项落地

- **R2 串线**：`_flow_key` 改为 `(conversation_key, message_id)`；`message_traces` 增 7 个身份列（schema 3 增量迁移，建表→迁移→建索引顺序保证旧库可升）；`update_trace_identity` 幂等补充（空→可信，冲突标 `identity_state=conflict`）；postprocessor compare-and-pop + 来源键回查；缓存淘汰留 `ingress_cache_evicted` 事实。
- **R5 spec**：`flow_spec_blobs` 按 full-64 digest 归档 canonical payload（`stella-flow-content-v1`，排除 source_revision）；`begin_trace` 以 owned bundle 单事务落 spec prerequisite+trace+root start，批失败按 trace 整包重放；API `?digest=` 精确匹配不回退；旧空 digest 读作 `legacy_unverified`。
- **R1 私聊**：输入按注册表负整数 storage_session_id + source_message_id 精确命中；`scope=None + 明确 ref` 落中立回执（group_id=''、learning_eligible=0），`scope=None 无 ref` 保留跳过原合同；`deliver_lines` 增加 `receipt_conversation`。
- **R3 连线**：`transition()` 事实（versioned metrics、确定性 edge_id）；首批 12 条边在真实控制边界埋点（闸门链/生成分支/发送/压缩派生）；`edgeTraversed` 只认显式事实（端点+attempt 匹配），兄弟 span/同 instance_key 不再激活边；终点锚依据真实 root finish。
- **R9 checkpoint**：checkpoint 是过程事实，不终态化 running 实例、不覆盖终态；实例键优先真实 span_id；事件按 seq/row 水位排序投影。
- **R4 闭包**：`ProjectIndex` 跨文件解析（相对导入/直接函数/类方法）；可达辅助符号带真实体 hash（辅助函数改动即漂移 manifest）；入口发现器双向对账（16 个新入口补登记），未登记新入口/失效锚点阻断生成；四个核心截断收口（cap 24→256，当前零截断）。
- **R7 导航**：关系 chip 可跳转子/父 trace；对象 chip 打开实体履历并回跳运行；生命周期锚点换成 `_start_*`/`_graceful_shutdown` 真实 hooks。
- **R8 取数**：列表 keyset 游标「加载更早」；事件首读固定快照水位、软上限显式 partial + 继续加载；「已载/存储」分离展示；缺 spec 回退事件时间线（边只来自合法 transition）；输出/指标可展开全部；「未经过」改「未观测」。
- **R6 实时**：`refreshTraceBundle` 在 trace_end/手动刷新时一次刷新 detail+IO+对象；receipt 事实 2s 节流刷新，不给每条 SSE 事件做全量 IO 查询。

## 验证范围（全部实际执行）

| 门禁 | 结果 |
| --- | --- |
| `pytest` 全矩阵（observability + webui API + 私聊入口 + registry + social 三件套） | **203 passed** |
| 新增回归（M0 锁定用例 + spec 绑定 + 身份绑定 + 闭包 + 中立回执 + 学习守卫 + transition 事实） | 全部由红转绿 |
| Dashboard `vitest`（reducer/layout/store/layered/perf 6 文件） | **76 passed** |
| `npm run typecheck`（vue-tsc） | 通过 |
| `npm run build` + `sync:webui`（dist → webui/dist、desktop/dashboard-dist） | 完成 |
| `python scripts/generate_message_flow.py --check` | 通过（a7e457cb822c） |
| GitNexus `analyze --index-only --pdg` | 刷新成功（86,136 节点 / 208,814 边） |
| GitNexus `detect-changes --scope all` | 3 文件 / 2 个测试符号，risk low，无 partial/truncated |
| 每符号编辑前 impact | Docker GitNexus 实跑（`_flow_key` CRITICAL 复核，与计划 §9 一致） |

## 剩余项（诚实清单）

1. **真实 QQ 账号/adapter 现场验收未执行**：私聊文本/图片/命令/预算拒绝/部分发送、双账号同消息 ID 并发、真实后台派生需在测试账号上走查（计划 §8 现场清单）。
2. **桌面/发行包验收未执行**：本地三快照（dashboard/dist、webui/dist、desktop/dashboard-dist）已同步，最终安装包验证按既有流程独立进行。
3. **首批外边仍为 static_only**：目录 137 条边中 12 条已埋点为 explicit，其余按计划以「静态未确认」样式展示，逐步补埋点；M4 输出的非核心动态边界清单以 manifest `entry_discovery`/boundaries 为准。
4. **10 万事件真实规模实测**：软上限与继续加载已实现并有单测，p50/p95 性能基准沿用宽门槛，未在真实生产数据量上压测。

## 风险与不兼容说明

- schema 3 全部增量（旧库打开即迁移，回退代码可读旧列）；`storage_session_id` 未知为 NULL，不伪造 0。
- 中立回执行永不进入群学习/引用归因（守卫有测试）；SOCIAL 总开关语义不变。
- 手改生成 JSON 禁止；`--check` 门禁含跨文件辅助体 hash 与发现差集，改动业务源码后必须重生成。
