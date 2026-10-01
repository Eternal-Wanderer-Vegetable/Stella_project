# Cometa 外部 Agent 任务运行层 人工测试清单 v1.0

> 适用分支：`feat/cometa-agent-task-layer`（M0–M3 已实施，自动化回归全绿）。
> 目的：覆盖自动化测不到的部分——真实 QQ 链路、真实进程生命周期（重启/关闭/
> 孤儿进程）、真实浏览器页面、投递故障与多用户授权。
> 对应设计文档：`design_docs/Cometa 外部 Agent 任务运行层实施方案 v1.0.md`
> 的 §8.3（人工与集成验收）与 §13（完成定义）。
> 日期：2026-09-30。测试人逐项勾选 ☐ 并在「结果」处记录实际现象。

## 使用说明

- **顺序**：T0 必须先做；T1–T19 相互独立，可任意顺序，但每项的「前置」要满足。
- **切换场景**：改 `STELLA_HOME/config/cometa.toml` 或 `.env` 后**必须重启 Bot**
  （cometa 配置在启动时加载，不做热更新）。
- **观察点**（后文反复引用）：
  - Bot 控制台/日志：搜 `[Cometa]` 前缀（装配、认领、恢复、投递都在这里）；
  - 任务库：`STELLA_HOME/cometa/tasks.db`（只读查看：`sqlite3 <路径> "select task_id,state,phase from tasks order by created_utc desc limit 5"`，**运行中不要写**）;
  - WebUI：`http://127.0.0.1:8080/#/cometa`（端口 = NoneBot 监听端口；dev 与 prod 同用 8080，起不来先查是否已有 bot 进程占着）；
  - WebUI 审计：`STELLA_HOME/logs/webui_audit.jsonl`。
- **确认 STELLA_HOME**：项目根目录执行
  `python -c "from config import STELLA_HOME; print(STELLA_HOME)"`。

---

## T0 环境准备

**前置**：本分支代码；`pip install -r requirements.txt` 已装。

1. 在 `STELLA_HOME/.env` 加入：
   ```ini
   COMETA_ENABLED=true
   COMETA_TASK_TIMEOUT_SECONDS=120
   ```
   （超时设短是为 T5；整套测完后记得改回或删除。）
2. 创建 `STELLA_HOME/config/cometa.toml`（内容如下，**替换 QQ 号/群号**）：
   ```toml
   schema_version = 1

   [limits]
   per_user_active = 1
   per_group_active = 4
   input_wait_seconds = 600
   retention_days = 7

   # 演示后端：fake_behavior 是本分支新增的人工测试键，仅 type="fake" 可用
   #   complete = 自动完成 / fail = 自动失败 / input = 先提问再完成 / hang = 挂起直到取消
   [backends.demo]
   type = "fake"
   fake_behavior = "complete"

   [profiles.coding]
   backend = "demo"

   [access]
   qq_user_ids = [10001]        # ← 你的 QQ 号（可加第二个号做 T9）
   qq_group_ids = [123456]      # ← 测试群号
   operator_user_ids = [10001]  # ← 管理员（审批用）
   ```
3. 启动 Bot（dev：项目根 `.\bot.py`）。
4. 确认 `STELLA_HOME/cometa/tasks.db` 已生成；控制台出现
   `✅ [Cometa] 外部 Agent 任务层已装配`。

**预期**：以上全部成立。另起一个 worker 进程不存在孤儿告警。

结果：☐ 通过 ☐ 不通过（现象：____________）

---

## T1 关闭态零回归（§13 第 1 条）

**前置**：`.env` 中 `COMETA_ENABLED` 删除或 `=false`，重启 Bot。

1. @Bot 普通聊天 → 正常回复；
2. 触发一个 Comes 工具（如既有能力指令）→ 正常执行；
3. 定时任务照常触发（如已配置）；
4. WebUI 打开 `#/cometa` → 显示蓝色「cometa 未启用」提示条，**不弹错误 toast**；
5. 控制台搜索 `[Cometa]`：只有 `❌ 初始化失败`（不应出现）——正常应**完全没有** cometa 装配日志。

**预期**：与合入前行为逐项一致；cometa 日志为零。

结果：☐ 通过 ☐ 不通过（现象：____________）

---

## T2 显式委派成功链路（QQ，§8.3 第 2 条的 Fake 替代）

**前置**：T0 配置（`fake_behavior = "complete"`）；Bot 已重启。

