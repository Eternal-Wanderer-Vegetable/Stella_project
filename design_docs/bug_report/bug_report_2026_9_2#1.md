我现在能在聊天里自动用上的能力有 5 项：
【娱乐】
· 推荐近期热门或值得一看的动画、番剧、ACG 作品
· 查询某一天放送、更新哪些动画（每日放送表）
· 按关键词、年份、标签、评分、排名等条件检索具体的 ACG 作品信息
· 查询某个哔哩哔哩 UP 主最近发布的动态内容
· 查询哔哩哔哩的热门视频、热榜、近期高热内容

> 注：这是别人部署后的错误回复。实际上没有安装任何插件。本项不该有任何内容。

---

状态：已修复（2026-09-03）。

根因：`registry.routable()` 只查 `route_enabled` / `enabled` / backoff 与原型语料，**不查声明指向的工具此刻在不在**。出厂目录里的 `config/capabilities/entertainment.toml` 声明了 5 项 ACG 能力，指向 `astrbot_plugin_bilibili` 的 5 个 `@llm_tool`——插件没装时那 5 项照样算「可路由」。不止是「你能做什么」答错：`routable()` 是 L0/L1/L2 三级路由**唯一**的候选集来源，所以「番剧推荐」「B站热门」这类话会真的被派给一个不存在的工具，最后在 Comes 里 failed，而那 5 条原型向量还一直在和真实能力抢 `ROUTER_CAPABILITY_MARGIN` 的间距。

修复：给注册表加一个**可注入的工具存活探针**，`routable()` 经 `_tool_live()` / `live_providers()` 查一句「这个工具此刻在不在」，判据与 `comes/executor.py::resolve_tools` 逐字一致（kind 是 `astrbot_tool`、查得到、且 `active`）。探针由 `bot.py::_bootstrap_capabilities` 在 `bootstrap()` **之前**调 `adapters/astrbot.py::install_tool_probe()` 装上，且在**每次查询**时才被调用，所以插件热重载后不用重装。

为什么是「可注入」而不是无条件检查：`deploy plugin-scaffold` 与 `python -m capability.router.benchmark` 刻意在没有插件的独立进程里跑 `bootstrap()`，它们量的是声明语料的质量，本就不该受装了哪些插件影响；而「空的工具注册表」在这两种场合和在一台全新部署上长得一模一样，两者只能靠「探针装没装」区分。没装探针时（默认）语义与从前一致。

顺带修正的措辞：`deploy capabilities` 与群内管理员那份清单，原来把这种情况一律说成「工具名拼错」——新部署上缺的是插件而不是拼写，现在两处共用 `inventory.HINT_MISSING_TOOL`，先说「插件没装」。

回归守卫：`tests/test_capability_query.py::test_factory_declarations_stay_dark_until_their_plugin_is_installed`（直接读仓库里真会出厂的那份 `config/capabilities/`）、`tests/capability/test_registry.py` 的「工具存活探针」一节、`tests/capability/test_astrbot_adapter.py::test_install_tool_probe_makes_a_declaration_wait_for_its_plugin`。设计理由见 `docs/capability-system.md`「声明指向的工具不在，这条能力就不进候选集」。
