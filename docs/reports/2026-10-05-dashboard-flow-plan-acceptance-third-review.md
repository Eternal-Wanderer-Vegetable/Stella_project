# Review: Dashboard 消息工作流第三轮验收

日期：2026-10-05。结论：**NOT READY；上轮 P1 已关闭，多项原反例通过，但仍未全部完成。**

依据：[第二轮报告](E:/stella/stella_project/docs/reports/2026-10-05-dashboard-flow-plan-acceptance-recheck.md)、[修复响应](E:/stella/stella_project/docs/reports/2026-10-05-acceptance-fixes-response.md)、[原计划](E:/stella/stella_project/docs/plans/2026-10-04-gitnexus-plan-dashboard-flow-completeness-repair.md)。本轮只评审新增修复与原合同剩余；明确关闭已通过的旧反例。

## Findings

### B1 [MEDIUM / P2，A2 剩余] events 已发出后隐藏页面，旧事件回包仍落地

[flow.ts:372](E:/stella/stella_project/dashboard/src/stores/flow.ts:372) 调用 fetchEvents 时没有传递 bundle 的 alive/session 条件；[461](E:/stella/stella_project/dashboard/src/stores/flow.ts:461) 只检查 trace generation/ID，随后合并 events。

隔离探针先完成 detail、挂起 events/IO/entities，再隐藏页面并释放旧响应，结果为 `session=1, lateEvents=['e2'], io=['old'], entities=0`。IO/entities 正确作废，events 仍合并。最终 catch-up 的 412 行也走同一路径。新增正式测试只挂起首 detail，因此原首阶段反例已关闭，但“所有异步回包绑定上下文”的合同仍未关闭。

修复要求：将 bundle/session 失效条件贯穿事件分页、事件合并和加载状态更新；补 detail 已完成、events 在途时隐藏的回归。

### B2 [MEDIUM / P2，新回归] 旧列表取尽状态阻止新增区间补漏

[flow.ts:231](E:/stella/stella_project/dashboard/src/stores/flow.ts:231) 对同过滤轮询的非空 next_cursor 不更新游标/取尽状态；[250](E:/stella/stella_project/dashboard/src/stores/flow.ts:250) 则在 listExhausted=true 时直接拒绝加载更多。

初始 1 条历史已取尽，隐藏或长时间未轮询期间新增 101 条；恢复后首屏取最新 100 条并返回 next_cursor。实测合并后 `loaded=101,total=102,cursor='',exhausted=true,missingNew1=true,listCalls=2`，夹在新首屏和旧历史之间的一条记录无法加载，loadMore 不发请求，后续首屏轮询也不能补齐。

原“无新增时轮询不重开取尽游标”的反例已通过；剩余问题是把旧快照的取尽状态延续到已出现新缺口的列表。应识别新数据区间并进行有界 keyset 补读，保留已有历史和过滤竞态保护；补隐藏期间新增超过一页的回归。

### B3 [MEDIUM / P2，A3 剩余] 真实 helper 闭包和部分注册反向合同仍未闭合

1. [generate_message_flow.py:460](E:/stella/stella_project/scripts/generate_message_flow.py:460) 用点号判断导入形态。有效的 `import pkg.helper; pkg.helper.normalize(v)` fixture 实际执行 entry(3)=4，但生成器记录不存在的 helper.py#helper.normalize，symbols=[]、truncated=false；normalize 的 `+1→+2` 不改变 closure hash。单段本地模块 `import helper as h` 也未解析。原 `import pkg.helper as h` 已正确解析并漂移，应继续保持关闭。
2. [796](E:/stella/stella_project/scripts/generate_message_flow.py:796) 只 hash 注册 handler 本体，未从 handler 展开真实下游。图与源码共同确认 [social_worker.py:315](E:/stella/stella_project/memory/social_worker.py:315) 会调用 handle_effect_feedback。完整 manifest 内存 AST 探针将该实际 helper 改为 return None，body hash 从 8a41e70c3c00f3a7 变成 78be7add84253403，仍 problems=[]，content hash 完全不变：`4a5fbef6b7eac869e5168d34b2cd543748f4cc3bebd5b48b251eb8119fd60885`。该 helper 和 log_settlement 都未进入 manifest source/helpers。原简单 Name handler 改绑及本体变化已能漂移，剩余是传递依赖。
3. [internal_flow_catalog.py:185](E:/stella/stella_project/core/observability/internal_flow_catalog.py:185) 的真实 lifecycle entries 没有 registration 期望，[generate_message_flow.py:826](E:/stella/stella_project/scripts/generate_message_flow.py:826) 仅检查非空 metadata。完整生成器内存 AST 探针删除 _start_stop_watcher 的 on_startup 装饰器、保留函数，仍 problems=[]、missing=[]，inventory 保留该 startup entry。**内容 hash 会改变，旧生成物的 --check 可发现漂移**；缺口是重新生成仍接受已失效的声明入口。已标注 scheduled_job 注销 fixture 已通过，不能代替所有生产入口覆盖。