1. 测试群 @Bot 发送：`委派 demo 帮我整理一份排序算法说明`
2. **2 秒内**收到受理确认（引用你那条消息 + @你）：
   `已受理外部任务（xxxxxxxx）：…完成后我会回报结果…`
   → 记下短 ID：________
3. **几秒后**收到最终结果推送：`任务 xxxxxxxx 已完成。` + 结果摘要；
4. **期间**（第 2、3 步之间）让群友正常聊几句、@Bot 问个普通问题 → 普通回复照常，长任务不阻塞聊天；
5. 发送 `任务状态 xxxxxxxx` → 回复「已完成」；
6. 发送 `任务结果 xxxxxxxx` → 回复结局 + 摘要。

**预期**：ack 只有**一条**（不是两条相同消息）；final 如实呈现「已完成」；聊天不受影响。

结果：☐ 通过 ☐ 不通过（现象：____________）

---

## T3 任务命令与边界（QQ）

**前置**：T0；依次做以下 5 个小项（每项之间无需重启）。

1. **不存在的任务**：发送 `任务状态 deadbeef` → 回复「没有找到任务 deadbeef…」；
2. **点名不可用后端**：发送 `委派 ghost 做点什么` → 回复
   `未能受理委派：backend_unavailable: 后端 'ghost' 不可用`（**不静默换后端**）；
3. **取消排队中的任务**：先把 toml 改 `fake_behavior = "hang"` 并重启；发送
   `委派 demo 测试取消`，**立刻**发送 `取消任务 xxxxxxxx` →
   回复「任务 xxxxxxxx 已取消。」+ 一条 final「任务在开始前被取消」；
4. **取消执行中的任务**：再次 `委派 demo 测试取消在途`，等 WebUI/日志显示
   running（约 3–5 秒）后发送 `取消任务 xxxxxxxx` →
   先回「已请求取消任务…确认停止后我会回报」，几秒后收到 final「任务 xxxxxxxx 已取消。」；
5. **不提前声称已取消**：第 4 项中，「已请求取消」与「已取消」是两条消息，
   第二条晚于第一条出现。

**预期**：以上文案与次序全部符合；toml 改回 `complete` 供后续用例（或保持 hang，T4/T5 会再改）。

结果：☐ 通过 ☐ 不通过（现象：____________）

---

## T4 输入与审批（§8.3 第 4 条的单用户半边）

**前置**：toml 改两处——`fake_behavior = "input"`、`[limits] input_wait_seconds = 180`；重启。

1. 发送 `委派 demo 测试输入` → ack 后约几秒收到提问：
   `任务 xxxxxxxx 需要你补充信息：演示：请补充任意一句话让任务继续。`；
2. 回复 `任务补充 xxxxxxxx 我用 main 分支` → 回复「已把补充信息转给任务…」；
3. 几秒后收到 final「已收到补充信息，演示任务完成。」；
4. **过期中断**：再次 `委派 demo 测试过期`，收到提问后**不回复** →
   约 3 分钟后收到 final（任务取消）；再发 `任务状态 xxxxxxxx` → 显示已取消；
5. **WebUI 答复**：再次 `委派 demo 测试网页答复`，打开 `#/cometa` 该任务详情 →
   顶部出现提问与答复输入框 → 填任意内容提交 → 状态推进到已完成（页面 5 秒轮询自动刷新）；
6. **过期请求不能答复**（可选，需浏览器 F12）：在第 4 步过期后，
   对旧 request_id POST `/api/v1/cometa/tasks/{id}/inputs/{request_id}` → 400。

**预期**：普通用户自己的补充信息能推进任务；过期即中断，沉默不等于批准。

结果：☐ 通过 ☐ 不通过（现象：____________）

---

## T5 超时 → timed_out（§6.2 状态机）

**前置**：toml `fake_behavior = "hang"`；`.env` 保持 `COMETA_TASK_TIMEOUT_SECONDS=120`；重启。

1. 发送 `委派 demo 挂起测试`；
2. 等待约 2 分钟 → 收到 final：`任务 xxxxxxxx 失败/取消。任务到达墙钟期限，已确认停止…`；
3. 发送 `任务状态 xxxxxxxx` → 显示「超时」（WebUI 里状态 chip 为「超时」）。

**预期**：任务被收束为**超时**终态而非永久挂起；已产生的部分内容（本场景无）会保留。

结果：☐ 通过 ☐ 不通过（现象：____________）

---

## T6 WebUI 页面与 API（§6.14）

**前置**：toml `fake_behavior = "complete"`；Bot 运行中。

