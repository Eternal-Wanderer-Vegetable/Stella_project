
---

# **Stella 记忆系统重构 - 技术规格文档**

**项目代号：** Stella Memory 2.0
**文档版本：** 1.0
**类型：** AI Agent 认知架构设计
**目标环境：** 本地部署 (RTX5080 + 64GB RAM), Python, SQLite, NoneBot2
**前置文档：** 无，此文档为新系统设计的完整规格说明。

---

## **第一部分：项目背景与核心目标**

### 1.1 项目背景
Stella 是一个长期运行于QQ群的“熟人型”AI Agent。当前系统（v1.x）虽具备基础记忆能力，但存在用户画像污染、记忆类型模糊、检索策略简单等问题，限制了其“像朋友一样交流”的能力。

### 1.2 核心目标
本次重构旨在将Stella的记忆系统从“聊天记录摘要系统”升级为“具备认知能力的长期记忆系统”。
核心目标可量化为：
1.  **更精准的记忆存储**：区分事实、偏好、事件等不同类型，避免信息混乱。
2.  **更智能的记忆提取**：通过评分和排序，只唤醒当前对话最相关的记忆。
3.  **更自然的记忆表达**：将结构化记忆转化为自然语言“回想”，融入Prompt。
4.  **更稳定的长期运行**：通过去重、压缩和原子化，控制数据库膨胀并提升检索效率。
5.  **完全的本地化隐私安全**：除可选的资料查询外，所有核心记忆处理均在本地完成。

### 1.3 设计哲学
1.  **记忆候选机制**：任何信息必须先成为`memory_candidate`，经审核后才能成为长期记忆。
2.  **分层存储与检索**：原始消息 -> 候选记忆 -> 长期记忆 -> 原子事实。
3.  **行为建模，而非人格标签**：系统应记录“用户喜欢详细解释技术问题”，而非“用户很理性”。
4.  **渐进式压缩**：根据记忆的生命周期和置信度，进行去重、摘要化和原子化。
5.  **本地SLM优先**：除主聊天模型（Gemma 27B）外，记忆摘要和原子化任务使用更小、更快的本地SLM处理。

---

## **第二部分：数据模型与存储设计**

### 2.1 核心表结构 (SQLite)

所有表均需包含 `id`, `created_at`, `updated_at` 基础字段。此处列出核心业务字段。

#### 2.1.1 `messages` (原始消息表, 替代 `group_messages`)
*   **职责**：永久存储所有原始聊天记录，作为不可变的事实日志。
*   **字段**：
    *   `id`: TEXT PRIMARY KEY
    *   `group_id`: TEXT (群聊ID)
    *   `user_id`: TEXT (用户ID)
    *   `content`: TEXT (原始消息内容)
    *   `timestamp`: INTEGER (Unix时间戳)

#### 2.1.2 `memory_candidates` (记忆候选表, 新增)
*   **职责**：存储LLM判断为“可能有价值”的信息，等待Memory Manager审核。
*   **字段**：
    *   `id`: TEXT PRIMARY KEY
    *   `user_id`: TEXT
    *   `type`: TEXT (枚举: `FACT`, `PREFERENCE`, `EVENT`, `PLAN`, `RELATION`)
    *   `content`: TEXT (记忆内容)
    *   `importance`: REAL (0-1, 重要程度)
    *   `confidence`: REAL (0-1, 可信度)
    *   `evidence`: TEXT (LLM生成此候选的理由，便于调试)
    *   `status`: TEXT (枚举: `NEW`, `OBSERVING`, `CONFIRMED`, `REJECTED`, `ARCHIVED`)
    *   `source_message_ids`: TEXT (JSON数组, 产生此候选的原始消息ID)

