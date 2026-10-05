# 2026-10-05 对话对象与记忆归属复现核查

日期与时间：Asia/Shanghai，2026-10-05。状态：**两个现场已确认，原因分别为跨会话记忆链路缺口与主动验证跨人取材/任务漂移；本次没有修改业务代码、配置或生产数据库。**

## 结论

1. **09:00:46：同一用户的私聊关系没有进入群聊上下文。** 当前用户一直是 `3996233487`，QQ 回复关系也正确。私聊中确认的 CP 关系已在 08:48:31 存成长期记忆，但被错误写为 `SPACE / space:space_4 / CURRENT_SPACE`；群聊检索在 `space_1`，无法读到该行。私聊触发整合仍走旧群入口，丢失 `ConversationRef`；即使先修复此入口，当前自动写入只支持 `PRIVATE_ONLY`，尚没有把“在群里也记得”落实为 `USER_SHARED` 的显式分享流程。
2. **14:09:19：主动验证时把另一个人的背景套到目标用户。** 系统正确选择 `176403822`，本应验证“外在形象固定，无法通过互动改变”，却发出“歌姬吧，那个Stella是你开发的吧？”。“开发/维护 Stella”的检索记录属于 `3089665724`，prompt 也如实标注了此归属。模型既跨人取材，又改换了验证问题；发送前没有候选一致性校验阻止它。
3. 两轮均包含新角色/事实规则、投影 v1 和正确的当前平台 ID；均没有预算裁剪，均有确认送达。因此不能解释为补丁未加载、当前用户 ID 丢失、截断或平台随机发送给另一个人。

## 时间与现场证据

用户给出的两个时间与 thought 日志的生成完成时间一致。该日志是本机 +08:00；本次 `memory_traces.ts`、`group_messages.timestamp` 使用 UTC，已与 JSONL 交叉核对。QQ `message_sent.time` 有另一个时钟基准：上午首泡平台时间为 09:00:19，本机事件到达 09:00:47；下午平台时间为 14:08:51，本机到达 14:09:20。本报告使用用户给出的本机时间定位，不混用时钟。

| 现场 | 当前用户 | 记忆 trace | turn trace | 预算估计/上限 | 送达 |
| --- | --- | --- | --- | --- | --- |
| 09:00:46 | 3996233487 | 1310（UTC 01:00:46） | 7959161bb4b248b3a2b48bae0fe800a8 | 1557 / 6340；truncated=false | 3 / 3 |
| 14:09:19 | 176403822 | 1395（UTC 06:09:19） | 3a46902f6d1f43dc9640bc43d0771649 | 2554 / 6340；truncated=false | 1 / 1 |

原始模型输出、实际 prompt、检索记忆与 turn 事件已冻结到 `evidence/dialogue-attribution-20261005/case-090046.json` 与 `case-140919.json`。跨场景数据库证据见同目录 `cross-case-evidence.json`，哈希见 `manifest.json`。数据库以 `mode=ro` 打开；冻结文件可能包含用户原话，仅保存于本地工作区。

### 上午：关系丢失的完整链路

08:46:53 私聊中，用户明确要求“那以后在群里，也要记得我们CP的关系哦”，Stella 回答“知道啦知道啦 / 在群里又要装高冷又要偷偷开心”。08:48:25 用户继续要求“那就明面表现出来就好啦”，Stella 再次同意。现场输入/输出在 `StellaData/logs/stella_thought_logs.md:72029` 与 `:72070`。

私聊注册记录正确：

```text
conversation_key = qq:1694717255:private:3996233487
storage_session_id = -3
memory_space = private:qq:1694717255:3996233487
```

但即时整合调用错误：

```text
handle_private_chat
  → maybe_consolidate(ref.storage_session_id, force=True)
  → _consolidate_with_flow
  → consolidate_group(-3)
  → _consolidate_group_core(memory_space=None, conversation=None)
  → resolve_space(-3) = space_4
  → _write_memory_candidates：PERSON 路由条件不成立
  → SPACE / space:space_4 / CURRENT_SPACE
```

源码锚点：`stella_project/plugins/bot_main/ai_gateway.py:1643`、`memory/consolidator.py:1943`、`:690`、`:1443`。正确的注册会话入口 `consolidate_conversation(ref)` 已存在于 `memory/consolidator.py:611`，但此即时触发链没有使用它。定时 `drain_registered_sessions` 走注册会话路径，不能把已经被另一入口处理并推进 checkpoint 的记录自动重新归属。

