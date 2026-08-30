# 配置参考

[中文](configuration.md) | [English](configuration.en.md)

**普通用户（Release 包）**：推荐用 `Stella.exe` 的「配置」页完成首次配置——填写群号、
连接方式、地址与模型 ID，保存后写入项目根目录的 `.env`；模型列表可从本机 LM Studio
自动读取，也可手工输入。

**开发者**：推荐用向导 `python -m deploy init`：只需回答 5 个必答项（群号、连接方式、
地址、两个模型 ID），模型 ID 会从 LM Studio 拉列表让你选编号，避免手打完整 ID
漏掉 `google/` 前缀；它会基于 `.env.example` 逐行生成 `.env`，模板里的注释（尤其
OneBot 连接那段跨 NapCat 的说明书）会原样保留。也可用 `--answers` 保存/复用答案。

本文是完整配置参考，用于调参。

配置集中在 [`config/settings.py`](../config/settings.py)，通过读取项目根目录的 `.env` 导出模块级常量。业务代码不需要改动该文件即可调参。

```bash
cp .env.example .env
```

按 `ENVIRONMENT` 可加载环境覆盖文件：`dev` / `development` → `.env.dev`，`prod` / `production` → `.env.prod`（覆盖 `.env` 中的同名项）。

布尔值接受 `true` / `1` / `yes`（大小写不敏感），其余视为 false。

## 最小可用配置

```env
ALLOWED_GROUPS=123456789
LM_STUDIO_BASE_URL=http://127.0.0.1:1234
LM_STUDIO_MODEL=your-chat-model
CONSOLIDATION_LM_STUDIO_MODEL=your-small-model
```

