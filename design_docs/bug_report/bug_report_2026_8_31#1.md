# 记忆模块缺陷分析：主动追问复读 + 时效性记忆被当作长期记忆

日期：2026-08-31
分析范围：`memory/` 记忆链路（整合 → 候选 → 晋升 → 主动验证 → 衰减）
状态：P0、P1、P2 已修复并落地（见 §7）；§4.c 与 §4.e 仍未修复

---

## 0. 现象

用户报告两个可观察现象：

1. **Stella 反复问同一个人同一个问题**（基于该用户的事实记忆）。
2. **强时效性信息被当成长期记忆保存**。例：某天群聊有人说「听到地震预警」，此后几天 Stella 反复就此询问该用户。

结论：**两个现象共用同一条根因链**。核心是整合 prompt 漏定义一个字段导致的晋升死锁，叠加一处「写了但没人读」的去重字段；时效性问题则是整条链路对记忆类型完全无感所致。

---

## 1. 根因 1：整合 prompt 从未定义 `importance`，候选一律以 0.0 落库，被晋升闸门第一道门槛永久挡死

### 事实

`memory/consolidation_prompt.py:125` 的候选结构模板包含 `"importance": 0.0`，但整篇「要求」清单对 `confidence`、`usage_tags`、`visibility`、`behavior_rule`、`evidence`、`content`、`user_id` 都有明确解释，**唯独 `importance` 一个字都没写**。

全文件 grep 确认：`importance` 只出现一次，就是模板里那个字面量 `0.0`。

模型照抄 `0.0`。`memory/consolidator.py:1126` 的兜底同样是 0：

```python
importance = float(c.get("importance", 0.0) or 0.0)
```

而 `memory/memory_manager.py:230` 的 `_decide_promotion`，**第一道检查就是 importance 下限**，位置在读取 confidence 之前：

```python
if imp < MEMORY_PROMOTE_MIN_IMPORTANCE:      # 默认 0.3
    return False, f"重要度不足（imp={imp:.2f} < {MEMORY_PROMOTE_MIN_IMPORTANCE}）"
```

于是这类候选**无论置信度多高、被确认多少次，都永远无法晋升**，只能反复回到 OBSERVING。

### 线上库实证（`memory/agent_memory.db`，2026-08-31 采样）

```
cb69d868… user=3644282359 FACT imp=0.0 conf=0.9 occ=1 OBSERVING 「居住地附近主要种植甘蔗、水稻和水果，很少种玉米。」
89adaecc… user=3644282359 FACT imp=0.0 conf=0.7 occ=1 OBSERVING 「在放假期间，对知识的记忆会衰退。」
```

两条卡死的候选 `importance` 都精确等于 `0.0`（模板字面量）。

对照两条成功晋升的 CONFIRMED 记录，`importance` 分别是 `0.5` / `0.8` —— 说明模型**偶尔**会自行填写，填了就过，没填就死。这解释了为什么问题是间歇性的、不易复现。

### 为什么 EXTRACT 路径没有这个问题

`memory/extraction_prompt.py:66,71` 的 few-shot 示例带有 `"importance": 0.6` / `0.5`，模型有样例可循。**只有 CONSOLIDATION 路径漏了这个字段的说明。**

---

## 2. 根因 2：`last_asked_candidate_id` 写了，但从来没有人读

`record_at()`（`memory/proactive_state.py:77-98`）把候选 id 存进 `proactive_state.last_asked_candidate_id`。

全仓 grep 结果：该字段只在**写入**与**原样读进 dict** 两处出现，**没有任何一处过滤条件用到它**。

`_fetch_observing_candidate()`（`memory/proactive_target.py:117-142`）的 SQL 只按 space + user + status + 置信度区间排序取 Top 1，不排除上次问过的候选：

```sql
SELECT id, content, type, confidence FROM memory_candidates
WHERE group_shared_space = ? AND user_id = ? AND status = 'OBSERVING'
  AND confidence >= ? AND confidence < ? AND content != ''
ORDER BY confidence DESC LIMIT 1
```

