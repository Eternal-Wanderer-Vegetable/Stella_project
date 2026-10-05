# 验收报告响应：H1–H5 / M1–M6 修复记录

日期：2026-10-05。回应对象：[2026-10-05 验收复核](2026-10-05-dashboard-flow-plan-acceptance-review.md)。
分支 `feat/dashboard-flow-completeness-repair`，回应共 9 个提交（f7650ac..2a00b8f + lint 尾随）。每项含回归用例；验证命令与结果见文末。

## H1 [HIGH] 真实 ConversationRef 不落中立回执 → 已修复

- `core/social/delivery.py`：身份读取同时接受两种形状——规范 `ConversationRef` 的 `kind/platform/bot_id` 与测试命名空间的 `conversation_kind`；`DeliveryReceipt` 增加 `platform/bot_id` 附加字段。
- `memory/social_store.py`：中立行的 `platform/bot_id` 从回执取（不再从空 scope 取空值）；`group_id=''`、`learning_eligible=0` 合同不变。
- 回归：`TestRealConversationRefNeutralReceipt` 用生产工厂 `qq_private_ref` 走 `deliver_lines → record_delivery` 全链路（成功段、失败段、归因不可见三例）。**真实库的存量私聊（已发送无回执）按计划口径记为缺档，不重发、不回填**——新轨迹起生效。

## H2 [HIGH] exact 输入跨 Bot → 已修复

- `webui/services/flow.py::_exact_input_row`：除 storage+msg_id 外核对业务行 `conversation_key/bot_id` 与 trace 身份；旧行（身份列空）保守标 `legacy_partial`；候选身份全部不匹配 → 无输入 + 诚实 note（绝不返回另一台 Bot 的正文）。
- 回归：`TestExactInputCrossBot`——同群同号两 Bot 各一行，双向取各自正文；身份不匹配返回 None。

## H3 [HIGH] keyset 方向/offset/total → 已修复

- 降序 keyset 改严格**小于**（`started_utc < ? OR (= AND trace_id < ?)`）；非游标路径恢复 `LIMIT ? OFFSET ?`；`total` 只按过滤条件计（不含游标），分页期间稳定。
- 回归：三页行走 + 取尽 + offset 兼容 + 翻页间隙并发插入不重不漏。

## H4 [HIGH] row_id 与 seq 水位混比 → 已修复

- 前端截断判定改用 `detail.high_watermark`（本 trace 的最大全局 row_id，与游标同单位）；`persisted_events`（MAX(seq)）不再参与比较；「已载/存储」chip 改用 `event_count`（COUNT）。**每一页**都钳制在同一冻结水位（此前只有首页传 until）。
- 回归：H4 探针原样（100001 条、水位 100001、全局 row 从 100001 起）——100 页后仍 partial、继续按钮不消失；以及「71 载 / 123 存储」不再显示为缺 52 条。

## H5 [HIGH] 手动刷新不补读事件 → 已修复

- `refreshTraceBundle` 先刷 detail（拿新水位），随后**并行补读事件** + IO + 实体；trace_end 走 `awaitFinality`：有界 3×1.5s 重试直至 `producer_ended + integrity` 落账，再补一轮事件。
- 回归：水位推进后手动刷新 `getEvents` 被调用且已载增长（旧实现 eventCalls=0）。

## M1 [MED] transition 未匹配端点 occurrence → 已修复

- `edgeTraversed` 增加：`edge_id` 必须等于候选边 `src->dst:edgeKind`（layered 传入边 kind，平行边不串）；transition 携带 `from/to_span_id` 时两端必须有**同 span** 的发起/到达事实（同节点重复执行不得借用别的 occurrence）；无 span 的 decision 保持节点+attempt 匹配。
- 回归：借用不存在的 occurrence → false；匹配 occurrence → true；edge_id 指向平行边 → false；无 span 回退 → true。

## M2 [MED] 旧 bundle 覆盖终态 / 列表异步无代际 → 已修复

- `refreshTraceBundle` 调用级 seq 代际：同 trace 的旧响应落地前核对仍是最新调用，迟到终态前响应整包丢弃（不回滚 ended/水位）。
- 列表：轮询合并新首屏并**保留已加载历史页**（按 (started, trace_id) 降序）；`loadMore` 请求前后核对过滤键，过滤切换后旧游标页整包丢弃。
- 回归：挂起→终态→迟到响应、轮询不吞历史页、切换过滤旧页不落地。

## M3 [MED] 发现门禁漏报 → 已修复

- 带参装饰器（`ast.Call` 下钻取 func）与模块级注册表达式（`register_handler("job", fn)`，符号取字符串键或 handler 名）均可扫描。
- **门禁确实咬人**：重建后 13 个此前不可见入口被抓出（6 命令 handler、6 apscheduler 作业、1 worker 注册），全部登记进 inventory；`discovered 33 / declared 49`。