1. **401**：无痕浏览器（或 `curl -i http://127.0.0.1:8080/api/v1/cometa/tasks`）→ 401 envelope；
2. **提交**：登录管理页 → `#/cometa` → 输入目标（≥8 字）→「委派」→ 列表 5 秒内出现新任务（排队中 → 执行中 → 已完成）；
3. **幂等重放**（可选，F12）：Network 面板对 `POST /api/v1/cometa/tasks` 重放同一请求体 → 返回 202 且 `task_id` 不变，列表不出现第二个任务；
4. **详情与事件**：点「详情」→ 事件列表含 `accepted`、`started`、`progress`、`completed`；
5. **取消按钮**：提交一个任务立即点「取消」→ 状态变「已取消」；
6. **产物下载**（可选）：FakeBackend 不产生文件，此项留待真实 Codex；自动化已覆盖 404/越界拒绝，手动只需确认详情页产物区无异常渲染；
7. **审计**：`STELLA_HOME/logs/webui_audit.jsonl` 出现 `cometa.submit`、`cometa.cancel` 行；
8. **审计不含敏感内容**：审计行里没有完整目标文本之外的凭据/提示词。

结果：☐ 通过 ☐ 不通过（现象：____________）

---

## T7 WebChat 重置不伤任务（§6.11 reset 语义）

**前置**：T6 环境不变。

1. 在 `#/cometa` 提交一个任务，记短 ID；
2. 打开 `#/chat`，发一句话，然后点「重置会话」；
3. 回到 `#/cometa` → 任务仍在，状态正常推进至完成；
4. 聊天页历史已清空，**不会**重新出现该任务的任何消息。

结果：☐ 通过 ☐ 不通过（现象：____________）

---

## T8 重启恢复（§8.3 第 3 条，关键）

**前置**：toml `fake_behavior = "hang"`；重启 Bot。

1. 发送 `委派 demo 恢复测试`，等日志出现 `claimed task=…`（任务已 running）；
2. **直接关闭 Bot 进程**（Ctrl+C 或关终端），不等任务结束；
3. 重新启动 Bot → 控制台出现
   `⚠️ recovered task=… attempt=… -> recovery_required`；
4. 发送 `任务状态 xxxxxxxx` → 显示「需管理员处理」；
5. **不重复执行核验**：WebUI 打开该任务详情 → 事件列表里 `started` 只出现**一次**，
   没有第二个 final；任务库（只读）`select attempt_no, count(*) from attempts group by task_id` 该任务 attempt 数为 1；
6. **queued 重启**：Bot 停止状态下用 WebUI 无法提交（进程死了）——改为：重启前提交任务后
   3 秒内关机（queued 未认领）→ 重启 → 任务照常被认领并完成（complete 场景）或保持挂起（hang）。

**预期**：重启不产生第二次执行；无法核对的状态如实标记「需管理员处理」，而不是悄悄重跑。

结果：☐ 通过 ☐ 不通过（现象：____________）

---

## T9 授权矩阵（§8.3 第 4 条）

**前置**：toml `[access] qq_user_ids = [10001, 10002]`（两个号都在白名单），`fake_behavior = "complete"`；重启。

1. 用 10001 发 `委派 demo A 的任务` → 记短 ID；
2. 用 10002 发 `任务状态 xxxxxxxx`（A 的任务）→ 回复「这不是你的任务，无法操作。」；
3. 用 10002 发 `取消任务 xxxxxxxx` → 同样拒绝；
4. 用 10002 发 `任务结果 xxxxxxxx` → 拒绝；
5. **未加白的用户**：用第三个号（不在 qq_user_ids）发 `委派 demo 越权` →
   回复 `未能受理委派：user_not_allowed: 该用户未获委派授权`，且**不产生任何任务**
   （任务库 count 不变）；
6. WebUI 管理员登录 → 能看到全部任务（不受 requester 限制）。

结果：☐ 通过 ☐ 不通过（现象：____________）

---

## T10 配额（§6.13 [limits]）

**前置**：toml `fake_behavior = "hang"`、`per_user_active = 1`；重启。

1. 用 10001 发 `委派 demo 占住配额`（hang，不结束）；
2. 再发 `委派 demo 第二个任务` → 回复
   `未能受理委派：该用户已有 1 个进行中任务（上限 1）`；
3. `取消任务` 释放第一个任务后再发 → 受理成功。

结果：☐ 通过 ☐ 不通过（现象：____________）

---

## T11 Codex fail-closed（M0 未过门禁的预期行为）

**前置**：toml 增加一段（不要动 demo）：