对比同一文件的冷启动分支（`memory/proactive_target.py:246-250`）**是有**去重的：

```python
if t != state["last_asked_topic"] and not _topic_covered(t, known)
```

verify 分支漏了这一层。

`docs/memory-system.md:270` 承诺的「状态落库 | 重启后不会重复追问同一个人同一件事」，**在代码里没有实现**。

### 实证

`proactive_state` 中 user `3644282359` 那行：`last_asked_candidate_id = '89adaecc…'`、`at_count_today = 2`，正是上面那条卡死的候选。

---

## 3. 现象 1 的完整闭环

```
候选 imp=0.0
  → _decide_promotion 第一道门槛拒绝 → 永不晋升
  → 停在 OBSERVING（最长 MEMORY_CANDIDATE_MAX_OBSERVING_DAYS = 30 天）
  → 落在验证窗口 [LOW-0.2, HIGH) = [0.4, 0.85) 内
  → 每次 pick_target 都命中它（无 last_asked 排除）
  → 问同一句
  → 用户回答
  → consolidator.py:1182-1198 强化：conf +0.12、status 回 NEW
     但 importance = max(0.0, 0.0) = 0.0
  → 再次被第一道门槛打回 OBSERVING
  → 回到第 4 步
```

### 这条闭环推翻了一个既有设计假设

`docs/memory-system.md:274-278` 记载的「问答关联采用隐式方案」：

> 用户的回答本身是 `AT_MENTION`，经整合会生成或强化同内容候选，`occurrence_count` +1 后跨过门槛。

这个假设**被 importance 门槛证伪了**：门槛在 occurrence / source_kind 判定之前执行，`occurrence_count` 无论累积到多少都跨不过去。

### 循环的唯一"出口"是一个副作用

conf 被 `+MEMORY_CANDIDATE_REOCCURRENCE_BONUS(0.12)` 累积到 ≥ 0.85 后，候选掉出验证窗口上界，于是**停止被追问**，然后静默卡在 OBSERVING 直到 30 天过期被标 REJECTED。

`cb69d868` 那条 conf=0.9 已经处于这个状态——它既晋升不了，也不会再被问，纯粹占着候选表。

---

## 4. 现象 2 的原因：整条链路对「时效性」完全无感

按发生顺序：

### a. 候选层没有任何 TTL 概念

`MEMORY_CANDIDATE_MAX_OBSERVING_DAYS = 30` 对**所有类型统一**，EVENT 与 FACT 一视同仁。「听到地震预警」这类候选会在池子里躺 30 天。

### b. `_fetch_observing_candidate` 不按 type 过滤

（`memory/proactive_target.py:129-135`）一个已经过去的 EVENT，和一条稳定 FACT 一样有资格被「主动验证」。

但**验证事件在语义上就是错的**：「你住在 X 吗」隔一周问仍然成立；「你听到地震预警了吗」隔一周问就是荒谬的。叠加根因 2 的无去重，就产生了「之后几天反复询问」。

### c. 即使晋升，EVENT 生命周期也长达 60 天

`config/settings.py:459-467`：

```python
MEMORY_DECAY_DAYS = {
    "FACT": 730.0, "STYLE": 365.0,
    "PREFERENCE": 180.0, "RELATION": 180.0,
    "EVENT": 60.0, "PLAN": 60.0,
    "GROUP_CONTEXT": 30.0,
}
```

一条地震预警要在检索池里待两个月。

### d. 衰减锚点 `last_accessed_at` 语义与文档不符，且存在自持循环

`_apply_decay`（`memory/compressor.py:299-317`）以 `last_accessed_at` 为准。但**检索路径从不刷新这个字段**——`UPDATE memories` 只出现在 `compressor.py` 与 `memory_manager.py`，`retriever.py` / `retrieval_v2.py` 一次都没有。

两个后果：

1. `docs/memory-system.md:147` 声称的「用 `last_accessed_at` 而非 `created_at`：一条老但仍被频繁调用的记忆比一条新却从未被用过的更有价值」，**在实际行为上不成立**。该字段实际语义是「最后一次被确认/合并的时间」。

