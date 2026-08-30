# Memory System

[中文](memory-system.md) | English

> Note: This version of the document was translated from the Chinese version by GPT-5.6 luna.

This document explains **why Stella's memory system is designed this way** and the specific rules for each gate. See the [architecture documentation](architecture.en.md) for the directory structure and processing flow, and the [configuration reference](configuration.en.md) for configuration options.

## Three Design Principles

### 1. Capture Broadly, Promote Strictly

Filtering should happen at the layer where data is **available, auditable, and reversible**.

In early versions, filtering was written into the consolidation prompt ("Do not output anything with confidence below 0.7" and "The following cases must return an empty array"). This caused two problems:

- Discarded information left **no trace**, so it could not be audited or used for improvement
- Rules in the prompt interfered with one another. In testing, the negative rule "discussion of third-party things (news, products, other people) should return an empty array" caused "My graphics card is an RTX5080" to be classified as "discussing a product"; only 1 out of 10 runs extracted it correctly

The division of responsibilities is now:

| Layer | Responsibility | Scale |
|---|---|---|
| **Capture layer** (consolidation prompt) | Record faithfully + strictly prohibit fabrication | Broad |
| **Promotion layer** (MemoryManager) | Confidence grading + cross-validation + quotas | Strict |

After loosening the capture layer, the consolidation prompt decreased from 3244 characters to 2515, positive-case regression improved from 0/9 to 9/9, the fabrication rate remained 0%, and the empty-output rate on real windows only decreased from 100% to 90%—loosening the rules did not mean letting everything through.

### 2. Core Idea: A User Has Few Truly Valuable Facts

"Better too little than too much" is implemented as a hard constraint rather than an attitude: long-term memory for an individual user has a quantity limit (`MEMORY_USER_QUOTA`, 25 by default), and once it is full, a new memory must displace the weakest existing one.

This keeps the total volume at the presentation layer under control, **and saves context space and generation time for locally deployed models**, naturally counteracting the growth caused by a looser capture layer.

### 3. Semantic Relevance ≠ Should Be Used

Retrieved memories must also pass three layers of filtering: mode matching, usage compatibility, and visibility. "The user does not like having their head patted" is highly related to "patting someone's head," but it **should never be brought up as a chat topic**—it can only exist as a behavioral constraint.

## Data Flow

```
group_messages          Raw messages (with source levels)
      ↓ Consolidation (CONSOLIDATION role, local small model by default; can target an online endpoint)
short_term_context      Topic summary + key messages
memory_candidates       Memory candidates (evidence can accumulate)
      ↓ Gate 1: three tiers
memories                Long-term memories
      ↓ Three-layer Policy filtering + ranking
Partitioned Prompt injection          Chat material / behavioral constraints
```

## Capture Layer: Uncertainty Allowed, Fabrication Forbidden

The consolidation prompt (`memory/consolidation_prompt.py`) does not apply hard confidence filtering, but retains three **anti-fabrication** clauses—which are unrelated to strictness and must not be removed under any circumstances:

- "Output only these items, **do not add inferences**"
- "Anything that **requires speculation to reach a conclusion** (\"they may like…\") → return an empty array"
- "`user_id` **must be the actual sender of that message**; misattribution is strictly forbidden"

The criterion for whether a piece of information is worth remembering is **"who is this sentence describing"**: a statement describing the speaker's own attributes (what equipment they own, what they can eat, where they live, what work they do) is a candidate; a statement describing a third-party thing is excluded. The presence of a product name or place name in a sentence does not by itself make it a discussion of a third party.

At the same time, the rule that "`memory_candidates` may be an empty array; returning an empty array is correct behavior" is retained—loosening capture does not mean forcing output.

`tests/test_consolidation_prompt.py` makes offline assertions about the clauses above, including reverse assertions (confirming that removed hard filters have not been written back).

### Code-Level Safety Nets

There are two mechanical safeguards beyond the prompt:

- **Sender allowlist**: candidates whose `user_id` is not in the set of actual senders in the current batch are always discarded
- **`BOT_SELF` exclusion**: the Bot's own messages do not enter the allowlist, so they can never become candidate owners

### Source Levels

| `source_kind` | Meaning | Marking in the prompt | Weight |
|---|---|---|---|
| `AT_MENTION` | User speaks directly to the Bot | `[Said to Bot]` | High-density evidence |
| `PASSIVE` | Passively ingested from the group chat | No marking | Must be reproduced |
| `BOT_SELF` | The Bot's own message | `[I said]` | Context only |