## M4 [MED] 别名/未解析/内部包/边界摘要 → 已修复

- `import_sources` 保留原名，`extract as transform` 解析回模块内 `extract`（体变化即漂移）；repo-local 解析到不存在符号 → 显式 `unresolved` 边界（不再静默跳过）；`astrbot_compat` 加入 PACKAGE_DIRS（重建后 external 归零）；非 Python 锚点（rust promotion）附源码 sha256 `source_digest` 进 manifest。

## M5 [MED] 生命周期事实 / 闭包视图 / 动态入口 → 已修复（合同范围内）

- 五个真实钩子（`_start_scheduling/_start_cometa/_start_stop_watcher/_start_hot_reload_watcher/_graceful_shutdown`）各自开 lifecycle root 并以诚实 outcome 收口（started/disabled/init_failed/stopped）；新 `root_kind=lifecycle` + `ops.lifecycle` 节点 + ENTRY_ROOTS + inventory 绑定。
- 11 个无边孤岛全部以诚实静态边接线（知识链、预约链、social worker→效果结算、astrbot 桥、参与评分活动面、flow.ingress→消息入口、lifecycle→调度/worker），**孤岛数清零**。
- 页面：入口筛选项 = 标签表 ∪ manifest entry_roots（19 项可选）；节点详情卡消费 `source_closure`（文件#符号、体哈希、可达辅助数、unresolved/dynamic/native 计数）。

## M6 [MED] 片段事实 / 缓存重入 / Flow 迁移恢复 → 已修复

- `message_io` 输出新增 `segments`：原 `part_index + status + 平台 ID + ack 时间` 逐段保留（0ack/1failed/2ack 不再坍缩为 [A,C]；全失败保留逐段说明）；IO 卡对非 ack 片段渲染状态徽标；命令回复仍走 checkpoint 路径。
- 缓存重入：淘汰后重入按来源键复用活跃 root（不造第二个 root）；ingress root 携带 occurrence token，结束路径 compare-and-pop 幂等。领域探针回归：创建→淘汰→重入→迟到结束×2 = 恰一条 trace、一次 trace_end。
- Flow schema 初始化改为显式 `BEGIN IMMEDIATE…COMMIT` 单事务 + 迁移前 backup API 快照；晚期失败整体回滚（无半迁移残留）并留下 `.pre-flow-*.bak`。回归注入晚期失败验证。

## 验证（全部实际执行）

| 门禁 | 结果 |
| --- | --- |
| 验收报告指定 Python 矩阵 | **217 passed** |
| Dashboard vitest / typecheck / build / sync | 94 passed / 通过 / 通过 / 三快照同步 |
| `ruff check .` | 全绿 |
| `generate_message_flow.py --check` | 通过（`a859e3032fd4`，140 节点、孤岛 0、discovered 33/declared 49） |
| GitNexus `analyze --index-only --pdg` | 刷新成功（87,670 节点 / 212,742 边） |
| GitNexus `detect-changes --scope all` | No changes detected（非 partial/truncated） |
| 运行环境 | bot 已带全部修复重启，NapCat 秒连，日志 0 ERROR |

## 仍待现场验收（与本轮代码修复无关的既有缺口）

真实 QQ 全场景矩阵（私聊文本/图片/命令/部分发送的新轨迹验证——H1 修复后新轨迹即可存档回执）、浏览器/桌面完整导航矩阵、最终安装包验收。逐项证据口径见验收报告 §Coverage；每项修复的 trace/digest/水位证据在上述各回归中。


---

## 第二轮复验响应（2026-10-05，A1–A8）

回应 [第二轮复验](2026-10-05-dashboard-flow-plan-acceptance-recheck.md)，提交 `3436a49`（A1/A2）、`aef202d`（A3）、`49f11f7`/`2a00b8f` 上轮关联、本轮 A4–A8（c315495）。