2. 更糟的是反向效应：
   ```
   Stella 追问 → 用户回应 → 候选强化 → 合并进记忆
   → memory_manager.py:441 刷新 last_accessed_at → 衰减时钟被重置
   ```
   **越是被反复追问的记忆越不会衰减**，形成自持循环。

### e. 排序阶段的时效衰减显式忽略类型

`memory/policy.py:585-598`：

```python
def _recency_factor(reference, age_days, mem_type=""):
    _ = mem_type  # 保留入参以兼容旧调用；衰减不区分类型
    tau_days = 30.0
    return max(0.0, min(1.0, math.exp(-max(0.0, age_days) / tau_days)))
```

EVENT 与 FACT 的时效衰减曲线完全相同，旧事件不会因为「它是事件」而在排序中被压下去。

---

## 5. 次要问题（本次顺带发现，非本报告主线）

### 5.1 退避机制形同虚设

`_check_reply_later`（`stella_project/plugins/bot_main/ai_gateway.py:629-650`）判定「是否获得回应」的标准是「该用户在 `PROACTIVE_REPLY_WINDOW_SECONDS`(300s) 内**在群里说过任何话**」，而不是「回复了 Bot」：

```python
last = get_proactive().last_spoke_ts(group_id, user_id)
replied = last is not None and last > asked_at
```

活跃群里这几乎恒为真 → `consecutive_no_reply` 一直被清零 → `PROACTIVE_MAX_NO_REPLY = 2` 的自动退避基本不会触发。

实证：`proactive_state` 12 行中 11 行 `consecutive_no_reply = 0`。

### 5.2 `last_asked_topic` 被存成了字符串 `'None'`

库中 5 行如此。这会让冷启动去重 `t != state["last_asked_topic"]` 永远匹配不上真实话题，导致冷启动话题也会重复。

`ProactiveTarget.topic` 的声明默认值是 `""`，不该出现 `'None'`，需单独排查是哪条路径把 `None` 字符串化了。

### 5.3 测试盲区

`tests/test_proactive_at_flow.py` / `tests/test_proactive_state.py` 覆盖了配额、跨日归零、退避计数，但**没有任何一条断言「同一候选不会被连续追问两次」**，也没有断言「候选 importance 缺省不应导致永久 OBSERVING」。这是两个缺陷长期未被发现的直接原因。

---

## 6. 修复优先级

| 优先级 | 修复项 | 位置 | 状态 |
|---|---|---|---|
| **P0** | consolidation_prompt 补 `importance` 的定义与取值指引（照 extraction_prompt 的写法）；consolidator 给非 0 兜底，否则库中现存候选仍然卡死 | `memory/consolidation_prompt.py`、`memory/consolidator.py` | ✅ 已修 |
| **P0** | verify 分支排除 `last_asked_candidate_id` | `memory/proactive_target.py` | ✅ 已修 |
| P1 | `_fetch_observing_candidate` 排除 EVENT/PLAN 等时效型，或给它们单独的短 TTL | `memory/proactive_target.py` | ✅ 已修（两者都做了） |
| P1 | 候选按类型设 TTL，EVENT 不应沿用 30 天 | `memory/memory_manager.py`、`config/settings.py` | ✅ 已修 |
| P2 | 回应判定改为「窗口内是否 @ 了 Bot / 回复了那条消息」 | `stella_project/plugins/bot_main/ai_gateway.py` | ✅ 已修 |
| P2 | 明确 `last_accessed_at` 语义：要么检索时刷新（则 decay 改用 `created_at`），要么改名 | `memory/retrieval_v2.py`、`memory/compressor.py` | ✅ 已修（decay 锚点取 `last_confirmed_at`，不是 `created_at`，理由见 §7） |

### 设计教训

