# 任务状态与会话交接

[Agent 导航](README.md)

适用：跨会话、长任务、恢复与结束会话。来源为 harness-creator 的状态/范围/生命周期模型；状态格式变化时复审。

## Startup Workflow

1. 读 [AGENTS.md](../../AGENTS.md)，核对分支、工作区和用户最新任务。
2. 读 [feature_list.json](../../feature_list.json) 的 active_feature、状态、依赖、done_criteria 和 evidence，再读 [progress.md](../../progress.md)。
3. 未完成任务沿 [session-handoff.md](../../session-handoff.md) 找文件、检查结果和下一步，核对工作区。
4. 选择一个任务，按 [验证门禁](verification.md) 记录基线，再开始范围内工作。

## 状态合同

- status 为 `planned` / `in_progress` / `blocked` / `done`；这是仓库任务状态，与聊天产品 goal 独立。
- 一个 active_feature；授权独立并行工作后先写文件所有权与依赖。
- done_criteria 必须可检查。缺必要条件不写 done；外部验收缺口不由单测替代。
- evidence 写命令、结果、目标版本和报告位置，不粘贴凭据或聊天原文。
- 清单只跟踪登记任务，不代表全部产品能力或历史计划的完成情况。

## End of Session

1. 核对本轮范围和已有修改，记录结果、失败/未执行项。
2. 更新 feature_list 的 status / active_feature；progress 写 Current State、What's Done、What's Next、Files。
3. handoff 写 Current Objective、Verification Evidence、Blockers、Recommended Next Step；完成后标明可归档，无新任务时不自行启动旧计划。
4. 未完成任务给出最小恢复命令和下一步；长期证据放日期报告，状态只留链接。
