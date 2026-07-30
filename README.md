# Stella — QQ 群聊 AI 机器人

基于 NoneBot 2 + OneBot V11 的 QQ 群聊机器人，具备短期记忆、长期记忆和用户画像功能。

## 架构

```
QQ 消息
  │
  ├─ 静默监听器 (priority=99)      ← 记录每条群消息到 DB
  │    └─ maybe_consolidate()       ← 每收到一条消息检查是否需要整合记忆
  │
  └─ @-消息处理器 (priority=1)
       └─ Pipeline 管线
            ├─ Pre‑hooks            ← 记录消息、构建上下文、加载用户画像
            ├─ LLM (LM Studio)      ← 本地大模型，直接 HTTP POST
            └─ Post‑hooks           ← XML 解析、破防过滤、换行拆分、思考日志
```

### 模块

| 路径 | 说明 |
|---|---|
| `core/` | 管线内核 — Pipeline 编排器 + LLM 后端抽象 + 扩展加载器 |
| `core/llm/lm_studio.py` | 本地 LLM 后端（LM Studio API 直连） |
| `core/llm/flexiweb.py` | 在线 LLM 后端（通过 FlexiWeb 抓取网页 LLM） |
| `memory/` | 记忆系统 — 消息记录、短期摘要、长期记忆、用户画像 |
| `extensions/` | 扩展目录 — 放入含 `setup(pipeline)` 的 Python 包即可自动加载 |
| `config/` | 集中配置 — 所有运行时参数 |

### 记忆流程

```
每一条群消息
  │
  ├─→ group_messages 表（原始消息，永不清除）
  │
  └─→ maybe_consolidate()
       └─ 每 100 条新消息触发一次
            ├─ FlexiWeb → 在线 LLM 分析
            └─ 写入三张表
                 ├─ short_term_context    ← 对话摘要 + 进行中话题（短期记忆）
                 ├─ user_profiles         ← 性格 / 态度（用户画像）
                 └─ long_term_memories    ← 重要性 >= 5 的事实（长期记忆）
```

- **短期记忆**：下次 @-bot 时作为上下文注入，或回退到最近 3 条原始消息
- **用户画像**：每次对话前读取，拼入 prompt 提供给 LLM
- **长期记忆**：对话前读取该用户的重要记忆拼入上下文
- **整合重叠窗**：每次处理 100 条新消息 + 向前 15 条重叠，防止话题截断

## 配置

所有参数集中在 `config/settings.py`，无需修改业务代码。

### LM Studio

```python
LM_STUDIO_BASE_URL = "http://127.0.0.1:1234"   # 你的 LM Studio 端口
LM_STUDIO_MODEL = ""                            # 模型名（LM Studio 单模型时可留空）
```

### FlexiWeb（可选，用于记忆整合）

```python
FLEXIWEB_BASE_URL = "http://127.0.0.1:8000"
CONSOLIDATION_SITE = "deepseek"                 # FlexiWeb config/{name}.json
CONSOLIDATION_BATCH_SIZE = 100                  # 每多少条新消息整合一次
CONSOLIDATION_OVERLAP = 15                      # 话题重叠窗
```

FlexiWeb 未启动时，记忆整合静默跳过，不影响聊天。

### 系统提示词

`pi_agent_core/SYSTEM.md` — LLM 的系统提示词，定义 Stella 的角色设定和回复格式（XML 标签）。

## 扩展

创建 `extensions/my_feature/__init__.py`：

```python
from core.pipeline import Pipeline
from core.context import ChatContext

async def my_hook(ctx: ChatContext) -> ChatContext:
    ctx.context += "\n[自定义信息]"
    return ctx

def setup(pipeline: Pipeline):
    pipeline.register_pre_hook(my_hook, priority=30)
```

放入 `extensions/` 目录，下次启动时自动加载。

## 启动

```bash
# 1. 启动 LM Studio 并加载模型

# 2. 启动 QQ 适配器（NapCat / Lagrange 等）

# 3. 启动 Stella
cd stella_project
python bot.py

# 4. （可选）启动 FlexiWeb 用于记忆整合
cd ../FlexiWeb_Stream_Scraper
.venv\Scripts\python.exe main.py -s deepseek --headless
```
