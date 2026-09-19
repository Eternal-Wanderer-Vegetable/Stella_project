# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""图片识别（视觉转述）：把图片翻译成一句客观文字描述。

设计见 ``design_docs/Stella_图片识别（视觉转述）实施计划 v1.0.md``。

链路：接入层提取图片来源（``extract_image_sources``）→ 本模块转述
（``describe_images``，走独立的 ``ROLE_VISION`` 角色）→ 描述并入
``ctx.message``，下游记忆/检索/prompt 全部照旧走纯文本。

**默认关闭**：``vision_available()`` 要求 ``VISION_ENABLED`` 且 VISION 角色
绑定了可用端点（默认 ``LLM_ROLE_VISION_ENDPOINT=none``）。未绑定时所有
新增行为不生效——这是默认状态而非降级路径，本地消费级模型普遍不具备
转述能力，必须显式配置。

图片来源形态（与 ``astrbot_compat.llm.entities._to_image_data_url`` 同款语义）：
http(s) URL 直传（在线端点）或下载转 data URL（本地端点）；``base64://``、
``data:`` 原样；本地路径读文件转 data URL。QQ CDN URL 会过期，描述必须
在收到消息时生成——图片本身不留到以后再看。
"""

from __future__ import annotations

import asyncio
import base64
import mimetypes
from collections import OrderedDict
from pathlib import Path
from typing import Any

import httpx
from nonebot import logger

from config import (
    VISION_DESCRIBE_TIMEOUT,
    VISION_ENABLED,
    VISION_INCLUDE_QUOTED,
    VISION_MAX_IMAGE_BYTES,
    VISION_MAX_IMAGES,
)
from core.llm import PRIORITY_INTERACTIVE, ROLE_VISION, acquire, backend_for, gate_of
from core.llm.registry import binding, endpoint_of
from core.llm.usage_store import budget_blocked

# 转述提示词：写死一句，不进配置。要求客观、简短——输出会被并到用户输入里，
# 任何发挥都会污染记忆与回复。
_DESCRIBE_PROMPT = (
    "请用一到两句中文客观描述这张图片的内容，包括主要人物/物体、场景和图中的文字。"
    "只说事实，不要评论，不要打招呼。"
)

# 转述结果缓存（key = 来源字符串）。同一 URL 在一条消息里重复出现、或
# 短时间内被引用时不必重复计费。容量限制防止内存无限涨。
_CAPTION_CACHE_MAX = 256
_caption_cache: OrderedDict[str, str] = OrderedDict()

# 下载图片时的连接/读取超时（秒）。写死不给配置项：QQ CDN 偶发慢，
# 15 秒足够覆盖又不至于拖住整条回复；真正的单图预算是 VISION_DESCRIBE_TIMEOUT。
_DOWNLOAD_TIMEOUT = 15.0

_IMAGE_PLACEHOLDER = "[图片]"


def _settings() -> Any:
    """读 ``config.settings`` 的属性（与 registry/provider 同款惯例）。"""
    from config import settings

    return settings


def vision_available() -> bool:
    """「识图功能此刻是否可用」的单一判据，所有新增行为的开关。

    要求 ``VISION_ENABLED`` 且 VISION 角色绑定了可用端点。未绑定时（默认）
    返回 False——触发放行、占位落库、转述钩子全部走旧路径。
    """
    if not VISION_ENABLED:
        return False
    try:
        return backend_for(ROLE_VISION) is not None
    except Exception:
        return False


def _segment_image_source(segment: Any) -> str:
    """从一个 OneBot image 消息段提取可用的图片来源；取不到返回空串。

    优先 ``data.url``（QQ CDN，在线端点可直接用）；退化 ``data.file``
    （本地路径 / file:// / base64://）；再退化 ``data.path``（NapCat 本地缓存）。
    """
    data = getattr(segment, "data", None)
    if not isinstance(data, dict):
        return ""
    for key in ("url", "file", "path"):
        value = str(data.get(key) or "").strip()
        if not value:
            continue
        return value.removeprefix("file://")
    return ""


def _collect_segment_images(message: Any) -> list[str]:
    """扫一条 OneBot Message 的全部 image 段。"""
    sources: list[str] = []
    if message is None:
        return sources
    for segment in message:
        if getattr(segment, "type", "") != "image":
            continue
        src = _segment_image_source(segment)
        if src and src not in sources:
            sources.append(src)
    return sources


def extract_image_sources(event: Any, *, include_quoted: bool | None = None) -> list[str]:
    """提取事件中可转述的图片来源（本体 + 可选的引用消息）。

    ``event`` 是 OneBot v11 消息事件（鸭子类型：get_message / reply）。
    引用消息由适配器的 ``_check_reply`` 自动 ``get_msg`` 填充，不需要额外
    API 调用；取不到时只跳过，不报错。

    返回去重、按 ``VISION_MAX_IMAGES`` 截断后的来源列表；顺序保持出现顺序。
    """
    if include_quoted is None:
        include_quoted = bool(VISION_INCLUDE_QUOTED)
    sources = _collect_segment_images(event.get_message())
    if include_quoted:
        quoted = getattr(event, "reply", None)
        quoted_msg = getattr(quoted, "message", None) if quoted is not None else None
        for src in _collect_segment_images(quoted_msg):
            if src not in sources:
                sources.append(src)
    limit = max(0, int(VISION_MAX_IMAGES))
    if limit and len(sources) > limit:
        logger.info(
            f"[Vision] 消息含 {len(sources)} 张图，按 VISION_MAX_IMAGES={limit} 截断"
        )
    return sources[:limit] if limit else []


def _mime_for_path(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    return mime if mime and mime.startswith("image/") else "image/jpeg"


async def _read_local_image(path_str: str) -> str:
    """本地文件 → data URL；读不出/超限返回空串。"""
    try:
        path = Path(path_str)
        if not path.is_file():
            return ""
        if path.stat().st_size > VISION_MAX_IMAGE_BYTES:
            logger.info(f"[Vision] 本地图片超限跳过: {path_str}")
            return ""
        b64 = base64.b64encode(path.read_bytes()).decode()
        return f"data:{_mime_for_path(path)};base64,{b64}"
    except OSError as e:
        logger.debug(f"[Vision] 本地图片读取失败 {path_str}: {e}")
        return ""


async def _download_image(url: str) -> str:
    """http(s) 图片 → data URL；下载失败/超限返回空串。"""
    try:
        async with (
            httpx.AsyncClient(
                timeout=httpx.Timeout(_DOWNLOAD_TIMEOUT), trust_env=False
            ) as client,
            client.stream("GET", url) as resp,
        ):
            resp.raise_for_status()
            declared = int(resp.headers.get("content-length") or 0)
            if declared and declared > VISION_MAX_IMAGE_BYTES:
                logger.info(f"[Vision] 图片超限跳过（{declared} 字节）")
                return ""
            chunks: list[bytes] = []
            size = 0
            async for chunk in resp.aiter_bytes():
                size += len(chunk)
                if size > VISION_MAX_IMAGE_BYTES:
                    logger.info(f"[Vision] 图片超限跳过（>{VISION_MAX_IMAGE_BYTES} 字节）")
                    return ""
                chunks.append(chunk)
            mime = resp.headers.get("content-type") or "image/jpeg"
            if not mime.startswith("image/"):
                mime = "image/jpeg"
            b64 = base64.b64encode(b"".join(chunks)).decode()
            return f"data:{mime};base64,{b64}"
    except Exception as e:
        logger.warning(f"[Vision] 图片下载失败: {e}")
        return ""


async def _normalize_source(src: str, *, is_local_endpoint: bool) -> str:
    """把来源统一成可直接进 messages 的 URL 或 data URL；不可用返回空串。

    在线端点直接传 http URL（厂商自己拉图，省一次下载+base64）；
    本地端点必须下载成 data URL——LM Studio 类服务不会去抓 QQ CDN。
    """
    src = (src or "").strip()
    if not src:
        return ""
    if src.startswith(("data:",)):
        return src
    if src.startswith("base64://"):
        return f"data:image/jpeg;base64,{src[9:]}"
    if src.startswith(("http://", "https://")):
        return src if not is_local_endpoint else await _download_image(src)
    return await _read_local_image(src)


def _vision_call_args() -> dict | None:
    """VISION 角色的端点 + 参数；未绑定时返回 ``None``（正常分支）。"""
    ep = endpoint_of(ROLE_VISION)
    b = binding(ROLE_VISION)
    if ep is None or b is None:
        return None
    return {
        "base_url": ep.base_url,
        "api_key": ep.api_key,
        "kind": ep.kind,
        "slot": ep.slot,
        "role": ROLE_VISION,
        "timeout": ep.timeout,
        "model": b.model,
        "temperature": b.temperature,
        "max_tokens": b.max_tokens,
    }


async def _describe_one(src: str, call_args: dict, *, is_local_endpoint: bool) -> str:
    """单张图 → 描述文本；任何失败返回空串（调用方按占位处理）。"""
    from core.llm.openai_client import chat_completion

    url = await _normalize_source(src, is_local_endpoint=is_local_endpoint)
    if not url:
        return ""
    user_content = [
        {"type": "text", "text": _DESCRIBE_PROMPT},
        {"type": "image_url", "image_url": {"url": url}},
    ]
    messages = [{"role": "user", "content": user_content}]
    async with acquire(
        gate_of(ROLE_VISION), tag="vision:describe", priority=PRIORITY_INTERACTIVE
    ):
        data = await asyncio.wait_for(
            chat_completion(messages, **call_args),
            timeout=VISION_DESCRIBE_TIMEOUT,
        )
    try:
        text = str(data["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError):
        return ""
    return text


async def describe_images(sources: list[str], *, user_text: str = "") -> list[str]:
    """把每张图转成一句客观描述；全链路吞异常，绝不阻断回复。

    参数:
        sources: ``extract_image_sources`` 的产出；
        user_text: 用户同时发的文字（预留：描述提示词的语境）。
    返回:
        与输入同序的描述列表；失败的图被跳过（调用方按 ``[图片]`` 占位处理）。
        功能不可用 / 预算拦下 / 输入为空时返回 ``[]``。
    """
    _ = user_text  # 预留给「结合用户问题看图」的提示词演进，当前固定提示词
    if not sources or not vision_available():
        return []
    blocked = budget_blocked(ROLE_VISION)
    if blocked:
        logger.warning(f"⚠️ [Vision] 图片转述被预算拦下，按占位处理（{blocked}）")
        return []
    call_args = _vision_call_args()
    if call_args is None:
        return []
    ep = endpoint_of(ROLE_VISION)
    is_local = bool(ep is not None and ep.kind == "local")

    captions: list[str] = []
    for src in sources:
        cached = _caption_cache.get(src)
        if cached is not None:
            _caption_cache.move_to_end(src)
            captions.append(cached)
            continue
        try:
            caption = await _describe_one(src, call_args, is_local_endpoint=is_local)
        except asyncio.TimeoutError:
            logger.warning(f"[Vision] 单张图片转述超时（{VISION_DESCRIBE_TIMEOUT}s），占位")
            caption = ""
        except Exception as e:
            logger.warning(f"[Vision] 单张图片转述失败（占位）: {e}")
            caption = ""
        if caption:
            _caption_cache[src] = caption
            _caption_cache.move_to_end(src)
            while len(_caption_cache) > _CAPTION_CACHE_MAX:
                _caption_cache.popitem(last=False)
            captions.append(caption)
    return captions


async def update_recorded_message(group_id: int, msg_id: int, content: str) -> bool:
    """把刚落库的群消息改写成最终内容（占位 → 带描述）。

    为什么需要它：``record_group_chat``（priority 0）必须先落库防丢失，
    那时图片描述还没生成；转述完成后按 ``msg_id`` 回写最终文本，尾巴与
    整合看到的就是完整内容。行找不到（msg_id=0 的 BOT_SELF 行、旧库）返回
    False，调用方无需处理。
    """
    if not msg_id or not content:
        return False
    try:
        import sqlite3

        from config import DB_PATH

        conn = sqlite3.connect(DB_PATH)
        try:
            cursor = conn.execute(
                "UPDATE group_messages SET content = ? "
                "WHERE msg_id = ? AND group_id = ?",
                (content, str(msg_id), str(group_id)),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()
    except Exception as e:
        logger.debug(f"[Vision] 回写消息描述失败（跳过）: {e}")
        return False


__all__ = [
    "_IMAGE_PLACEHOLDER",
    "describe_images",
    "extract_image_sources",
    "update_recorded_message",
    "vision_available",
]