运行日志印证此链：`memory_consolidation_log.md:99996` 记录 08:48:13 对“群 -3 / space_4”开始整合；JSONL `stella.2026-10-05_02-54-56_387574.jsonl:24231` 记录 08:48:31 完成至消息行 39548。长期记忆 `9e3bfcc209004463bf7c71afe8789b3a` 在 UTC 00:48:31 创建，内容正是“确立 CP 关系并要求在群聊公开表现”，归属却是上述旧 SPACE。源用户消息行 39547、39551 带正确 `PRIVATE_DIRECT` 和 canonical private key。

09:00:46 的群聊 prompt 完全没有这条关系，只选出三条背景：当前用户“喜欢名为 Stella 的对象（具体身份未明）”、其他成员对 Nox 的亲密互动偏好、第三人的恐怖片习惯。输出因此声称“群友加偶尔聊天的搭子”。这直接证明该轮没有拿到已经确认的私聊关系；不是关系从未保存。

`memory/ownership.py:169` 的群聊 scope 仅允许当前 SPACE 和当前用户的 `PERSON / USER_SHARED`，不能读取 `space:space_4`。只读探针复用生产 scope 函数和 SQL 谓词，确认上述关系行对群聊不可见。该用户在 `personal_profile_facts` 中没有对应行；本次数据库也没有 `USER_SHARED` 记忆。

第二个独立缺口在 `memory/consolidator.py:1409` 的契约说明：本版写入只支持私聊 `PRIVATE_ONLY` 和 SPACE，明确没有自动识别显式分享意图。所以仅把即时整合换成注册入口，能修复错误空间，却不能完成用户要求的跨会话共享。

此外，`space_1` 中本就存在该用户的旧伴侣关系记忆（例如 `44a0fdbdb53a4c92885ddd7caeee14e9`）；它有群聊读取资格，但未被这一轮选入最终背景。现场证据确认其没有被使用，尚不能仅凭当前数据库断定它当时是被 FTS、候选池新鲜度上限、排序还是缓存排除。不能把所有召回问题都归因于私聊空间错误。

### 下午：主动验证的目标正确，取材与问题错误

14:09:16 系统选择用户 `176403822`。候选 ID 为 `3cebd0ad49e447758133e18241c95caf`，内容“外在形象固定，无法通过互动改变”，confidence=0.80，源行 35304。该源行已不在当前消息表中，故本次没有把候选原始抽取是否正确算作已核验事实。

模型生成的问句却是：

> 歌姬吧，那个Stella是你开发的吧？

这与候选主题无关。实际 prompt 的第一条检索背景为：

```text
群共享背景 [记录=用户(3089665724)；事实主语未确认]：
正在开发或维护一个名为Stella的BOT……
```

它对应长期记忆 `a91752bd6b0b4606a724f23e69277f88`；其他四条背景也都记录在 `3089665724` 或 `3559802578` 名下。prompt 已明确当前用户为 `176403822`，并给出归属规则。模型仍从别人的背景生成针对当前人的问题。现场输出见 `stella_thought_logs.md:78250`；QQ @ 与数据库行 40272 均确认收件人是 `176403822`。

可确定的程序缺口：

- `_proactive_at_user` 在 `ai_gateway.py:3181` 把 `build_instruction(target)` 放进 `ctx.message`，然后复用普通用户记忆上下文。指令型 intent 在路由和 prompt 组装中已有处理，但记忆检索仍直接使用 `ctx.message`（`memory/pre_processors.py:899`、`:907`）。
- 候选没有技术内容，任务模板却含“拥有 RTX5080 显卡”的示例。`memory/policy.py:306` 的技术关键词包含 `rtx` 与 `显卡`。生产 `detect_mode` 的隔离探针得到：候选单独输入 → `CASUAL_REPLY`；完整主动指令 → `TECH_HELP`；删除 GPU 示例后 → `CASUAL_REPLY`。真实 memory trace 1395 的 mode 也为 `TECH_HELP`。这是模板污染检索模式的确定性证据。
- 有访问 scope 时，`retrieval_v2.py:196` 使用 SPACE/PERSON owner 谓词，SPACE 分支允许同空间其他成员的背景；它没有再按当前 user_id 限制 SPACE 行。共享背景出现在普通群上下文是现有设计，但主动验证只有一个目标与候选，仍广泛召回其他人的背景，会增加任务漂移的机会。
- `ai_gateway.py:3222` 起只检查空回复、skip 标记、拼接后为空及近期重复，随后直接 @ 目标并发送；没有校验输出的事实主语或问题是否仍对应 `target.candidate_id`。发出后 `record_at(... candidate_id=target.candidate_id)` 仍按原候选记账。这次错误问题因此通过了发送边界。是否导致后续错误确认/长期记忆污染，本次未证实。