1. **prompt 模板里的字面量会被模型当作答案照抄。** JSON 示例中的占位值必须与「要求」段落的字段说明一一对应，缺一项就等于给了一个默认答案。
2. **闸门的检查顺序即优先级。** 把最不可靠的指标（LLM 自评的 importance）放在第一道硬门槛，等于让它一票否决所有其他证据——这与 `docs/memory-system.md:114` 「importance 不单独构成晋升依据」的设计意图正好相反：它现在不能单独让候选**通过**，却能单独让候选**永久失败**。
3. **写入而不读取的状态字段是沉默的缺陷。** `last_asked_candidate_id` 写得很完整，连注释和文档都写了，唯独没有消费方。这类缺陷不会报错，只会表现为行为不符合文档。

---

## 7. 落地记录

### P0（2026-08-31）

| 改动 | 位置 |
|---|---|
| `importance` 补全定义、取值区间（0.7-1.0 / 0.1-0.4）、「与 confidence 无关」、「不要照抄示例值」 | `memory/consolidation_prompt.py`、`memory/extraction_prompt.py` |
| 落库兜底：模型给 0 时回填 `MEMORY_CANDIDATE_DEFAULT_IMPORTANCE`，模型给了值则原样保留 | `memory/consolidator.py`、`config/settings.py` |
| 存量解锁：v12 迁移回填 `importance <= 0` 的候选（幂等） | `memory/migrations.py`、`memory/schema.py` |
| verify 分支排除 `last_asked_candidate_id` | `memory/proactive_target.py` |

护栏：`tests/test_memory_promotion_deadlock.py`。

### P1（2026-08-31）

**候选 TTL 按类型分档。** 新增 `MEMORY_CANDIDATE_MAX_OBSERVING_DAYS_BY_TYPE = {"EVENT": 3.0, "GROUP_CONTEXT": 7.0, "PLAN": 14.0}`（`config/settings.py`），未列出的类型沿用全局 30 天。淘汰逻辑（`memory/memory_manager.py`）拆成三块：`_observing_ttl_days()` 负责查档、`_reject_stale_candidates()` 负责分类型遍历、`_reject_stale_batch()` 负责执行一次 UPDATE。

几个刻意的取舍：

- **代码级常量而非 `.env` 键**，与 `MEMORY_DECAY_DAYS` 同例。「这类信息多久之后不再值得等第二次证据」是语义判断，不是部署参数。
- **分类型逐条 UPDATE 而不是一条 CASE。** 超期淘汰是完全不可见的后台动作，按类型分行记日志才能事后看出淘汰的是哪一类；可审计性优先于少一次 UPDATE。
- **脏 `type` 一律走全局值。** SQL 侧用 `UPPER(COALESCE(type, 'FACT'))` 归一，所以类型缺失不会让候选永久豁免淘汰；查档侧则宁可多留几天，不因一个拼错的类型名提前丢弃候选。
- **不需要 schema 迁移。** `_reject_stale_candidates` 在每轮 `process_new_candidates` 开头执行，库里已经超期的 EVENT 会在下一轮自动被扫掉。

**主动验证排除时效型。** 新增 `PROACTIVE_VERIFY_EXCLUDE_TYPES`（默认 `EVENT,PLAN,GROUP_CONTEXT`），`_fetch_observing_candidate` 的 SQL 加一段 `NOT IN` 过滤（`memory/proactive_target.py`）。

- **这个做成了 `.env` 键**，与 `PROACTIVE_AT_EXCLUDE_USERS` 同例——运维想重新允许追问某一类，不该去改代码。
- **留空 = 所有类型都可验证。** `NOT IN ()` 在 SQLite 里是语法错误，所以空配置必须返回空片段，不能顺手塞一个默认类型进去。
- **排除的只是追问这一条路径。** 这些候选照常落库，也照常可以凭 `AT_MENTION` 单次晋升或靠被动复现晋升——不为它们花配额，不等于不记它们。
- SQL 文本里只有占位符个数，类型名一律参数绑定。
- `GROUP_CONTEXT` 另有一层理由：它归属于群而不是人，向某个人验证群层面的事本身就错位。

