记录于2026/8/12 11：03

1.顺序我没有意见。现在确实是排查到了这个流程的巨大缺陷。按照你说的做即可。没有必要看消融实验了。
2.配额上限做成可变配置。目前暂定默认值为25条。
3.没有必要纠结那对死配置。若与改进冲突删除即可。
4.有一个更加远期的计划：让agent主动发言时概率验证目前活跃用户的记忆是否正确。这个效果要比随机接话好得多。


方向确定。我把你原则 4（主动验证）也纳进设计了——它不是远期附加功能，而是这套架构缺的最后一块，我在阶段 D 说明为什么。

先补两个我这轮读代码新发现的问题，都影响清单：

**`compressor._merge_duplicate_memories` 过滤了 group+type，但同样没过滤 user_id。** 和 `memory_manager._find_similar_memory` 是同一个 bug 的两个副本，都得修。这个更危险——它跑在周度定时任务里，会把 A、B 两人的记忆合并后把其中一条标 archived，数据不可恢复。

**`retrieval_v2._merge_similar` 也只比 type + 内容相似度**，不比 user_id。@ 回复路径已按 user_id 过滤所以安全，但主动发言路径（`include_user=None`）取的是全群记忆，会把不同人的记忆合并成一条送进 prompt。这条不写库，但会造成回复里张冠李戴。

---

# 阶段 A：修正确性 bug（先做，独立可上线）

## A1 `memory/memory_manager.py` — `_find_similar_memory` 加归属过滤

SQL 改为：

```python
        rows = cursor.execute(
            "SELECT id, content FROM memories WHERE status = 'active' "
            "AND group_id = ? AND user_id = ? AND type = ? "
            "ORDER BY last_accessed_at DESC",
            (str(candidate["group_id"]), str(candidate["user_id"]), candidate["type"]),
        ).fetchall()
```

docstring 补一句：**必须同群同用户**，否则会把 A 的候选合并进 B 的记忆（`_resolve_conflicts` 已经是对的，与之对齐）。

## A2 `memory/compressor.py` — `_merge_duplicate_memories` 加 user_id 判定

现有的跳过条件加一项：

```python
                if (
                    memory["group_id"] != other["group_id"]
                    or memory["user_id"] != other["user_id"]
                    or memory["type"] != other["type"]
                ):
                    continue
```

注释写明：跨用户合并会导致「用户 A 的事实被并入 B 的记忆并把 A 那条 archived」，不可逆。

## A3 `memory/retrieval_v2.py` — `_merge_similar` 加 user_id 判定

```python
            if (
                existing["type"] == mem["type"]
                and existing.get("user_id") == mem.get("user_id")
                and _is_similar(existing["content"], mem["content"])
            ):
```

## A4 测试

新建 `tests/test_cross_user_isolation.py`，三个用例分别覆盖 A1/A2/A3：构造两个用户内容高度相似的记忆（比如都含「喜欢玩游戏」），断言合并不发生、两条都还在、status 都是 active。这三条是回归护栏，以后不能再退。

**A 阶段跑 `python -m pytest tests -q` 通过即可 commit，不需要模型。**

---

# 阶段 B：候选强化机制（你那套「暂存→交叉验证→逐步强化」）

## B1 Schema

**`memory/schema.py`**：`SCHEMA_VERSION` 3→4；`_ADDITIVE_COLUMNS` 给 `memory_candidates` 追加三列：

- `occurrence_count INTEGER DEFAULT 1` — 该事实被独立观察到几次
- `first_seen_at DATETIME` — 首次观察时间（用于超期淘汰，不能用 created_at，那个会被 upsert 刷新）
- `source_kinds TEXT DEFAULT '["PASSIVE"]'` — 历次证据的来源集合（JSON 数组）

注意 `source_kinds` 是复数，与阶段 3 已有的单数 `source_kind` 并存：单数记「本次」，复数记「历次」。晋升时看复数。

`_INDEXES` 加一条 `(group_id, user_id, type, status)` 复合索引到 `memory_candidates`——B2 的相似查询会高频走它。

**`consolidator._ensure_common_tables`** 与 **`memory_manager._ensure_tables`** 的 `memory_candidates` DDL 同步加这三列。

## B2 `memory/consolidator.py` — `_write_memory_candidates` 改为 upsert 语义

在现有的白名单校验之后、validate_candidate 之前，插入查找逻辑：查 `memory_candidates` 中同 group + 同 user + 同 type 且 `status IN ('NEW','OBSERVING')` 的行，用 `MemoryManager._is_similar` 比内容。命中则更新而非插入：