修复要求：明确记录模块/符号导入形态；把实际绑定 handler 纳入现有 ProjectIndex closure seeds；对依赖注册证据的生产入口补齐 registration 期望，并验证注销阻断生成。补无 as、handler 下游 helper 变化、生产 lifecycle 注销三类回归。

native 摘要已有实质改善：backend/selector/Python backend 与多个 Rust 合同文件已纳入全文件摘要。settings.py 筛选结果为空 SHA 是当前无匹配行的事实；selector 的 os.getenv 逻辑本身已入摘要。本轮不把它单独报为缺陷，也不要求 hash 私密运行环境值。

### B4 [MEDIUM / P2，A4 剩余] 实际停止错误仍被吞掉，取消仍没有终态

[ai_gateway.py:2857](E:/stella/stella_project/stella_project/plugins/bot_main/ai_gateway.py:2857) 的生产 _stop_cometa 内层 suppress runtime.stop 错误，外层新 stop_errors 无法收到实际失败。AST 抽取并执行生产 _stop_cometa + _graceful_shutdown，假 runtime.stop 抛 RuntimeError，仍得到 `stopped,complete=True`。Facade 的 [4185](E:/stella/stella_project/stella_project/plugins/bot_main/ai_gateway.py:4185) drain/stop 同样吞错，探针也显示 stopped。

[4169](E:/stella/stella_project/stella_project/plugins/bot_main/ai_gateway.py:4169) 至 end/flush 之间仍无 finally；假 _stop_cometa 抛 CancelledError，lifecycle_end 与 flush 均调用 0 次。启动 start_failed/cancelled 和外层 helper 抛错后的 stopped_with_errors 已通过，不能用外层 fake 抛错代替实际内层链路。

修复要求：让实际停止结果进入统一错误汇总，并保留取消语义，以 finally/明确终态保证异常、取消均收口和有界 flush；不重排既有资源停止顺序。当前 flush 返回 None，新增 timeout=3 调用只能证明尝试了有界排空，不能证明已收到提交成功确认。

### B5 [MEDIUM / P2，A8 剩余] 全失败截断提示未到页面，剩余片段和命令正文仍不可查

[flow.py:556](E:/stella/stella_project/webui/services/flow.py:556) 已生成截断 note，但 [655](E:/stella/stella_project/webui/services/flow.py:655) 仅在 ACK lines 非空时合并 receipt_notes。临时库 25 个 failed 回执返回 20 segments、segments_truncated=true，notes 却无截断说明。前端类型/页面未消费新 bool，故 UI 仍没有剩余段提示。仅将第 0 段改为 ACK，同一探针正确返回截断 note，**mixed ACK 改善已通过**。

[682](E:/stella/stella_project/webui/services/flow.py:682) 仍只有 lines/count/segments/segments_truncated，没有剩余片段读取、完整正文或 total/cursor。命令 [ai_gateway.py:448](E:/stella/stella_project/stella_project/plugins/bot_main/ai_gateway.py:448) 仍存 text[:500]；生产函数 AST + fake matcher 发送 600 字，checkpoint 仅 500 字。修复响应也承认命令正文未实现。它属于**实现合同未完成**，不是只等待现场测试。

修复要求：回执诊断不依赖存在 ACK；接通前端截断状态与继续读取/全文访问；命令进入完整、精确关联的回执路径。补全部失败超限与大于 500 字命令的回归。

## Change and blast-radius summary

