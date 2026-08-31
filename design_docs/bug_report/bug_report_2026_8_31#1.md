# 记忆模块缺陷分析：主动追问复读 + 时效性记忆被当作长期记忆

日期：2026-08-31
分析范围：`memory/` 记忆链路（整合 → 候选 → 晋升 → 主动验证 → 衰减）
状态：已定位，P0 修复见文末

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

| 优先级 | 修复项 | 位置 |
|---|---|---|
| **P0** | consolidation_prompt 补 `importance` 的定义与取值指引（照 extraction_prompt 的写法）；consolidator 给非 0 兜底，否则库中现存候选仍然卡死 | `memory/consolidation_prompt.py`、`memory/consolidator.py` |
| **P0** | verify 分支排除 `last_asked_candidate_id` | `memory/proactive_target.py` |
| P1 | `_fetch_observing_candidate` 排除 EVENT/PLAN 等时效型，或给它们单独的短 TTL | `memory/proactive_target.py` |
| P1 | 候选按类型设 TTL，EVENT 不应沿用 30 天 | `memory/memory_manager.py`、`config/settings.py` |
| P2 | 回应判定改为「窗口内是否 @ 了 Bot / 回复了那条消息」 | `stella_project/plugins/bot_main/ai_gateway.py` |
| P2 | 明确 `last_accessed_at` 语义：要么检索时刷新（则 decay 改用 `created_at`），要么改名 | `memory/retrieval_v2.py`、`memory/compressor.py` |

### 设计教训

1. **prompt 模板里的字面量会被模型当作答案照抄。** JSON 示例中的占位值必须与「要求」段落的字段说明一一对应，缺一项就等于给了一个默认答案。
2. **闸门的检查顺序即优先级。** 把最不可靠的指标（LLM 自评的 importance）放在第一道硬门槛，等于让它一票否决所有其他证据——这与 `docs/memory-system.md:114` 「importance 不单独构成晋升依据」的设计意图正好相反：它现在不能单独让候选**通过**，却能单独让候选**永久失败**。
3. **写入而不读取的状态字段是沉默的缺陷。** `last_asked_candidate_id` 写得很完整，连注释和文档都写了，唯独没有消费方。这类缺陷不会报错，只会表现为行为不符合文档。