| 项 | 修复 | 回归 |
| --- | --- | --- |
| A1 | finality 确认后按新水位**最终补读**事件 + 再刷 IO/实体；detail 瞬时失败有界 2 次重试且**不取消**独立来源刷新 | pending→final 探针（3 次 event 调用、IO 更新）；detail 瞬时失败仍刷新独立来源并恢复 |
| A2 | bundle 回包绑定 streamSession（隐藏页面即在途作废）；loadMoreEvents 钳制同一冻结水位；整体失效时跳过 round-1 派发 | 挂起→隐藏→迟到回包不落地不触发事件；继续页 until=1500 断言 |
| A3 | `import pkg.helper as h` 模块别名解析原名（体变化即漂移）；RuntimeEntry.registration 反向注销差集（删注册即 missing）；worker 注册记录 handler 绑定+体哈希（换绑即漂移）；rust.promotion 补 contract_files 摘要（backend/selector/python_backend/__init__ + 5 个 .rs + settings 按 MEMORY_BACKEND\|RUST 行过滤，CRLF 归一） | 模块别名漂移、反向注销、换绑漂移三组 fixture |
| A4 | `_start_scheduling` 的 runtime.start 包入 cancelled/start_failed 收口；`_graceful_shutdown` 如实记录 cometa/scheduling 停止失败（failed decision + stopped_with_errors）并以有界 flush 确认末尾观测落库 | start 抛 RuntimeError → start_failed；抛 CancelledError → cancelled 且 complete=0 |
| A5 | occurrence 凭据改绑**事件对象身份**（id(event) → root trace + token），结束须出示匹配凭据；凭据消费即幂等 | 替换 occurrence 探针：旧事件迟到 end 不再关闭新 root |
| A6 | 输出「（无）」占位改按真实空输出判定（与 segments 条件解耦）；静态标签表含 qq_private，入口下拉 = 静态 ∪ entry_roots ∪ 已见 root（初始即 20 项）；列表新增 exhausted 状态——取尽后轮询不再恢复首屏游标 | DOM 条件变更 + store 状态测试 |
| A7 | 备份失败 → 拒绝迁移（连接返回 None、原库原样、观测降级） | 注入备份失败：无 .bak、无新列 |
| A8 | segments 截断按片段维度显式报告（segments_truncated + note），25 段探针返回 20 段 + 截断标记；命令完整正文继续列为现场待验（未标完成） | 25 段探针 |

门禁：pytest 224+ 全绿、dashboard 98 测试 + typecheck + build + 三快照同步、ruff 全绿、manifest `4a5fbef6b7ea` --check 通过。仍未完成：命令完整正文合同（A8 保留项）、真实 QQ 全场景矩阵、浏览器/桌面完整导航、最终安装包验收。


---

## 第三轮复验响应（2026-10-05，B1–B5）

回应 [第三轮复验](2026-10-05-dashboard-flow-plan-acceptance-third-review.md)，提交 `aa25537`（B1/B2）、`fca2457`（B3/B4/B5）。

| 项 | 修复 | 回归 |
| --- | --- | --- |
| B1 | fetchEvents 接受 staleness 回调；bundle 的两轮事件补读贯穿 alive()（session/seq/trace）——隐藏页面后的旧事件回包不合并、不污染截断标志 | detail 完成→events 在途→隐藏→释放：合并数保持 0 |
| B2 | 旧快照取尽后若新首屏含未知记录 → 以新快照游标重开 keyset（有界、历史保留、去重合并）；known 集取自合并前快照 | 1 条取尽→新增 101 条→恢复：缺口记录可达、最终 exhausted |
| B3.1 | `import pkg.helper`（无 as）与单段 `import helper as h` 经模块键后缀回退解析到真实符号——normalize 体 +1→+2 即漂移 | 无 as 漂移、单段解析两例 |
| B3.2 | worker 注册记录 handler 的**传递本地闭包**（handler_closure = file#qual:hash 列表 + truncated 标记）——下游 helper（如 handle_effect_feedback→log_settlement）体变化即漂移 | _downstream 42→43 记录漂移 |
| B3.3 | 五个生产 lifecycle entry（start_scheduling/start_cometa/start_stop_watcher/start_hot_reload_watcher/graceful_shutdown）声明 registration=lifecycle_hook——装饰器删除（函数保留）即 registration_removed 阻断 | 装饰器删除反例 |
| B4 | _stop_cometa 真实停止错误外传（注册表清空放 finally）；facade drain/stop 失败进 stop_errors；shutdown 主体拆分——CancelledError → cancelled(complete=0)、Exception → shutdown_failed，均收口 + 有界 flush；成功路径 flush 后**核对 lifecycle 行已落账**（producer_ended），未落账打降级日志 | fake runtime 注入两例 + 既有 17 项生命周期测试 |
| B5 | 回执诊断（截断/failed/unknown 计数）不依赖 ACK 行存在——全失败超限的截断说明到达 notes；页面渲染 segments_truncated 提示；**命令回复进入完整回执路径**（turn=trace、part 0、acknowledged、全文 social_deliveries——600 字可查；500 字 checkpoint 摘要降级为无档案旧轨迹的兜底） | 25 全失败探针 + 600 字命令全文探针（content_hash 核对） |

门禁：pytest 231 全绿、dashboard 100 测试 + typecheck + build + 三快照同步、ruff 全绿、manifest `b695e0f2eab9` --check 通过（同版本旧文件已清）。仍未完成（现场）：真实 QQ 全场景矩阵、浏览器/桌面完整导航矩阵、最终安装包验收；命令回复的平台消息 ID 关联（当前 turn=trace、part 0，平台 ID 在 OneBot 命令路径不可得）列为下轮剩余合同。