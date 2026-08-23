# scripts/probe_astrbot_llm.py
# SPDX-License-Identifier: AGPL-3.0
"""AstrBot 插件 LLM 兼容层探针：拿真实本地模型跑一遍插件的调用面。

pytest 里 ``chat_completion`` 是打桩的，所以「能不能真的问到模型」「小模型会不会
真的调工具」只能靠这个探针。它跑的是生产链路：``core/llm/scheduler`` 闸门 →
``core/llm/openai_client.py`` → ``StellaChatProvider`` → ``run_tool_loop``。

用法（项目根目录，LM Studio 已加载 ``ASTRBOT_LLM_MODEL`` 指定的模型）：
    python scripts/probe_astrbot_llm.py                 # 全部小节
    python scripts/probe_astrbot_llm.py chat tools      # 只跑指定小节

小节：chat / persona / stream / tools / budget / conversation

会话与偏好读写指向临时库，**不会碰 DB_PATH 对应的真实数据库**。
"""

from __future__ import annotations

import asyncio
import logging
import sys
import tempfile
from pathlib import Path

# 允许直接 `python scripts/probe_astrbot_llm.py` 运行：把项目根加入 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from astrbot_compat.llm import (
    FunctionTool,
    ProviderRequest,
    ToolSet,
    run_tool_loop,
)
from astrbot_compat.llm.manager import get_provider_manager
from config import settings


def _redirect_db() -> Path:
    """把兼容层的两张表指到临时库，别动用户的真实数据库。"""
    from astrbot_compat import conversation as conv_mod
    from astrbot_compat import preferences as pref_mod

    db = Path(tempfile.mkdtemp(prefix="stella_probe_")) / "probe.db"
    conv_mod.DB_PATH = db
    pref_mod.DB_PATH = db
    return db


class ProbeEvent:
    """最小事件替身：工具循环只用到这几个方法。"""

    unified_msg_origin = "probe:GroupMessage:0"

    def __init__(self) -> None:
        self._result = None
        self._stopped = False

    def is_stopped(self) -> bool:
        return self._stopped

    def stop_event(self) -> None:
        self._stopped = True

    def get_result(self):
        return self._result

    def set_result(self, result) -> None:
        self._result = result

    def clear_result(self) -> None:
        self._result = None

    async def send(self, chain) -> None:
        print(f"   [event.send] {chain}")