#### 2.1.3 `memories` (长期记忆表, 替代 `long_term_memories`)
*   **职责**：存储经Memory Manager确认并整合后的长期记忆。
*   **字段**：
    *   `id`: TEXT PRIMARY KEY
    *   `user_id`: TEXT
    *   `type`: TEXT (枚举同 `memory_candidates`)
    *   `content`: TEXT (当前有效的记忆内容, 可能已被摘要压缩)
    *   `content_raw`: TEXT (原始完整内容, 摘要压缩前备份)
    *   `importance`: REAL (0-1)
    *   `confidence`: REAL (0-1)
    *   `status`: TEXT (枚举: `active`, `outdated`, `archived`)
    *   `confirmation_count`: INTEGER (被确认的次数)
    *   `last_confirmed_at`: INTEGER (最后确认时间)
    *   `last_accessed_at`: INTEGER (最后被检索到的时间)
    *   `compressed_at`: INTEGER (摘要化的时间, NULL表示未压缩)
    *   `compression_version`: INTEGER (压缩版本号)
    *   `is_atomized`: INTEGER (布尔值, 是否已被原子化)

#### 2.1.4 `atomic_facts` (原子事实表, 新增)
*   **职责**：存储从高度确认的 `memories` 中拆解出的最小事实单元，用于精确检索。
*   **字段**：
    *   `id`: TEXT PRIMARY KEY
    *   `memory_id`: TEXT (外键, 关联到 `memories` 表)
    *   `subject`: TEXT (主体, 通常是 `user_id`)
    *   `predicate`: TEXT (谓词, 如 `likes`, `has_hardware`)
    *   `object`: TEXT (宾语, 如 `Helldivers2`, `RTX5080`)
    *   `confidence`: REAL (0-1)

#### 2.1.5 `user_profiles` (用户行为模型, 重构)
*   **职责**：存储可观察、可预测的用户行为模式，用于指导Stella的交流策略。
*   **字段**：
    *   `user_id`: TEXT PRIMARY KEY
    *   `data`: TEXT (JSON字段)
*   **数据结构示例**：
    ```json
    {
      "conversation_style": {
        "relaxed": 0.8,
        "playful": 0.6,
        "likes_detailed_tech": 0.9
      },
      "interests": {
        "game": ["Helldivers2", "FPS"]
      },
      "habits": {
        "shares_personal_experience": 0.7
      }
    }
    ```

---

## **第三部分：核心模块与流程设计**

### 3.1 模块一：Memory Candidate Generator (整合于 `consolidator.py`)

*   **输入**：从 `messages` 表获取的最近一批消息。
*   **处理流程**：
    1.  **规则过滤**：丢弃长度<5字符、纯表情、无意义高频词（如“哈哈”、“233”）的消息。
    2.  **轻量分类 (可选)**：使用本地SLM或`embedding`模型对消息进行粗筛，判断其是否可能包含个人信息、偏好或事件。
    3.  **深度整理 (Gemma 27B)**：对通过粗筛的消息，使用特定Prompt让Gemma 27B生成 `memory_candidates`。
*   **输出**：一个或多个 `memory_candidate` 对象写入 `memory_candidates` 表。
*   **触发时机**：可由消息数量或空闲时间触发，建议每10-20条消息或每15分钟运行一次。

### 3.2 模块二：Memory Manager (新增核心模块 `memory_manager.py`)

*   **输入**：新写入 `memory_candidates` 表的一条或多条候选记忆。
*   **处理流程**：
    1.  **去重 (Deduplication)**：计算新候选与 `memories` 表中所有 `active` 记忆的 `embedding` 相似度。
        *   若相似度 > 0.85，则判定为同一主题，进入合并流程。
        *   若相似度 <= 0.85，则判定为新记忆，进入创建流程。
    2.  **合并 (Merge)**：
        *   合并 `content`：将新内容追加到旧内容中，形成更完整的描述。
        *   更新 `confidence`：按公式更新 `min(旧confidence * 1.05 + 0.02, 0.98)`。
        *   更新 `importance`：取两者最大值。
        *   `confirmation_count` + 1。
        *   更新 `last_confirmed_at`。
        *   **冲突处理**：如果新记忆与旧记忆存在直接冲突（如“喜欢A”变为“不喜欢A”），则将旧记忆状态标记为 `outdated`，并创建新记忆。
    3.  **创建 (Create)**：
        *   使用候选记忆的信息创建一条新的 `memory`，状态设为 `active`。
    4.  **生命周期更新**：
        *   读取所有 `active` 记忆，根据其 `decay_rate` (由type决定) 和 `last_accessed_at` 更新 `importance` 和 `status`。例如，超过90天未访问的 `EVENT` 类型记忆可设为 `archived`。