- Repo：E:/stella/stella_project；当前分支 feat/dialogue-attribution-role-repair；remote 默认 origin/main。
- 精确两点比较：`4fe05ec2c866908233ca18fd8668dd7ec3bfdb62..b9df97d291d6ce3a426074abc02d96e6417c2364`。15 个文件，包括生成 manifest rename、源码、测试及修复响应。原计划未改。
- Docker stella-gitnexus 在 /repo 刷新 analyze --index-only --pdg 成功，536.5 秒；lastCommit 对齐 HEAD，indexedAt=2026-10-05T04:52:59.639Z（12:52:59 UTC+8）；87,925 nodes / 213,459 edges / 945 clusters / 831 sampled flows。原始图证据 Docker /tmp/stella-flow-third-acceptance/。
- detect_changes(compare,上述 base) 为 15 files / 54 changed symbols / 10 affected processes、risk HIGH，无 partial/truncated 标记。它是范围信号，不是本轮 finding 的严重性依据。
- 父审阅独立完成 context、20 个 upstream impacts、四个数据边界 explain 和 PDG，再由前端/后台/闭包三个领域复验。_connect HIGH、11 个直接依赖；ingress MEDIUM；store/object 方法与动态 hooks UNKNOWN，使用源码和探针补证，未以零 caller 判无调用。
- 检查了 diff 外直接依赖的 entity history、writer loss/heartbeat/finality/prune、trace IO router、generator 的 CI/fixture consumers，以及 _trigger_shutdown。_connect=None 的消费保守降级，未发现新增调用形状破坏。
- 四个 explain 无 finding，但工具不覆盖 closure/property/implicit flow。PDG bundle 62、ingress-end 45、shutdown 22、discovery 25 条 controls，有实际守卫/分支证据。message_flow 文件 PDG 为 645 条、返回 200 条截断，未把它当完整函数覆盖；备份守卫另由当前源码及真实临时 SQLite 回归证明。
- 图流程存在入口排名/深度/预算与 callable 候选截断；大 manifest 被普通符号索引跳过，另用正式生成器与完整 JSON 检查。不把缺流程当不存在，不追溯声称历史每个编辑都执行了 impact。

## Coverage and residual risk

### 本轮门禁与实测

| 检查 | 结果 |
| --- | --- |
| 原指定 Python 矩阵 | **225 passed / 58 warnings** |
| Dashboard tests | **6 files / 98 passed** |
| Dashboard typecheck | 通过 |
| Dashboard production build | 通过，外部 Temp 输出；既有 chunk/dynamic-import 提示 |
| manifest --check | 通过，message-flow.4a5fbef6b7ea.json |
| fresh build 对三处资产 | 各 **50 个文件，逐文件 SHA-256 一致** |
| python -m ruff check . | 通过；ruff 命令不在 PATH，使用已安装 Python 模块完成 |
| git diff --check | 通过 |
| 前端补充探针 | 9 个，含原反例关闭及 B1/B2 失败形状确认 |
| 后台/闭包补充探针 | AST/fake、临时 SQLite、有效 import fixture、完整 manifest 内存 AST，见各项具体观测 |

Python 命令：`python -m pytest tests/observability tests/webui/test_message_flow_api.py tests/test_private_chat_ingress.py tests/test_conversation_registry.py tests/test_social_delivery.py tests/test_social_migrations.py tests/test_reply_effect_service.py -q`。Dashboard test/typecheck/build 与 generator 使用原入口。build 指定 `--outDir C:/Users/Vegetable/AppData/Local/Temp/stella-flow-third-acceptance-build`，未覆盖部署目录或执行 sync。检查 dashboard/dist、webui/dist、desktop/dashboard-dist 均与新构建一致。

反例探针的断言通过表示缺陷被确认，不算产品验收通过。临时测试/fixture 均清理。当前 manifest 仍为 140 nodes / 148 edges / 20 roots / 49 declared / 33 discovered，当前 undeclared/missing 为空；已知 helper/注册反例限制见 B3，不能用空差集宣称完整闭包。

### 上轮 A1–A8 关闭矩阵

| 上轮项 | 本轮验收 | 证据与剩余边界 |
| --- | --- | --- |
| A1 finality / detail 异常 | **原反例已关闭** | pending→final：high=2、loaded=2、最终 IO 两段；detail 永久失败仍刷独立来源；awaitFinality 有界重试仍完成独立查询 |
| A2 session / 冻结续页 | **部分完成** | 首 detail 期间隐藏作废、until=1500 续页通过；events 在途阶段仍见 B1 |
| A3 alias / 注册 / native | **部分完成** | dotted alias、已标注 scheduled 注销、handler 改绑/本体、native 静态合同改善；传递闭包和部分注册仍见 B3 |
| A4 生命周期 | **部分完成** | startup 失败/取消通过；外层 stop_errors 与有界 flush 调用通过；真实内层链路与关闭取消见 B4 |
| A5 replacement occurrence | **原主要反例已关闭** | 旧事件 late end 不关闭新 root，新事件自行正常结束 |
| A6 输出 / 入口 / exhausted | **原反例已关闭；新列表回归** | 真实 Vue SSR 有输出且无矛盾占位，初始私聊/未知 root 可选；无新增时取尽不重开；新增区间遗漏见 B2 |
| A7 备份失败迁移 | **已关闭** | backup 返回空串→_connect=None、原列/原行保留 |
| A8 截断 / 正文 | **部分完成** | mixed ACK 超限有提示；全 failed 提示、剩余段读取与命令完整正文见 B5 |