纯在线部署（不跑本机 LM Studio）的最小集换成端点与角色，本机模型 ID 可以完全留空——详见 [模型服务 · 端点与角色](#端点与角色两层配置)：

```env
ALLOWED_GROUPS=123456789
LLM_ENDPOINT_ONLINE_CHAT_BASE_URL=https://api.example.com
LLM_ENDPOINT_ONLINE_CHAT_API_KEY=sk-对话专用
LLM_ENDPOINT_ONLINE_CHAT_MODEL=vendor/chat-model
LLM_ENDPOINT_ONLINE_MEMORY_BASE_URL=https://api.example.com
LLM_ENDPOINT_ONLINE_MEMORY_API_KEY=sk-记忆专用
LLM_ENDPOINT_ONLINE_MEMORY_MODEL=vendor/cheap-model
LLM_ROLE_CHAT_ENDPOINT=ONLINE_CHAT
LLM_ROLE_ROUTER_ENDPOINT=ONLINE_CHAT
LLM_ROLE_PLUGIN_ENDPOINT=ONLINE_CHAT
LLM_ROLE_COMPACT_ENDPOINT=ONLINE_MEMORY
LLM_ROLE_CONSOLIDATION_ENDPOINT=ONLINE_MEMORY
LLM_ROLE_EXTRACT_ENDPOINT=ONLINE_MEMORY
# 可选：让阶段 2 提取在同一个端点上换用强模型（角色级覆盖，不填就用端点的模型）
LLM_ROLE_EXTRACT_MODEL=vendor/strong-model
```

模型 ID 写在**端点**上，指到该端点的角色默认都用它——不必在六个角色上各写一遍同一个字符串。两把 key 必须不同，原因见[为什么必须两把在线 key](#为什么必须两把在线-key)。用安装器的「配置 → 模型服务」分区点一下「纯在线（双 key）」预设，等价于上面这段。

---

## 群聊与路径

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `ALLOWED_GROUPS` | 空 | 允许响应的群号，逗号分隔。**留空则不响应任何群** |
| `STELLA_HOME` | 自动定位 | **用户数据根目录**（见下）。只能用真环境变量设置，不能写在 `.env` 里 |
| `SYSTEM_PROMPT_PATH` | `<数据目录>/system_prompts/default.md` | 系统提示词文件（人格）。数据目录里没有时用发布包自带的那份 |
| `DB_PATH` | `<数据目录>/memory/agent_memory.db` | SQLite 数据库 |
| `EXTENSIONS_DIR` | `<程序目录>/extensions/` | 扩展自动加载目录（程序代码，随版本替换） |
| `MEMORY_BENCHMARK_DIR` | `<程序目录>/memory/benchmark` | Benchmark 用例目录 |

路径类配置若在 `.env` 中设置，会被解析为绝对路径。

### 两个根目录：程序目录与数据目录

2026-08-27 起用户数据可以放在安装目录之外，这样**升级只需替换程序目录**：

| | 内容 | 升级时 |
|---|---|---|
| 程序目录（`PROJECT_ROOT`） | 代码、`.env.example`、`extensions/`、发布包自带的默认人格与能力配置、`runtime/` | 整体被新版本替换 |
| 数据目录（`STELLA_HOME`） | `.env`、`memory/`（记忆库与账本）、`config/spaces/`、`system_prompts/`、`data/plugins` 等、`logs/` | **不动** |

定位顺序（判据在 `config/home.py`，**不读 `.env`**——否则会形成「要读 `.env` 才知道 `.env` 在哪」的死循环）：

1. 环境变量 `STELLA_HOME`；
2. 机器级指针文件（Windows `%LOCALAPPDATA%\Stella\home.txt`，其他平台 `~/.config/stella/home.txt`）。它在程序目录之外，所以任何一份新解压的程序都能立刻接上老数据；
3. 安装目录本身有 `.env` 或 `memory/agent_memory.db` → **就地使用**（旧布局，3.0.0 及更早的安装零改动继续工作）；
4. 安装目录里存在 `StellaData/` → 用它（**便携模式**：程序与数据自包含，可整体拷走。开发仓库走的就是这条）；
5. 都没有 → 安装目录**同级**的 `StellaData/`。

**为什么默认是「同级」而不是「内部」**：程序目录是升级时被整体替换、也会被用户当作「旧版本」删掉的那个目录。
把数据默认放进去，等于让「删掉旧版本文件夹」这个再自然不过的清理动作变成不可逆的数据丢失。
所以默认在外，只有用户**显式**建了 `StellaData/` 子目录时才认为他要的是自包含布局
（那种情况下升级前必须先导入或备份）。

发布包因此**不带内层 `Stella/` 目录**：zip 解压后得到 `Stella-v3.1.0-win64/` 就是程序目录，
数据落在它的同级。多一层嵌套会把「同级」顶成「版本文件夹的内部」——这正是 v3.1.0 的缺陷。

数据目录内部的相对布局与旧安装完全一致，所以「旧布局」只是「数据目录恰好等于安装目录」的一个特例。
用 `python -m deploy paths` 查看当前解析结果（`deploy doctor` 也会显示）。

既随发布包出厂、又允许用户改的文件（`system_prompts/default.md`、`config/capabilities/*.toml`）
按「数据目录优先、否则用程序目录里出厂的那份」解析：新版本的默认值能随升级到达，用户的修改不会被覆盖。

## 日志

**所有运行期日志都落在 `LOG_DIR`（默认 `logs/`）。** 改这一个变量就能把全部日志搬走；单个文件仍可用各自的 `*_PATH` 单独覆盖。目录由写入方按需创建，不必手工建。

| 配置项 | 默认值 | 内容 |
|---|---|---|
| `LOG_DIR` | `logs/` | 所有日志的根目录 |
| `STELLA_JSON_LOG_PATH` | `logs/stella.jsonl` | 结构化日志，给程序读（GUI 的日志面板、`deploy status`） |
| `THOUGHT_LOG_PATH` | `logs/stella_thought_logs.md` | 思考/决策日志：每轮的完整 prompt、原始输出、路由判定、工具结果 |
| `CONSOLIDATION_LOG_PATH` | `logs/memory_consolidation_log.md` | 每批记忆整合的运行摘要与 LLM 原文 |
| `MEMORY_COMPRESS_LOG_PATH` | `logs/memory_compressor_log.md` | 每次记忆压缩的合并/原子化/归档计数 |
| `BOOT_DIAG_LOG_PATH` | `logs/boot_debug.log` | 启动诊断：插件发现与加载、能力装配、原型预热。**每次启动清空重写** |

同目录下还有 `logs/stella.pid`（`deploy start --detach` 写的进程号，不是日志）。

> **只有 `stella.jsonl` 有轮转与保留策略**（10 MB 轮转、保留 5 份，由 loguru 提供）。三个 Markdown 日志与 `boot_debug.log` 都是无上限追加——`boot_debug.log` 每次启动清空所以不会涨，另外三个会一直长（实测思考日志跑一个月约 3.5 MB）。需要的话自己定期清，或把 `LOG_DIR` 指到有清理策略的位置。

> 2026-08-25 之前这些文件散在项目根目录（`stella_thought_logs.md` 等），排查时要在一堆源码里翻，每加一个日志还要多一条 `.gitignore`。迁移后 `.gitignore` 只需 `logs/` 一条。旧的 `MEMORY_COMPRESS_LOG_FILENAME` 已废弃（它是**文件名**不是路径，只能落在项目根），改用 `MEMORY_COMPRESS_LOG_PATH`；旧键留在 `.env` 里不报错但完全不生效，`python -m deploy doctor` 会提示。

## 群组共享空间

多个 QQ 群可以归入同一个**群组共享空间**，共享用户画像、长期记忆与人格；而「当下这场对话的状态」仍按真实 QQ 群隔离。

### 两层归属

| 数据 | 归属 | 理由 |
|---|---|---|
| 消息尾巴、整合 checkpoint、短期话题、会话压缩 | **QQ 群** | 混群会让 Bot 在 A 群回应 B 群的对话 |
| 静音开关、主动 @ 配额 | **QQ 群** | 打扰程度是针对具体群的 |
| 用户画像、长期记忆、原子事实 | **共享空间** | 同一个人在同一空间就是一份认知 |
| 人格（system prompt）、发言策略 | **共享空间** | 同一形象应有同一套行为 |

### 配置方式

空间配置**不在 `.env` 里**，而是 `config/spaces/` 下的 TOML 文件，**文件名即空间名**：

```toml
# config/spaces/casual.toml —— 空间名为 "casual"
qq_groups = [123456789, 987654321]
```

目前只解析 `qq_groups`。`persona` 与 `[proactive]` 等字段是为将来的人格分群与群级配置预留的，当前会被忽略。

### 隐式空间

未被任何 TOML 收录的群会**自动分配**一个空间名（`space_1` / `space_2` …），并持久化在数据库目录下的 `.space_assignments.json`。单群部署零配置即可工作。

编号必须持久化而不是现算：若按群号排序的下标计算，加入一个群号更小的新群会让所有编号平移，原有记忆的归属随之错位且无声无息。

### 改名与合并

把一个已运行的群从自动分配的 `space_1` 改成显式的 `casual` 时，**历史记忆仍挂在 `space_1` 下**
（改名不会自动跟随）。程序会输出告警并给出一条命令：

```bash
python -m deploy space-merge --from space_1 --to casual --dry-run   # 先看预览
python -m deploy space-merge --from space_1 --to casual
```

它会改写全部按空间归属的表（含列名仍叫 `group_id` 的 `long_term_memories`）、重建 FTS 索引、
更新账本，并在 `user_profiles` 撞主键时保留互动次数多的那份（冲突写进报告）。操作前自动备份。

**不做「启动时自动跟随配置改名」**是刻意的：合并会撞画像主键、需要明确的合并语义，而且
**不可逆**——合并后只能靠 `origin_group_id` 溯源列或备份还原。让用户改一行 toml 就静默触发
一次跨群画像合并，风险与收益不对称。因此仍**建议在正式积累记忆之前就定好空间名**。

### 冲突处理

同一个群出现在多个 TOML 里时，按文件名排序取先者并输出 error 日志。静默取后者会让记忆在两次启动间落到不同空间，这种错乱事后极难发现。

## 模型服务

### 端点与角色：两层配置

Stella 的模型配置分两层：

- **端点（Endpoint）** = 一个 OpenAI 兼容服务：地址、API key、类型、**默认模型**、并发闸门、超时。它是「一把 API key 的归属单位」，也是「一道排队闸门的归属单位」。
- **角色（Role）** = 一次具体调用：用哪个端点、什么温度、多少 max_tokens，外加一个**可选的**模型覆盖。

模型 ID 挂在端点上而不是每个角色上重复一遍：一个端点通常只对应一家服务商的一份模型清单，「换服务商」就该只改一处。

共 4 个端点槽 × 6 个角色。「对话走在线、整合留本地」这类组合因此只是改几个 `LLM_ROLE_*_ENDPOINT`，不需要碰代码，也不需要为某家服务商写适配。

安装器「配置 → 模型服务」分区是这两层的图形界面（端点卡片 + 角色矩阵 + 三个一键预设），手改 `.env` 与用 GUI 等价。**槽名和角色名都是静态声明的**：`deploy/env_schema.py` 靠 AST 扫描 `config/settings.py` 里的字面量 `_env*("KEY", …)` 调用来生成 GUI 表单，动态拼出来的键名不会出现在界面上。

### 端点（Endpoint）

键名形如 `LLM_ENDPOINT_<槽名>_<字段>`，字段有 `BASE_URL` / `API_KEY` / `MODEL` / `KIND` / `CONCURRENCY` / `TIMEOUT`。

| 槽名 | 用途 | 默认 `KIND` | 默认 `CONCURRENCY` | 默认 `TIMEOUT` |
|---|---|---|---|---|
| `LOCAL` | 本机 LM Studio | `local` | `1` | `120.0` |
| `ONLINE_CHAT` | 在线服务商 · 对话生成域 | `online` | `4` | `120.0` |
| `ONLINE_MEMORY` | 在线服务商 · 记忆域 | `online` | `2` | `120.0` |
| `EXTRA` | 备用槽 / 第二个本机实例 | `local` | `1` | `120.0` |

- `MODEL` 是该槽的默认模型 ID，指到本槽的角色都用它（角色仍可单独覆盖，见下节）。
- `KIND` 只有 `local` / `online` 两个值，它是判据而非注释：`online` 端点没填 API key、或指向它的角色最终没有模型可用，都会被 `registry.validate()` 判成 **error**（`python -m deploy doctor` 会打出来）。GUI 的端点卡片**不给这一项控件**（卡头的徽标只显示结果）：两个 `ONLINE_*` 槽固定 `online`，`LOCAL` 与 `EXTRA` 按地址推导（`127.*` / `10.*` / `192.168.*` / `172.16-31.*` / `localhost` / 裸主机名 / 留空算 `local`，其余算 `online`），保存时按推导值落盘。手工编辑 `.env` 可以写任意值，但下次在 GUI 里保存会被推导值覆盖。若你的部署是「跑在 `127.0.0.1` 的中转网关、按上游厂商计费」，请把它填进两张在线卡，而不是改本机卡的类型——那种地址在本机、钱是真花的情况，按地址推导一定判错。
- `CONCURRENCY` 是该槽闸门的并发上限，同槽内 FIFO 严格串行。本机 LM Studio **不排队**，并发请求只会互相拖慢且难以归因，所以本地槽保持 `1`；在线端点可以放大到服务商允许的并发。
- `TIMEOUT` 是单次请求超时，**与 `LLM_TIMEOUT` 不是一回事**——后者是 `core/pipeline.py` 的整轮回复预算。

`LOCAL` 与 `EXTRA` 的地址和 key 留空即继承旧键，因此**未迁移的 `.env` 行为与升级前完全一致**，不需要任何手工迁移：

| 新键 | 留空时继承 |
|---|---|
| `LLM_ENDPOINT_LOCAL_BASE_URL` | `LM_STUDIO_BASE_URL` |
| `LLM_ENDPOINT_LOCAL_API_KEY` | `LM_STUDIO_API_KEY` |
| `LLM_ENDPOINT_EXTRA_BASE_URL` | `CONSOLIDATION_LM_STUDIO_BASE_URL`（它再继承 `LM_STUDIO_BASE_URL`） |
| `LLM_ENDPOINT_EXTRA_API_KEY` | `CONSOLIDATION_LM_STUDIO_API_KEY` |

`MODEL` 不走这套继承，而是「留空则由角色各自回落到自己的旧键」（见下节的解析顺序）：`LLM_ENDPOINT_LOCAL_MODEL` 留空时，绑在 `LOCAL` 上的角色仍分别用 `LM_STUDIO_MODEL` / `ASTRBOT_LLM_MODEL` / `MEMORY_EXTRACT_LM_STUDIO_MODEL`，与改造前逐字一致；填上它就等于「本机槽统一用这一个模型」，会盖掉那些旧键。GUI 的本机卡片与备用卡片上那个「模型 ID」输入框写的是旧键（`LM_STUDIO_MODEL` / `CONSOLIDATION_LM_STUDIO_MODEL`），`LLM_ENDPOINT_LOCAL_MODEL` / `LLM_ENDPOINT_EXTRA_MODEL` 留在高级配置里当逃生口。

> 纯本地部署下 `EXTRA` 与 `LOCAL` 同址，它的作用只是给整合一道**独立的闸门**：整合是长任务，与聊天共用闸门会让 @ 回复排在它后面。

### 角色（Role）

键名形如 `LLM_ROLE_<角色>_<字段>`，字段有 `ENDPOINT` / `MODEL` / `TEMPERATURE` / `MAX_TOKENS` / `FALLBACK_ENDPOINT`。

| 角色 | 干什么 | 默认端点 | 默认温度 | 默认 max_tokens |
|---|---|---|---|---|
| `CHAT` | 回复群友的主模型，质量优先 | `LOCAL` | `0.7` | `2000` |
| `ROUTER` | 判断「这条要不要回」，二分类任务 | `LOCAL` | `0.7` | `2000` |
| `PLUGIN` | 第三方插件借用的 LLM | `LOCAL` | 继承 `ASTRBOT_LLM_TEMPERATURE` | 继承 `ASTRBOT_LLM_MAX_TOKENS` |
| `COMPACT` | 会话压缩：把较早的对话压成回顾 | `LOCAL` | `0.3` | `0`（= `SESSION_SUMMARY_MAX_TOKENS × 3`） |
| `CONSOLIDATION` | 两阶段整合的阶段 1 | `EXTRA` | 继承 `CONSOLIDATION_LM_STUDIO_TEMPERATURE` | 继承 `CONSOLIDATION_LOCAL_MAX_TOKENS` |
| `EXTRACT` | 阶段 2 记忆候选提取 | `LOCAL` | 继承 `MEMORY_EXTRACT_LM_STUDIO_TEMPERATURE` | 继承 `MEMORY_EXTRACT_MAX_TOKENS` |

**`MODEL` 通常不用填。** 模型 ID 的正常出处是上一节的 `LLM_ENDPOINT_<槽名>_MODEL`（GUI 的端点卡片就是它），角色级 `MODEL` 只是**覆盖项**，用于「同一个端点上，某个角色要用另一个模型」——例如兜底判定挑一档更便宜的。GUI 的角色矩阵里「模型」一列因此是只读显示（显示最终结果与它的出处），要覆盖请改高级配置里的 `LLM_ROLE_<角色>_MODEL`。

完整解析顺序（`core/llm/registry.py::_resolve_role_model`）：

1. **角色显式 `MODEL`** —— 判据是「值与它继承的旧键不同」。`MODEL` 全部是继承型（`CHAT` / `ROUTER` / `COMPACT` 继承 `LM_STUDIO_MODEL`，`PLUGIN` 继承 `ASTRBOT_LLM_MODEL`，`CONSOLIDATION` 继承 `CONSOLIDATION_LM_STUDIO_MODEL`，`EXTRACT` 继承 `MEMORY_EXTRACT_LM_STUDIO_MODEL`），所以「只写了旧键」的存量 `.env` 落在第 3 档，行为与改造前逐字相同；
2. **该角色所绑端点的 `MODEL`**；
3. **角色自己的旧键**（第 1 档括号里那个）。这一档在**在线**端点上只对「这个旧键归属的那张卡」生效：`LM_STUDIO_MODEL` 归 `LOCAL`、`CONSOLIDATION_LM_STUDIO_MODEL` 归 `EXTRA`。把角色挪到 `ONLINE_CHAT` / `ONLINE_MEMORY` 而端点没填模型时，本机模型名不会被误带到在线服务商去（那一律是 400），而是当场报「该端点没填模型」。

> **「留空即继承」要求真的留空。** 继承型键写成 `KEY=`（等号后什么都没有）与「整行不存在」**不等价**：空串会被当成显式值，把继承链就地切断。2026-08-28 之前 `MEMORY_EXTRACT_LM_STUDIO_BASE_URL` 正是这样变成空串，使阶段 2 每次都拼出无协议 URL 而失败。手改 `.env` 时请**删掉整行**而不是清空等号右边；GUI 已经代你处理（留空的继承型键不写进 `.env`）。

### 三个典型场景

只需要改 6 个 `LLM_ROLE_*_ENDPOINT`，GUI 里对应三个一键预设。三个场景的 `MEMORY_EMBEDDING_GATE` 都保持 `auto`。

| 角色 | A 纯本地 | B 纯在线（双 key） | C 混合：对话在线 · 整合本地 |
|---|---|---|---|
| `CHAT` | `LOCAL` | `ONLINE_CHAT` | `ONLINE_CHAT` |
| `ROUTER` | `LOCAL` | `ONLINE_CHAT`（挑廉价模型） | `ONLINE_CHAT`（挑廉价模型） |
| `PLUGIN` | `LOCAL` | `ONLINE_CHAT` | `ONLINE_CHAT` |
| `COMPACT` | `LOCAL` | `ONLINE_MEMORY` | `LOCAL` |
| `CONSOLIDATION` | `EXTRA` | `ONLINE_MEMORY` | `LOCAL` |
| `EXTRACT` | `LOCAL` | `ONLINE_MEMORY`（挑强模型） | `LOCAL` |

场景 C 是省钱与隐私的折中：只有对话生成出网，群聊原文不发给在线服务商。

### 为什么必须两把在线 key

`ONLINE_CHAT` 与 `ONLINE_MEMORY` **必须填不同的 API key**。在线服务商的提示词缓存按 key 划分缓存域，而这两类调用的提示词前缀完全不同（对话带人格与上下文，整合带整合指令与群聊原文）。共用一把 key 会让两边不断互相打断对方的前缀缓存，缓存命中率塌到接近 0，省钱的前提就没了。

GUI 在两把 key 相同时给出警告；`registry` 的键共用检查会把它作为 warn 写进 doctor 报告。

### 失败回退

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `LLM_FALLBACK_ENABLED` | `true` | 全局开关 |
| `LLM_FALLBACK_COOLDOWN` | `300` | 端点失败后冷却多少秒再重试它 |
| `LLM_ROLE_<角色>_FALLBACK_ENDPOINT` | 空 | 该角色失败时改用哪个端点槽 |

**回退只在角色显式写了 `FALLBACK_ENDPOINT` 时才发生**，全局开关本身不会替你选备用端点。典型用法：在线对话回退到 `LOCAL`，网络抖动或额度耗尽时降级而不是不说话。

### 成本控制：用量记账与每日预算

在线端点按 token 计费，记忆域（整合 / 压缩 / 提取）又是高频后台任务——**不记账就不知道钱花在哪，没有预算就没有上限**。用量按「日期 × 角色 × 端点槽 × 模型」累加进 `llm_usage_daily` 表，在 GUI「运行状态」页与 `python -m deploy status` 里可见。

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `LLM_USAGE_ACCOUNTING` | `true` | 是否把用量落库。关掉则完全不挂钩子、不建表、不写库 |
| `LLM_DAILY_TOKEN_BUDGET` | `0` | 每日 token 预算（输入 + 输出之和），**0 = 不限** |
| `LLM_BUDGET_SCOPE` | `online` | 预算算哪些端点：`online` 只算在线（本地不花钱）／`all` 全算 |
| `LLM_BUDGET_EXHAUSTED_ACTION` | `pause_memory` | 撞破预算之后做什么，三档见下 |

撞破预算之后的三档动作：

| 值 | 行为 |
|---|---|
| `pause_memory`（默认） | 只停记忆域三个角色（整合 / 压缩 / 提取），**群里照常能说话** |
| `pause_all` | 连对话一起停：被拦下的消息**静默不回**，只写一条 warn 日志。不发提示句、也不回落到本地端点——回落会让「全停」名不副实，而纯在线部署本来就没有本地端点可落 |
| `warn_only` | 只在日志里告警一次，从不拦任何调用 |

认不出的值按最保守的 `pause_memory` 处理。

三条容易踩的点：

- **预算按本地日期在零点自然翻滚**，用的是日期键而不是计时器；进程重启当天的累计从表里读回，不清零（否则「每日预算」会变成「每次启动后 24 小时」）。
- **关掉记账等于关掉预算**：没有用量数据，超额无从判断。`LLM_DAILY_TOKEN_BUDGET` 会变成一个不生效的数字，doctor 会为此报 warn。
- **超额只是 warn，不阻塞启动**：默认动作下对话仍然可用，拿它拦住启动等于把「记忆暂时不更新」升级成「Bot 起不来」。

日账保留 90 天后在读回时自动清理，这个天数写死不给配置项——一天最多几十行，没有需要调的理由；真要长期留存应该导出，而不是让库无限长。

#### 缓存命中率：唯一能验证前缀缓存生效的手段

用量面板里的**缓存命中率分母是输入 token 而不是调用次数**（一次长请求命中一半，与两次短请求各命中全部，省下来的钱完全不同）。

这个数字长期是 0，说明提示词的固定前缀被破坏了，前缀缓存根本没生效——最常见的原因是前缀里混进了每次都变的内容（时间戳、随机排序的记忆列表），或者 `ONLINE_CHAT` 与 `ONLINE_MEMORY` 共用了同一把 key（见上一节）。在线部署跑上半小时后应当去看一眼这个数。

### embedding 不随 LLM 上线

`MEMORY_EMBEDDING_*` 恒定指向本机，**不参与端点/角色体系**。换 embedding 模型等于换向量维度，整库向量都要重算，不能随「今天用在线」这种决定一起漂。GUI 的角色矩阵里 embedding 那一行端点列固定灰显。

它只需要决定排队闸门归属：

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `MEMORY_EMBEDDING_GATE` | `auto` | `auto` = 与本地 LLM 槽共用闸门（没有本地 LLM 端点时等于不排队）；`<槽名>` = 指定共用哪个槽的闸门；`none` = 不排队 |

`auto` 的两种解析结果都是对的：本地槽存在时共用闸门可避免 embedding 与聊天抢同一个 LM Studio；纯在线部署下没有本地 LLM 端点，embedding 独占本机，排队只会白等。

### 主聊天模型

本节与下面的「记忆整理模型」「记忆候选提取」三段的键**仍然是配置的主入口**（向导写的就是它们，GUI 里本机与备用两张端点卡片上的「模型 ID」也是它们），同时充当上面角色键的继承上游——`LLM_ROLE_CHAT_MODEL` / `_ROUTER_MODEL` / `_COMPACT_MODEL` 留空时都取 `LM_STUDIO_MODEL`。只有要让某个角色**不同于**本机默认时，才需要填对应的 `LLM_ROLE_*`。

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `LM_STUDIO_BASE_URL` | `http://127.0.0.1:1234` | LM Studio 地址 |
| `LM_STUDIO_MODEL` | 空 | 模型 ID，留空由服务端默认路由 |
| `LLM_TIMEOUT` | `90.0` | 单次生成超时（秒） |

### 记忆整理模型

整合与聊天分离，可指向同一实例的不同模型或独立端口。**建议整合模型走 CPU 推理**，避免与主聊天模型抢占显存。

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `CONSOLIDATION_LM_STUDIO_BASE_URL` | 同 `LM_STUDIO_BASE_URL` | 整合服务地址 |
| `CONSOLIDATION_LM_STUDIO_MODEL` | `google/gemma-4-e4b` | 整合模型 ID |
| `CONSOLIDATION_LM_STUDIO_TEMPERATURE` | `0.3` | 低温保证 JSON 输出稳定 |
| `CONSOLIDATION_LOCAL_BATCH_SIZE` | `30` | 常规整合批次大小 |
| `CONSOLIDATION_LOCAL_FORCE_BATCH_SIZE` | `10` | force 路径（@ 触发/主动发言前）的小批次 |
| `CONSOLIDATION_OVERLAP` | `15` | 向前回看条数，保证话题不被批次边界切断 |
| `CONSOLIDATION_LOCAL_MAX_TOKENS` | `1200` | 整合最大生成 token |
| `CONSOLIDATION_TRIGGER_NEW_MESSAGES` | `10` | 累积多少新消息才触发一次整合 |

#### 整合走在线时的另一组批量

上面那组 `CONSOLIDATION_LOCAL_*` 是**本地**端点的取值：本地推理不计费，代价只是时间，所以批量小、重叠多、force 路径尽快出结果都是对的。切到在线端点后同一组取值就变成「每批都在重复付固定成本」，因此另给一组在线取值，**只在 CONSOLIDATION 角色实际落在在线端点上时生效**（`LLM_ROLE_CONSOLIDATION_ENDPOINT` 指向 `ONLINE_*`）。填成与本地键相同的值即可关掉对应行为。

| 配置项 | 默认值 | 对应的本地键 | 说明 |
|---|---|---|---|
| `CONSOLIDATION_ONLINE_BATCH_SIZE` | `60` | `CONSOLIDATION_LOCAL_BATCH_SIZE`（30） | 固定 prompt 成本按批摊薄，批量翻倍等于把每条消息摊到的固定成本砍半 |
| `CONSOLIDATION_ONLINE_FORCE_BATCH_SIZE` | `30` | `CONSOLIDATION_LOCAL_FORCE_BATCH_SIZE`（10） | force 路径本来用 1/3 的批量付同一份固定成本，是全链路单位成本最高的一条路径 |
| `CONSOLIDATION_ONLINE_OVERLAP` | `0` | `CONSOLIDATION_OVERLAP`（15） | 0 = 不重叠。重叠消息每批都要重复计费，而话题连续性已经由每批都在传的 `current_summary` 承担 |

> ⚠️ **省钱只能靠加大批量，绝不能靠拉长 `CONSOLIDATION_SCHEDULE_INTERVAL`。** 厂商的前缀缓存是分钟级 TTL，间隔一旦超过 TTL，固定前缀就从缓存价回到全价，反而更贵。间隔请保持 ≤ 4 分钟——这与「减少调用次数」的直觉相反，但账单上是这么算的。

> 把 force 批量从 10 提到 30 只会让摘要新鲜度稍滞后，不会让 @ 变慢：force 整合走 `asyncio.create_task` 的 fire-and-forget，不在 @ 回复的关键路径上。

> **在线端点建议同时收紧 `LLM_ROLE_CONSOLIDATION_MAX_TOKENS`**（默认继承 `CONSOLIDATION_LOCAL_MAX_TOKENS` 的 1200）。在线模型的输出单价通常是输入的 3~4 倍，而整合阶段 1 的实际输出很少超过 800 token；填 `800` 能砍掉一截纯粹白付的余量。**不要压到 600 以下**——输出被截断会导致 JSON 解析失败，见上一条注意事项。默认值刻意不动：本地推理不计费，没有收紧的理由。

> `CONSOLIDATION_LM_STUDIO_BASE_URL` 现在还是 `EXTRA` 端点槽的继承上游，`CONSOLIDATION_LM_STUDIO_MODEL` / `_TEMPERATURE` / `CONSOLIDATION_LOCAL_MAX_TOKENS` 则是 `LLM_ROLE_CONSOLIDATION_*` 的上游。**不要因为改用了角色键就删掉它们**——删掉会把 `EXTRA` 槽的地址一起清空。整合改走在线只需设 `LLM_ROLE_CONSOLIDATION_ENDPOINT=ONLINE_MEMORY`，模型填在 `LLM_ENDPOINT_ONLINE_MEMORY_MODEL` 上。

> **注意 `CONSOLIDATION_LOCAL_MAX_TOKENS`**：批次 30 + overlap 15 意味着单次最多喂入 45 条消息，输出被截断会导致 JSON 解析失败，而解析失败时 checkpoint **仍会推进**（防止同批反复重跑），那批消息就永久丢失了。`core/llm/lm_studio.py` 会在 `finish_reason=length` 时输出告警，建议运行一段后检查日志有无该告警。

### 整合调度

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `CONSOLIDATION_SCHEDULE_INTERVAL` | `120` | 定时整合的检查间隔（秒） |
| `CONSOLIDATION_MAX_ROUNDS_PER_RUN` | `3` | 单次定时任务最多连续整合几批 |
| `CONSOLIDATION_BACKLOG_WARN` | `300` | 积压超过该条数时日志提升为 warning |
| `CONSOLIDATION_MAX_SKIP_STREAK` | `3` | 预筛连续跳过多少次后强制整合一次（`0` = 不兜底，不建议） |

> **为什么需要定时整合**：整合此前只在 @ 触发与主动发言前进行，被动摄入速度超过整合速度时会无界积压（2026-08-16 实测积压 1004 条），且超过 `MESSAGE_CLEANUP_KEEP_COUNT` 后未整合消息会被清理直接丢弃。
>
> 单次批数不宜过多：CPU 小模型单批 20~60 秒，批次太多会长时间占用整合模型，太少则追不上积压。

**`CONSOLIDATION_MAX_SKIP_STREAK` 兜的是什么**：整合前有一道**纯本地、零成本**的预筛（图片刷屏、单字应答、@ 占比过低、与上一批语义高度重复），命中就跳过这一轮，把消息攒到下一轮——**跳过时不推进 checkpoint，所以跳过是攒批，不是丢弃**。但如果某个群长期只有图片刷屏，它会无限滞留下去；连续跳过达到这个次数就强制整合一次并清零，保证最坏情况下只是延迟，不是丢失。

### 记忆候选提取（阶段 2）

整合分两阶段执行：

| 阶段 | 任务 | 模型 |
|---|---|---|
| 阶段 1 | 短期摘要 + 用户画像 + `has_self_disclosure` 布尔判断 | 整合模型（CPU 小模型） |
| 阶段 2 | 精确提取 `memory_candidates` | 本段配置的模型（默认继承主聊天模型） |

阶段 2 **只在阶段 1 判定本批含用户自我披露时才唤醒**（软门槛）。这样日常刷屏、寒暄、第三方讨论只花小模型的算力。

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `MEMORY_EXTRACT_ENABLED` | `true` | 关闭则退回单阶段（整合模型一次性出全部） |
| `MEMORY_EXTRACT_LM_STUDIO_BASE_URL` | 同 `LM_STUDIO_BASE_URL` | 提取服务地址 |
| `MEMORY_EXTRACT_LM_STUDIO_MODEL` | 同 `LM_STUDIO_MODEL` | 默认继承主聊天模型 |
| `MEMORY_EXTRACT_LM_STUDIO_TEMPERATURE` | `0.2` | 抽取任务不需要发散，比整合的 0.3 更低 |
| `MEMORY_EXTRACT_MAX_TOKENS` | `1000` | 只输出候选数组，不需要很大 |

> 这四个 `MEMORY_EXTRACT_LM_STUDIO_*` / `MEMORY_EXTRACT_MAX_TOKENS` 是 `LLM_ROLE_EXTRACT_*` 的继承上游。要让阶段 2 走在线强模型，改 `LLM_ROLE_EXTRACT_ENDPOINT` 即可（模型取该端点的 `MODEL`；要与同端点其他角色用不同的模型才需要写 `LLM_ROLE_EXTRACT_MODEL`），本节的键不用动。

**为什么要拆**：小模型能总结主题，却在噪音环境下系统性地把候选提取判空。2026-08-16 实测 7 批整合全部返回空候选，而信息明确出现在它自己写的摘要里——是「读到了但主动弃掉」，不是没看到。候选提取是高精度抽取任务，交给大模型。

`probe_consolidation.py` 的 `insomnia_breakfast_noisy` 用例锁住了这个差异：同样的信息埋在 Bot 寒暄与刷屏之中，单阶段命中 1/2、两阶段命中 2/2。

**代价**：实测提取单次占用主聊天模型约 20 秒（1600 prompt tokens + 280 生成 @19 tok/s）。默认配置下（EXTRACT 与 CHAT 都绑在 `LOCAL` 槽）它与聊天走同一道闸门、FIFO 串行，因此聊天期间发起的提取会排在后面，反之亦然。把两者拆到不同端点槽（例如 EXTRACT 走 `ONLINE_MEMORY`）后这道串行就消失了，见 [LLM 资源调度](#llm-资源调度)。

### 向量语义检索（可选）

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `MEMORY_EMBEDDING_ENABLED` | `false` | 关闭时用规则版词面语义（离线、确定） |
| `MEMORY_EMBEDDING_BASE_URL` | `http://127.0.0.1:1234` | embedding 服务地址 |
| `MEMORY_EMBEDDING_MODEL` | 空 | 向量模型 ID |
| `MEMORY_EMBEDDING_TIMEOUT` | `10.0` | 单次请求超时（秒） |
| `MEMORY_EMBEDDING_CONTEXTUAL_MIN` | `0.25` | embedding 路径下 `CONTEXTUAL` 记忆的主题匹配余弦阈值 |

服务或模型不可用时**自动回退规则版**，链路不中断。

### LLM 资源调度

LM Studio **不限制并发**：多个请求同时打到同一模型时服务端不会排队，只会把并发推理挤在一起，让每个请求都变慢且难以定位是谁在抢算力。因此应用层必须为共享模型加闸门。

**闸门就是端点槽**：一个角色排在哪道闸门后面，取决于它的 `LLM_ROLE_<角色>_ENDPOINT` 指向哪个槽，并发上限取该槽的 `LLM_ENDPOINT_<槽名>_CONCURRENCY`。同槽内 FIFO 严格串行，不同槽之间真正并行。默认（纯本地）落成两道：

| 闸门（槽） | 谁在用 | 默认并发 |
|---|---|---|
| `LOCAL` | 聊天回复、兜底判定、插件、会话压缩、候选提取，以及 `MEMORY_EMBEDDING_GATE=auto` 下的 embedding 编码 | `1` |
| `EXTRA` | 两阶段整合的阶段 1 | `1` |

把对话切到 `ONLINE_CHAT` 之后，聊天与本地整合就落在不同槽上，不再互相排队——这是切在线除省显存之外的另一个收益。

> `core/llm/scheduler.py` 里的 `RESOURCE_CHAT` / `RESOURCE_CONSOLIDATION` 两个常量是旧资源名，项目内已无调用点，保留只为不破坏外部 import。用它们 acquire 会建出一把**与任何端点都不对应**的独立闸门，起不到串行保护作用；新代码请用 `registry.gate_of(role)`。

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `LLM_SCHEDULER_WAIT_WARN_SECONDS` | `30.0` | 排队等待超过该秒数则告警 |
| `LLM_SCHEDULER_HOLD_WARN_SECONDS` | `90.0` | 单次持有超过该秒数则告警 |
| `LLM_SCHEDULER_QUEUE_WARN_DEPTH` | `3` | 排队深度达到该值即告警 |
| `LLM_SCHEDULER_PRIORITY_ENABLED` | `false` | **尚未实现**，保留开关 |
| `LLM_SCHEDULER_GATE_EMBEDDING` | `true` | **已废弃**，被 `MEMORY_EMBEDDING_GATE` 取代（本键 `true`→`auto`、`false`→`none`）。仅在未显式设置新键时仍被读取 |

持有告警的阈值考虑了后端的 3 次重试（每次超时 120 秒），因此单次持有的上界远大于一次正常请求；持续超阈值说明不是排队，而是调用本身卡住了。

`MEMORY_EMBEDDING_GATE` 默认 `auto` 的原因：`MEMORY_EMBEDDING_BASE_URL` 默认与主聊天同一个实例，而一次检索要对每条候选记忆各编码一次（候选池可达 20+），不串行会出现间歇性变慢且极难定位。若把 embedding 部署在独立实例，设 `none` 可避免不必要的串行。`python -m deploy doctor` 会把 `LLM_SCHEDULER_GATE_EMBEDDING` 提示为旧键。

**优先级为什么没实现**：多群下严格 FIFO 会让 @ 回复排在后台任务之后。但后台任务每群最多 1 个在途、数量有界，实际影响需要真实排队数据才能判断。先积累 `core.llm.snapshot()` 的观测数据，再决定是否偏离 FIFO。

## 上下文

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `RECENT_TAIL_LIMIT` | `12` | 每次回复附加的最近原始消息条数（含 Bot 自己的发言） |
| `RECENT_TAIL_MAX_AGE_MINUTES` | `45.0` | 尾巴时间窗（分钟）：超出时长的消息不再算「最近的对话」；`0` 不做时间过滤 |
| `RECENT_TAIL_GAP_MARK_MINUTES` | `15.0` | 相邻消息间隔超过该分钟数时在尾巴里插入断层标记；`0` 关闭 |
| `SHORT_TERM_SUMMARY_STALE_MINUTES` | `60.0` | 摘要超时未更新则标题改为「之前的话题」并注明时长；`0` 关闭 |
| `MAX_REPLY_LINES` | `5` | 单次回复最大行数 |
| `SEND_INTERVAL` | `0.8` | 多行之间的发送间隔（秒） |
| `FALLBACK_REPLY` | `......？` | 兜底回复 |
| `BAD_PHRASES` | 见 settings.py | 破防语句清单，命中即替换为兜底回复 |

> **`RECENT_TAIL_LIMIT` 的权衡**：太小会让活跃群的刷屏把 Bot 自己的提问挤出窗口，用户的简短回应（「手机」「对」）会被接到上一个话题上；太大则无关历史干扰模型且 prompt 变长。12 是起点，需按群的刷屏速度调整。

> **尾巴的时间窗与断层标记**：仅按 id 取最近 N 条时，停机数小时后重启会把几小时前的对话当成刚刚发生的事（2026-08-15 缺陷）。`RECENT_TAIL_MAX_AGE_MINUTES` 过滤掉超时消息；窗口内部相邻消息间隔超过 `RECENT_TAIL_GAP_MARK_MINUTES` 时插入一行「（……中间隔了 X……）」标记，让模型知道「之前聊过但已经过去很久」，而非直接失忆。

### 会话上下文压缩

短时连续对话中，早期消息会滚出尾巴窗口而彻底消失。本机制把滚出的部分压缩成一段回顾，使 Bot 在长对话里保持连贯（类似 coding agent 的 compact）。

**三层上下文按消息 id 划分，绝不重叠**：

| 层 | 范围 |
|---|---|
| 会话摘要 | `summarized_up_to_id` → 尾巴起点（较早部分，已压缩） |
| 原始尾巴 | 最近 `RECENT_TAIL_LIMIT` 条（原文） |
| 话题摘要 | 整合器产出的跨会话背景 |

重叠会导致同一段对话出现两个版本，模型以摘要为准从而接错话题（2026-08-13 缺陷的成因）。

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `SESSION_CONTEXT_ENABLED` | `true` | 会话压缩总开关 |
| `SESSION_COMPACT_THRESHOLD_TOKENS` | `600` | 待压缩文本超过该 token 估算值才触发 |
| `SESSION_SUMMARY_MAX_TOKENS` | `300` | 摘要自身的预算，超过则连同新内容重新压缩 |
| `SESSION_COMPACT_MAX_MESSAGES` | `60` | 单次压缩最多喂入的消息条数 |
| `SESSION_IDLE_TIMEOUT_SECONDS` | `900.0` | 空闲多久视为会话结束（结束时清空摘要并触发一次完整整合） |
| `SESSION_IDLE_CHECK_INTERVAL` | `300` | 空闲检查间隔（秒） |

压缩用**主聊天模型**而非整合模型：整合模型跑 CPU、单次 20~60 秒，而压缩在每次回复之后异步触发，必须快。压缩不阻塞当前回复，摘要从下一轮开始生效。

会话结束时整合一次的理由：这一场对话的内容此前只以压缩摘要形式存在于内存，重启即失；结束时整合把它沉淀为长期记忆的候选。

## 记忆：捕获与晋升

### 来源分级与候选强化

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `MEMORY_SOURCE_KIND_ENABLED` | `true` | 关闭后所有消息等权，prompt 不标注来源 |
| `MEMORY_AT_MENTION_CONFIDENCE_BONUS` | `0.05` | `AT_MENTION` 来源候选的置信度奖励 |
| `MEMORY_CANDIDATE_REOCCURRENCE_BONUS` | `0.12` | 同一事实复现时的置信度增益 |
| `MEMORY_CANDIDATE_MAX_OBSERVING_DAYS` | `30` | 观察区停留上限，超期标 `REJECTED`（不删除） |
| `MEMORY_CANDIDATE_EVIDENCE_MAX_CHARS` | `800` | `evidence` 累积上限 |

`0.12` 的取值使 0.5 起步的候选约 2 次复现后跨过 0.6 门槛。

### Gate 1 三档

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `MEMORY_CONFIRM_HIGH_CONFIDENCE` | `0.85` | 达到即直接晋升 |
| `MEMORY_OBSERVE_LOW_CONFIDENCE` | `0.6` | 达到则看证据充分度 |
| `MEMORY_PROMOTE_MIN_OCCURRENCE_PASSIVE` | `2` | 被动来源晋升所需的最低观察次数 |
| `MEMORY_PROMOTE_AT_MENTION_SINGLE_SHOT` | `true` | `AT_MENTION` 来源是否单次即可晋升 |
| `MEMORY_PROMOTE_MIN_IMPORTANCE` | `0.3` | 晋升所需的最低重要度（下限，不单独构成依据） |

### 每用户配额

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `MEMORY_QUOTA_ENFORCE` | **`false`** | 关闭时只输出 dry-run 日志，不实际淘汰 |
| `MEMORY_USER_QUOTA` | `25` | 单用户在**单个共享空间**的 active 记忆上限 |
| `MEMORY_QUOTA_W_IMPORTANCE` | `0.4` | 竞争分权重：重要度 |
| `MEMORY_QUOTA_W_CONFIRMATION` | `0.3` | 竞争分权重：被确认次数 |
| `MEMORY_QUOTA_W_RECENCY` | `0.3` | 竞争分权重：近期访问 |
| `MEMORY_QUOTA_CONFIRMATION_CAP` | `3` | 确认次数归一化上限 |

> **开启前先观察**。`MEMORY_QUOTA_ENFORCE=false` 时日志会输出 `[Quota dry-run] ... 本来会淘汰 xxx`，确认淘汰对象合理后再开启。淘汰是置 `archived` 而非删除，但恢复需要手工 SQL。

> 多个 QQ 群归入同一空间时配额实际收紧了（同一个人在同一空间只有一份认知）。这符合设计，但调参时需要知道。

## 记忆：检索与排序

### RAG 开关

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `RAG_ENABLED` | `true` | 关闭则永远走加权回退排序 |
| `RAG_SQLITE_FTS_ENABLED` | `true` | 是否使用 FTS5 全文索引 |
| `RAG_TOP_K` | `5` | FTS 候选池下限 |
| `MEMORY_V2_ENABLED` | `true` | 关闭则回退旧检索与旧 Prompt 组装 |

### 排序权重

六维加权，权重和约为 1.0。原则是 **Policy / Context 优先于相似度**——避免「找错」而非「找不到」。

| 配置项 | 默认值 | 维度 |
|---|---|---|
| `MEMORY_SCORE_W_CONTEXT` | `0.25` | 上下文契合（触发条件 / 用途契合度） |
| `MEMORY_SCORE_W_USAGE` | `0.20` | 用途与当前模式的匹配度 |
| `MEMORY_SCORE_W_SEMANTIC` | `0.35` | 语义相似（embedding 余弦或词面回退） |
| `MEMORY_SCORE_W_RECENCY` | `0.10` | 时效衰减（指数，τ=30 天） |
| `MEMORY_SCORE_W_CONFIDENCE` | `0.05` | 置信度 |
| `MEMORY_SCORE_W_IMPORTANCE` | `0.05` | 重要度 |

`confidence` / `importance` 权重刻意压低：它们描述「记忆本身可靠/重要」，与「当前该不该用这条」关系弱，只适合做 tie-breaker。

未启用 embedding 时，语义维会被丢弃并把剩余权重重新归一化。

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `MEMORY_SCORE_MIN` | `0.40` | 低于此分不进 Prompt（动态数量而非固定 Top-K） |
| `MODE_DETECT_MIN_SCORE` | `0.5` | Mode 检测的最低得分，低于则回退 `CASUAL_REPLY` |
| `USAGE_TYPE_MISMATCH_PENALTY` | `0.75` | 用途与类型不兼容时的降权系数（非硬排除） |

### 各模式记忆条数上限

| 配置项 | 默认值 |
|---|---|
| `MEMORY_LIMIT_CASUAL_REPLY` | `3` |
| `MEMORY_LIMIT_ACTIVE_JOIN` | `3` |
| `MEMORY_LIMIT_HUMOR` | `3` |
| `MEMORY_LIMIT_TECH_HELP` | `5` |
| `MEMORY_LIMIT_RECOMMEND` | `5` |
| `MEMORY_LIMIT_EMOTIONAL` | `3` |
| `MEMORY_LIMIT_CONFLICT_AVOID` | `10` |
| `MEMORY_LIMIT_GROUP_EVENT` | `5` |

`CONFLICT_AVOID` 上限最大是安全优先——行为约束宁多勿漏。

### Prompt 长度预算

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `MEMORY_CONVERSATION_MAX_TOKENS` | `500` | 聊天素材区上限 |
| `MEMORY_CONVERSATION_TECH_MAX_TOKENS` | `1000` | 技术场景放宽 |
| `MEMORY_BEHAVIOR_MAX_TOKENS` | `150` | 行为约束区上限 |

### 旧检索（`MEMORY_V2_ENABLED=false` 时生效）

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `PROACTIVE_LONG_TERM_LIMIT` | `10` | 主动发言时引用的记忆条数 |
| `REPLY_LONG_TERM_LIMIT` | `3` | @ 回复时引用的该用户记忆条数 |
| `LONG_TERM_RELEVANCE_ENABLED` | `true` | 是否对他人旧记忆做关键词相关度筛选 |
| `LONG_TERM_RELEVANCE_KEYWORDS` | `5` | 提取的关键词数量 |
| `LONG_TERM_RELEVANCE_CANDIDATE_LIMIT` | `20` | 候选池上限 |
| `LONG_TERM_RELEVANCE_WEIGHT_KEYWORDS` | `2.0` | 加权：关键词重叠 |
| `LONG_TERM_RELEVANCE_WEIGHT_RECENCY` | `1.0` | 加权：最近访问 |
| `LONG_TERM_RELEVANCE_WEIGHT_IMPORTANCE` | `1.2` | 加权：重要度 |
| `LONG_TERM_RELEVANCE_WEIGHT_CONFIDENCE` | `0.8` | 加权：置信度 |
| `LONG_TERM_RELEVANCE_WEIGHT_USER_RELEVANCE` | `0.6` | 加权：用户相关性 |

## 主动发言

### 话题参与概率曲线

双锚点插值 + 幂次整形。同一条曲线通过参数即可表达两种相反意图，无需模式开关。

```
interval <= FAST → PROB_AT_FAST
interval >= SLOW → PROB_AT_SLOW
中间             → t = (SLOW - interval) / (SLOW - FAST)
                   prob = PROB_AT_SLOW + (PROB_AT_FAST - PROB_AT_SLOW) × t^GAMMA
```

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `PROACTIVE_ENABLED` | `true` | 主动发言总开关 |
| `PROACTIVE_INTERVAL_FAST` | `20.0` | 视为「高频」的平均间隔上界（秒） |
| `PROACTIVE_INTERVAL_SLOW` | `180.0` | 视为「冷清」的平均间隔下界（秒） |
| `PROACTIVE_PROB_AT_FAST` | `0.15` | 高频端概率 |
| `PROACTIVE_PROB_AT_SLOW` | `0.0` | 冷清端概率 |
| `PROACTIVE_PROB_GAMMA` | `1.0` | 曲线整形指数，>1 更保守 |
| `PROACTIVE_TOPIC_WARMUP_SECONDS` | `45.0` | 话题预热时长，不足则不参与 |
| `PROACTIVE_COOLDOWN` | `600` | 群级硬冷却（秒） |
| `PROACTIVE_CHECK_INTERVAL` | `60` | 定时检查间隔（秒） |
| `PROACTIVE_FREQ_WINDOW` | `10` | 频率估算窗口（最近 N 条消息） |
| `PROACTIVE_MAX_LINES` | `1` | 主动插话最大行数 |
| `PROACTIVE_MIN_MESSAGES_SINCE_SPOKE` | `15` | 距上次自己发言，群里至少要有多少条新消息才允许再开口。0 表示不限制 |

**三种预设**：

```env
# 热闹时插话（默认，适合闲聊群）
PROACTIVE_PROB_AT_FAST=0.15
PROACTIVE_PROB_AT_SLOW=0.0

# 热闹时闭嘴（旧行为，适合技术群）
PROACTIVE_PROB_AT_FAST=0.05
PROACTIVE_PROB_AT_SLOW=0.5

# 完全关闭话题参与（保留主动 @）
PROACTIVE_PROB_AT_FAST=0.0
PROACTIVE_PROB_AT_SLOW=0.0
```

**为什么需要消息数门槛**：纯时间冷却在冷清群里会造成「自己说完等 10 分钟又自己说」。消息数门槛能保证「话题真的往前走了」才插话。该计数是进程内的，重启后视为「新消息足够」，不会因重启而永久卡住主动发言。

三种预设的实际频率参考（`CHECK_INTERVAL=60`）：`PROB_AT_FAST=0.15` 时活跃群命中期望约 6.7 分钟，叠加 `COOLDOWN=600` 与消息门槛后，实际发言间隔通常在 10 分钟以上。

### 主动 @ 用户

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `PROACTIVE_AT_ENABLED` | `true` | 主动 @ 总开关 |
| `PROACTIVE_AT_QUOTA_BASE` | `2` | 每用户每日基础配额 |
| `PROACTIVE_AT_QUOTA_BONUS_MAX` | `2` | 高频用户最多上浮次数 |
| `PROACTIVE_AT_BONUS_MSGS_LOW` | `20` | 奖励起点（24h 发言数） |
| `PROACTIVE_AT_BONUS_MSGS_HIGH` | `100` | 奖励满点 |
| `PROACTIVE_AT_USER_COOLDOWN` | `7200.0` | 同一用户两次主动 @ 的最小间隔（秒） |
| `PROACTIVE_AT_ACTIVE_WITHIN` | `300.0` | 判定「正在活跃」的时间窗（秒） |
| `PROACTIVE_MAX_NO_REPLY` | `2` | 连续无回应上限，超过则暂停追问 |
| `PROACTIVE_REPLY_WINDOW_SECONDS` | `300.0` | 回应检测窗口（秒） |
| `PROACTIVE_COLDSTART_TOPICS` | 见 settings.py | 冷启动话题清单，逗号分隔 |
| `PROACTIVE_AT_EXCLUDE_USERS` | 空 | 不会被选为主动搭话对象的 QQ 号（逗号分隔） |

排除名单的主要用途是**群内其他 AI** —— 互相 @ 会触发无终止的循环对话。被排除的账号仍会被动收集信息（消息照常落库与整合），只是不主动向它们提问。

配额上限硬封顶在 `BASE + BONUS_MAX`（默认 4 次/天）。**「越活跃越被骚扰」是必须避免的失控模式**，因此奖励幅度不建议调大。

配额为「发出即计数」，不论用户是否回应——否则无回应的追问不占配额，会导致对同一人连续搭话。

### 睡眠时段

模拟人类作息：睡眠期间关闭一切主动发言（话题插话 + 主动 @），但**被 @ 时照常回复**。

不在睡眠期停止回复的理由：用户主动叫它却不回应看起来像掉线，且 `AT_MENTION` 是当前唯一的记忆来源，睡眠期不回复等于每天损失数小时的采集。被动信息收集（消息落库、整合）在睡眠期照常进行。

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `PROACTIVE_SLEEP_ENABLED` | `true` | 睡眠时段总开关 |
| `PROACTIVE_SLEEP_START` | `23:30` | 入睡时刻（`HH:MM`，**本地时间**） |
| `PROACTIVE_SLEEP_END` | `07:30` | 苏醒时刻（`HH:MM`，**本地时间**） |
| `PROACTIVE_WAKEUP_GRACE_SECONDS` | `900.0` | 醒来缓冲：苏醒后多久内仍不主动发言 |
| `PROACTIVE_SLEEP_ANNOUNCE` | `true` | 是否在入睡/苏醒时播报一句 |
| `PROACTIVE_SLEEP_MESSAGES` | 见 settings.py | 入睡播报台词（逗号分隔，随机选一条） |
| `PROACTIVE_WAKEUP_MESSAGES` | 见 settings.py | 苏醒播报台词 |

支持跨午夜区间（`START > END` 时视为跨天）。`START == END` 视为不睡眠。时间格式非法时回退到默认值并输出警告——配置笔误不应让 Bot 通宵说话。

**这里用本地时间而非 UTC**：它描述的是人类作息，与数据库时间戳无关。这是全项目唯一该用本地时间的地方。

**醒来缓冲的必要性**：积压一夜的活跃度统计会让 Bot 一睁眼就连发几句。缓冲期从「检测到苏醒跃变」开始计时。

播报按「每群每类每日最多一次」去重（记录在 `group_runtime_state`）。播报由定时任务触发，不去重的话睡眠期内重启会重复播报「我去睡了」。播报不经过 Pipeline（无需 LLM），但会写入 `group_messages`（`BOT_SELF`）供下一轮整合理解语境。

### 运行时开关

管理员可在群内临时关闭主动发言，作为配置级开关之外的另一道闸门。便于部署者在群成员反馈后即时调整。

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `PROACTIVE_RUNTIME_TOGGLE_ENABLED` | `true` | 是否启用运行时开关命令 |
| `PROACTIVE_TOGGLE_ADMINS` | 空 | 额外授权的 QQ 号（逗号分隔）。留空则仅群主/管理员可操作 |

用法：@ 机器人并说出关键词。

| 动作 | 关键词 |
|---|---|
| 静音 | 安静、闭嘴、别说话、停止主动发言 |
| 恢复 | 恢复、醒醒、可以说话、开启主动发言 |

静音状态**持久化在 `group_runtime_state` 表，重启后仍生效**——管理员关掉它通常是因为出了问题，重启不该把它悄悄打开。

静音只影响主动发言，被 @ 时仍照常回复。非管理员触发时不做任何改动也不回复。

## 记忆压缩

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `MEMORY_COMPRESS_LIGHT_THRESHOLD` | `500` | 轻量压缩触发的 active 记忆数 |
| `MEMORY_COMPRESS_LIGHT_COOLDOWN_SECONDS` | `3600` | 轻量压缩冷却（秒） |
| `MEMORY_ARCHIVE_IMPORTANCE_THRESHOLD` | `0.3` | 低价值归档的重要度阈值 |
| `MEMORY_ARCHIVE_INACTIVE_DAYS` | `180` | 低价值归档的未访问天数 |
| `MEMORY_COMPRESS_LOG_PATH` | `logs/memory_compressor_log.md` | 压缩日志（见[日志](#日志)） |
| `MEMORY_RECENCY_HALF_LIFE_DAYS` | `120.0` | Recency 兜底半衰期（天） |

`MEMORY_DECAY_DAYS` 是代码内的字典（不走 `.env`），定义各类型记忆的生命周期：

| 类型 | 天数 |
|---|---|
| `FACT` | 730 |
| `STYLE` | 365 |
| `PREFERENCE` / `RELATION` | 180 |
| `EVENT` / `PLAN` | 60 |
| `GROUP_CONTEXT` | 30 |

## 决策追踪与清理

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `MEMORY_TRACE_ENABLED` | `true` | 是否记录记忆决策轨迹 |
| `MEMORY_TRACE_TABLE` | `memory_traces` | 追踪表名 |
| `MESSAGE_CLEANUP_ENABLED` | `true` | 是否启用消息表定期清理 |
| `MESSAGE_CLEANUP_KEEP_COUNT` | `1000` | 每群保留的最近消息条数 |
| `MESSAGE_CLEANUP_HOUR` | `4` | 每日清理时间（24 小时制） |
| `MESSAGE_CLEANUP_PROTECT_UNCONSOLIDATED` | `true` | 清理时保护未整合的消息（checkpoint 之后的不删除） |
| `DB_CLEANUP_ON_START` | `false` | **测试期用**：启动时清空短期/长期记忆并重置 checkpoint |
| `DB_CLEANUP_CLEAR_MESSAGES` | `false` | 清理时是否连原始消息一起删除（危险） |

> `DB_CLEANUP_ON_START=true` 会在每次启动时丢失记忆并重置整合进度。测试结束后务必改回 `false`。

> 关闭 `MESSAGE_CLEANUP_PROTECT_UNCONSOLIDATED` 会导致积压超过 `MESSAGE_CLEANUP_KEEP_COUNT` 时未整合消息被永久丢弃，那些内容永远不会进入记忆系统，且 checkpoint 对齐会让丢失变得不可见。

## HTML → 图片渲染（插件卡片）

大量 AstrBot 插件把结果卡片做成 Jinja2 模板 + CSS，靠 `Star.html_render` 出图。实现见 `astrbot_compat/render.py`。

| 变量 | 默认 | 说明 |
|---|---|---|
| `RENDER_ENABLED` | `true` | 总开关。关闭后卡片类插件一律走它们自己的纯文本降级 |
| `RENDER_AUTO_INSTALL` | `true` | 浏览器内核缺失时首次渲染前自动后台下载 |
| `RENDER_INSTALL_RETRY_SECONDS` | `3600` | 自动安装失败后的冷却（秒） |
| `RENDER_CACHE_DIR` | `data/render_cache` | 渲染产物目录。**不放 `logs/`**——这是要发出去的图片，不是日志 |
| `RENDER_CACHE_KEEP` | `50` | 保留最近多少张产物 |
| `RENDER_MAX_CONCURRENCY` | `2` | 同时最多渲染几张 |
| `RENDER_SETTLE_MS` | `300` | 页面 `load` 之后再等多少毫秒截图 |
| `RENDER_TEXT_WIDTH` | `800` | `text_to_image` / `t2i` 出图宽度（像素） |

**后端是本地 Chromium（playwright），不是远程服务。** 上游 AstrBot 默认把 HTML 发到远程 t2i 服务出图，Stella 不走那条路：模板里填的是群友昵称、动态正文、头像 URL，属于聊天内容。全本地部署下其他环节都在本机，渲染没有理由成为唯一出网的一环；接了在线模型的部署也一样——出网的对象是用户自己挑定的服务商，不该再多一个他没选过的渲染服务。

**依赖分两层**：`playwright` 的 pip 包在 `requirements.txt` 里（几 MB）；浏览器内核约 270MB，**首次真正需要渲染时**才后台下载。下载期间插件照常降级为纯文本，装好后自动生效、不用重启。

只装 headless shell 是刻意的——我们永远只截图，不需要带界面的浏览器：

```bash
python -m playwright install chromium-headless-shell   # 约 270MB
python -m playwright install chromium                  # 约 700MB，含用不到的完整浏览器
```

启动时会按 `chromium-headless-shell` → 默认 `chromium` 的顺序尝试，所以已经装了完整版的机器也能直接跑。

> 部分国内 pip 镜像不收录 `playwright`（实测清华源装不上）。装不上时换官方源：`pip install playwright -i https://pypi.org/simple`。

> `pillow` 也是必需的：插件普遍在拿到图后用 PIL 校验一遍（bilibili 插件的 `_validate_image`），缺了它渲染会以「图片验证失败」的形式静默失效。它已显式写进 `requirements.txt`——此前只是 `qrcode` 的传递依赖恰好带了进来。

**渲染不可用时返回空串而不是抛异常。** 插件普遍在 `if img_path:` 上分支降级（上游的远程服务也会挂），抛异常只会被它的 `except` 吞掉再重试——2026-08-25 实测 bilibili 插件为此白等 3×2s。

`deploy doctor` 会检查渲染后端并给出安装命令；缺失只报 warn，因为它只影响卡片类插件，主链路对话不受影响。

## 能力路由与工具执行

判断一次请求需要哪些能力（聊天 / 记忆 / 工具），并让工具在 Stella 的聊天上下文**之外**执行。设计与排查手册见 [能力系统](capability-system.md)。

### Router

| 变量 | 默认 | 说明 |
|---|---|---|
| `CAPABILITY_ROUTER_ENABLED` | `true` | 总开关。关闭后等同于「照常聊天、照常读记忆、不调工具」 |
| `ROUTER_ROUTE_AUTO_CAPABILITIES` | `false` | 没有声明的插件工具（`tool.<工具名>`）是否参与路由竞争 |
| `ROUTER_RULE_ENABLED` | `true` | Level 0 关键词规则（零延迟、不调模型） |
| `ROUTER_SEMANTIC_ENABLED` | `true` | Level 1 Embedding 语义路由，复用 `MEMORY_EMBEDDING_*` 的服务与模型 |
| `ROUTER_FALLBACK_ENABLED` | `false` | Level 2 模型兜底。只在 L1 落入不确定带时触发 |
| `ROUTER_SEMANTIC_THRESHOLD` | `0.50` | 能力进入候选列表的绝对地板 |
| `ROUTER_TOOL_THRESHOLD` | `0.70` | 判定 `tool=true` 所需的最高分置信线 |
| `ROUTER_CAPABILITY_MARGIN` | `0.12` | 命中能力允许比最高分低多少（相对间距裁剪）。`0` 关闭 |
| `ROUTER_UNCERTAIN_FLOOR` | `0.55` | 不确定带下界。低于它就是「确定不需要工具」，不进 Level 2 |
| `ROUTER_MAX_CAPABILITIES` | `3` | 单次最多路由几个能力 |
| `ROUTER_GATE_MEMORY` | `false` | 是否真的按 `route.memory` 门控长期记忆检索 |
| `ROUTER_TIMEOUT` | `8.0` | 单次判定超时（秒）。超时按降级处理，不阻塞回复 |

> **声明优先（`ROUTER_ROUTE_AUTO_CAPABILITIES=false`）。** 要让一个插件工具能在聊天里被触发，得在 `config/capabilities/*.toml` 里给它写一条 `[[capability]]`。没有声明的工具照常注册、仍可被显式执行，但不参与语义路由——**启动日志会点名有哪些**，所以这不是静默失效。
>
> 依据是 2026-08-24 的首轮实测。工具描述是写给「看着全部工具做选择」的决策器的指令句（`"当用户询问 X 时调用"`），拿它当语义原型去和用户的**问句**算余弦，同一语域的工具之间几乎没有区分度。5 个 bgm/bilibili 工具、12 条用例、真实 embedding 的对照：
>
> | | 工具假阳 | 首位选错 | 无关工具被执行 | 负样本阈值余量 |
> |---|---|---|---|---|
> | 自动派生（工具描述做原型） | 1 | 2 / 5 | 13 次 | **−0.024** |
> | 显式声明（中文 examples 做原型） | 0 | 0 | 0 次 | **+0.141** |
>
> 设成 `true` 可恢复「装上插件就能路由」的旧行为，但**必须同时下调三条阈值**：自动派生的打分整体低约 0.2（正样本只到 0.61~0.71），不调的话工具会静默地永远不触发。

**四条阈值是一组**，2026-08-25 用 `qwen3-embedding-0.6b` 在 12 条用例上标定，前提是能力带中文 `examples`。实测分布：负样本上界 `0.559`、正样本下界 `0.851`。复现：

```bash
python -m capability.router.benchmark --cases capability/router/benchmark/acg.json
```

`ROUTER_TOOL_THRESHOLD=0.70` 取两个分布的中点，两侧余量 +0.141 / +0.151。没有按「工具假阳代价更高」进一步上调，因为样本里只有 1 条是线上真实用户消息，上调会先牺牲真实用户的召回。

`ROUTER_CAPABILITY_MARGIN` 治的是「搭车能力」：一旦 `tool=true`，所有过了绝对地板的能力都会**各自执行一次**，并把结果贴上「真实数据，回答时以此为准」送进 prompt——首轮实测里「帮我推荐一些新番」因此同时调了每日放送和 B 站热门视频。**绝对地板替代不了它**：正确能力实测 0.851~0.911，搭车能力 0.616~0.743，后者高于任何不误杀正样本的地板值。只有相对间距能分开（正确能力与第二名的落差实测 0.155~0.336）。

`ROUTER_MAX_CAPABILITIES` 是延迟阀门——每个命中能力在 Comes 里是一次独立的受限 agent 调用，都排在 `PLUGIN` 角色所绑端点的那道闸门后面（纯本地时是 `LOCAL`，与聊天同一道，见 [LLM 资源调度](#llm-资源调度)）。不设上限会让一条消息卡住整个群的回复。

> **一类假阳只有 Level 2 能治。** 余弦分不开「陈述 X」和「请求 X」：实测「我最近在追新番」得 0.835，与 examples 里的「有什么值得追的新番吗」高度相似。抬阈值治不了（正样本下界 0.851，只剩 0.016 余量）。这条留在 `capability/router/benchmark/acg.json` 里作为已知失败项。

> **`ROUTER_GATE_MEMORY` 默认关闭，不要随手打开。** Router 误判 `memory=false` 会让 Stella 当轮悄悄丢失长期记忆——不抛异常、不影响回复，只是「它突然不记得你了」，与 2026-08-17 那次 `AT_MENTION` 全为 0 的缺陷同一类型（静默、难察觉、后果严重）。打开前先跑 benchmark 确认**记忆假阴为 0**：
>
> ```bash
> python -m capability.router.benchmark              # 全链路（需要 embedding 服务）
> python -m capability.router.benchmark --rules-only # 只测 Level 0，可进 CI
> ```
>
> 退出码 0 表示可以打开。报告把四类错误分开计数，刻意不合成单一准确率——合成会把高代价错误藏在平均值里。

`ROUTER_FALLBACK_ENABLED` 默认关闭是为了省 27B 推理资源：纯本地默认配置下 Level 2（`ROUTER` 角色）与主聊天绑在同一个 `LOCAL` 端点槽上，用同一个模型、排同一道闸门。先靠 L0/L1 跑一段时间、用 benchmark 量出准确率再决定。把 `ROUTER` 单独指到廉价的在线端点可以消掉这层顾虑。

### Comes

| 变量 | 默认 | 说明 |
|---|---|---|
| `COMES_ENABLED` | `true` | 工具执行总开关 |
| `COMES_SYSTEM_PROMPT` | 见 `.env.example` | 执行器人格。刻意不用 Stella 的人格 |
| `COMES_MAX_TOOL_STEPS` | `5` | 单任务工具调用最大轮数 |
| `COMES_TOOL_TIMEOUT` | `60` | 单个工具调用超时（秒） |
| `COMES_TASK_TIMEOUT` | `90` | 单任务总超时（秒），含模型往返 |
| `COMES_SUMMARY_MAX_CHARS` | `300` | 进 Stella prompt 的摘要长度上限 |
| `COMES_DIRECT_CALL_NO_ARGS` | `true` | 单个无参工具时跳过 LLM 直接调用 |
| `COMES_PROVIDER_FAILURE_THRESHOLD` | `3` | 连续失败多少次后退避一个 provider。`0` 表示不退避 |
| `COMES_PROVIDER_RECOVER_SECONDS` | `600` | 退避恢复时间（秒） |

`COMES_MAX_TOOL_STEPS=5` 比 `ASTRBOT_LLM_MAX_TOOL_STEPS=10` 小：Comes 是单一能力的定向执行，需要 5 轮以上通常意味着模型在打转。`COMES_TOOL_TIMEOUT=60` 比 `ASTRBOT_LLM_TOOL_TIMEOUT=120` 短得多：Comes 挂在聊天主链路上，用户在等回复，不能为一个工具等两分钟。

provider 退避是**时间窗**而非永久禁用：插件依赖的外部 API 抖动是常态，永久禁用会让一次网络波动永久关掉一个能力，而这不报错、只表现为「这个功能后来就不好使了」。

### 能力声明

`config/capabilities/*.toml`，**文件名即 domain**。格式与逐项说明见 `config/capabilities/information.toml.example`；随仓库发的一份真实声明是 `config/capabilities/entertainment.toml`（对应 bilibili/bgm 插件的 5 个工具），可以照抄。

**声明不再是可选的**（`ROUTER_ROUTE_AUTO_CAPABILITIES=false` 起）：没有声明的插件工具照常注册、仍可被显式执行，但不参与语义路由。启动日志会点名有哪些工具处于这个状态。

| 字段 | 服务于 | 怎么写 |
|---|---|---|
| `examples` | Level 1 语义匹配的原型语料 | **用户会怎么问**，写成中文问句。不要照抄工具描述——那是写给决策器的指令句（「当用户询问 X 时调用」），与问句不同构，同域工具之间分不开 |
| `keywords` | Level 0 字面匹配 | 名词短语。命中即零延迟拍板，省掉一次 embedding 编码 |
| `providers` | Comes 执行 | `llm_tools` 里的**工具名**（不是插件名）。启动日志的「已登记函数工具」能查到 |

> `keywords` **绝不从 `examples` 里猜**。中文没有词边界，从「会不会下雨」切出来的候选里既有「下雨」也有「不会」，后者会命中几乎任何句子（「我不会用这个软件」→ 去查天气）。Level 0 的职责是处理高置信度请求，猜出来的词达不到这个标准。

两条来自实测的经验：

- **`keywords` 宁缺勿滥，但该给的要给。** 「今天的放送表」的 L1 得分只有 0.641（低于 0.70 的置信线，会漏），靠 `anime.schedule` 的关键词「放送」才被零延迟接住。反面例子：`anime.recommend` 的关键词写成「新番推荐」而不是「新番」，否则「我最近在追新番」会被 Level 0 直接拍板去查。
- **需要参数才能执行的能力不要给 `keywords`。** `anime.search` 要检索关键词、`video.dynamics` 要 UID，Level 0 拿不到这些参数，拍板了也只是让 Comes 去猜。

## OneBot 连接

Bot 通过 OneBot V11 WebSocket 与 NapCat 通信。**NapCat 侧必须先登录**：用
[NapCatQQ Desktop](https://github.com/NapNeko/NapCatQQ-Desktop) 安装并完成 QQ 登录，
Bot 不再代管 NapCat 进程——自动登录会退化为扫码，登录必须有人在场
（见 `design_docs/deprecated_napcat_manager.md`）。

| 方式 | Bot 侧（`.env`） | NapCat 侧（WebUI 网络配置） |
|---|---|---|
| 反向 WS（推荐） | `HOST` + `PORT`（NoneBot 默认 `0.0.0.0:8080`），反向 WS 端点固定 `/onebot/v11/ws` | 添加「WebSocket 客户端」，URL 填 `ws://<Bot地址>:<PORT>/onebot/v11/ws` |
| 正向 WS | `ONEBOT_WS_URLS`（JSON 数组）+ `ONEBOT_ACCESS_TOKEN` | 开启「WS 服务端」，记下监听地址与 token |

若两侧都配了 access token，两边的值必须一致。相关环境变量见 `.env.example` 顶部。

## 端口占用一览

**Stella 只监听一个端口**——反向 WS 端点与状态接口复用同一个 HTTP 服务器（NoneBot 的 FastAPI app），不新增端口。排查网络问题时先确认这张表：

| 端口 | 归属 | 谁在监听 | 配置项 |
|---|---|---|---|
| 8080 | **Stella 唯一的监听端口** | 本项目 | `PORT` |
| 1234 | LM Studio | 外部程序 | `LM_STUDIO_BASE_URL` |
| 6099 | NapCat WebUI | 外部程序 | NapCat 侧 |
| 3001 | NapCat 正向 WS 服务端 | 外部程序（仅 forward 模式） | `ONEBOT_WS_URLS` |
| 8765 | 安装器前端预览 | 开发期 `stella-installer/serve.bat` | 不进 Release |

## 本地状态接口

`deploy status` 与桌面 GUI 通过 `http://HOST:PORT/stella/status` 读取**进程内**状态（链路健康度、调度器排队深度、今日 token 用量、启动时长）——那些数据外部进程拿不到，HTTP 端点则天然「连不上就是没运行」。

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `STELLA_STATUS_API_ENABLED` | `true` | 是否注册状态路由 |
| `STELLA_STATUS_API_PATH` | `/stella/status` | 路由路径（与将来的其他路由冲突时再改） |

**只接受回环地址的请求**（`127.0.0.1` / `::1` / `127.x.x.x` / `localhost`），且响应体不含凭据与群聊内容（`allowed_group_count` 只给数量不给群号，`usage` 只给计数与比率、绝不含 prompt 与模型输出）——`HOST` 可能配成 `0.0.0.0`（NapCat 在另一台机器时），那时路由会暴露到局域网。设计说明见 architecture.md 的「本地状态接口」。

### 安全实测：`HOST=0.0.0.0` 时仍仅回环可访问

`HOST=0.0.0.0` 会让 Stella 监听所有网卡，但 `/stella/status` 在应用层校验 `request.client.host` 是否为回环地址，非回环一律返回 `403 {"error":"forbidden"}`（实现见 `stella_project/plugins/bot_main/status_api.py:_is_loopback`）。

实测（`PORT=8080`，`HOST=0.0.0.0`）：

```bash
# 本机回环 → 200
curl -i http://127.0.0.1:8080/stella/status
# HTTP/1.1 200 OK
# {"version":"2.6.0","pid":1234,"uptime_seconds":...}

# 同机通过局域网 IP 访问 → 403（模拟局域网其他机器）
curl -i http://192.168.1.20:8080/stella/status
# HTTP/1.1 403 Forbidden
# {"error":"forbidden"}

# IPv6 回环 → 200
curl -i http://[::1]:8080/stella/status
# HTTP/1.1 200 OK
```

因此即使 `HOST=0.0.0.0` 暴露到局域网，外部机器也无法通过状态接口探测运行信息或凭据；`deploy status` 与 GUI 始终通过 `127.0.0.1` 访问，不受影响。

## 优雅停止

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `SHUTDOWN_GRACE_SECONDS` | `30.0` | Bot 侧停止时等待在途任务（整合/压缩）收尾的上限（秒） |
| `STELLA_STOP_SENTINEL` | `.stella-stop-request` | 停止请求哨兵路径（deploy stop 写入、Bot 内 watcher 观察后自行退出）；项目目录只读时可改到可写位置 |
| `STOP_WATCH_INTERVAL_SECONDS` | `0.5` | 哨兵轮询间隔（秒） |

停止链路：deploy 写哨兵 → Bot 内 watcher 观察到后触发 uvicorn 优雅关闭（走 `on_shutdown` → 整合收尾）→ 超时降级信号 → 硬杀兜底。不用 `POST /shutdown`：status_api 只读，加写接口就多一个无鉴权、局域网可触发的远程关机。详见 development.md 的「停止链路（哨兵优先）」。

## 链路监测

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `LINK_MONITOR_ENABLED` | `true` | 是否启用链路监测 |
| `LINK_MONITOR_TIMEOUT` | `300` | 距上次收到**任何** OneBot 事件（含心跳元事件）超过该秒数，才做一次主动探活 |
| `LINK_MONITOR_CHECK_INTERVAL` | `60` | 定时检查间隔（秒） |
| `LINK_MONITOR_ALERT_INTERVAL` | `300` | 告警节流（秒）：断线期间不重复刷同样的 error |

**只告警、不重启。** 登录风控使自动重启无效（自动登录会退化为扫码），进程管理因此
没有收益（见 `design_docs/deprecated_napcat_manager.md`）。Bot 只负责监测链路并给出
排查提示，NapCat 的启停与登录由 NapCatQQ Desktop 人工完成。

> **静默 ≠ 断线。** NapCat 周期性发 `meta_event.heartbeat`（默认 15s），群里没人
> 说话时心跳仍在。判定超时后 Bot 会主动调用一次 `get_status()` 二次确认：探活成功
> 只说明「没人说话」，探活失败才是真断开。只挂 `on_message` 会把安静的群误判为
> 链路中断（2026-08-14 重启循环的成因）。

## 调参建议

| 想要的效果 | 调整方向 |
|---|---|
| Bot 太吵 | 降 `PROACTIVE_PROB_AT_FAST`；升 `PROACTIVE_COOLDOWN` 与 `PROACTIVE_MIN_MESSAGES_SINCE_SPOKE`；降 `PROACTIVE_AT_QUOTA_BASE`；或让管理员在群内说「安静」临时关闭 |
| Bot 太安静 | 升 `PROACTIVE_PROB_AT_FAST`；降 `PROACTIVE_TOPIC_WARMUP_SECONDS` |
| 深夜还在说话 | 确认 `PROACTIVE_SLEEP_ENABLED=true`，检查 `PROACTIVE_SLEEP_START/END` 是否覆盖目标时段 |
| 一觉醒来连发几句 | 升 `PROACTIVE_WAKEUP_GRACE_SECONDS` |
| 记不住事 | 降 `MEMORY_OBSERVE_LOW_CONFIDENCE`；降 `MEMORY_PROMOTE_MIN_OCCURRENCE_PASSIVE`；确认 `PROACTIVE_AT_ENABLED=true`（被动摄入的产出接近零） |
| 记错事 | 升 `MEMORY_CONFIRM_HIGH_CONFIDENCE`；升 `MEMORY_PROMOTE_MIN_OCCURRENCE_PASSIVE`；关闭 `MEMORY_PROMOTE_AT_MENTION_SINGLE_SHOT` |
| 回复提到不相关的旧事 | 升 `MEMORY_SCORE_MIN`；降各 `MEMORY_LIMIT_*` |
| 接错话题 | 升 `RECENT_TAIL_LIMIT` |
| 把几小时前的旧对话当成当前话题 | 降 `RECENT_TAIL_MAX_AGE_MINUTES` |
| 尾巴里断层太多/太少 | 调整 `RECENT_TAIL_GAP_MARK_MINUTES` |
| 记忆库膨胀 | 开启 `MEMORY_QUOTA_ENFORCE`（先看 dry-run）；降 `MEMORY_USER_QUOTA` |
| 整合太慢 | 降 `CONSOLIDATION_LOCAL_BATCH_SIZE`；换更小的整合模型 |
| 在线账单比预想的高 | 先看用量面板的**缓存命中率**：长期为 0 说明前缀缓存没生效（见[缓存命中率](#缓存命中率唯一能验证前缀缓存生效的手段)）。命中率正常则升 `CONSOLIDATION_ONLINE_BATCH_SIZE`、把 `CONSOLIDATION_ONLINE_OVERLAP` 保持 0、收紧 `LLM_ROLE_CONSOLIDATION_MAX_TOKENS`。**不要拉长 `CONSOLIDATION_SCHEDULE_INTERVAL`** |
| 想给账单加个硬上限 | 设 `LLM_DAILY_TOKEN_BUDGET`；默认动作 `pause_memory` 只停记忆域，群里照常能说话 |
| 记忆突然不更新了，但对话正常 | 大概率撞破了每日预算（`python -m deploy doctor` 会 warn，用量面板也会点名被暂停的角色）；其次查预筛是否连续跳过（升或清空 `CONSOLIDATION_MAX_SKIP_STREAK`） |
| 用量面板整块不显示 | Bot 没在运行，或状态接口不可达；显示「已关闭」则是 `LLM_USAGE_ACCOUNTING=false`（此时预算也不生效） |
| @ 对话完全学不到东西 | 查 `SELECT source_kind, COUNT(*) FROM group_messages GROUP BY source_kind`；`AT_MENTION` 为 0 说明 @ 消息未入库（见 development.md 排查表） |
| 记忆晋升过快、配额压力大 | `MEMORY_PROMOTE_AT_MENTION_SINGLE_SHOT` 生效后 @ 对话单次即可晋升，属预期；先看 `MEMORY_QUOTA_ENFORCE=false` 的 dry-run 日志再决定是否收紧 |
| 回复变慢、日志出现 Scheduler 告警 | 27B 上排队较重（聊天 + 压缩 + 提取共用）；可临时关 `MEMORY_EXTRACT_ENABLED` 或调大 `CONSOLIDATION_SCHEDULE_INTERVAL` |
| 链路掉线 / 收不到消息 | 看日志里的 `[LinkMonitor]` 告警，按告警文案的排查步骤检查（Bot 只告警不重启，NapCat 侧需人工处理） |
| 插件装了但从不被调用 | 最常见原因是**没写能力声明**——启动日志里那条「以下 N 个工具没有能力声明，不参与语义路由」的 WARNING 会点名；其次看 `[capability][boot] 能力装配完成` 的 `routable` 数（`derived` 大而 `routable` 小就是这个情况），再确认工具是否 `active` |
| 声明的 `examples` 好像没生效 | 确认工具归属：应指向你声明的能力 id，而不是 `tool.<工具名>`；装配顺序要求先读声明再自动派生 |
| 凭空调用工具 / 调错工具 | 升 `ROUTER_TOOL_THRESHOLD`；检查 `keywords` 里有没有过泛的词；**同时执行了无关工具**则降 `ROUTER_CAPABILITY_MARGIN`（这是搭车能力，不是选错） |
| 该调工具却没调 | 给能力补中文问句 `examples` 与 `keywords`；降 `ROUTER_TOOL_THRESHOLD`。改完跑一次 benchmark 再定 |
| 开了工具后回复明显变慢 | 每个命中能力都是一次独立的受限 agent 调用、都排 `PLUGIN` 角色那道闸门（纯本地时与聊天同一道）；降 `ROUTER_MAX_CAPABILITIES` 或 `COMES_MAX_TOOL_STEPS`，或把 `LLM_ROLE_PLUGIN_ENDPOINT` 指到在线槽 |
| 每条消息都比以前慢 2 秒左右 | Router 的一次 embedding 编码。实测本身只要约 70ms，2.5s 是 embedding 与 27B 聊天模型共用同一个 LM Studio 实例时的模型换入换出；把 `MEMORY_EMBEDDING_BASE_URL` 指到独立实例/端口，或设 `MEMORY_EMBEDDING_GATE=none` 让它不排队 |
| 「它突然不记得我了」 | 先查 `ROUTER_GATE_MEMORY` 是否被打开；跑 `python -m capability.router.benchmark` 看记忆假阴 |

改动阈值前建议先跑一次探针验证，见 [开发指南](development.md)。
