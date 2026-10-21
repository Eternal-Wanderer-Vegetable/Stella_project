# WP11 平台认证与发布验收记录

- 日期：2026-10-21（Asia/Shanghai）。
- 分支：`codex/cross-platform-implementation`；开始时 HEAD 为 `7359c85`。
- WP11 实现提交：`22ce1d0`（矩阵与真实事件/fake 回投夹具）。
- 结论：本地矩阵与代表性夹具已交付；官方 32 项仍全部 `NOT CERTIFIED`。平台 live、完整 L2/L3、QQ 灰度、干净 VM 和全量 Python 绿灯均未达成，WP11 与 XPLAT-IMPL 保持 `in_progress / NOT READY`。

## 范围与矩阵

[机器可读矩阵](../../tests/platforms/adapter_matrix.json)保留官方快照 SHA-256 `6e9d36324a4a2f209a569cbb9c9bb7ab1b3696ae392446af807e7787f0e0119a` 的 32 条记录，并由[test守卫](../../tests/platforms/test_adapter_matrix.py)逐行对比[执行附录](../plans/2026-10-20-cross-platform-inventory.md)的平台、模块名、包名和优先级。现有 CI 的 Python `pytest tests/` 会自动发现新测试，因此无需重复维护 CI 文件清单。

每行保留包观察、Python 要求、driver、Normalizer/Exporter/TargetCodec/CapabilityProvider、场景、权限、发送窗口、限流、维护状态，以及 L0–L3 各自的 local/fixture/live 结果。未知项显式留空并标 `not_assessed`，没有用 NoneBot 商店登记或共享合同测试推断成平台支持。

隔离 `.venv` 的 `importlib.metadata` 观察到 OneBot V11/V12 共用的 `nonebot-adapter-onebot 2.4.6`，发行包声明 `Requires-Python >=3.9,<4.0`；这只是当前本机包元数据。其余 30 个发行包未安装，版本和 Python 范围保留未知。Python 3.10/3.11/3.12 的完整兼容性矩阵、官方维护状态和 driver/协议组合均未在本阶段验证。

| 平台 | L0 local | L1 fixture | L2 | L3 fixture | live | 最终状态 |
| --- | --- | --- | --- | --- | --- | --- |
| OneBot V11 | pass：WP09 隔离 NoneBot Driver 注册了 `OneBot V11` | pass：真实 `GroupMessageEvent` 归一化并回投到同一 Bot/群；fake transport | not_run | partial：现有 fake segment exporter 测试，不代表平台接受 | not_run | NOT CERTIFIED |
| OneBot V12 | not_run（包已安装不等于驱动已注册） | not_run | not_run | not_run | not_run | NOT CERTIFIED |
| 其余 30 项 | not_run（对应发行包未安装） | not_run | not_run | not_run | not_run | NOT CERTIFIED |

OneBot V11 的 L0 证据来自 [WP09 隔离 Driver smoke](2026-10-21-wp09-adapter-assembly-health.md)：仅执行 `nonebot.init()` 和默认装配，未运行 Bot 生命周期或连接网关。L1 夹具覆盖适配器模型→Stella 规范事件→同一 `self_id` 和群目标→fake `UniMessage.send`。它不覆盖完整对话 runtime，也不是 live 收发。L2 的记忆隔离、命令和多账号/重启恢复没有平台级全链证据；L3 仅为 fake 出站段转换的部分夹具，没有服务端回执、权限、窗口或限流验证。

## GitNexus 影响分析

使用仓库固定启动器 GitNexus 1.6.11；提交实现前索引绑定 `7359c85`，提交后已刷新到实现提交 `22ce1d0`。

| 目标 | Upstream | 直接调用 | 风险 | 处置 |
| --- | ---: | ---: | --- | --- |
| `OneBot11Normalizer` | 6 | 1 | LOW | 仅新增使用它的事件夹具，没有改生产实现 |
| `OneBotV11TargetCodec` | 40 | 1 | MEDIUM | 仅在测试中复用；目标保持由可信归一化事件构造 |
| `OneBotV11Exporter` | 40 | 1 | MEDIUM | 仅在测试中复用；fake send 不修改平台副作用实现 |
| inventory plan file | 17 | 6 | MEDIUM | 核对引用后同步状态与矩阵链接 |
| implementation plan file | 17 | 6 | MEDIUM | 保留逐包状态语义，只标记 WP11 in progress |
| `progress.md` / `feature_list.json` / `session-handoff.md` | 26/19/19 | 3/2/2 | LOW | 更新任务状态与交接记录 |
| WP11 report file | 17 | 3 | LOW | 新报告，无调用流程修改 |