*   **输出**：更新 `memories` 表。
*   **触发时机**：每次 `memory_candidates` 表有新记录写入时触发，并每日凌晨运行一次全局维护。

### 3.3 模块三：Memory Retriever & Ranker (整合于 `pre_processor.py`)

*   **输入**：用户当前消息。
*   **处理流程**：
    1.  **硬性过滤**：根据当前消息意图，排除明显不相关的记忆。
    2.  **检索**：使用 `embedding` 模型从 `memories` 和 `atomic_facts` 表中检索与当前消息语义相关的记忆，获取 Top-10 候选。
    3.  **排序 (Ranking)**：对 Top-10 候选计算综合得分，公式如下：
        `FinalScore = SemanticScore × 0.35 + ImportanceScore × 0.25 + ConfidenceScore × 0.20 + RecencyScore × 0.10 + ContextMatchScore × 0.10`
        *   **SemanticScore**: `embedding` 余弦相似度。
        *   **ImportanceScore**: 直接使用 `importance` 值。
        *   **ConfidenceScore**: 直接使用 `confidence` 值。
        *   **RecencyScore**: 由 `last_accessed_at` 计算衰减，`exp(-days_since / decay_half_life)`。`EVENT` 类型衰减更快。
        *   **ContextMatchScore**: 根据当前场景分类（如“游戏讨论”、“技术讨论”）与记忆 `type` 的匹配度。
    4.  **类型权重调整**：根据 `type` 动态调整各维度权重。例如，`FACT` 提升 `importance` 和 `confidence` 权重，`EVENT` 提升 `recency` 权重。
    5.  **截取**：取排序后的 Top 3-5 条记忆。
*   **输出**：一个包含 Top 3-5 条记忆的列表。

### 3.4 模块四：Prompt Builder (整合于 `pre_processor.py`)

*   **输入**：排序后的 Top 3-5 条记忆，用户消息，短期上下文 (`short_term_context`)。
*   **处理流程**：
    1.  **记忆自然化**：将结构化的 `memory` 对象转化为自然语言“回想”句子。
        *   `PREFERENCE`: `（你印象里 {user_name}{verb}{object}）`
        *   `FACT`: `（你记得 {user_name} 的 {subject} 是 {object}）`
        *   `EVENT`: `（你想起 {user_name} 最近 {event_description}）`
    2.  **组装Prompt**：
        *   **System**: Stella 角色设定。
        *   **短期上下文**: `【当前上下文】` (来自 `short_term_context`)。
        *   **用户行为模型**: `【和 {user_name} 说话时】` (来自 `user_profiles`)。
        *   **唤醒的记忆**: `【你自然想起的关于 {user_name} 的事】` (自然化后的记忆)。
        *   **对话历史**: 最近3-5条原始消息。
        *   **用户当前消息**: `{user_message}`。
*   **输出**：完整的、结构清晰的Prompt字符串。
*   **关键原则**：不要直接输出“记忆库查找到以下内容...”，而是模拟Stella的“自然回想”。

### 3.5 模块五：Memory Compressor (新增 `compressor.py`)

*   **目标**：由本地SLM驱动，定期维护 `memories` 表，防止其膨胀并提升检索精度。
*   **模型配置**：
    *   **摘要模型 (Summarizer)**: `Qwen2.5-7B-Instruct` (Q4量化)，负责压缩长记忆。
    *   **原子化模型 (Atomizer)**: `Phi-3.5-mini` (Q4量化) 或 `Qwen2.5-3B`，负责拆解事实。