A5 的容量限制不作为本轮主要阻断：特殊的同活跃 root、513 个重复 event 且反复淘汰缓存的形状会挤出旧凭据。尚无普通生产调用链证明因此漏终态；513 个不同 root 另涉及既有 active registry 上限，不能混为新缺陷。建议后续以真实并发边界明确降级事实。

### 真实数据库与页面

沿用用户授权，只读 URI mode=ro、query_only=ON、读事务访问 turn_trace.db 与 agent_memory.db；服务投影探针把数据库连接显式替换成同样只读连接。没有迁移/回填真实库、发 QQ、重启服务。

最新 12 条已结束且绑定新 4a5f… digest 的私聊样本，时间 **2026-10-05 12:40:57–12:52:10 UTC+8**：11 条 delivered，每条 3 acknowledged 回执、3 行输出/3 segments；1 条 not_delivered，1 个 failed 回执、0 行确认输出。当前生产 message_io 对这 12 条均能读取 exact 输入；每条精确 digest 的 spec 均可找到。样本回执 learning_eligible=0。另有新 digest 的三条 started/complete 生命周期 root。活动中轨迹不判成故障或验收通过。

浏览器打开当前部署页面，未选择详情前入口下拉已有 **20 项，包括 qq_private**，确认原初始过滤问题关闭。后续 DOM 读取超时，本轮不声称已完成完整浏览器导航或 latest detail 的 DOM 验收；输出模板由实际 Vue SSR 补证。新构建 hash 一致与真实 API/DB 样本不能替代桌面或发行包测试。

不记录私聊正文、账号或会话 ID。修复响应当前仍明确保留真实 QQ 全场景矩阵、浏览器/桌面完整导航和最终安装包未验；沿用用户此前“尚未完成现场验收”的回答，未反复要求确认。

### 原计划 DoD 状态

| DoD | 本轮判断 |
| --- | --- |
| 1 R1–R9 全部证据 | 未完成，B1–B5 与现场缺口保留 |
| 2 canonical/root/结束隔离 | 核心反例通过；容量/并发全部现场矩阵非本轮全验 |
| 3 精确 spec / A-B / legacy / missing | 保留既有回归，新真实样本按精确 digest 可读；完整 loader 多文件/cache 矩阵未补全 |
| 4 事务 / fail-open / loss | 指定合同与迁移矩阵通过；未扩大为全故障矩阵 |
| 5 transition / finality | 前轮 transition 核心通过；A1 finality 补读已关闭 |
| 6 span / checkpoint / unknown | 现有矩阵通过，无本轮新增阻断 |
| 7 所有回执与命令可查 | 普通私聊/失败/不学习有证据；B5 未完成 |
| 8 辅助闭包 / 入口漂移 | B3 未完成 |
| 9 生命周期内部事实 | 启动改善通过；B4 未完成 |
| 10 刷新 / 回包上下文 | A1 通过，B1 未完成 |
| 11 分页 / 完整加载 / 正文 | 主要分页通过，B2/B5 未完成 |
| 12 导航 / auth / 脱敏 | 既有代码证据；完整浏览器/桌面矩阵仍待验 |
| 13 自动门禁 / CI / 生成 | 本轮指定命令通过；缺陷反例与实际 manifest 100k p50/p95 尚未纳入完整回归 |
| 14 资产 / QQ / 发行包 | 三处 hash 同步与新 DB 样本通过；桌面/完整 QQ/最终包仍待验 |
| 15 图门禁 | 本轮 HEAD 对齐 compare/impact/PDG；不追溯证明历史逐编辑门禁 |
| 16 交付范围与剩余项 | 命令正文应明确保留为实现未完成；更新 B1–B5 清单 |

## Verdict

**NOT READY。上轮 P1 已关闭，本轮主要阻断均为 P2 的完整性/异常边界与一个列表回归。** 不能验收“全部探测缺陷与原计划全部完成”。应按 B1–B5 补相应反例，关闭实现剩余，再分别完成完整浏览器/桌面/真实 QQ 与最终安装包验收。

本轮仅新增此报告；业务源码、正式测试、配置、manifest 和三处资产未修改，未提交。已有未跟踪报告、Laya 计划与 .bot-restart.log 保留。