护栏：`tests/test_time_sensitive_candidates.py`（25 例）。用例**成对出现**——一条断言时效型被压下去，一条反向断言稳定型没被连带压下去。只测前者的话，「一律不追问」「TTL 一律 3 天」也能通过，而那会把 `FACT` 的采集一起毁掉。阈值全部从 `_observing_ttl_days` / 配置反推，不写死 3/14/7/30。

### P2-1（2026-08-31）：回应判定改为只认「对 Bot 说话」

§5.1 的问题是判据错位：`_check_reply_later` 读的是 `last_spoke_ts`（「群里有没有人在说话」），在活跃群里几乎恒为真，于是 `consecutive_no_reply` 一直被清零，`PROACTIVE_MAX_NO_REPLY` 的自动退避从来没有真正触发过。

改法是新开一条时间线而不是改写旧的：`memory/proactive.py` 增加 `_last_tome` / `record_tome()` / `last_tome_ts()`，与 `record_message` / `last_spoke_ts` 并列。入库侧（`ai_gateway.record_group_chat`）在 `source_kind == "AT_MENTION"` 时两者都记——OneBot 的 `is_tome()` 已经覆盖 @ Bot、回复 Bot 的消息、以昵称呼叫三种情况，正是这里要的正信号。活跃度统计仍然要算上所有消息，所以 `record_message` 不能被取代。

一个必须同时做掉的副作用：**判据收紧会把纯文本接话的人误判为「没回应」**，而 `consecutive_no_reply` 没有任何按时间的自然衰减，攒满 `PROACTIVE_MAX_NO_REPLY` 就再没有归零的机会——这个人会被永久踢出验证池。既然「主动 @ 是主要的记忆来源」（见 `docs/memory-system.md`），把人永久排除的代价远高于多问一次。因此新增 `proactive_state.reset_no_reply()`，在该用户任意一次「对 Bot 说话」时归零，让退避自愈。

护栏：`tests/test_reply_detection.py`（9 例）。三段成对断言——纯文本发言不得算作回应／`record_tome` 之后必须算；归零只影响目标用户、且归零之后计数仍能重新累积；退避先按预期触发、再被一次「对 Bot 说话」解除。阈值取自 `PROACTIVE_MAX_NO_REPLY` 而非写死。`tests/test_proactive_at_flow.py` 里那条名字带 `detects_reply` 的旧用例同步改名为 `tracks_any_message`，并补一条反向断言（`last_tome_ts` 此时应为 `None`）——名字留着会让人以为回应检测仍由它守着。

### P2-2（2026-08-31）：拆开 `last_accessed_at` 与 `last_confirmed_at` 的语义

§4.d 的现象是「文档说的和代码做的不一致」，但根因是**两件事被同一个列表达**：检索路径从不写 `last_accessed_at`，只有候选强化与压缩合并写，而它们同时也写 `last_confirmed_at`。两列长期同步变动，于是「最后一次被用到」和「最后一次被证实」是同一个数。

落地后的分工：

| 时间戳 | 含义 | 写 | 读 |
|---|---|---|---|
| `last_confirmed_at` | 这条事实最后一次被观察到 | 候选强化（`memory_manager._merge_into_memory`）、压缩合并（`compressor._merge_duplicate_memories`） | `policy._mem_timestamp`（排序新鲜度维）、`compressor._apply_decay`（类型衰减）、候选池取数与相似记忆归并的 `ORDER BY` |
| `last_accessed_at` | 这条记忆最后一次真正进了 Prompt | `retrieval_v2._touch_accessed` | `memory_manager._quota_score`（配额竞争的 recency 项）、`compressor._archive_low_value_memories`（低价值归档） |

**与报告原文的偏离，需要明确记录：decay 锚点取 `last_confirmed_at` 而不是 §6 表格里写的 `created_at`。** `created_at` 会把再确认的证据整个丢掉——一条 `FACT` 上周才被第三个人重复讲过一次，用 `created_at` 算它照样是「两年前的老记忆」。类型生命周期问的是「这条事实还新鲜吗」，答案应该由最后一次观察决定。