```toml
[backends.codex_local]
type = "codex"
enabled = true
```

重启后：

1. 发送 `委派 codex_local 做点什么` → **受理成功**（返回 ack，短 ID）；
2. 数秒后收到失败 final；`任务状态` 显示失败；
3. 日志/结果错误码为 `backend_probe_failed`，原因含
   「openai-codex SDK 未安装」或「未找到 Codex 可执行文件」（取决于本机是否装了 codex CLI）；
4. **关键**：任务明确失败，绝不静默换到 demo 后端执行。

**预期**：未通过 M0 门禁的 Codex 后端只禁用自己，不污染其他链路。测完可把该段 `enabled = false`。

结果：☐ 通过 ☐ 不通过（现象：____________）

---

## T12 自动委派灰度（M3，auto 模式）

**前置**：toml `fake_behavior = "complete"`；`.env` 加 `COMETA_DELEGATION_MODE=auto`；重启。

1. 发送 `帮我实现一个新的缓存模块，要求支持过期时间` → **自动**收到 ack（无需「委派」命令）；
2. 发送 `今天天气不错哈哈` → 普通聊天回复，**不**产生任务；
3. 发送 `帮我实现一个新的缓存模块，要求支持过期时间` 后马上再发普通消息 →
   普通消息走正常聊天（已受理的任务互不影响）；
4. 测完把 `.env` 改回 `COMETA_DELEGATION_MODE=explicit`（或删除）并重启。

**预期**：auto 模式只对明确的编码/调研类请求委派，闲聊零误触发。主动插话路径永不委派（该分支由自动化测试覆盖，手动难以触发）。

结果：☐ 通过 ☐ 不通过（现象：____________）

---

## T13 投递故障与 delivery_unknown（§6.5/§6.11）

**前置**：toml `fake_behavior = "complete"`；**停止 NapCat**（或断开 OneBot 连接）；重启 Bot。

1. Bot 起来后（QQ 已断），通过 **WebUI** 提交一个任务（QQ 发不了消息）；
2. 任务在后台正常执行完成（看日志 `notification … 已投递` 或失败告警）；
3. 观察日志：ack 发送失败 → `ack 发送失败（结果未知，不自动重发）` 或泵侧
   `投递结果未知` / 退避告警；
4. **恢复 NapCat**，等 2 分钟 → **不会**突然收到迟到重发（delivery_unknown 是终态）；
5. 只读核对：`sqlite3 tasks.db "select kind,state,error from notifications where state='delivery_unknown'"` → 有行；
6. 此后通过 QQ 发 `任务结果 <短ID>`（任务库还在）→ 仍能取回结果。

**预期**：平台调用失败的结果**不自动重发**（防刷屏），但结果本身可随时查询取回。

结果：☐ 通过 ☐ 不通过（现象：____________）

---

## T14 优雅关闭与进程清理（§6.8）

**前置**：toml `fake_behavior = "hang"`；任务运行中。

1. 记下当前 python 进程数（Windows：`tasklist | find /c "python"`）；
2. Ctrl+C / `deploy stop` 停止 Bot；
3. 控制台出现 `worker 关闭：请求中断 N 个在途任务`，随后
   `cometa worker 已停止 worker=…`；
4. 再查 python 进程数 → 恢复到任务开始前水平（无残留 worker / Agent 子进程）；
5. 再次启动 → 无「数据库被锁」类报错（WAL 正常恢复）。

**预期**：关得掉、无孤儿进程；在途任务在重启后按 T8 的矩阵呈现。

结果：☐ 通过 ☐ 不通过（现象：____________）

---

## T15 数据落点（§6.13/§9 打包安全）

1. 确认以下全部位于 **STELLA_HOME**（用户数据目录），而不是程序目录：
   - `STELLA_HOME/cometa/tasks.db`（+ `-wal`/`-shm`）；
   - `STELLA_HOME/config/cometa.toml`（你自己创建的那份）；
2. 升级演练（可选）：切换到 main 分支再切回来，确认 tasks.db 与 toml 未被覆盖/删除；
3. 备份提醒：备份时**不能只拷贝 tasks.db**——需连同 `-wal` 一起做一致性备份
   （或停机后拷贝）。

结果：☐ 通过 ☐ 不通过（现象：____________）

---

## T16 Codex 认证配置（WebUI 双路线 + 托管 codex_home）

**前置**：T0 完成；`pip install openai-codex==0.159.2 -i https://pypi.org/simple`
已装（SDK 缺失时认证按钮会报 503，属预期）；WebUI 可访问 `/#/cometa`。
注意：本项**全程不需要重启 Bot**（认证即时生效是设计行为）。

