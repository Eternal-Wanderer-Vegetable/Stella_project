# AstrBot 插件兼容层

中文 | [English](integrations.en.md) · [文档总览](../README.md)

## AstrBot 插件兼容层

`astrbot_compat/` 让 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 生态的插件在 Stella 里**不改源码**直接跑。做法是 `shim.py` 伪造出一整棵 `astrbot.*` 模块树，把插件的 `import` 指向兼容层的真实现。插件放进 `data/plugins/` 即被发现并加载。

它有两条独立的通路，别混起来看：

| 通路 | 入口 | 用途 |
|---|---|---|
| **指令分发** | `plugin_handler`（priority 2） | `@command` / `@regex` / `@event_message_type` 这类插件自己响应的场景 |
| **工具执行** | Comes → `llm_tools` | 插件用 `@llm_tool` 注册的函数工具，由能力层按需调用 |

分发通路的唤醒判定照搬上游 `WakingCheckStage`：对每一条消息都跑一遍 handler 的 filter，是否唤醒由 filter 自己决定。是否进管道由 `should_dispatch()` 把关（群白名单 + 挡自身回显 + 消息非空）。

**兼容层不参与人格与记忆。** 插件拿不到 Stella 的系统提示词与记忆内容；反过来插件工具的结果经 Comes 压缩成一句 `summary` 才进 Stella 的 prompt。理由与能力层的上下文隔离同源，见 [能力系统](capability-system.md)。

未实现的上游能力一律抛 `StellaCompatNotSupported`（而不是静默返回假值），插件报错时能直接看出缺的是哪个接口。