- `occurrence_count += 1`
- `confidence = min(1.0, max(旧, 新) + MEMORY_CANDIDATE_REOCCURRENCE_BONUS)`
- `content` 取更完整的一方（复用 `_merge_content` 的逻辑，别新写一份）
- `evidence` 追加新证据（用 `；` 分隔，截断到合理长度）
- `source_message_ids` 并集，`source_kinds` 并集
- `status` 若为 OBSERVING 则重置为 `NEW`，让它重新参与本轮晋升评估
- `first_seen_at` 保持不变

**关键**：`_is_similar` 现在是 `MemoryManager` 的实例方法，consolidator 里调它需要构造实例。建议把 `_is_similar` / `_normalize_text` / `_jaccard_similarity` / `_merge_content` 这四个提到 `memory/text_similarity.py` 做模块级函数，三处（consolidator、memory_manager、compressor）都 import 它。现在这套逻辑在 `memory_manager`、`compressor`、`retrieval_v2` 里各有一份近乎相同的副本，A2/A3 那个 bug 就是抄漏导致的。这次顺手收敛，否则以后还会漏。

## B3 `config/settings.py` + `.env.example`

```python
# ---------- 候选强化与晋升（Gate 1 分档） ----------
# 同一事实被再次观察到时的置信度增益。「交叉验证」的核心：单次陈述不足以晋升，
# 复现才是证据。设计上让 0.5 起步的候选经 2~3 次复现后跨过晋升线。
MEMORY_CANDIDATE_REOCCURRENCE_BONUS = _env_float("MEMORY_CANDIDATE_REOCCURRENCE_BONUS", 0.12)
# 候选在 OBSERVING 停留的最长天数，超期未获新证据即标记 REJECTED（不删除，保留供审计）
MEMORY_CANDIDATE_MAX_OBSERVING_DAYS = _env_int("MEMORY_CANDIDATE_MAX_OBSERVING_DAYS", 30)
# 晋升所需的最低独立观察次数（PASSIVE 来源）。AT_MENTION 来源单次即可（见下）
MEMORY_PROMOTE_MIN_OCCURRENCE_PASSIVE = _env_int("MEMORY_PROMOTE_MIN_OCCURRENCE_PASSIVE", 2)
# AT_MENTION（用户直接对 Bot 说）是高密度证据，单次即可晋升
MEMORY_PROMOTE_AT_MENTION_SINGLE_SHOT = _env("MEMORY_PROMOTE_AT_MENTION_SINGLE_SHOT", "true").lower() in ("true", "1", "yes")

# ---------- 每用户记忆配额（宁缺毋滥的硬约束） ----------
# 单用户在单群的 active 记忆上限。到顶后新记忆必须挤掉现存最弱的一条（转 archived）
MEMORY_USER_QUOTA = _env_int("MEMORY_USER_QUOTA", 25)
# 配额淘汰的排序权重：得分最低者先被挤掉
MEMORY_QUOTA_W_IMPORTANCE = _env_float("MEMORY_QUOTA_W_IMPORTANCE", 0.4)
MEMORY_QUOTA_W_CONFIRMATION = _env_float("MEMORY_QUOTA_W_CONFIRMATION", 0.3)
MEMORY_QUOTA_W_RECENCY = _env_float("MEMORY_QUOTA_W_RECENCY", 0.3)
```

那对死配置（`MEMORY_CONFIRM_HIGH_CONFIDENCE` / `MEMORY_OBSERVE_LOW_CONFIDENCE`）在 B4 里接线使用，不删——它们的语义正是我们要的分档，只是当初没接上。

## B4 `memory/memory_manager.py` — Gate 1 改真正分档 + 超期淘汰

`process_new_candidates` 的判定逻辑替换为三档，并把当前那个 `and` 语义的双阈值删掉：

```
conf >= MEMORY_CONFIRM_HIGH_CONFIDENCE (0.85)          → 直接晋升
conf >= MEMORY_OBSERVE_LOW_CONFIDENCE (0.6)            → 看证据充分度：
    source_kinds 含 AT_MENTION 且开关开   → 晋升
    occurrence_count >= MIN_OCCURRENCE_PASSIVE (2)     → 晋升
    否则                                               → OBSERVING
conf < MEMORY_OBSERVE_LOW_CONFIDENCE                   → OBSERVING（等复现）
```

SELECT 要加上 `occurrence_count, source_kinds, first_seen_at` 三列。

同时在循环前加超期清理：`first_seen_at` 早于 `MAX_OBSERVING_DAYS` 且仍为 OBSERVING 的候选批量置 `REJECTED`，记日志条数。

OBSERVING 的日志带上 `occurrence_count` 与 `conf`，这样你能直接看出「哪些事实在被反复提及却晋升不了」——这是调阈值的唯一依据。

## B5 每用户配额

`memory_manager.py` 新增 `_enforce_user_quota(cursor, group_id, user_id)`，在 `_create_memory` 成功之后调用：