`BOT_SELF` provides context. Without it, when a user answers "yes" or "phone," the consolidation model cannot see what the Bot asked and can only give up or fabricate. The prompt explicitly requires that "no information about the user may be extracted from content marked `[I said]`."

## Candidate Reinforcement: Reproduction Is Evidence

When the same fact is observed again, **a new row is not inserted**; evidence is accumulated instead:

| Field | Change |
|---|---|
| `occurrence_count` | +1 |
| `confidence` | `min(1.0, max(old, new) + MEMORY_CANDIDATE_REOCCURRENCE_BONUS)` |
| `content` | Use the more complete version |
| `evidence` | Append (with a length limit) |
| `source_kinds` | Take the union (the source set across observations) |
| `source_message_ids` | Take the union |
| `status` | Return to `NEW` and participate in promotion evaluation again |
| `first_seen_at` | **Remain unchanged** |

Similarity matching requires **the same group + same user + same type + similar content** (`memory/text_similarity.py`, Jaccard ≥ 0.65 or one string is a substring of the other).

Keeping `first_seen_at` unchanged is intentional: it is the anchor for expiration. `OBSERVING` candidates that have not received new evidence after `MEMORY_CANDIDATE_MAX_OBSERVING_DAYS` are marked `REJECTED` (not deleted, and retained for auditing).

Without this mechanism, `OBSERVING` would be a dead end with entries but no exits—the same fact would be stored with a new uuid each time, each instance would remain stuck, and cross-validation would never succeed.

## Promotion Layer: Gate 1 Three Tiers

The decision logic in `memory/memory_manager.py` is:

| Confidence | Decision |
|---|---|
| ≥ `MEMORY_CONFIRM_HIGH_CONFIDENCE` (0.85) | Promote directly |
| ≥ `MEMORY_OBSERVE_LOW_CONFIDENCE` (0.6) | Check evidence sufficiency:<br>· If past sources include `AT_MENTION` and the switch is enabled → promote<br>· If `occurrence_count` ≥ `MEMORY_PROMOTE_MIN_OCCURRENCE_PASSIVE` → promote<br>· Otherwise → `OBSERVING` |
| < 0.6 | `OBSERVING`, wait for more evidence |

There is also a lower bound of `MEMORY_PROMOTE_MIN_IMPORTANCE` for `importance`, which eliminates overly trivial information.

**`importance` is not independently a basis for promotion**: it is self-assessed by the LLM and is the least reliable of all metrics. The early version used the rule "observe only when **both** confidence and importance are below their thresholds," which meant a candidate with `confidence=0.3 / importance=0.6` would directly become a long-term memory.

## Conflict Resolution

When a new candidate conflicts with an existing memory (same user and type, shared key object words, opposite emotional polarity):

- If the new candidate has higher confidence → mark the old memory as `conflict` (remove it from retrieval, but do not delete it)
- Otherwise → change the new candidate to `OBSERVING` and wait for more evidence

## Cross-User Isolation (Hard Constraint)

Content similarity **does not mean** that items can be merged. If user A and user B say the same sentence, they are two independent memories.

All three merge paths must filter by ownership:

| Location | Impact |
|---|---|
| `memory_manager._find_similar_memory` | Writes to the database; A's fact is merged into B's memory |
| `compressor._merge_duplicate_memories` | Writes to the database and runs in a scheduled task; one side is set to `archived` and is **irreversible** |
| `retrieval_v2._merge_similar` | Does not write to the database, but can cause replies to misattribute information (active messages retrieve memories from the entire group) |

`tests/test_cross_user_isolation.py` has one positive case (must not merge) and one negative case (the same user must still merge) for each of the three locations. Testing only "do not merge" would allow an always-false condition to pass, causing deduplication to fail silently.

## Quotas: Cap the Presentation Layer

After creating a memory, the system checks the number of active memories for that group and user. When it exceeds `MEMORY_USER_QUOTA`, the weakest memory by ascending competition score is evicted (set to `archived`, not deleted):

```
Score = W_IMPORTANCE × importance
      + W_CONFIRMATION × min(1, confirmation_count / CONFIRMATION_CAP)
      + W_RECENCY × exp(-age_days / 30)
```

Use `last_accessed_at` rather than `created_at`: an old memory that is still frequently retrieved is more valuable than a new one that has never been used.