“把其他成员背景变成当前目标的确认问题”是明确的现场语义错误；内部模型为何忽略指令不能由单个样本唯一归因到模型参数或量化。没有做替换模型对照，不将 IQ2_XS 单独定为根因。

## 与昨天修复和验收的关系

昨日的多气泡投影与角色/事实规则已经实施，今天两轮真实 prompt 都可见它们。今天的上午场景主要属于私聊→群聊记忆连续性；下午属于主动候选验证与共享背景归属，不能简单等同为昨天“Bot 条件威胁归给用户”的旧样例。

现有 `2026-10-04-dialogue-attribution-model-acceptance.md` 明确记录 80 次矩阵通过，但评估没有生产人格 system prompt，不含私聊回归，真实 QQ 灰度待执行；也没有今天这种“主动验证目标 + 待确认候选 + 他人开发背景”的完整场景。其 0/80 结论是该矩阵的采样结果，不能覆盖这两个现场。无需推翻已完成的数据层修复，也不能以其通过宣称当前对话归属完全修复。

## 后续修复顺序（建议，未实施）

1. 统一私聊即时触发、空闲收尾、定时排空的注册会话整合入口；携带完整 `ConversationRef`，并阻止负存储 ID 进入真实群空间解析。核对 checkpoint，防止旧入口先消费导致正确入口无数据。
2. 对已有 `-3 / space_4` 等错误归属做可审计迁移方案，依据 registry 和源消息验证；不要直接合并整个空间。显式分享只作用于用户指定的个人事实，使用同 Bot/同人的 `USER_SHARED`；其余私聊继续受 `PRIVATE_ONLY` 限制。
3. 主动验证把“任务指令”和“检索主题”拆成不同输入，以目标候选及近期相关对话做检索。对其他成员背景保留主语证据并控制其进入验证任务的条件。
4. 发送前要求输出仍对应同一候选/主体，承接不足或检查失败时退出，不发送并不记作已验证；检查方案必须经过真实模型/QQ评估，不能靠一句更强的 prompt 声称保证。
5. 将今天两条完整现场加入回归，并使用实际人格 prompt；覆盖即时整合/定时整合竞争、已存关系的跨会话共享、模板示例不改变 mode、他人背景不得替换候选，以及不相关输出不能消耗原候选验证状态。

实施前仍须对具体待改符号重新运行 GitNexus impact，实施后按仓库要求进行图变更分析与相应验证；本报告没有执行这些代码改动。

## 本次验证与 GitNexus 边界

- 使用 `gitnexus-debugging`，Docker 容器 `stella-gitnexus`，显式绑定 `Stella_project`。
- 已运行 `analyze --index-only --pdg`：537.6 秒，88,058 nodes、213,790 edges、949 clusters、827 flows；索引 HEAD 与当前业务源码 HEAD 均为 `6b35b6ba85752ddef66c50e2f56d045f6a5bb908`。
- 已执行私聊整合/主动验证概念 query，以及 `maybe_consolidate`、`handle_private_chat`、`consolidate_group`、`_build_user_context_v2`、`_proactive_at_user` context。图确认私聊入口调用旧 maybe_consolidate；检索/发送链以对应源码和真实 prompt 交叉验证。图输出冻结在证据目录 `gitnexus-*.txt`。
- 分析器报告 entry point/process 截断及跨语言链接限制，部分 context 没有 process；没有把它们视作“没有执行路径”。索引刷新后新增的是本次报告/冻结数据；随后 status 的 stale 是这些新诊断文件尚未索引，业务源码没有改动。没有宣称整个工作区完全 fresh。
- 两项隔离只读探针通过：scope 排除错误私聊 SPACE 行；主动指令示例把 mode 确定性推到 TECH_HELP。未调用新的模型、未发 QQ 消息、未重启服务，未运行或声称代码修复测试通过。