WP11 实现提交 `22ce1d0` 后，GitNexus 1.6.11 增量刷新成功：99,376 nodes / 246,828 edges / 1,042 clusters / 847 inferred flows，`status=up-to-date`。刷新仍报告 20 个大文件跳过、925 个跨语言属性缺边、2,746 个入口候选未进入排序及 trace/branch 预算截断；流程图仍是 lower-bound。表中 plan/inventory/report 文件 impacts 在刷新后的索引上复查；report 首次查询 partial 后串行重跑完成。

本阶段没有改动运行时源文件。GitNexus 流程仍受大文件、回调/动态边、跨语言属性和入口预算限制；影响计数是当前索引下界，不是平台安全或 live 正确性的证明。

## 验证结果

- 定向命令：`STELLA_HOME=/tmp/stella-wp11-20261021 .venv/bin/python -m pytest -q tests/platforms/test_adapter_matrix.py tests/test_transport_normalizers.py tests/test_transport_outbound.py`：**18 passed**。
- 全量命令：`timeout 600s env STELLA_HOME=/tmp/stella-wp11-20261021 .venv/bin/python -m pytest tests/ -q --timeout=120 -n auto --dist loadgroup`：**3873 passed / 29 skipped / 6 failed**，79.06 秒。
- 串行复跑全部 6 个失败项，仍为 **6 failed**；因此不是 xdist 竞态。失败为：
  - `tests/runtime/test_proactive_native.py::test_proactive_at_goes_through_native_facade`、`test_proactive_join_goes_through_native_facade`：fake Bot 的 `send_group_msg` 未被调用；统一投递记录目标不可用/发送失败。
  - `tests/test_candidate_reinforcement.py::test_reoccurrence_eventually_promotes_end_to_end`：第二次候选后预期晋升 1 条，实际 0 条。
  - `tests/test_capture_ingress_gating.py::test_private_closed_gate_skips_persist_reply_still_works`：日志确认闭门后仍生成回复，但 fake 投递未接受片段。
  - `tests/test_memory_replay.py::test_replay_gate_all_green`：replay gate 仍报 `promotion_correctness`、`memory_delta` 等三项失败。
  - `tests/webui/test_webui_manage.py::test_scheduling_crud`：旧兼容入口的默认 Bot ID `self` 不能构成有效 QQ target，服务抛 `InvalidTaskError`。
- 失败文件均未在 WP11 改动；这次运行也不能证明根因属于某个历史工作包。它们作为全仓回归阻塞保留，不能用定向通过覆盖。
- `ruff check --fix` 曾只整理新测试 import 顺序，随后该文件 Ruff 检查通过。消息流程 `generate_message_flow.py --check` 通过，manifest 为 `9b80952673b2`，没有新增 runtime entry。
- 状态文档检查：`python scripts/check_docs.py` 119 files / 1,235 links / 577 anchors / 0 errors；全仓 Ruff 通过；message-flow 检查通过；feature/matrix JSON parse 与 `git diff --check` 通过。
- 提交前 GitNexus 检查（固定 1.6.11）：scope all 为 5 tracked files / 15 symbols / 0 processes / LOW。compare 首轮遇到 `process-lookup` interrupted，返回 partial/unknown；按门禁立即串行重跑后完整为 336 files / 1,140 symbols / 106 processes / CRITICAL，无 partial/truncated；符号列表 capped，计数覆盖全部累计范围。新 fixture/matrix 与新报告为未跟踪文件，不会被 GitNexus tracked diff 代替校验；前者有定向 pytest/JSON 对账，报告已执行 file impact。

## 未验收与下一步

- 未配置或使用任何平台账号、网关、生产 `.env`、生产数据库、真实 Bot、模型服务或 QQ 灰度。
- 未执行 Windows/Linux 干净 VM 安装、跨进程多账号恢复 live、Python 3.10/3.11 独立 runtime、外部 Release 生成/回读。
- 不更改 release/version manifest：没有平台达到认证条件，也未进行真实发布。
- 首先关闭上列全仓回归项；然后按 P0→P1→P2 安装并分别验证适配器与 driver，逐平台维护 fixture、L0–L3 和协议适用性证据；最后分别完成 live、多账号恢复、QQ 灰度和干净 VM 门禁。32 项分母和非聊天事件型语义维持不变。
