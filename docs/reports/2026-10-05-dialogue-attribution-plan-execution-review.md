# Stella 对话归属修复计划执行复核

日期：2026-10-05（Asia/Shanghai）。
结论：**NOT READY。计划仅部分落实，当前不能标记 R0—R8 完成，也不具备灰度发布条件。**

本次复核没有修改业务代码、配置或生产数据库，没有调用真实模型或发送 QQ。本报告是复核交付物；所有反例仅在临时目录、临时 SQLite 或假运行依赖中执行。

## 1. 复核范围与证据

- 计划：[2026-10-05-gitnexus-plan-dialogue-attribution-recurrence-repair.md](../plans/2026-10-05-gitnexus-plan-dialogue-attribution-recurrence-repair.md)。通过安全 read-plan receipt 读取，计划字节 digest 为 sha256:62583fb8687a6356774602858009bbc33d45664b97630deee3282d8320eb9b33。
- 分支：feat/dialogue-attribution-role-repair。
- 精确比较：6b35b6ba85752ddef66c50e2f56d045f6a5bb908..f752538e18b9f5467e8821739d4f154e647ead5c。前者为计划固定的实施基线；本次按计划执行范围审查，未以整个分支对 main 的累计差异代替。
- origin 默认分支为 main，当前远端 ref 为 ec9803e1f71febf2adbcc2df461020e320529244。
- 差异：17 个文件；新增模块、迁移、工具、测试和实施总结，网关业务改动仅私聊整合入口三行。核心 ChatContext、TurnService、pre/post_processors、prompt_builder、proactive_target/prompt、评估脚本及真实场景夹具均未改变。
- 本地没有 staged/unstaged 业务改动。原有 untracked 为 .bot-restart.log、Laya 计划、本次修复计划、两份调查报告及证据目录；不是这批新增业务实现。
- Docker stella-gitnexus 在当前 HEAD 刷新 --index-only --pdg，耗时 151.1 秒，88,742 nodes / 215,444 edges / 955 clusters / 820 flows。刷新后 status 确认 indexed/current commit 同为 f752538，997 个覆盖文件内容匹配。
- detect_changes(compare, base_ref=完整基线 SHA)：166 changed symbols / 17 files / 5 affected processes，完整返回，无 partial/truncated。本地 all：0 个未提交结构变化。
- 对新模块全部顶层函数和改变的关键入口运行 upstream impact(includeTests=true)，并检查 d=1 未改调用方；对七个信任/持久化文件执行 explain，并核验七个 PDG 控制/数据切片。taint 查询未报告 findings；这不能证明共享授权、角色或运行时接线安全。

反例、完整 diff 和图结果保存在本地临时证据目录：

C:/Users/Vegetable/AppData/Local/Temp/stella-attribution-review-qi3r21zp/

主要文件为 probes.json、graph-results.json、diff.patch、sharing-warm-default-probe.json、sharing-lens-probes.json、sharing-lens-reproduce.py。临时证据不是生产库迁移记录。

## 2. 阻断与重要发现

### F1 [HIGH] R3/R5/R6 没有接入真实运行链路，开关启用不会启用保护

锚点：config/settings.py:1532；core/dialogue_attribution.py:422；memory/proactive_contract.py:133；memory/personal_sharing.py:120。

GitNexus context 显示 apply_attribution_guard 无 incoming，grant_sharing_authorization 与 validate_bridge_event 只有测试 caller。针对 UNKNOWN/空结果继续全量文字核对：三个开关均只定义未消费；分享授权检测/写入、候选桥接与问题选择没有生产调用。

现有 TurnService.finalize_turn（core/runtime/turn_service.py:601）仍仅执行原 trace 和 post hooks；ai_gateway.py:656 只注册 parse_output=100、bad_phrase_filter=80、split_lines=60、log_thought=40，没有计划的 guard。主动入口 ai_gateway.py:3183 仍以 build_instruction(target) 作 ctx.message，并把模型 ctx.lines 拼接、直接交付，再按原候选记账。ChatContext 投影仍是 schema 4，没有 typed retrieval_query、合同、证据或 reply_disposition。

因此三个 helper 模块存在不等于线上行为已修复。原 13:19/14:09 主动换主体、13:31 原话倒置和私聊分享均没有新业务阻断点。现有新增测试只调用 helper，没有通过真实 prepare/finalize/发送的集成反例。