1. **初始状态**：打开「后端认证（Codex）」卡片，选中 `codex_local` → 状态徽章
   应为「未配置」，reason 指引在 WebUI 配置；
2. **自定义端点路线**：填 Base URL（如 LM Studio `http://127.0.0.1:1234`）、
   模型名、API Key →「测试」应列出模型 →「保存」→ 状态变「自定义端点」（绿），
   **无重启提示**；
3. **真实任务**：`委派 codex_local 整理一个排序算法` → probe 应通过（不再
   backend_probe_failed）；任务进入执行（端点须支持 Responses API + 函数工具，
   LM Studio 本地端点可能在真实 turn 断流——那是端点限制，不是认证问题）；
4. **空串保护**：再保存一次但 API Key 留空 → 保存成功且原 key 保留
   （`stella_credentials.json` 不变）；
5. **零回显**：卡片与接口响应任何地方都不出现 key 原文（只有「已设置」布尔）；
6. **审计**：`webui_audit.jsonl` 出现 `cometa.auth.custom_endpoint` 记录，
   detail 无 key；
7. **设备码路线**（需 OpenAI 域名可达，含代理透传）：点「发起登录」→ 出现
   verification_url + 设备码 → 浏览器完成授权 → 2s 轮询内变「登录完成」，
   状态变「ChatGPT 已登录」；bot 重启后会话丢失属预期（重新发起即可）；
8. **旧版迁移**：存在 `~/.codex/auth.json` 的机器上，未配置时卡片出黄色
   「检测到旧版登录」横幅 → 「一键迁移」→ 状态变已登录；再次迁移应被拒绝
   （托管目录已有认证）；
9. **登出**：点「登出」→ 状态回「未配置」，自定义端点配置保留
   （`config.toml`/`stella_credentials.json` 仍在）；
10. 认证数据落点检查：`STELLA_HOME/cometa/codex_home/codex_local/` 下三个文件
    （auth.json / config.toml / stella_credentials.json），`cometa.toml` 内
    **无任何凭据**，`config_hash` 不因认证操作变化（health 接口可查）。

> 注：SDK 已装但未配置认证时，T11 第 3 步的失败原因现在是
> 「未配置认证……请在 WebUI cometa 页配置」（旧文案「未找到 Codex 认证」已
> 被 T16 的托管认证取代）。

结果：☐ 通过 ☐ 不通过（现象：____________）

---

## 覆盖映射与已知边界

| 设计文档验收项 | 本清单 | 说明 |
| --- | --- | --- |
| §8.3-1 搜索任务（真实 Codex） | 暂缓 | 等 M0 门禁（SDK 固定版本 + fixture）；FakeBackend 无法模拟联网 |
| §8.3-2 编程任务（真实仓库 + 补丁产物） | 部分覆盖 | T2 用 fake 验证链路；真实编码任务与补丁产物留待 M0 后 |
| §8.3-3 重启不重复执行 | T8 | |
| §8.3-4 A/B 隔离 | T9 | |
| §8.3-5 取消与现场保留 | T3/T5 | |
| §8.3-6 WebChat reset | T7 | |
| §8.3-7 第二个真实后端 | 暂缓 | M4 |
| §13 产物可获取 | T6（部分） | 下载链路自动化已覆盖；端到端附件留待真实后端 + NapCat 拓扑验证 |
| §13 QQ 附件交付 | 暂缓 | 依赖真实文件产物与 NapCat 共享/上传拓扑 |

## 已知实现边界（测试时不要误报为缺陷）

1. `fake_behavior` 是本分支为人工验收新增的 **TOML 扩展键**，只对 `type="fake"` 合法；配置错误会在启动时直接拒绝（TOML 校验 fail-closed）。
2. 审批（approval 类请求）在 Fake 预设里以「输入」形态出现；「仅管理员可答审批」由自动化覆盖（tests/cometa/test_service.py）。
3. 超时终态显示为「超时」，其结果行的 outcome 字段是 cancelled（方案 §6.2 的 timed_out 语义；摘要文案带「到达墙钟期限」）。
4. WebChat 聊天流（#/chat）暂不提供委派入口——WebUI 的委派入口在 #/cometa 页（POST /tasks）；聊天页 reset 不影响任务（T7）。
5. delivery_unknown 后恢复网络**不会**自动重投——这是设计行为（防刷屏），结果通过任务查询取回。