**工具执行通路多一步**：`@llm_tool` 注册成功不等于聊天能触发它——路由候选集来自 `registry.routable()`，需要一份能力声明。声明有三层（用户 `STELLA_HOME/config/capabilities/` > 出厂 `<项目根>/config/capabilities/` > 插件自带 `<插件目录>/capability.toml`），格式完全一致，同一工具被高优先层认领后低层那条整条跳过；插件自带层由 `ASTRBOT_PLUGIN_CAPABILITIES_ENABLED`（默认 `true`）控制，且只扫加载成功的插件。写插件的完整规则见 [插件接入规范](../reference/plugin-spec.md)，分层与路由细节见 [能力系统](capability-system.md#四层注册通路)。

**热重载**（`ASTRBOT_PLUGIN_HOT_RELOAD_ENABLED`，默认关闭；打开后由群内管理员发「@Stella 重载插件 <名>」触发）定位是调试便利而非重启：它能收回 handler、工具、能力声明、`sys.modules` 里的模块与磁盘上的 `__pycache__`，但收不回裸 `asyncio.create_task()` 起的任务、插件起的线程、monkeypatch 与已被别处持有的旧实例引用。这也是规范要求后台任务走 `context.register_task` 的原因——只有登记过的任务带归属标记，重载时才只掐掉这一个插件的。

### 加载时机与目录名

**插件在事件循环里装载**，入口是 `bot.py` 的 `on_startup` 钩子 `_bootstrap_astrbot_plugins()`（装载 + `initialize_plugins()`）。这不是随便放的：上游 AstrBot 的插件加载整条链路是异步的，因此插件在 `__init__` 里 `asyncio.create_task(...)` 起后台任务是**官方插件的常规写法**（`astrbot_plugin_bilibili` 即是）。放回 import 期同步装，这类插件会以 `RuntimeError: no running event loop` 加载失败——而用户唯一的出路是改插件源码，与「不改源码直接跑」正相反。两条约束别破：钩子必须是 `async def`（同步钩子被 nonebot 丢进线程池，那里同样没有运行中的循环），且必须注册在 `_bootstrap_capabilities` 之前（启动钩子按注册顺序**串行**执行）。

**目录名不必是合法的 Python 模块名**。`data/plugins/<目录>` 装不进 `import data.plugins.<目录>.main` 时（GitHub「Download ZIP」解出来的 `-master` / `-main` 后缀最常见，上游 git clone 装插件所以撞不到），`loader.py` 把目录归一化成合法模块名，再按文件路径挂成包（`__path__` 指回真实目录），插件内部的 `from .x` / `from ..y` 照常解析。两个目录归一化后同名时，第二个加短摘要后缀区分，绝不互相顶替。`ASTRBOT_PLUGINS_DIR` 指到项目外时走同一条挂载路径。

元数据里的 `root_dir_name` 始终是磁盘上的真实目录名，而插件数据目录按 metadata 的 `name` 走——所以用户事后把 `xxx-master` 改名成 `xxx`，订阅数据不会丢。

### HTML → 图片渲染

大量插件把结果卡片做成 Jinja2 模板 + CSS，靠 `Star.html_render` 出图。实现在 `astrbot_compat/render.py`，后端是**本地 Chromium**（playwright）。

**为什么不用远程服务**：上游 AstrBot 默认把 HTML 发到远程 t2i 服务。模板里填的是群友昵称、动态正文、头像 URL，属于聊天内容。全本地部署下其他环节都在本机，渲染没有理由成为唯一出网的一环；接了在线模型的部署也一样——出网的对象是用户自己挑并且付了钱的服务商，没有理由再多搭一个他没选过的渲染服务。

**为什么必须是浏览器内核**：插件模板普遍用 flexbox、线性渐变、border-radius、box-shadow（实测一个插件的三个模板各 350~460 行 CSS）。weasyprint 之类缺完整 flex 支持，出图会错版——而错版比降级更糟，因为它看起来「成功了」。

依赖分两层：`playwright` 的 pip 包进 `requirements.txt`（几 MB）；浏览器内核约 270MB，**首次真正需要渲染时**才后台下载，期间插件照常降级为纯文本，装好后自动生效、不用重启。只装 headless shell 是刻意的——永远只截图，不需要带界面的浏览器。

渲染不可用时返回**空串而不抛异常**：插件普遍在 `if img_path:` 上分支降级（上游的远程服务也会挂），抛异常只会被它的 `except` 吞掉再重试。

浏览器单实例复用（冷启一次 1~2 秒，而这是主链路上的同步等待），`bot.py` 注册了 `on_shutdown` 关闭它——playwright 起的是独立的 node + chromium 子进程，Python 退出不会带走它们。

配置项见 [配置参考](../reference/configuration.md#html--图片渲染插件卡片)。
## 本地状态接口

`deploy status` 与桌面 GUI 需要读到进程内状态（`link_status()`、调度器排队深度），外部进程拿不到。

**为什么用 HTTP 而不是状态文件**：状态文件有陈旧问题——Bot 崩了之后文件仍在，读到的「运行中」是假的。HTTP 端点天然「连不上就是没运行」，还顺带覆盖了「进程在但 HTTP 服务没起来」的中间态（`api_reachable=false`，GUI 据此显示「正在启动…」）。

**为什么不新增端口**：NoneBot 本就跑着 FastAPI/uvicorn，反向 WS 端点 `/onebot/v11/ws` 就是它提供的。状态路由直接挂在同一个 app 上（`GET /stella/status`），Stella 仍然只有一个监听端口（`PORT`）。

**实现**：`stella_project/plugins/bot_main/status_api.py`。`setup_status_api()` 在 ai_gateway 的启动段（扩展加载之后）调用；`build_payload()` 聚合 `link_status()`、`core.llm.snapshot()`、`usage_store.usage_snapshot()`、`capability.inventory.snapshot()`、skills 运行时状态与版本/进程信息，返回 `{version, instance_id, pid, uptime_seconds, allowed_group_count, link, scheduler, usage, capabilities, skills}`，外加两个条件键：`runtime`（Runtime Contract 状态，取到才出现）与 `chat_engine`（对话引擎面：mode/keys/inflight——facade 唯一引擎的健康快照，同样只有结构化字段）。消费方是 `deploy/process.py` 的 `_fetch_live_status()`（回环查询、1 秒超时）与 GUI/WebUI 面板。

**安全约束**：`HOST` 可能是 `0.0.0.0`（NapCat 在另一台机器时必须如此），此时路由暴露到局域网。两道防护：① 只接受回环地址的请求，其余返回 403；② 响应体不含凭据与群聊内容——`allowed_group_count` 只给数量不给群号，`usage` 只有计数与比率（token 数、调用次数、缓存命中率、槽名与模型 ID），绝不含 prompt 与模型输出，`capabilities` 只有结构化字段（能力 id、域、来源层、是否可路由、provider 工具名与健康度、examples 条数），不含声明里的 `description` 与 `examples` 原文——那两个字段是唯一可能夹带 URL 与密钥的地方，不放进响应体就不必为它加一道守卫。`tests/test_status_api.py` 把这条约束钉成了断言：它拿 `usage_snapshot()` 的真实输出过一遍序列化，出现 `api_key` / `Bearer` / `http://` 即失败。
## 扩展机制

`extensions/` 下的每个模块/包若提供 `setup(pipeline)`，启动时会被自动加载。扩展可以注册 Hook、注入实现、启动自己的定时任务。

`link_monitor` 是参考实现：它在 import 时注册一个 `event_preprocessor`（任何 OneBot 事件刷新心跳）、两个 driver 钩子（`on_bot_connect` / `on_bot_disconnect`）与一个自己的定时任务（事件超时后主动探活，探活失败只告警不重启）。扩展无需改动业务主程序即可接入。
## v2 控制面（WebUI 与桌面壳）

浏览器与桌面壳共用的管理面板：`dashboard/`（Vue 3 + Vuetify 3）为前端，
`webui/`（FastAPI 子应用）挂在 NoneBot 同一 ASGI 端口上——**不新增端口**；
`desktop/`（Tauri 2 壳）内嵌同一份面板，离线时经窄契约（启动/自检/配置）
工作。鉴权、首启向导、故障排查见 [docs/webui.md](../guides/webui.md) 与
[design_docs 的 v2 方案](../../design_docs/Stella%20GUI%20v2%20%E4%B8%8E%20WebUI%20%E5%BB%BA%E8%AE%BE%E6%96%B9%E6%A1%88%20v1.0.md)。
v1 安装器（`stella-installer/`）已冻结于 tag `gui-v1-final`。