修复：按计划 R1/R3/R5/R6 补上下文合同、前后处理、网关发送复核、来源/授权绑定和回执记账；在 legacy/native 实际链中验证错误零发送、合法输出可发送。不能仅“打开开关”进入灰度。

### F2 [HIGH] Nox 的真实纠正原句仍被拒绝

锚点：memory/conversation_identity.py:117。

对整句检查“不是/不叫”后直接返回 None。实测：

- 我是Nox → ("Nox", false)
- 我是Nox，不是红中没摸鱼 → None
- 我叫Nox，不叫红中 → None

该句正是计划要求支持的现场正例；process_message_identity（同文件:629）不会登记 Nox、失活错误称呼或推进 identity revision。“我是谁”“这是Lumi不是我”的负例改善属实，但不能替代复合肯定纠正。关系语句“我是她姐”“我是你教父了”也仍能进入 self_alias。

GitNexus impact 为 HIGH，直接影响 process_message_identity 和身份测试；PDG 明确显示全文否定 guard 控制立即返回。新增测试只测简单介绍和“我才是Lumi”，遗漏原句。

修复：先识别有限的肯定本人声明及更正语义，将独立否定尾句作为排除信息，不能全句拒绝；添加完整原句落库、旧别名失活、下一轮生效及关系描述反例。

### F3 [HIGH] 分享首次复制路径引用候选表不存在的列

锚点：memory/personal_sharing.py:257、:261。

memory_candidates 的规范 DDL（memory/schema.py:549）没有 confirmation_count / last_confirmed_at，复制 SQL 却同时 INSERT/SELECT 这些列。首次授权且没有既有 USER_SHARED 副本、实际进入候选复制 SQL 时，正式 memories/candidates DDL 加 v17 合同列的临时库实测：

OperationalError: table memory_candidates has no column named confirmation_count

即使候选表没有匹配行，SQL 编译也失败；已有 active grant 或既有共享副本等提前返回路径可能不执行此 SQL。失败路径中函数之前已经创建 grant、复制 memories；调用者必须回滚，不能在捕获异常后继续提交。

新增幂等测试（tests/test_dialogue_attribution_repair.py:160）只创建授权表和 scope_versions，没有 memories/candidates；新增 present 检查会直接跳过复制，因而测试通过但没有验证真实库路径。

修复：按规范候选字段复制 occurrence/evidence/source 字段，校验全部真实 schema 路径与事务回滚；加入包含 memories、candidates、FTS/证据的正式临时库测试。

### F4 [HIGH] 分享授权没有按 Bot/本人/受众绑定，引用或普通聊天也能被识别为授权

锚点：memory/personal_sharing.py:83、:249、:275、:333。

复制、已存在检查和撤回只按 fact_key + audience 匹配，不使用 bot_id/user_id/规范 owner_key/subject_key。fact_key 的生产生成（consolidator.py:1522）仅包含 type 与规范内容，不包含本人或 Bot；不同用户同内容具有相同键是正常情况。

隔离探针给用户 123 授权同键事实，复制结果同时包含用户 123 和 456 的 USER_SHARED 行。撤回也同样会改动别人的共享副本。授权函数不读取 source row 验证实际发送人、会话、原文或事实；不存在的授权 source 也返回 granted。detect_sharing_intent("他说可以在群里分享这件事") 和 ("我在群里玩游戏") 均返回 true。

pending/source 绑定、sharing_audit_log 写入、memory_evidence、共享副本 compat namespace 也未完成。当前模块未接生产，**此项是新实现的权限缺陷，不能表述为已经发生线上泄漏**。

修复：所有查询使用规范本人/Bot owner + subject + audience + fact/source；服务端查证授权消息，拒绝引用/第三人/普通群话题；未绑定事实时 pending；副本、证据、授权审计和权限版本同事务提交。用跨用户/跨Bot同内容和真实 source 反例验收。

### F5 [HIGH] 撤回共享推进了错误版本键，暖缓存仍召回已撤回副本

锚点：memory/personal_sharing.py:185、:349。

grant/revoke 写 user:{uid}；实际 owner 是 person:{platform}:{bot_id}:{uid}（ownership.py:52）。retrieval_v2.py:598—609 读取当前 SPACE 与规范 PERSON owner 的版本，因此权限变化没有更换缓存键。