`MEMORY_QUOTA_ENFORCE` is **disabled by default**; in that case, the system only outputs a `[Quota dry-run]` log explaining "who would have been evicted." It is recommended to observe for a while and confirm the behavior before enabling it—there is no way to know what 25 items will evict in a specific database without looking at the logs.

## Retrieval: Policy Before Similarity

The core distinction of `memory/retrieval_v2.py` lies in the question itself: old retrieval asked "which memory text is most relevant?"; v2 asks "which memory does the current behavior actually need?"

```
Mode detection (rule-based scoring, no LLM call)
  → SQL visibility pre-filter        ← first decide what is eligible to be found
  → FTS5 / weighted fallback candidate pool
  → Usage-layer filtering
  → Ranking (six weighted dimensions)
  → Merge same types (by user)
  → Separate chat material / behavioral constraints
  → Score threshold + per-mode item limit
```

### Behavioral Modes (Mode)

`CASUAL_REPLY` `ACTIVE_JOIN` `HUMOR` `TECH_HELP` `RECOMMEND` `EMOTIONAL` `CONFLICT_AVOID` `GROUP_EVENT`

Use weighted keyword scoring rather than a short-circuit if chain: `hit count × weight × (1 + longest matched term length/10)`. The highest score wins, provided it exceeds `MODE_DETECT_MIN_SCORE`. This allows long terms and strong-signal terms to naturally outweigh frequent weak signals such as "haha" and "tired."

### Three Layers of Filtering

**Mode → Usage**: each mode has a list of allowed and forbidden uses. For example, `CASUAL_REPLY` forbids `BOUNDARY_PROTECTION` and `CONFLICT_AVOID`; `TECH_HELP` forbids `HUMOR`.

**Usage → Type**: each use is tagged with its "primary source" type. Incompatibility is not a hard exclusion; instead, the item is downweighted by `USAGE_TYPE_MISMATCH_PENALTY`—an omission in the matrix should not directly determine the ranking result.

**Visibility**:

| Level | Semantics |
|---|---|
| `OPEN` | Freely usable |
| `CONTEXTUAL` | Activated only when the topic matches |
| `RESTRICTED` | Visible only to `CONFLICT_AVOID`, and used only as a constraint |
| `INTERNAL` | For system decisions only; **must not enter the Prompt** |

### Ranking (Six Dimensions)

```
score = W_CONTEXT × context fit
      + W_USAGE × usage match
      + W_SEMANTIC × semantic similarity
      + W_RECENCY × recency decay (exp, τ=30 days)
      + W_CONFIDENCE × confidence
      + W_IMPORTANCE × importance
```

The six dimensions are independent, avoiding duplicate calculation of the same signal by two weights. The weights for `confidence` / `importance` are deliberately low (0.05 each): they describe whether the "memory itself is reliable/important," which has a weak relationship to "whether it should be used now," so they are suitable only as tie-breakers. Otherwise, high-confidence decoy memories could game the question of "whether they should be used."

When embeddings are not enabled, lexical semantics are unreliable. In that case, **discard the semantic dimension and renormalize the remaining weights**, rather than letting a score of 0 lower every candidate.

Memories below `MEMORY_SCORE_MIN` do not enter the Prompt—use a dynamic count rather than a fixed Top-K to avoid the over-retrieval noise of "filling the limit whenever there are enough valid candidates."

### Partitioned Injection

Chat material and behavioral constraints are **strictly separated**, each with an independent token budget:

```
Chat background for reference:
- The user likes playing co-op games

Interaction notes:
- Avoid proactively engaging the relevant member in interactions involving "not liking having their head patted."
```

Memories with `RESTRICTED` / `INTERNAL` visibility, or with `BOUNDARY_PROTECTION` / `CONFLICT_AVOID` usage, may enter only the second section. The two sections are never mixed.

## User Profile Governance

`user_profiles` stores only **stable facts** (language preferences, technical proficiency, observable behavior). Personality judgments, mental states, and value judgments are filtered by `stable_profile_facts()` on both the write and read sides.

The reason is that descriptions such as "gentle, humorous, sensitive" are largely inferences; treating them as facts would continuously amplify early misjudgments.

## Compression and Forgetting

| Action | Trigger | Description |
|---|---|---|
| Deduplication merge | Lightweight + weekly | Same group, same user, same type, and similar content → merge; the merged item is `archived` |
| Atomization | Lightweight + weekly | Split memories longer than 80 characters into atomic facts |
| Low-value archiving | Weekly | Importance below the threshold and not accessed for a long time |
| Type decay | Weekly | Archive according to the type lifespan defined by `MEMORY_DECAY_DAYS` |