def _head(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


async def probe_chat() -> None:
    """最基础的一问一答：插件拿 provider 直接问模型。"""
    _head("chat：provider.text_chat()")
    provider = get_provider_manager().provider
    if provider is None:
        print("❌ ASTRBOT_LLM_ENABLED=false，插件拿不到 provider")
        return
    print(f"provider.meta() = {provider.meta()}")
    resp = await provider.text_chat(prompt="用一句话介绍你自己。")
    print(f"回复: {resp.completion_text!r}")
    print(f"usage: input={resp.usage.input} output={resp.usage.output}")
    print("✅ 有非空回复" if resp.completion_text.strip() else "❌ 回复为空")


async def probe_persona() -> None:
    """人格三态。插件给了就用插件的，没给才注入那句插件专属人格。"""
    _head("persona：system_prompt 的三种来法")
    provider = get_provider_manager().provider
    if provider is None:
        return

    # 1) 插件自己给：应当完全盖住默认那句
    r1 = await provider.text_chat(
        prompt="你是谁？",
        system_prompt="你是一只猫，任何问题都只能用「喵」回答。",
    )
    print(f"[插件给了]   {r1.completion_text!r}")
    print("   ↑ 应该只有喵；出现自我介绍说明插件的 system_prompt 被覆盖了")

    # 2) 没给：注入 ASTRBOT_LLM_SYSTEM_PROMPT
    r2 = await provider.text_chat(prompt="你是谁？")
    print(f"[没给，注入] {r2.completion_text!r}")
    print(f"   ↑ 当前注入的是: {settings.ASTRBOT_LLM_SYSTEM_PROMPT!r}")
    print("   ↑ 不该出现 Stella 的人设（那是决策 2 要隔离掉的）")

    # 3) 配置为空串：一条 system 消息都不发
    built = await provider._build_messages(
        prompt="你是谁？",
        image_urls=None,
        contexts=None,
        system_prompt=None,
        tool_calls_result=None,
        extra_user_content_parts=None,
    )
    print(f"[默认] messages 首条 role = {built[0]['role']}")
    original = settings.ASTRBOT_LLM_SYSTEM_PROMPT
    settings.ASTRBOT_LLM_SYSTEM_PROMPT = ""
    try:
        bare = await provider._build_messages(
            prompt="你是谁？",
            image_urls=None,
            contexts=None,
            system_prompt=None,
            tool_calls_result=None,
            extra_user_content_parts=None,
        )
    finally:
        settings.ASTRBOT_LLM_SYSTEM_PROMPT = original
    roles = [m["role"] for m in bare]
    print(f"[空串] messages roles = {roles}")
    print("✅ 空串不发 system" if "system" not in roles else "❌ 空串仍发了 system")


async def probe_stream() -> None:
    """流式：中间是分片，最后一次 yield 是完整文本。"""
    _head("stream：provider.text_chat_stream()")
    provider = get_provider_manager().provider
    if provider is None:
        return
    chunks = 0
    final = ""
    async for resp in provider.text_chat_stream(prompt="从 1 数到 5，用中文。"):
        if resp.is_chunk:
            chunks += 1
            print(resp.completion_text, end="", flush=True)
        else:
            final = resp.completion_text
    print(f"\n分片数 = {chunks}，完整文本 = {final!r}")
    print("✅ 分片与完整结果都拿到了" if chunks and final else "❌ 流式没产出")


async def probe_tools() -> None:
    """工具调用循环。小模型的 function calling 不稳，这一节最值得实测。"""
    _head("tools：run_tool_loop() 真的会调工具吗")
    provider = get_provider_manager().provider
    if provider is None:
        return

    called: list[str] = []

    async def get_weather(event, location: str):
        """查询某地天气。

        Args:
            location(string): 地点名
        """
        called.append(location)
        return f"{location}：晴，26 摄氏度"

    tools = ToolSet()
    tools.add_tool(
        FunctionTool(
            name="get_weather",
            description="查询某地今天的天气",
            parameters={
                "type": "object",
                "properties": {"location": {"type": "string", "description": "地点名"}},
                "required": ["location"],
            },
            handler=get_weather,
        ),
    )

    event = ProbeEvent()
    req = ProviderRequest(
        prompt="北京今天天气怎么样？请用工具查。",
        session_id=event.unified_msg_origin,
        func_tool=tools,
    )
    resp = await run_tool_loop(provider, req, event)
    print(f"工具被调用: {called}")
    print(f"最终回复: {resp.completion_text!r}")
    if called:
        print("✅ 模型调了工具，并把结果复述给用户")
    else:
        print(
            "⚠️ 模型没调工具。链路本身没问题（tools 已随请求送出），"
            "这是本地小模型 function calling 能力的问题——换更大的模型再试。",
        )


async def probe_budget() -> None:
    """上下文预算：塞一堆历史进去，应当被裁剪而不是被服务端拒。"""
    _head("budget：超预算的上下文会被裁掉最早的几条")
    provider = get_provider_manager().provider
    if provider is None:
        return
    filler = "这是一条用来占满上下文窗口的历史消息。" * 20
    contexts = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"{i}. {filler}"}
        for i in range(120)
    ]
    print(f"送入 {len(contexts)} 条历史（上限 {settings.ASTRBOT_LLM_MAX_CONTEXT_TOKENS} token）")
    print("↓ 下面应出现「上下文超预算，已丢弃最早的 N 条」的 WARNING")
    resp = await provider.text_chat(prompt="就回答「收到」两个字。", contexts=contexts)
    print(f"回复: {resp.completion_text!r}")
    print("✅ 超长上下文没让请求失败" if resp.completion_text else "❌ 请求没拿到回复")


async def probe_conversation() -> None:
    """会话表：建、写、读、删。不需要模型。"""
    _head("conversation：ConversationManager 落库往返")
    from astrbot_compat.conversation import get_conversation_manager

    mgr = get_conversation_manager()
    umo = "probe:GroupMessage:0"
    cid = await mgr.new_conversation(umo, title="探针会话")
    print(f"新建 cid = {cid}")
    print(f"当前会话 id = {await mgr.get_curr_conversation_id(umo)}")

    await mgr.add_message_pair(
        cid,
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好呀"},
    )
    conv = await mgr.get_conversation(umo, cid)
    print(f"history（JSON 字符串）= {conv.history!r}")
    lines, pages = await mgr.get_human_readable_context(umo, cid)
    print(f"可读上下文 = {lines}（共 {pages} 页）")

    await mgr.delete_conversation(umo, cid)
    print(f"删除后还剩 {len(await mgr.get_conversations(umo))} 条会话")
    ok = conv is not None and len(lines) == 2
    print("✅ 会话往返正常" if ok else "❌ 会话往返异常")


SECTIONS = {
    "chat": probe_chat,
    "persona": probe_persona,
    "stream": probe_stream,
    "tools": probe_tools,
    "budget": probe_budget,
    "conversation": probe_conversation,
}


async def main(names: list[str]) -> None:
    db = _redirect_db()
    print(f"临时库: {db}")
    print(f"base_url = {settings.ASTRBOT_LLM_BASE_URL}")
    print(f"model    = {settings.ASTRBOT_LLM_MODEL}")
    for name in names:
        await SECTIONS[name]()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s | %(message)s",
    )
    requested = sys.argv[1:] or list(SECTIONS)
    unknown = [n for n in requested if n not in SECTIONS]
    if unknown:
        sys.exit(f"未知小节 {unknown}，可选: {list(SECTIONS)}")
    asyncio.run(main(requested))