使用实际 Python retrieve_memories、默认阈值 .4、规范 owner person:qq:10000:20001 复测：撤回前得到 p-shared；撤回提交后仍返回相同缓存对象 p-shared；清缓存后才变成空。规范 scope version 仍为 0，数据库仅写了 user:20001=1。

strict=True 只保证错误键写成功，不保证权限缓存失效。现有测试没有 grant/revoke 后暖缓存检索。scope_versions.bump 的旧 d=1 调用保持默认 strict=False、签名兼容；本项属于新授权调用键错误，并非已经证明旧调用回归。

修复：使用与 MemoryAccessScope 完全相同的规范 owner key，按实际影响范围在行变更事务内 bump；覆盖暖/冷缓存、跨进程版本、session cache、FTS/embedding/native 的撤回一致性。

### F6 [HIGH] 数据修复按全局 fact_key 去重，会失活合法私有/共享副本及别人的记录

锚点：tools/data_repair.py:157、:311。

preview_duplicate_records 仅 GROUP BY fact_key，不含 owner、Bot、audience/scope，也不排除空 key；保留 GROUP_CONCAT 的第一个且没有稳定排序。正式 DDL 下，合法 PRIVATE_ONLY 原件 + USER_SHARED 副本、另一 owner 的同内容事实、两条空 key 行，都产生错误 duplicate 清单；随后 apply 会无条件 DEPRECATED。

这直接破坏授权设计要求的双受众副本及多人隔离。新测试未验证 duplicate 反例。

修复：重复只在同一可信归属、受众、来源和事实合同内确认，空 key 保持 unknown；保留项有稳定选择与来源依据。不得将该预览应用到生产。

### F7 [HIGH] 孤儿判断使用身份 revision 表，会把正常会话的候选误删

锚点：tools/data_repair.py:197。

conversation_identity_versions 只在身份声明/纠正时写入，不是会话注册表。已注册且有真实 PRIVATE_DIRECT source row、但未声明姓名的正常会话，在该表没有行，会被判为 orphan。

正式 DDL、真实 get_or_register_private 和来源 row 101 的隔离探针仍得到 valid-source 待失活项。工具默认 preview 包含 orphan，应用会误失活合法候选。

修复：验证真实 registry 与 source row 的存在、会话和作者；缺身份 revision 不表示缺来源。增加“已注册、有来源、无身份声明”的正常反例和来源确实已删除的拒绝形状。

### F8 [HIGH] 修复撤回把 audience 写回 status，且无旧内容 CAS/权限版本保障

锚点：tools/data_repair.py:332、:402。

wrong_space 预览把 audience 放入 current_value，apply 写成 audit.old_value；revoke 一律将 old_value 写回 status。实测 preview→apply→revoke 返回成功，却从 (DEPRECATED, SPACE) 变成 (SPACE, SPACE)，无法恢复原状态。duplicate 还固定旧状态为大写 ACTIVE，不能恢复真实 active 等原值。

apply 仅按 record_id 更新，无源证据/预期旧 digest/CAS；revoke 同样不保护之后用户的新变化。工具没有更新 scope_versions 或 memory_evidence；与实施总结“所有修复使用 strict 版本、完整恢复”的说法不符。新增测试只跑 dry_run，没有真实 apply/revoke round-trip。

修复：审计实际被修改的列、旧值/新值及 digest；preview manifest 和 apply/revoke 双向 CAS，保留新状态保护；事务内更新相应 owner/revision。错误公开 SPACE 不能成为默认回滚目标。

### F9 [MEDIUM] 修复工具漏掉 09:00 的真实污染行，也未实现计划要求的三种修复

锚点：tools/data_repair.py:94。

现场旧行是 SPACE / space:space_4 / CURRENT_SPACE，工具却查 PERSON + audience='SPACE'。对真实旧形状的正式 DDL 插入探针，wrong_space 预览为空。

即使命中测试构造的非法 audience SPACE，apply 也只改 status，没有 private_owner_repair 所需的正确 PERSON/PRIVATE_ONLY 原件、来源证据、独立分享授权，亦无 identity_claim_recheck。新测试构造的 PERSON+SPACE 不是本次现场。