*   **处理流程**：
    1.  **触发**：每周日凌晨3:00运行一次。
    2.  **摘要化 (Summarization)**：
        *   **条件**：`content` 长度 > 50词，或 `confirmation_count` > 5。
        *   **操作**：调用 **摘要模型**，Prompt: “请将以下关于用户的记忆压缩为1-2句简洁且完整的摘要，保留所有关键事实...”。
        *   **结果**：将 `content` 原内容移至 `content_raw`，用摘要覆盖 `content`，更新 `compressed_at` 和 `compression_version`。
    3.  **原子化 (Atomization)**：
        *   **条件**：`is_atomized == 0` AND `confidence` > 0.90 AND `status` == `active`。
        *   **操作**：调用 **原子化模型**，Prompt: “请将以下记忆拆解为独立的事实单元... JSON输出”。
        *   **结果**：将解析出的JSON数组写入 `atomic_facts` 表，并将 `is_atomized` 设为 1。
    4.  **资源释放**：任务完成后，立即从显存中卸载SLM模型。

---

## **第四部分：记忆类型、规则与评分标准**

### 4.1 记忆类型 (`type`) 定义与准入规则

| 类型 | 定义 | 准入规则 (进入 `memories` 表) | 生命周期/衰减 |
| :--- | :--- | :--- | :--- |
| **`FACT`** | 客观、稳定的事实信息 | 1. 用户明确表达<br>2. 无冲突 | 极长 (近乎永久) |
| **`PREFERENCE`** | 用户的喜好、厌恶和习惯 | 1. 用户明确表达“喜欢/不喜欢”一次, **或**<br>2. 同一主题重复出现 ≥3次 | 长 |
| **`EVENT`** | 已发生的、一次性的经历 | 1. 直接保存 (准入宽松)<br>2. `importance` 决定其寿命 | 短 (数周至数月) |
| **`PLAN`** | 用户未来的计划或目标 | 1. 用户明确表达“准备、打算”等 | 特殊 (完成后转为 `EVENT`) |
| **`RELATION`** | 用户与其他人或事物之间的关系 | 1. 同一关系互动出现 ≥3次 | 长 |
| **`CONVERSATION_STYLE`** | 用户的交流偏好和习惯 | 1. 基于长期统计, **不由单次候选创建** | 长 (持续更新) |

### 4.2 `importance` 与 `confidence` 评分指引

*   **`importance` (0-1)**: 衡量记忆对“未来交流”的价值。
    *   `0.9 - 1.0`: 核心事实，影响长期互动 (如：用户专业、核心配置)。
    *   `0.7 - 0.89`: 重要偏好或计划 (如：喜欢的游戏、职业规划)。
    *   `0.5 - 0.69`: 一般性事件或兴趣 (如：参加过某次活动)。
    *   `< 0.5`: 临时状态或低价值信息 (如：今天心情好)，不予保存。
*   **`confidence` (0-1)**: 衡量记忆“为真”的可信度。
    *   `0.9 - 1.0`: 用户明确、直接表达。
    *   `0.7 - 0.89`: 用户行为间接推断 (如：多次讨论某游戏)。
    *   `0.5 - 0.69`: 单次、非明确表达。
    *   `< 0.5`: 强烈推测，应进入 `candidate` 观察。

### 4.3 `user_profiles` 字段规范

*   **禁止存储**: 任何“人格形容词” (如：温柔、幽默、善良、理性、感性)。
*   **允许存储**: 可观察的“行为模式” (如：喜欢详细解释, 常使用短句, 偏好技术讨论)。
*   存储格式为结构化JSON，便于程序读取和更新。

---

## **第五部分：本地SLM部署与调度方案**

### 5.1 模型配置
*   **主聊天模型**: `Gemma 27B` (实时推理)
*   **摘要模型**: `Qwen2.5-7B-Instruct` (Q4量化, 约5GB显存)
*   **原子化模型**: `Phi-3.5-mini` (Q4量化, 约2GB显存)