统计该 group+user 的 active 条数，超过 `MEMORY_USER_QUOTA` 则按 `w_imp*importance + w_conf*min(1, confirmation_count/3) + w_rec*recency` 升序，把最弱的若干条置 `archived`（不删），每条记一行日志说明被谁挤掉。

**这一步会改变已有数据状态且不可逆**，所以：

- 首次上线前手动备份：`python -m memory.schema --backup` 不行（已存在则跳过），需要你手动复制 `memory/agent_memory.db` 到别处
- `_enforce_user_quota` 里加一个 `dry_run` 参数，并在 `config` 加 `MEMORY_QUOTA_ENFORCE`（默认 **false**）。先跑一段只记日志不执行，看它想淘汰什么，确认合理再打开。这是我唯一坚持要加开关的地方——25 条的配额在你的库上会淘汰什么，现在谁都不知道。

## B6 测试

`tests/test_candidate_reinforcement.py`：

1. 同一事实写两次 → 候选表一行、`occurrence_count=2`、confidence 递增、status 回到 NEW
2. 内容不相似的两条 → 两行，互不干扰
3. 不同 user 的相同内容 → 两行（不能因为内容像就并到一起）
4. conf 0.5 + occurrence 1 → OBSERVING；再复现一次跨过 0.6 且 occurrence=2 → 晋升
5. conf 0.5 + `source_kinds` 含 AT_MENTION → 单次晋升
6. 超期 OBSERVING → REJECTED
7. 配额：写第 26 条时最弱的被 archived、总数回到 25；`MEMORY_QUOTA_ENFORCE=false` 时不淘汰只记日志

---

# 阶段 C：放宽捕获层

B 全绿并且你在真实库上观察过 OBSERVING 队列之后再做。

`memory/consolidation_prompt.py`：删三条负例与 `confidence <0.7 不要输出这条候选`；**保留**「只输出这些，不要补充推断」「需要推测才能得出结论的不要」「user_id 必须是实际发送者」——这三条防的是编造，与放宽无关。把判据句加上（描述谁，而不是句子里有没有产品名）。`memory_candidates 允许为空数组` 保留：没有就是没有。

`tests/test_consolidation_prompt.py` 按新结构重写：删掉对负例与 0.7 门槛的断言，新增对三条防编造条款的断言。

验证口径同步换：`--positive --repeat 3` 看召回；`--limit 20` 不再看空输出率，改看**编造率**——人工检查产出的候选是否都有出处、归属是否正确。空输出率下降是预期的。

---

# 阶段 D：主动验证（你的原则 4）

这不是远期功能，它是这套架构的闭环。B 建立了 OBSERVING 队列——一堆「疑似为真、证据不足」的候选，而被动等待复现在低频群里可能永远等不到。主动验证是**主动获取证据**，把 OBSERVING 的出口从「等」变成「问」。

而且它同时解决主动发言的老问题：现在的主动发言是「随机找个切入口说句话」，靠 `PROACTIVE_MAX_PROB` 控频；改成「以一定概率挑一条当前活跃用户的 OBSERVING 候选，自然地把它问出来」，发言有了目的，回答直接构成证据。

需要的东西大部分已经有了：`proactive.py` 有活跃度判断和冷却，`ai_gateway._proactive_speak_for_group` 有完整链路，`source_kind=AT_MENTION` 能把用户的回答识别为高密度证据。缺的是：

- 一个「取该群近期活跃用户的 OBSERVING 候选」的查询
- 主动发言 prompt 的一个变体（把候选内容变成一句自然的确认，而不是审问）
- 一个「待验证候选 → 用户回答」的关联机制，让下一轮整合知道这条回答是在回答哪个候选。这是唯一的新结构，建议在 `memory_candidates` 加 `pending_verification_at`，并在群上下文里保留「上次问了什么」

这块我不写细清单，因为它依赖 B 跑起来之后 OBSERVING 队列的实际形态——队列里是什么、有多少、多久积一条，决定了验证频率和挑选策略。等 B 有数据我们再设计。

现在建议做一件事：**在 `design_docs/` 新建一份 `Memory Verification Loop（草案）.md`**，把你刚才那段原话和上面这几点记进去。这个想法比它看起来重要——它是从「记录型记忆」走向「主动维护型记忆」的转折，值得有独立文档，而不是埋在对话里。

---

# 建议的 commit 切分

1. A1–A4（跨用户污染修复 + 护栏测试）
2. B2 的前置：`memory/text_similarity.py` 抽取 + 三处改为 import（纯重构，测试应全绿）
3. B1 + B2 + B3 + B6 前三个用例（强化机制）
4. B4 + B6 用例 4–6（Gate 1 分档）
5. B5 + B6 用例 7（配额，默认关闭）
6. 阶段 C
7. `design_docs/Memory Verification Loop（草案）.md`

A 可以现在就开，不依赖任何未定决策。有问题随时问，改完 commit 我看 diff。