**执行顺序是这次改动的关键。** 直接给检索加刷新，会立刻在三个地方制造「富者愈富」：`policy._mem_timestamp` 的新鲜度维、候选池的 `ORDER BY last_accessed_at DESC`、以及 `_apply_decay` 的衰减时钟——取用一次就把时钟重置，越被反复引用的记忆越不会过期。所以先把所有「证据新鲜度」读取方改指 `last_confirmed_at`，再打开检索侧的记账。因为两列此前一直同步写入，这一轮重指向在今天的数据上是**行为无变化**的，这正是随后加刷新时不会引入回归的原因。

几个刻意的取舍：

- **不做 schema 迁移。** 两列一直同步写，所以库里没有一行数据是错的——错的只有读取方。所有新增读取都用 `COALESCE(last_confirmed_at, last_accessed_at)`，既覆盖存量 NULL，也覆盖只有 `last_accessed_at` 一列的旧库与 benchmark 夹具。
- **`_fetch_candidates_legacy` 刻意不改。** 走到那个回退分支就说明主查询的列缺失，`last_confirmed_at` 很可能也不存在，再引用它会把最后一条退路一起打空。这条退路本身也不是无损的：它没有 Visibility 过滤，静默退化进去是真实的正确性损失——`tests/test_embeddings.py` 的夹具当时就因为缺 `last_confirmed_at` 而整体落到回退路径，两例随即失败（已给夹具补上该列）。
- **`_create_memory` 仍然给 `last_accessed_at` 写建库时间。** 语义上新记忆还没被检索过，但置 NULL 会让 `_archive_low_value_memories` 的「从未访问」分支立刻归档低重要度的新记忆，等于不给宽限期。
- **两处合并只刷 `last_confirmed_at`，不再顺手刷 `last_accessed_at`。** 合并是新证据，不是被读取；一并刷会让配额竞争的 recency 项与 confirmation 项重复计同一个信号，也会让「长期未访问」的归档判定永远不成立。
- **缓存命中不记账。** 5 分钟内的重复检索不重复写库。归档与配额判定都是天粒度的，一次对话把访问时间钉在「现在」没有意义，还要为每句话付一次写库。
- **只有真正进 Prompt 的才记账**（聊天素材与行为约束两个分区都算）。若刷新整个候选池，「有没有人用得上它」就退化成「有没有被查出来过」，`_archive_low_value_memories` 会再也归档不掉任何东西。
- **不新增索引。** `idx_memories_space_status_accessed` 保持原样：`COALESCE` 本来就用不上该列的索引，而 `(group_shared_space, status)` 前缀仍然有效，当前数据量下没有必要为此重建索引。
- **`retriever.py`（v1 回退）里的行 dict 键改叫 `freshness_at`。** 同一个槽位在 `memories` 上取的是确认时间，在待废弃的 `long_term_memories` 上只有 `last_accessed_at` 可取，继续叫 `last_accessed_at` 会误导；`long_term_memories` 的两条 UNION 分支保持原样，那张表没有 `last_confirmed_at` 可 `COALESCE`。
- **benchmark 夹具把同一个值同时写进两列。** 用例里的 `last_accessed_at` 覆盖是用来测「新记忆压过旧记忆」的，而排序读的是确认时间，且访问时间会被检索刷新——只写一列会让同一用例跑第二遍时新鲜度变了。

护栏：`tests/test_access_semantics.py`（15 例），四段成对断言——进了 Prompt 的记账／被过滤掉的不记账；排序优先 `last_confirmed_at`／旧库仅有 `last_accessed_at` 时回退链仍要给出可用时间戳；过期的 `EVENT` 即使刚被取用过也照样衰减归档／生命周期内有新证据的不得被归档，同时低价值归档反过来要放过刚被取用的低重要度记忆；两处合并只前移确认时间／访问时间保持原样。

### 仍未修复

§4.c（`EVENT` / `PLAN` 晋升后 60 天生命周期）与 §4.e（`_recency_factor` 显式忽略类型）不在本轮范围内，仍记录在 `docs/memory-system.md` 的「已知限制」中。§4.d（衰减锚点语义与自持循环）已由 P2-2 解决。