### 5.2 调度策略
*   **模型加载**: 采用“**用时加载，用完释放**”策略，避免同时加载多个模型占用显存。
*   **批量处理**: `Compressor` 在执行压缩任务时，应收集所有需要处理的记忆，进行批量摘要或拆解，以提高效率。
*   **定时任务**: 使用系统 `cron` (Linux) 或 `Task Scheduler` (Windows) 调度 `compressor.py` 每周日凌晨运行。

### 5.3 `Compressor` 工作流程伪代码

```python
# compressor.py
class MemoryCompressor:
    def run_weekly(self):
        # 1. 检查任务
        if not self.db.has_memories_to_compress():
            return
        # 2. 加载摘要模型
        summarizer = load_model("Qwen2.5-7B")
        memories = self.db.get_memories_for_summarization()
        for mem in memories:
            summary = summarizer.summarize(mem.content)
            mem.compress(summary)
            self.db.update_memory(mem)
        # 3. 释放摘要模型
        unload_model(summarizer)
        # 4. 加载原子化模型
        atomizer = load_model("Phi-3.5-mini")
        stable_memories = self.db.get_stable_memories(confidence=0.90)
        for mem in stable_memories:
            facts = atomizer.atomize(mem.content)
            self.db.save_atomic_facts(mem.id, facts)
            mem.is_atomized = True
            self.db.update_memory(mem)
        # 5. 释放原子化模型
        unload_model(atomizer)
```

---

## **第六部分：实施路线图**

建议按以下顺序推进开发，以快速验证并降低风险。

### 阶段一：数据层与候选生成 (1-2周)
1.  创建/修改所有SQLite表 (见第二部分)。
2.  修改 `consolidation_prompt.py`，使其输出新格式的 `memory_candidates`，而不是直接写入 `long_term_memories`。
3.  编写将 `memory_candidates` 写入新表的代码。

### 阶段二：核心逻辑 - Memory Manager (2-3周)
1.  实现 `memory_manager.py`，包含去重、合并、冲突处理、创建和生命周期管理逻辑。
2.  集成一个轻量级Embedding模型 (如 `BGE-small`) 用于计算相似度。
3.  编写单元测试，验证合并和冲突处理逻辑的正确性。

### 阶段三：检索与Prompt重构 (1-2周)
1.  重构 `pre_processor.py`，集成 `Memory Retriever & Ranker`。
2.  实现 `Prompt Builder`，包括“记忆自然化”功能。
3.  进行人工对话测试，调整Ranking权重和Prompt模板。

### 阶段四：Compressor与SLM集成 (1周)
1.  搭建本地SLM推理环境，测试 `Qwen2.5-7B` 和 `Phi-3.5-mini` 的摘要和原子化效果。
2.  实现 `compressor.py` 模块。
3.  配置定时任务。

### 阶段五：全面测试与调优 (持续)
1.  在真实或模拟QQ群环境中进行长期运行测试。
2.  监控数据库增长、Prompt长度和模型推理时间。
3.  根据实际效果微调Ranking权重和压缩策略。

---

## **第七部分：开发者注意事项**

1.  **隐私与安全**：所有处理流程必须**本地完成**。严禁将用户消息或任何记忆数据上传至任何云端API。唯一的例外是“查阅资料”功能，必须设计为可选（opt-in）功能。
2.  **错误处理**：所有与LLM/SLM的交互都需要有完善的降级策略。例如，如果 `compressor` 任务失败，不应导致整个服务崩溃，而应记录错误并重试，或保留原始内容。
3.  **异步处理**：除了主聊天推理，`Memory Manager` 和 `Compressor` 等任务都应在后台异步处理，不得阻塞Stella的实时回复。
4.  **数据可观测性**：保留 `evidence` 字段和关键日志，以便调试。例如，当Stella召回了一条不恰当的记忆时，可以通过日志追溯其来源和评分。
5.  **测试数据**：在开发阶段，请使用模拟的QQ群消息进行测试，避免污染线上数据库。

---