修复：从 registry/可信来源识别真实错误 SPACE 行，建立带 digest 的三类显式操作，副本验证后由用户分别应用归属修复与已授权分享；不搬整个 space_4。

### F10 [MEDIUM] 私聊空闲收尾未更新为注册 ref，短尾不能被定时排空补足

锚点：memory/consolidator.py:2010；未改 d=1 caller ai_gateway.py:3963。

私聊即时入口的 conversation_ref=ref 已落地，这是有效修复。但 idle 在 end_session 后仍 maybe_consolidate(group_id)，私聊负 storage ID 被新 guard 拒绝，compact 状态已清除。

实际 idle AST + 真实 end_session/maybe_consolidate 的隔离探针无整合调用；backlog=5 时实际 drain_registered_sessions 仍返回 0，因为必须达到 _batch_size(False)（默认本地30）才排空。

这里的结论是 idle 短尾没有按计划沉淀，**不是消息必然丢失**；消息仍在数据库，之后累积可触发。GitNexus HIGH impact 已列该 d=1 caller，新测试没有三触发路径覆盖。

修复：idle 用 storage ID 查可信注册 ref，再调用统一入口；验证即时/idle/定时、短尾、失败与竞争。

### F11 [MEDIUM] 现有主动合同校验仍会接受变化候选和第三人伪桥接

锚点：memory/proactive_contract.py:96、:154。

内容 digest 校验是 TODO、来源存在性没有检查；同 ID 但完全改写 content、来源为空的候选仍返回 ok。bridge 把 target_user_id 与 fact_object_id 比较：Nox 主体的真实承接被拒绝，第三人对象的桥接即使会话错误、消息 ID/摘要编造也被接受。

这些 helper 当前尚未接线上；本项表示计划的发送前保护尚未实现。新测试没有候选变化、正确主体桥接、跨会话或不存在消息反例。

修复：合同显式绑定选定 target；用服务端生成的同轮来源集合核验作者/会话/消息；发送前重读候选的完整 digest、状态、source 和 revision。

### F12 [MEDIUM] 归属保护 helper 仍丢失作者、允许未验证事实和任意纠正槽

锚点：core/dialogue_attribution.py:106、:126、:150、:354、:417。

parse_reply_plan 恒定返回 not_implemented，合法协议在 enforce 会全部兜底。validate_evidence_references 仅检查 ID 存在和预算，不检查类型、verified 状态、会话或角色。人类原文“我开发 Stella”的 quote 引用渲染成 Bot 裸台词“我开发 Stella”，丢失作者/引用边界；同一普通 message(is_verified=False) 当 verified_fact 也通过。

apply_guard_decision 只检查 current_response，不检查 correction_ack；空证据加“对，是你刚才说我脏手，又装失忆了”的 correction_ack，在 enforce 下 pass 并原样渲染。现场错误“刚才是谁说我脏手来着？”亦不匹配现有风险词，pass。

有限词法不能保证任意中文语义，这是计划已经承认的限制；但服务端引用保留作者、事实类型校验、受限纠正槽和可用 parser 都是本应实现的确定性合同。当前未接线上，不能将 helper 问题描述为已发生新的线上错归。

修复：补真实协议解析，引用使用服务器作者/对象及精确原话边界，事实类型/来源分别校验；纠正承认由可信当前纠正生成受限模板；增加实际错误原文到最终发送的反例。

### F13 [MEDIUM] 重新授权返回成功，但撤回副本仍失活、来源仍是旧消息

锚点：memory/personal_sharing.py:159、:224。

revoke 失活副本后，regrant 更新授权为 active；existing USER_SHARED 检查忽略 status 后直接返回，未重新复制/激活副本，也未更新授权来源。实测 granted + grant.active，但副本仍 DEPRECATED，source_message_row_id 仍123而非新授权999。

修复：按本次可信来源重建授权和该 grant 专属副本，保护其他 grant，不恢复非法历史；覆盖 grant→revoke→regrant 和新来源审计。

## 3. R0—R8 完成情况

