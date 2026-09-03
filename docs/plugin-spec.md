# 插件接入规范 v1.0

中文 | [English](plugin-spec.en.md)

本文是给**插件作者**的规范：怎么写一个能被 Stella 完整用起来的插件，以及为什么某些写法必须这样写。设计过程与取舍记录见 `design_docs/插件接入规范落地方案 v1.0.md`；运行期机制见 [能力系统](capability-system.md)与[架构说明](architecture.md)。

一句话概括：**Stella 插件 = AstrBot 插件 + 一个可选的 `capability.toml`**。你不需要学一套新框架，也不需要为 Stella 单独维护一份代码。

## 0. 适用范围与兼容性承诺

Stella 通过 `astrbot_compat/` 把 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 的插件 API 伪装进 `sys.modules`，所以插件里的 `from astrbot.api.star import Star` 这类导入在 Stella 里照常成立。这层的兼容声称版本是 `ASTRBOT_COMPAT_VERSION`（默认 `4.27.0`）。

三条承诺：

- **加法，不是分叉。** 本规范只增加**可选文件**（`capability.toml`）与**可选字段**（`metadata.yaml` 里的 `stella` 段）。不新增基类、不新增装饰器、不新增加载器。
- **双向可跑。** 按本规范写的插件放回 AstrBot 也能原样运行——AstrBot 不读 `capability.toml`，多一个文件不影响它。
- **不保证全量可用。** 兼容层是重新实现，不是移植；AstrBot 的部分 API 在 Stella 里没有对应物（见 [§11 兼容性矩阵](#11-兼容性矩阵)）。碰到这些 API 会抛 `StellaCompatNotSupported`，异常信息里带 API 全名，**不会静默降级成错误行为**。

如果你只想让现成的 AstrBot 插件在 Stella 上跑起来，`README` 的「装插件」三步就够了；本规范面向的是「想让插件在 Stella 上**完整**发挥」的情况——差别集中在 [§6 工具通路](#6-工具通路规范核心)。

## 1. 最小可跑插件

```python
# data/plugins/astrbot_plugin_hello/main.py
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star


class HelloPlugin(Star):
    def __init__(self, context: Context, config=None) -> None:
        super().__init__(context, config)

    @filter.command("你好")
    async def hello(self, event: AstrMessageEvent):
        yield event.plain_result(f"你好，{event.get_sender_name()}")
```

放进 `data/plugins/astrbot_plugin_hello/`，重启，群里 `@机器人 /你好` 即可。到这一步不需要任何附加文件。

一份可以直接拷走的完整模板在 [`docs/examples/astrbot_plugin_stella_template/`](examples/astrbot_plugin_stella_template/)——它同时是本规范的可执行脚注（`plugin-check` 对它断言零 error、零 warn）。

## 2. 目录结构清单

| 文件 | 必需性 | 作用 | AstrBot 是否也读 |
|---|---|---|---|
| `main.py` | **必需** | 入口。必须有 `Star` 子类；没有这个文件的目录直接被跳过 | 是 |
| `metadata.yaml` | 建议 | `name` / `desc` / `version` / `author` / `repo`；缺失时回退到 `@register` 参数，再回退到目录名 | 是 |
| `capability.toml` | **有 `@llm_tool` 就必需** | 能力声明。缺了工具照常注册，但**永远不会被聊天触发**（[§6.2](#62-capabilitytoml-与三层优先级)） | 否（Stella 扩展） |
| `_conf_schema.json` | 可选 | 用户可配项的 schema，展开后经 `self.config` 读取 | 是 |
| `requirements.txt` | 可选 | 依赖。默认**不自动装**（`ASTRBOT_AUTO_INSTALL_REQUIREMENTS=false`），只在日志里点名 | 是 |
| `README.md` | 建议 | 也是 `plugin-scaffold` 生成 `examples` 时最好的语料来源 | — |

目录名不必是合法的 Python 标识符：GitHub「Download ZIP」解出来的 `xxx-master` / `xxx-main` 会被自动挂到一个合法包名下（日志里会写明挂成了什么）。但**压缩包本身必须先解压**——`data/plugins/` 下的 `.zip` 不会被加载，启动诊断会单独把它列出来。

以 `.` 或 `_` 开头的目录被忽略，可以用来临时停用一个插件。

## 3. 两条接入通路怎么选

Stella 有两条完全不同的触发路径，选错的代价不对称：

```
用户消息
  ├─ 唤醒前缀 + @ 机器人 ──→ 指令通路（@filter.command）确定性触发
  └─ 普通对话 ──→ Router 判定 ──→ Comes 执行 ──→ 工具通路（@filter.llm_tool）语义触发
```

**决策树：**

1. 这个功能会**发消息、下单、改外部状态、花钱、删东西**吗？
   → 必须走 `@filter.command`。**不要**做成可路由工具。
2. 这个功能是**只读、幂等**的查询（查天气、查番剧、算字数）吗？
   → 做成 `@filter.llm_tool` 并写 `capability.toml`，用户可以用自然语言问。
3. 两者都想要？
   → 两个都写，共用一个内部实现函数。模板插件就是这个形态。

第 1 条是硬要求，理由是**Comes 调工具时不会向用户确认**。Router 判定「需要工具」之后，Comes 会在一个隔离的受限 agent 里直接调用，中间没有人类确认环节，也没有「你是不是想……」的追问。所以可路由工具的语义必须是「问一下」，不能是「去做」。

> 判错一次的代价对比：漏调一次只读工具，用户最多再问一遍；凭空调一次写操作工具，可能真的发出了消息或改了外部状态。规范按后者的代价来定。

## 4. 生命周期与加载时机

```
bot.py 启动
  ↓
install_shim()            伪装 astrbot.* 模块
  ↓
load_all_plugins()        逐目录 import main.py，实例化 Star 子类
  ↓                       （此时事件循环已在运行）
initialize_plugins()      逐个 await plugin.initialize()
  ↓
capability bootstrap()    读三层声明 → 自动派生 → 打装配日志
```

三个钩子：

| 钩子 | 何时调用 | 约束 |
|---|---|---|
| `__init__(self, context, config=None)` | import 后立即 | **在事件循环内**，所以起 task 是允许的；但不要做慢 IO |
| `async initialize(self)` | 全部插件实例化之后 | 起后台任务的推荐位置 |
| `async terminate(self)` | 禁用 / 重载 / 退出时 | **超时 5 秒**，别在这里做慢 IO 或等网络 |

**后台任务必须走 `self.context.register_task(coro, desc)`**，不要裸调 `asyncio.create_task(...)`：

```python
async def initialize(self) -> None:
    self.context.register_task(self._poll(), "my_poller")   # ✅
    # asyncio.create_task(self._poll())                     # ❌ 卸载时收不回
```

只有登记过的任务在插件卸载与热重载时会被取消。裸 task 在重载后会**残留并继续跑**，而这不报错——表现是「改了代码重载了，旧行为还在」，或者两份轮询同时打同一个 API。`plugin-check` 的第 ⑮ 项会扫这个写法并报 warn。

`config` 参数要允许为 `None`：没有 `_conf_schema.json` 的插件、单元测试里直接实例化的插件都会传 `None`。默认值写在代码里，不要假定 schema 一定被读到了。

## 5. 指令通路规范

`@filter.command("名字")` 注册的指令，触发条件是**唤醒前缀 + 被唤醒**两者都满足：

- 唤醒前缀由 `ASTRBOT_WAKE_PREFIXES` 配置，默认 `/`（逗号分隔可配多个）；
- 群聊里必须 @ 机器人，私聊由 `ASTRBOT_COMPAT_ALLOW_PRIVATE` 控制（默认 `true`）。

所以群里的实际用法是 `@Stella /你好`。

哪些平台事件会进插件管道，由 `astrbot_compat.pipeline.should_dispatch()` 把关，它有三道：

1. **自身回显不进**——机器人自己发的消息不会触发插件；
2. **群白名单**——只有 `ALLOWED_GROUPS` 里的群会分发，私聊看 `ASTRBOT_COMPAT_ALLOW_PRIVATE`；
3. **消息必须有内容**——判据是「消息段数量 > 0」而**不是**纯文本非空。

第 3 条的写法有实测理由：QQ 的小程序卡片、图片、纯 @ 这些消息的 `get_plaintext()` 是空串，用纯文本判据会把它们整批挡在插件之外（2026-08-25 实测），而这类消息恰恰是图片处理、卡片解析类插件唯一的输入。

插件命中后（`priority=2`）Stella 的主聊天链路（`priority=3`）就不再介入这条消息，不会再叠一层 LLM 回复。

其他不受唤醒前缀约束的监听器（`@filter.regex`、`@filter.event_message_type`）照常可用，但要清楚它们会看到**白名单群里的所有消息**——在群聊里做全量正则匹配很容易误触发。

## 6. 工具通路规范（核心）

这一章是 Stella 与 AstrBot 差别最大的地方。AstrBot 把全部工具的 schema 塞进每次对话请求，让主模型自己挑；Stella 不这么做（理由见 [§7](#7-上下文预算契约8k)），而是先用 embedding 判断「要不要用工具、用哪个」，再把选中的工具交给一个隔离的受限 agent 执行。

后果是：**工具能不能被聊天触发，取决于你有没有提供合适的语义原型语料**，而不是取决于工具注册成功没有。

### 6.1 签名与 docstring 契约

```python
@filter.llm_tool("get_weather")
async def get_weather(self, event: AstrMessageEvent, city: str, days: int = 1):
    """查询指定城市未来几天的天气。

    Args:
        city(string): 城市名，如「杭州」
        days(number): 查询天数，默认 1
    """
```

- 签名固定为 `async def tool(self, event, <参数...>)`；
- **参数类型只从 docstring 的 `Args` 段读取**，不看类型注解。`parse_tool_docstring()` 只认上面这一种格式（`名字(类型): 说明`，缩进在 `Args:` 之下）；写错格式的结果是参数**静默丢失**，模型调用时不传值；
- 类型写法支持 `string` / `number` / `int` / `boolean` / `object` / `array` / `list[string]` 这一类；
- 在函数签名里给了 Python 默认值**不代表参数可选**——docstring `Args` 段里列出的参数一律登记为必填。参数是否必填会影响 `keywords` 该不该写（[§6.4](#64-怎么写-keywords)）；
- 工具名取 `@filter.llm_tool("名字")` 的参数，省略时取函数名。这个名字就是 `capability.toml` 里 `providers` 要填的东西，**拼错的后果是静默失效**（`plugin-check` 第 ⑤ 项专门查这个）。

### 6.2 `capability.toml` 与三层优先级

声明文件放在插件根目录，格式与 `config/capabilities/*.toml` **完全一致**：

```toml
reviewed = true      # 人审闸门，见下

[[capability]]
id = "weather.query"
domain = "information"        # 插件自带声明缺省落在 plugin 域，建议显式写
description = "查询天气信息"
examples = [                  # Level 1 语义原型语料：写「用户会怎么问」
    "明天天气怎么样",
    "会不会下雨",
    "杭州这几天热不热",
    "帮我看下天气",
]
# keywords = ["天气预报"]     # Level 0 字面词，可以不写；有必填参数时**不要**写
providers = ["get_weather"]   # llm_tools 里的工具名，不是插件名
```

**一种格式管三个位置**，优先级从高到低：

| 层 | 位置 | 谁维护 |
|---|---|---|
| 用户 | `<数据目录>/config/capabilities/*.toml` | 部署者 |
| 出厂 | `<程序目录>/config/capabilities/*.toml` | Stella 仓库 |
| 插件自带 | `<插件目录>/capability.toml` | **插件作者** |
| （自动派生） | 无文件，启动时按工具名生成 `tool.<name>` | — |

同一个工具被高优先层认领后，低优先层里对应的那条**整条跳过**（不是跳过单个 provider——半条能力的 examples 与 providers 不再自洽，比缺一条更糟），日志里会写明被哪一层顶掉。所以用户想改插件写歪的 `examples`，只要在自己的 `config/capabilities/` 里放一条同 id 或同工具名的声明即可覆盖，不必改插件源码。

插件层可以整体关掉：`ASTRBOT_PLUGIN_CAPABILITIES_ENABLED=false`。默认 `true`——零配置是本规范的意义所在；留这个开关是因为「谁决定我的机器人会调什么」应当能被部署者收回。

**只有加载成功的插件的声明会被读取。** import 失败的插件没有登记任何工具，它的声明会造出指向不存在工具的能力——那种能力会照常参与路由竞争、抢走判定间距，最后在 Comes 里必然失败。

**`reviewed` 闸门**：`reviewed = false` 的文件、以及 `capability.toml.draft` 这种带 `.draft` 后缀的文件，一律不载入，只在启动日志里记一条「有草稿待审」。这个键缺省视为已审（手写声明不必写它）。它存在的意义见 [§12](#12-自检生成与发布)：机器生成的语料在进入路由之前必须有人过目一遍。

**没有声明会怎样**：工具照常注册、照常可以被显式执行，但不进 `registry.routable()`，于是三级路由都看不到它——现象是「插件装了、日志说注册成功了、可就是从来不被调用」。启动时会打一条 WARNING 点名这些工具。`plugin-check` 把这种情况判为 **error**。

### 6.3 怎么写 `examples`

`examples` 是 Level 1 的语义原型语料。**写用户会怎么问，不是写给决策器的指令句。**

这是整套设计里最容易写错、也最要紧的一条。对比：

| | 写给谁看 | 要求的形态 |
|---|---|---|
| AstrBot 的工具 `description` | 一个看着**全部**工具做选择的决策器 | 指令句 + 边界条件：「当用户询问今天更新什么动画时调用」 |
| Stella 的 `examples` | 与用户**问句**算余弦相似度 | 用户会怎么问：「今天更新什么动画」 |

12 条用例、真实 embedding 的对照实测：

| 原型语料 | 工具假阳 | 首位选错 | 无关工具被执行 | 负样本阈值余量 |
|---|---|---|---|---|
| 工具描述（不写声明时的现状） | 1 | 2 / 5 | 13 次 | **−0.024** |
| 中文问句 `examples` | 0 | 0 | 0 次 | **+0.141** |

负样本余量为负意味着：一句与本工具无关的话，得分比置信线还高——凭空调工具只是时间问题。

写法要点：

- **4~6 句**，每句覆盖一种不同的问法（不同措辞、不同句式、有的带地名有的不带）。少于 3 条 `plugin-check` 报 warn；
- 全部写成用户的口语问句。出现「当用户」「时调用」「本工具」「用于」这类词的，基本可以确定写成了指令句（第 ⑧ 项 warn）；
- 别把同一句话换个标点重复四遍。原型向量是全部 examples 编码后的**均值**，重复不增加信息，只会让这个能力的中心更偏；
- 同域的能力之间要能区分开。原型彼此差不到 0.06 时，路由基本是在掷骰子——这个数会被 `plugin-check` 第 ⑫ 项算出来。

写不动的时候可以让 `plugin-scaffold` 生成第一版再自己改（[§12](#12-自检生成与发布)）。

### 6.4 怎么写 `keywords`

`keywords` 是 Level 0 的确定性字面词：命中即拍板执行，**没有二次判定**。所以它的取舍原则是**宁缺勿滥**。

四条规则：

1. **写名词短语**，至少 3 个字。「新番」不如「番剧推荐」——短词会串进无关句子；
2. **绝不从 `examples` 里切词**。中文没有词边界，从「会不会下雨」里切出来的候选既有「下雨」也有「不会」，后者会命中几乎任何句子（「我不会用这个软件」→ 去查天气）。滑窗切词能切出好词，但一定同时切出坏词，而坏词的代价是凭空调一次工具；
3. **不要与别的能力的 `examples` 串味**。一个泄漏的关键词就是一次高代价的工具假阳；
4. **工具有必填参数时不要写 `keywords`**。Level 0 只做字面命中、**不抽取参数**，拍板执行只会让 Comes 去猜那个必填值。

出厂声明里正反两例都有：`anime.search`（必填 `keyword`）不给 `keywords`；`video.dynamics` 破例给了，因为它的参数有合理默认值。按这个标准取舍。

不写 `keywords` 完全没问题——Level 1 照样能路由到，只是多花一次 embedding。

### 6.5 返回值契约

工具返回值**不会原样进入 Stella 的人格 prompt**。链路是：

```
工具 return  →  受限 agent 的 8192 窗口  →  summarizer 摘要（≤ COMES_SUMMARY_MAX_CHARS，默认 300 字符）  →  Stella 的 prompt
```

两个后果：

- **别甩几千字 JSON。** 它先要挤进受限 agent 自己的 8192 token 窗口，超了就是截断，截断处之后的内容等于没返回；
- **返回值要写成人话。** 最终进 prompt 的是那 300 字符的摘要，摘一段结构化数据的效果远不如摘一句「杭州明天多云，18~26℃」。

返回 `None` 表示「没有返回值或已经直接回复用户了」。

### 6.6 失败契约（最容易写错的一条）

**失败要抛异常，不要 `return "查询失败：……"`。**

```python
# ✅
if resp.status_code != 200:
    raise RuntimeError(f"天气 API 返回 {resp.status_code}")

# ❌
if resp.status_code != 200:
    return "查询失败：接口超时了"
```

为什么这条不是风格问题：抛出的异常会被 `agent.execute_tool` 包成 `f"error: {e}"`，`summarizer.is_error()` 靠开头的 `error:` 判定失败。返回一串普通文字的话，**三件事同时发生**——

1. 那串字不以 `error:` 开头 → 被当成**成功输出**；
2. 于是它被贴上「刚刚查到的信息（真实数据，回答时以此为准）」进 Stella 的 prompt → Stella 把失败文案当事实**转述给用户**；
3. provider 健康度**记不到这次失败** → 连续失败退避（`COMES_PROVIDER_FAILURE_THRESHOLD` 次后退避 `COMES_PROVIDER_RECOVER_SECONDS` 秒）永远不触发，一个坏掉的工具会被反复调用。

异常信息会进日志，所以写清楚是什么坏了：`raise RuntimeError("和风天气 403，API key 可能过期")` 比 `raise RuntimeError("失败")` 有用得多。

### 6.7 超时

工具执行超时是 `COMES_TOOL_TIMEOUT`，默认 **60 秒**；整个任务是 `COMES_TASK_TIMEOUT`，默认 90 秒。

这条链路挂在聊天主链路上——**用户正在群里等回复**。60 秒是上限不是预算，一个体感正常的工具应该在 5 秒内返回。要做长任务，用「立刻返回一句『在查了』+ 后台 `register_task` + 完成后 `StarTools.send_message` 主动发」的形态，别把用户挂在同步等待上。

### 6.8 无参直调

没有必填参数的工具会跳过一次模型往返，由 Comes 直接调用（`COMES_DIRECT_CALL_NO_ARGS=true`，默认开），省一次 LLM 调用与它的延迟。

这意味着**无参工具的副作用会更早发生**，进一步说明 [§3](#3-两条接入通路怎么选) 那条「写操作不做成工具」的必要性。

### 6.9 一个能力多个实现

一条 `capability` 可以有多个 `providers`（比如两个不同的天气插件）。选择顺序按 `priority`，失败的 provider 会被记账并短暂退避，期间自动切到下一个。

所以多写一个 provider 是真的有容错价值的；但前提是 [§6.6](#66-失败契约最容易写错的一条)——失败必须抛异常，否则退避永远不触发，容错等于没有。

## 7. 上下文预算契约（8K）

Stella 的工作窗口是 **8192 token**，这个数字决定了整套工具设计。

| | AstrBot | Stella |
|---|---|---|
| 工具怎么被选中 | 全部工具 schema 进每次对话请求，主模型自己挑 | embedding 比对原型向量，只把选中的交给受限 agent |
| N 个工具的上下文成本 | 每次请求 N × 60~120 token，**线性涨** | N 个原型向量，一次性编码 + 按注册表版本落盘缓存，**对话窗口不涨** |
| N 变大时的代价 | 装满插件后正常对话挤不进窗口 | 同域工具混淆概率上升 |

两个必须记住的结论：

- **工具描述与原始返回值都不进人格 prompt。** 你写在 `description` 里的话不会影响 Stella 的说话方式，也别指望通过描述给 Stella 传达指令；
- **代价换了形态，没有消失。** 装得越多，同一语域里的能力越容易互相抢——所以 [§6.3](#63-怎么写-examples) 的区分度要求不是洁癖，它是这套设计的成本所在。

## 8. 渲染契约

`Star.html_render(tmpl, data)` / `text_to_image(text)` / `t2i(...)` 由**本地 Chromium** 出图，首次需要出图时会在后台下载约 270MB 的浏览器内核，期间渲染不可用。

两条与上游不同的地方，插件必须适配：

1. **返回本地文件路径，不是 URL。** `return_url=True` 被刻意忽略——上游那个分支返回的是远程 t2i 服务的 URL，而 Stella 不把聊天内容发出去。拿到路径后用 `event.image_result(path)` 或 `chain.file_image(path)` 都正常。**不要用 `url_image(path)`**，那个函数收到本地路径时会抛 `ValueError`（`plugin-check` 第 ⑭ 项会扫源码里的 `url_image(`）；
2. **不可用时返回空串，不抛异常。** 没装浏览器、正在后台下载、模板报错，都返回 `""`。所以插件必须有降级分支：

```python
img = await self.html_render(TMPL, data)
if img:
    yield event.image_result(img)
else:
    yield event.plain_result(self._render_as_text(data))   # 必须有
```

选择返回空串而不是抛异常，是因为插件普遍会把渲染包在 `try` 里再重试，抛异常只会被吞掉然后重试三次都失败；空串能让 `if img:` 这种最常见的写法自然走进降级分支。

## 9. 配置与数据

**用户可配项**：`_conf_schema.json` 声明，`self.config` 读取。

```json
{
    "max_items": {"description": "max_items", "type": "int", "hint": "一次最多返回几条", "default": 10}
}
```

```python
limit = 10 if self.config is None else int(self.config.get("max_items", 10))
```

始终用 `.get(键, 默认值)` 并处理 `self.config is None`——单元测试与没装 schema 的场景都会传 `None`。

**数据落盘**：

| 用途 | API | 位置 |
|---|---|---|
| 任意文件 | `StarTools.get_data_dir()` | `<数据目录>/data/plugin_data/<插件名>/` |
| 小 KV（异步） | `await self.put_kv_data(k, v)` / `get_kv_data` / `delete_kv_data` | 同目录下的 `kv.json` |
| 小 KV（同步） | `self.set_data` / `get_data` + `self.save_data()` | 同上（`set_data` 只改内存，必须显式 `save_data`） |

不要往插件自己的安装目录里写数据——升级会整个替换那个目录。

**群与空间的分界**：Stella 有「共享空间」概念（多个群共用一份记忆与人格），但**插件拿不到 `group_shared_space`**。插件视野里只有 `event.get_group_id()`。要按群隔离数据，就自己拿 `group_id` 拼键：

```python
await self.put_kv_data(f"subscriptions:{event.get_group_id()}", items)
```

这是刻意的：空间归属是记忆系统的语义，插件按它分组会在管理员合并 / 拆分空间时产生一堆无主数据。

## 10. 隐私与出网声明

Stella 的默认姿态是不把聊天内容发出去：判断该不该用工具、压缩工具结果、渲染卡片全在本地完成。**插件是唯一被允许出网的环节**，所以出网的插件必须自己说清去哪儿、干什么：

```yaml
# metadata.yaml
stella:
  egress:
    - host: api.weatherapi.com
      purpose: 查询公开天气数据，只发送用户提到的城市名
```

**这是披露契约，不是沙箱。** 我们不拦未声明的请求，规范里必须把这句写明白——`stella.egress` 的作用是让部署者在装插件之前能看见「这个插件会把什么发到哪里」，靠的是社区约定与 `plugin-check`（第 ⑯ 项：import 了 `httpx`/`aiohttp`/`requests` 却没写 `egress` → warn），不是技术强制。

两条附带要求：

- `purpose` 写**发送什么**，不只写「查询数据」。「只发送城市名」和「发送用户原话」对部署者是两回事；
- 不要把群聊原文、用户 ID、消息 ID 发给第三方服务。需要这么做的功能应当在 `purpose` 里明确写出来，让部署者自己决定装不装。

## 11. 兼容性矩阵

兼容层是重新实现。三种状态：

**① 已实现，行为对齐上游**

- `Star` 的全部生命周期钩子、指令参数解析、KV 存储
- `@filter.command` / `command_group` / `regex` / `llm_tool` / `event_message_type` / `permission_type` / `platform_adapter_type` / `custom_filter` 与全部 `on_*` 钩子、`GreedyStr`
- `AstrMessageEvent` 的取值方法（`get_sender_id` / `get_sender_name` / `get_group_id` / `get_messages` / `get_message_str` / `is_admin` / `is_private_chat` …）与结果构造（`plain_result` / `image_result` / `chain_result` / `make_result`）
- `MessageChain` 的链式构造、`MessageEventResult` 的 `stop_event` / `continue_event`
- 消息组件：`Plain` / `Image` / `Record` / `Video` / `File` / `Face` / `At` / `AtAll` / `Reply` / `Poke` / `Json` / `Music` / `Share` / `Location` / `Dice` / `RPS` / `Shake` / `Contact` / `Forward` / `Unknown`
- `Context`：`get_registered_star` / `get_all_stars` / `send_message` / `register_task` / `get_platform` / `activate_llm_tool` 系列 / provider 系列 / `conversation_manager` / `persona_manager` / `register_llm_tool`
- `StarTools`：`send_message` / `get_data_dir` / `activate_llm_tool` 系列
- `AstrBotConfig`、`sp`（偏好存储）、`FunctionTool` / `ToolSet`

**② 降级实现，行为与上游不同**

| API | 差别 | 详见 |
|---|---|---|
| `html_render` / `text_to_image` / `t2i` | 忽略 `return_url`，返回本地路径；不可用时返回空串 | [§8](#8-渲染契约) |
| `@filter.llm_tool` 注册的工具 | 注册成功 ≠ 能被聊天触发，需要 `capability.toml` | [§6.2](#62-capabilitytoml-与三层优先级) |
| `metadata.yaml` 的 `astrbot_version` | 不匹配只告警，仍然加载 | [§15](#15-版本与兼容策略) |
| `requirements.txt` | 默认不自动 `pip install`，只在日志点名 | [§2](#2-目录结构清单) |
| `Context.llm_generate` / `tool_loop_agent` / `get_current_chat_provider_id` | `ASTRBOT_LLM_ENABLED=false` 时抛 `StellaCompatNotSupported` | — |

**③ 抛 `StellaCompatNotSupported`**

| API | 为什么没有 |
|---|---|
| `StarTools.get_db` / `Context.get_db` | Stella 的库是记忆系统的私有 schema，不对插件开放 |
| `StarTools.get_event_queue` / `Context.get_event_queue` | 事件分发走 NoneBot，没有上游那条队列 |
| `StarTools.get_config` | 没有上游那份全局配置对象 |
| `StarTools.register_web_api` / `Context.register_web_api` | Stella 没有对外 HTTP 服务（状态接口只回环、只读） |
| `Context.kb_manager` / `subagent_orchestrator` / `knowledge_db_manager` | 知识库与子 agent 编排未实现 |
| `astrbot.api.platform.Platform` / `register_platform_adapter` | 只支持 OneBot V11 一个平台 |
| `astrbot.api.html_renderer` / `astrbot.api.agent` | 用 `Star.html_render` / Comes 代替 |
| `Node` / `Nodes` 作为普通消息段发送 | 合并转发要走 `send_group_forward_msg`，不是消息段 |
| 组件的 `convert_to_file_path()`（来源无法解析时） | 拿不到源文件就没有路径可返回 |

第 ③ 类里 `Context` 的三个属性抛的是 `StellaCompatUnsupportedAttribute`，它同时是 `AttributeError` 的子类——所以插件用 `hasattr(ctx, "kb_manager")` 做特性探测会得到 `False` 并优雅降级，而直接访问仍然抛出可识别的异常。这个双重继承是刻意的。

## 12. 自检、生成与发布

完整流水：

```bash
python -m deploy plugin-scaffold <插件目录>    # 生成 capability.toml.draft 并量化（可选）
#   → 人审：改 examples、按需取用注释里的候选 keywords、reviewed = true、去掉 .draft 后缀
python -m deploy plugin-check <插件目录>       # 16 项检查，有 error 时退出码非零
python -m capability.router.benchmark          # 路由基准，确认四类路由错误没变差
```

`plugin-check` **会 import 并实例化你的插件**（和启动时做的事同类），输出里会明确写「已执行该插件代码」。`--json` 供 GUI 使用：报告走 stdout、日志走 stderr。

16 项检查：

| # | 检查项 | 级别 |
|---|---|---|
| ① | 缺 `main.py` / 目录里是未解压的压缩包 | error |
| ② | import 失败 / 没有 `Star` 子类 / `initialize()` 抛异常 | error |
| ③ | `requirements.txt` 里的包在当前环境缺失 | error |
| ④ | 有 `@llm_tool` 工具未被任何声明的 `providers` 认领 | error |
| ⑤ | 声明的 `providers` 出现不存在的工具名 | error |
| ⑥ | 只有 `.draft` / `reviewed = false` | error |
| ⑦ | `examples` 少于 3 条 | warn |
| ⑧ | `examples` 疑似指令句 | warn |
| ⑨ | `keywords` 串进了别的能力的 `examples` | warn |
| ⑩ | `keywords` 出现短于 3 字的词 | warn |
| ⑪ | 工具有必填参数却给了 `keywords` | warn |
| ⑫ | 同域能力原型分离度不足 / 负样本余量为负 | warn |
| ⑬ | 能力 id 或工具与用户 / 出厂层撞名 | info |
| ⑭ | 源码出现 `url_image(` | warn |
| ⑮ | 裸 `asyncio.create_task(` 而未走 `context.register_task` | warn |
| ⑯ | import 了 httpx/aiohttp/requests 但未声明 `stella.egress` | warn |

发布前的最低要求是**零 error**。warn 是「请复核」而不是「必须改」——第 ⑩ 项在出厂声明里就有一个经实测确认的破例（`anime.schedule` 的「放送」只有两个字，靠它把一句 0.641 分的问句从 0.70 置信线下救回来）。判断的是你，不是检查器。

`plugin-scaffold` 的开关：`--endpoint <槽>` 换模型槽（默认走 `ROLE_EXTRACT` 那一档，见 `core/llm/registry.py`）、`--dry-run` 只打印不落盘、`--force` 覆盖已有草稿、`--measure` **跳过生成**、只对现成的声明（`capability.toml` 或 `.draft`）重算一遍量化报告——人审时改完 examples 拿它复算，不必再花一次模型调用。它和 `plugin-check` 一样**会 import 并实例化你的插件**：枚举 `@llm_tool` 只有这一个办法。

关于生成：**离线生成一份草稿、人审之后才生效**是被支持的；运行期无声地从工具描述生成 examples 灌进内存**不被支持**（那正是 `ROUTER_ROUTE_AUTO_CAPABILITIES` 默认关闭的原因）。差别在于有没有文件、有没有人过目、有没有量化基准，`reviewed` 闸门就是这条分界的实现。

生成器的输入按信息量排序：插件 `README.md` → `@command` 的指令名与说明 → `@llm_tool` 的 docstring `Args` → 工具 `description` 与工具名 → `metadata.yaml`。只喂工具描述正是 −0.024 那一行的成因。生成后会直接用真实 embedding 打一份报告（同域分离度、每条 example 与本能力原型的余弦、负样本余量），所以「生成质量无法验证」在有文件、有审阅、有基准的前提下不成立。

## 13. 调试

**看日志。** 插件相关的启动信息全在 `logs/boot_debug.log`：发现了哪些目录、加载成功还是失败、失败原因、能力装配的分层计数、哪些工具没有声明。路由判定与工具结果在 `logs/stella_thought_logs.md`。

**「插件装了但从来不被调用」** 的排查顺序：

1. `boot_debug.log` 里有没有这个插件？没有 → 目录名以 `.` / `_` 开头，或者压缩包没解压；
2. 加载失败？→ 看失败原因，多数是缺依赖（`requirements.txt` 默认不自动装）；
3. 加载成功但工具从不触发 → 十有八九是缺 `capability.toml`，日志里那条 WARNING 会点名；
4. 有声明但还是不触发 → `providers` 里的工具名拼错了，或者被高优先层顶掉了。`plugin-check` 第 ⑤ / ⑬ 项直接给答案。

**热重载**由 `ASTRBOT_PLUGIN_HOT_RELOAD_ENABLED` 控制，**默认关闭**——它会重新 import 并执行插件代码，比只读查询大一档，不该在没人明确打开时可用。打开后由**群内管理员**触发：

```
@Stella 重载插件 astrbot_plugin_bilibili
```

权限沿用主动发言开关那套（`PROACTIVE_TOGGLE_ADMINS` 白名单，或群主/管理员）；非管理员发这句不会有任何反应。选群内命令而不是给状态接口开一个 POST，是因为那个端点是只读的，加一条能触发任意插件 re-import 的写入口是比只读端点大一档的安全步骤。

它做的事：跑 `terminate()`（5 秒超时）→ 取消该插件经 `register_task` 登记的后台任务 → 摘掉它的 handler（含定义在子模块里的）、函数工具、能力声明与工具归属 → 清掉 `sys.modules` 里的插件包与磁盘上的 `__pycache__` → 重新加载 + `initialize()` → 重跑三层声明与自动派生，并在后台重算 Router 的原型向量。

`__pycache__` 那步不是顺手打扫：`.pyc` 的有效性只按「源文件 mtime 整秒 + 字节数」判定，所以「同一秒内改了一个字符」这种编辑（调试时改常量、改开关，恰恰最常见）会命中旧字节码——重载报成功，跑的还是旧代码。

**清不掉**的是这些：

- 裸 `asyncio.create_task()` 起的后台任务（这就是 [§4](#4-生命周期与加载时机) 要求走 `register_task` 的原因）
- 插件起的线程、注册的全局钩子、monkeypatch、第三方库的模块级状态
- 已经被别处持有的旧实例引用

所以热重载的定位是**调试便利，不等于重启**。怀疑状态不干净就重启——这句话也会跟在每一条重载成功的回复后面。

新代码 import 失败时重载返回失败并把原因报回群里，**不回滚**：旧模块已经从 `sys.modules` 里摘掉了，没有可回滚的东西。改完再重载一次即可。

`ASTRBOT_PLUGIN_HOT_RELOAD_WATCH`（默认关闭，需与主开关同时打开）会监视已加载插件目录里 `*.py` 与 `capability.toml` 的 mtime，改完存盘就自动重载。调试最省事，但「自动」在生产上危险：一次误存盘就会在群里跑一遍重新 import。轮询间隔由 `ASTRBOT_PLUGIN_HOT_RELOAD_WATCH_INTERVAL`（默认 5 秒）控制。

## 14. 能力查询

三个入口、同一份数据源：

- **群里问**「你能做什么」「有什么功能」——按域分组列出可路由的能力，末尾一行说明有多少插件工具因为没配声明而不会被自动触发。普通群友可查；来源层、provider 健康度、未声明工具的具体名单属于排查信息，只对管理员显示；
- **`python -m deploy capabilities [--json]`**——表格形式：哪些能被聊天触发、哪些不能、各自来自哪一层、哪个 provider 正在退避；
- **GUI**「插件」页——按**插件**重新索引的同一份 payload：左边列出装了哪些插件（每项一个圆点与一句结论：加载失败 / 已停用 / N 个工具未声明 / 正常），点进去才看这个插件的指令与工具。工具那一列直接回答「有没有被能力声明认领」——绿点＝已认领、聊天里会自动触发，灰点＝没有任何声明认领它，只能显式调用；工具不存在 / 已停用 / 正在退避也标在同一行。没解压的压缩包、只有 `capability.draft.toml`、`reviewed = false` 都会在对应插件上点名。「运行状态」页的「复制诊断信息」仍会带上「可路由 N / 共 M / 未声明工具」这三个数。

payload 只放结构化字段（id、domain、来源层、是否可路由、provider 工具名、工具是否真的存在、退避状态、examples 条数），**不含 `description` 与 `examples` 原文**——状态接口有「响应体不含凭据与聊天内容」的硬约束，而自由文本是唯一可能夹带 URL 或密钥的字段。原文在本地直接读那三层 TOML 就有。

## 15. 版本与兼容策略

- `metadata.yaml` 的 `astrbot_version` 约束**只告警不拦**。兼容层的声称版本是 `ASTRBOT_COMPAT_VERSION`（默认 `4.27.0`），它表达的是「API 表面对齐到哪个上游版本」，而不是「行为逐字等价」——按它硬拦会把大量实际可用的插件挡在外面；
- `version` 字段沿用上游惯例，可以带 `v` 前缀（`version: v1.6.4`）；缺失时按 `0.0.0` 处理；
- **本规范的版本是 v1.0。** 后续版本只以加法方式演进：新增可选字段、新增检查项。已有字段的语义不会在小版本里改变。`capability.toml` 的格式与 `config/capabilities/*.toml` 保持一致这一点是承诺而不是巧合——它意味着三层里任何一层的写法都能直接搬到另一层。

## 相关文档

| 文档 | 内容 |
|---|---|
| [能力系统](capability-system.md) | Router 三级级联、Comes 执行层、注册表分层的运行期细节 |
| [架构说明](architecture.md) | 目录结构、消息处理流程、AstrBot 兼容层在整体里的位置 |
| [配置参考](configuration.md) | 本文提到的全部配置项 |
| [模板插件](examples/astrbot_plugin_stella_template/) | 可以直接拷走的完整示例 |