Type lifespans: `FACT` 730 days → `STYLE` 365 → `PREFERENCE`/`RELATION` 180 → `EVENT`/`PLAN` 60 → `GROUP_CONTEXT` 30.

All "deletions" are `status = 'archived'`; the data only leaves retrieval and is retained.

## Proactive Acquisition: Why It Is Essential

An actual run on a clean database (985 group messages, consolidation executed normally throughout, with no parsing failures):

| Metric | Result |
|---|---|
| Candidates produced | **0** |
| Long-term memories produced | 0 |

Conclusion: **the expected output of passive ingestion in a casual chat group approaches zero, and tuning cannot improve it**—the threshold is not too high; the information simply does not exist. Users do not state their stable attributes while joking and role-playing.

Therefore, proactive @-mentions are not "a supplement to the memory system" but **the primary source of memory**.

> Note: This is also one reason to prioritize fully local deployment—the data produced while proactively building a user profile is strongly privacy-sensitive. When connecting to an online endpoint, this step (the `CONSOLIDATION` / `EXTRACT` roles) sends the original group-chat text to the provider, so the "hybrid" mode keeps consolidation local: only the dialogue-generation step goes out over the network. See [configuration.en.md · Three Typical Scenarios](configuration.en.md#three-typical-scenarios).

### Target Selection

Priority:

1. **Verification**: active users with an `OBSERVING` candidate whose confidence is closest to the promotion line—one question can cross the threshold, producing the highest benefit
2. **Cold start**: users with no candidates but recent activity; start from an everyday topic
3. Neither → do not speak

Exclusion conditions: the daily quota is full, the user is within the user-level cooldown, or the maximum number of consecutive non-responses has been exceeded.

### Safeguards

| Mechanism | Function |
|---|---|
| Daily quota | 2 by default, with up to 2 additional attempts for frequent speakers; hard cap |
| User-level cooldown | Minimum interval between two proactive @-mentions of the same user (2 hours by default) |
| Consecutive no-response backoff | Stop follow-up questions to the user after reaching `PROACTIVE_MAX_NO_REPLY` |
| Count on sending | Consumes quota regardless of whether a response is received, otherwise the system would repeatedly address the same person |
| Persist state | After a restart, the system does not ask the same person the same thing again |

"The more active someone is, the more they are harassed" is the runaway behavior that must be avoided, so the frequency reward is deliberately kept small.

### Question-Answer Association

The **implicit approach** is used: no explicit tracking is established between "question ↔ answer." The user's answer is itself `AT_MENTION`; consolidation generates or reinforces a candidate with the same content, and after `occurrence_count` increases by 1, it crosses the threshold.

This reuses the existing reproduction-reinforcement mechanism and is much simpler than a state machine with timeout handling.

### Two Hard Constraints for Line Generation

- **Do not repeat the candidate's original text**. A candidate is an internal note with stilted wording; quoting it directly makes the conversation sound like an archive verification
- **Do not sound like an interrogation**. Ask only one thing at a time, use a casual tone, and allow the other person not to answer

The system also requires "do not respond to any sentence in the context, including anything you just said"—during a proactive @-mention, the context is only material for tone, not content awaiting a response.

## Known Limitations

- **Role-playing content may be treated as a real-person attribute**. "I am an exiled vampire" has a source, correct ownership, and no inference, so it can pass all anti-fabrication clauses. This is a data problem rather than a model problem; it can only be mitigated by the promotion layer's reproduction threshold
- **`MEMORY_PROMOTE_MIN_OCCURRENCE_PASSIVE = 2` is almost never satisfied on the passive path**. Whether to lower it should be reassessed after the proactive path has accumulated data
- **Deduplication of cold-start topics is weak**. Keyword avoidance for Chinese topics depends on segmentation, which is currently largely ineffective for Chinese; when the topic list is short, the cost of repeated questions is acceptable
- **During proactive @-mentions, Mode detection and the retrieval query use the full task-instruction text**, which has a poor signal-to-noise ratio. This has no visible impact when the memory store is empty; after data exists, an independent `retrieval_query` should be introduced

## Further Reading

The design process and empirical records are in [`design_docs/`](../design_docs/):

- `Memory Schema / Consolidation / Retrieval / Policy Matrix / Evaluation & Debug Specification v1.0.md` — original specification
- `Memory Verification Loop.md` — design of the proactive acquisition loop
- `check_point/` — key decision points and empirical data
- `bug_report/` — defect analysis
