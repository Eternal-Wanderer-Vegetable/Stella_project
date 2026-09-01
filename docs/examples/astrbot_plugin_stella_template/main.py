# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Stella 插件接入规范的模板插件。

这份文件同时是**文档**与**回归夹具**：`tests/test_plugin_check.py` 会拿它跑一遍
`python -m deploy plugin-check`，断言零 error、零 warn。规范与校验器一旦漂移，
这个测试会先失败——所以它比一段示例代码更耐用。

它演示了规范里最容易写错的四件事：

1. 两条接入通路各写一个（`@filter.command` 指令 / `@filter.llm_tool` 工具）；
2. 工具是**只读、幂等**的——Comes 不经用户确认就会调它；
3. 后台任务走 `self.context.register_task`，不裸调 `asyncio.create_task`；
4. 失败**抛异常**而不是 `return "查询失败……"`（理由见 docs/plugin-spec.md §6.6）。

导入路径全部用 `astrbot.api.*`：这样它在 AstrBot 上也能原样跑，Stella 侧由
`astrbot_compat/shim.py` 把这些模块伪装进 `sys.modules`。
"""

from __future__ import annotations

import asyncio

from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star

MAX_TEXT_CHARS_DEFAULT = 2000


class StellaTemplatePlugin(Star):
    """一个最小但完整的 Stella 插件。"""

    def __init__(self, context: Context, config=None) -> None:
        super().__init__(context, config)
        self._calls = 0

    @property
    def _max_chars(self) -> int:
        """读 `_conf_schema.json` 里的 `max_text_chars`。

        `self.config` 是 `AstrBotConfig`（由 schema 展开出默认值后与用户配置合并），
        用 `.get(key, 默认值)` 取——`config` 为 None 的场景（未装 schema、单测直接实例化）
        必须能正常工作，所以默认值写在代码里而不是假定 schema 一定被读到了。
        """
        if self.config is None:
            return MAX_TEXT_CHARS_DEFAULT
        return int(self.config.get("max_text_chars", MAX_TEXT_CHARS_DEFAULT))

    async def initialize(self) -> None:
        """插件被激活时调用。此时事件循环已经在跑，可以起后台任务。

        **必须走 `register_task`**：只有登记过的任务在插件卸载与热重载时收得回。
        裸 `asyncio.create_task(...)` 起的任务重载后会残留并继续跑，而这不报错。
        """
        self.context.register_task(self._heartbeat(), "template_heartbeat")

    async def terminate(self) -> None:
        """插件被禁用 / 重载时调用。超时 5 秒，别在这里做慢 IO。"""
        self._calls = 0

    async def _heartbeat(self) -> None:
        """示范用的空转任务：什么都不做，只证明它会被正确回收。"""
        while True:
            await asyncio.sleep(3600)

    # ---------- 通路一：指令 ----------

    @filter.command("模板")
    async def show_intro(self, event: AstrMessageEvent):
        """`/模板` —— 指令通路：确定性触发，不经过语义路由。

        会发消息、下单、改外部状态的功能一律走这里，**不要**做成可路由工具：
        Comes 调工具时不会向用户确认。
        """
        yield event.plain_result(
            "我是 Stella 插件模板。\n"
            f"指令：{event.get_platform_name()} 下发 /模板\n"
            f"工具：直接问「这段话有多少字」即可（已被调用 {self._calls} 次）",
        )

    # ---------- 通路二：可路由工具 ----------

    @filter.llm_tool("get_text_stats")
    async def get_text_stats(self, event: AstrMessageEvent, text: str):
        """统计一段文字的字数、行数与非空白字符数。

        Args:
            text(string): 要统计的那段文字
        """
        _ = event
        if not text or not text.strip():
            # 失败要**抛异常**。改成 return "统计失败：没有内容" 的话，那串字不以
            # error: 开头，会被当成成功输出、贴上「真实数据」进 Stella 的 prompt，
            # 于是 Stella 把失败文案当事实转述给用户，而 provider 退避永远不触发。
            raise ValueError("没有可统计的文字")
        limit = self._max_chars
        if len(text) > limit:
            raise ValueError(f"文字过长（{len(text)} 字），上限 {limit} 字")
        self._calls += 1
        dense = "".join(text.split())
        # 返回值要短：它只经 summarizer 摘成 ≤300 字符进 prompt，
        # 而且要先过受限 agent 自己的 8192 窗口。别甩几千字 JSON。
        result = f"共 {len(text)} 字（非空白 {len(dense)} 字）"
        with_lines = self.config is None or self.config.get("reply_with_lines", True)
        if with_lines:
            result += f"，{len(text.splitlines()) or 1} 行"
        return result + "。"
