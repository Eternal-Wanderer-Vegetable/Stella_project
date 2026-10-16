# 2026-10-16 回复协议多 current 兜底：诊断与修复报告

本次结论：**「我没看明白这条结构化回复」兜底的直接原因是小量化模型用重复 `<current>`（或嵌套 `<reply>`）表达三段短句，被 ReplyEnvelope 解析器以 `duplicate_or_attributed_current` 整体拒绝。根因是协议只示例了单个 current 槽、从未说明唯一性与多段写法，而对话历史投影把 bot 旧消息渲染成多段 JSON 数组，反向示范了分段风格。已在 `fix/reply-envelope-multicurrent` 分支叠加两项修复：协议提示词明确单槽换行规范（方案 A）+ 解析器按换行合并重复裸 current、带属性 current 仍拒（方案 B）。**

诊断阶段只读源码与 `StellaData/logs/stella_thought_logs.md`，未修改业务数据；修复阶段新增本报告、测试与 P2 oracle 修订，未动用户数据。

## 1. 现场与频率

- 触发样本：2026-10-16 19:08:16 私聊（用户 3996233487），模型 `qwen3.8-flash-next-iq2_xs`，输出 `<reply kind="social"><current>唔…别咬啦</current><current>（缩了一下）</current><current>很痛诶，下次轻点嘛</current></reply>`。
- 全部 thought 日志 2241 条中真兜底 17 条；当日 41 条中 3 条（约 7%），均在同一私聊会话。当日三种失败形态同源：17:17 嵌套三个 `<reply>`（仅闭合最后一个）→ `legacy_malformed_xml`；18:17、19:08 重复 `<current>` → `duplicate_or_attributed_current`。
- 排查陷阱：按「条目全文包含兜底文案」过滤会大量误报——prompt 的对话历史里会引用此前发出的兜底话；判真兜底必须只看「💬 最终台词」字段本身。
- 历史对照：2026-10-09 群聊那批兜底多数属旧版解析器（缺 response 外壳即拒），已被 952007e 的外壳修复路径修掉；用当前代码重放验证 8 条全部 PASS。

## 2. 因果链

1. 对话历史投影把 bot 旧消息渲染为 `[{"part":0,...},{"part":1,...},{"part":2,...}]`，模型据此形成「我按三短句说话」的风格压力。
2. 协议模板（`protocol_instructions`）只示例单个 `<current>`，未说明该槽唯一，也未说明多段应写成同一 `<current>` 内换行（`split_lines` 本就按 `\n` 切段、`MAX_REPLY_LINES=5`）。
3. 模型自发泛化为重复标签；解析器（`core/dialogue_attribution.py` 原 `duplicate_or_attributed_current` 分支）整体拒绝，`memory/post_processors.py::parse_output` 转受限服务器兜底文案。

## 3. 修复内容

- 方案 A（`core/dialogue_attribution.py::protocol_instructions`）：协议说明新增一行「current 槽只写一个；要分多段短句时在同一个 current 里用换行分隔，不要重复 current 标签或嵌套 reply。」经 `reply_system_prompt`、`turn_service` 与评估脚本共用同一函数，三处一致生效。
- 方案 B（`parse_reply_envelope`）：重复的裸 `<current>` 按换行合并为 `current` 多段文本；带 `user_id` 等属性的 current 仍以 `attributed_current` 拒绝，归属防伪不变；空段丢弃，全空仍由 `invalid_social_slots` 拒。协议版本保持 2026-10-08.1（仅放宽服务端接受面，模型侧语法不变）。
- 影响面（GitNexus 本机注册表损坏不可用，rg 兜底清点）：`parse_reply_envelope` 调用方为 live 回复链（`memory/post_processors.py:58`）与归属 guard（`core/dialogue_attribution.py::1120`）；`protocol_instructions` 调用方为系统提示词、turn service、评估脚本。无 Rust/native 孪生实现。

## 4. P2 oracle 修订

`tests/runtime/fixtures/legacy_traces/p2_protocol/` 中 7 个含 LLM 调用的场景按 952007e 同样的审阅流程重算：在 pytest 环境（conftest 强制 v1 记忆路径）重放，差异经逐字段 diff 审查后仅落在白名单路径（`trace.llm_calls.0.prompt`、`trace.llm_calls.0.system_prompt` 与派生的 token 诊断三字段），回复/钩子/输入/raw 冻结不变。`oracle-update-manifest.json` 新增 `current_slot_prompt_revision` 块记录前后 SHA-256。注意：工作区历史混用 LF/CRLF，重写统一为 CRLF，字节级哈希因此整体偏移。

教训（已写入过程记录）：脱离 pytest 环境单独跑重放脚本会让 v2 记忆链路混入「角色与事实规则」段污染夹具；oracle 修订必须在 conftest 环境内执行。

## 5. 验收

- `python -m pytest tests/test_dialogue_attribution_repair.py -q`：59 passed（新增 4 例：合并、空段丢弃、attributed 拒绝、提示词含新规范；原「重复 current 必拒」两处断言改为新语义）。
- `python -m pytest tests/test_attribution_wiring.py tests/runtime/test_turn_service.py tests/test_memory_cas_contract.py tests/runtime/test_legacy_reference_traces.py -q`：37 passed。
- 引用受影响模块的全部测试文件（full_workflow、session_compact、prompt_cache_prefix、evidence_contract 等 17 个文件）：187 passed。
- `python -m ruff check core/dialogue_attribution.py tests/test_dialogue_attribution_repair.py`：通过。
- 真实故障样本重放：19:08:16 与 18:17:38 两个现场输出均解析为三段合并 current；带属性 current 样本仍拒绝。
- 未运行：真实 QQ 灰度观测（需用户重启 bot 后观察兜底率）；全仓 pytest（改动面已由上述定向集覆盖）。

## 6. 残余风险与后续

- 嵌套 `<reply>`（17:17 形态）是畸形 XML，仍走澄清兜底；方案 A 的提示词已明示禁止，发生率待灰度观察。
- 合并后的多段回复沿用 `MAX_REPLY_LINES=5` 上限，超限走 `too_many_atomic_segments` 静默，属既有行为。
- bot 进程需重启才会加载新解析器与提示词；重启前线上兜底率不变。