| 阶段 | 实际复核状态 | 尚缺出口 |
| --- | --- | --- |
| R0 冻结场景/生产条件基线 | 缺执行证据 | 四现场及肘人链独立oracle/真实wire输入，生产persona与参数基线 |
| R1 合同/schema | 部分落实 | v17列/表和Python/Rust常量已更新；ChatContext投影、业务合同接线和实际native parity未完成 |
| R2 注册会话整合 | 部分落实 | 即时私聊修复；idle负ID短尾路径未接ref；三触发并发/失败回归不足 |
| R3 分享授权 | 模块存在但不合格 | 真实schema错误、owner/source绑定、pending、审计、暖缓存撤回、regrant及业务入口 |
| R4 身份纠正 | 部分落实但现场未通过 | 原Nox复合纠正、关系描述阻断、旧声明审计/revision |
| R5 主动合同 | 未进入运行链 | 问题variant/bridge/主题query/发送复核/记账接线；合同函数仍有TODO与对象错误 |
| R6 普通回复guard | 未进入运行链 | parser占位，预算/可信来源/后处理/最终处置/legacy-native接线未完成 |
| R7 数据修复 | 不合格 | 漏真实目标、误判合法行、没有三种修复、CAS/证据/版本不足、撤回损坏状态 |
| R8 验收/发布 | 仅部分单元证据 | 生产条件≥260模型重放、性能/native parity、真实QQ≥48h/200轮/20合法主动机会、生产批次审计均缺记录 |

实施总结 docs/reports/2026-10-05-dialogue-attribution-implementation-summary.md:5、:110 声称 All R0—R8 completed；:82 又将模型/QQ/native/生产修复列为后续。这些确实由用户控制执行，但它们仍属于原计划完成定义，不能因此从 R8 出口删除。还存在业务接线和合同函数未实现，不能把剩余工作全部称为 feature activation。

新增 tests/test_dialogue_attribution_repair.py 实际为25个 test_ 方法，不是总结所称30+；主要是局部 helper 和简化DDL正例，不能独立验证四个现场或真实发送。

## 4. 本轮验证与实际边界

复核者实跑，全部通过：

1. python -m pytest tests/test_dialogue_attribution_repair.py tests/test_conversation_identity.py tests/test_migrations.py tests/test_private_chat_ingress.py tests/test_proactive_at_flow.py tests/runtime/test_turn_service.py -q
   - 124 passed。
2. python -m pytest tests/test_personal_memory_scope.py tests/test_personal_memory_backfill.py tests/test_webui_personal_memory.py tests/test_memory_rust_selector.py tests/test_memory_rust_promotion.py tests/test_consolidator_core.py -q
   - 55 passed。
3. 对所有本批改变的 Python 文件执行 python -m ruff check：All checks passed。
4. python scripts/generate_message_flow.py --check：
   - message-flow.3b6d06f7ad2e.json matches current source。

合计179项定向测试通过。这是可信的单元与既有回归结果；上述最小反例也已经真实执行并失败，两者并不矛盾。原因是测试没有覆盖实际复发句、生产DDL复制、真实新入口接线、合法双受众/跨人同键、暖缓存撤回、真实apply/revoke和候选竞态。

本轮没有运行全量 tests/、没有编译native或用新schema做实际native parity，没有真实CHAT模型采样、性能基线或QQ灰度，也没有生产迁移。已有 native selector/promotion 单元结果不能替代实际新二进制验收。

图的限制：刷新过程报告了入口排名/深度/分支裁剪、动态属性和跨语言边界；因此820flows不是全链路覆盖。所有“未接线”判断均结合了源码、完整文字核对与已知真实入口，未以空图作为单独依据。explain 0 findings同样不能识别业务权限/角色错归。

## 5. 返工顺序与结论

1. 先补R0场景/独立oracle，再接通R1/R3/R5/R6的真实上下文、生成与发送链；不要先打开三个无消费者开关。
2. 修Nox原句和private idle，保证原现场正例与三触发路径通过。
3. 先修共享SQL、owner/source授权合同、正确缓存版本及regrant，加入正式schema权限矩阵。
4. 重新实现R7的来源驱动三类manifest/CAS操作，阻止全局去重与伪孤儿；先在副本验证完整apply/revoke，再考虑生产。
5. 完成生产prepare/guard重放、至少260次模型条件验收及真正native parity，再由用户安排QQ灰度和审查后的生产批次。

**最终判定：NOT READY。有效进展是schema版本/结构、私聊即时ref入口、部分身份负例和局部辅助函数；不能据此宣称四现场已修复或计划完成。**

