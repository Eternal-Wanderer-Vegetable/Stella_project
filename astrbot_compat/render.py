# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""HTML → 图片渲染：``Star.html_render`` / ``text_to_image`` 的后端。

## 为什么需要真的实现它

大量 AstrBot 插件把「结果卡片」做成 Jinja2 模板 + CSS，靠 ``html_render`` 出图。
这个方法之前在兼容层里直接 ``raise StellaCompatNotSupported``，后果是**插件永远走
降级分支**：2026-08-25 实测 bilibili 插件每次都回「渲染图片失败了 (´;ω;`)」+ 纯文本，
而且它自己还会重试 3 次、每次间隔 2 秒——为一个永远不可能成功的调用白等约 4 秒。

## 为什么是本地 Chromium 而不是远程服务

上游 AstrBot 默认把 HTML 发到远程 t2i 服务出图。Stella 不走这条路：模板里填的是
群友昵称、动态正文、头像 URL，属于聊天内容；本项目其他环节（对话模型、embedding、
记忆整合）全部在本地，渲染没有理由成为唯一出网的一环。

代价是浏览器内核（headless shell 约 270MB，见 _INSTALL_TARGET）。**不能用轻量方案替代**：插件模板普遍用 flexbox、线性渐变、
border-radius、box-shadow（bilibili 插件的三个模板各 350~460 行 CSS），
weasyprint 之类没有完整 flex 支持，出图会直接错版——错版比降级更糟，因为它看起来
「成功了」。

## 依赖策略：pip 包是硬依赖，浏览器按需下载

``playwright`` 的 pip 包只有几 MB，进 requirements.txt；浏览器内核约 270MB，
**首次真正需要渲染时**才在后台下载（``RENDER_AUTO_INSTALL``）。下载期间照常降级
（插件回纯文本），装好后自动生效，不需要重启。

这样「装了 Stella 但从不用渲染类插件」的人零成本，而用的人也不必手工装。

## 失败一律降级，绝不抛给插件

所有入口返回 ``Path | None``：``None`` 表示这次渲染不可用。插件那边本来就有降级分支
（它必须有——上游的远程服务也会挂）。抛异常只会让插件的 except 吞掉后重试。
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import re
import sys
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("astrbot_compat.render")

# 模板里普遍写 <meta name="viewport" content="width=700">，取不到时的兜底宽度
DEFAULT_VIEWPORT_WIDTH = 700
# device_scale_factor_level（上游 options 里的枚举）→ 实际缩放倍数
_SCALE_LEVELS = {"low": 1.0, "medium": 1.5, "high": 2.0, "ultra": 3.0}
_VIEWPORT_RE = re.compile(
    r"""<meta[^>]*name\s*=\s*["']viewport["'][^>]*content\s*=\s*["']([^"']*)["']""",
    re.IGNORECASE,
)
_WIDTH_RE = re.compile(r"width\s*=\s*(\d+)")
# playwright 在浏览器没装时抛的错里一定有这两个特征之一
_MISSING_BROWSER_MARKERS = ("executable doesn't exist", "playwright install")
# 只装/只用 headless shell：我们永远只截图，不需要带界面的浏览器。
# 实测 `playwright install chromium` 会拉 ~700MB（chromium 428MB + shell 272MB），
# 只装 shell 是 ~270MB。装了完整 chromium 的机器也能跑——见 _LAUNCH_CHANNELS。
_INSTALL_TARGET = "chromium-headless-shell"
# 启动渠道的尝试顺序：先 headless shell，失败再退回 playwright 自带的 chromium
# （用户可能装的是完整版，或 playwright 版本老到没有这个 channel）。
_LAUNCH_CHANNELS: tuple[str | None, ...] = (_INSTALL_TARGET, None)


def _settings() -> Any:
    """读 config.settings 的属性而不是 ``from config import X``（见 capability/router/semantic.py）。"""
    from config import settings

    return settings


# ============================================================
# 纯函数：options → playwright 参数
# ============================================================


def parse_viewport_width(html: str, default: int = DEFAULT_VIEWPORT_WIDTH) -> int:
    """从 ``<meta name="viewport" content="width=700">`` 取宽度。

    模板作者用这个 meta 声明「这张图该多宽」，是唯一可靠的宽度来源——不读它就得靠
    猜，卡片会被压窄或留大片空白。取不到/非法时返回 default。
    """
    m = _VIEWPORT_RE.search(html or "")
    if m:
        w = _WIDTH_RE.search(m.group(1))
        if w:
            with contextlib.suppress(ValueError):
                width = int(w.group(1))
                if 100 <= width <= 4000:
                    return width
    return default


def context_kwargs(html: str, options: dict | None = None) -> dict:
    """浏览器上下文参数（视口与像素密度）。

    ``device_scale_factor`` 必须在**上下文**上设，不能在 screenshot 上设——后者只有
    ``scale`` 这个二选一开关。上游 options 里的 ``device_scale_factor_level``
    是个枚举（low/medium/high/ultra），这里换成实际倍数。
    """
    opts = options or {}
    level = str(opts.get("device_scale_factor_level") or "medium").lower()
    factor = _SCALE_LEVELS.get(level, _SCALE_LEVELS["medium"])
    with contextlib.suppress(TypeError, ValueError):
        # 也允许直接给数字（上游有插件这么传）
        if opts.get("device_scale_factor"):
            factor = float(opts["device_scale_factor"])
    factor = min(max(factor, 1.0), 4.0)
    return {
        "viewport": {"width": parse_viewport_width(html), "height": 800},
        "device_scale_factor": factor,
    }


def screenshot_kwargs(options: dict | None = None) -> dict:
    """``page.screenshot()`` 参数。

    ``quality`` 只有 jpeg 能带——png 传了会被 playwright 直接拒（报错而不是忽略），
    所以必须按 type 过滤，不能原样透传 options。
    """
    opts = options or {}
    img_type = str(opts.get("type") or "png").lower()
    if img_type not in ("png", "jpeg"):
        img_type = "png"
    kwargs: dict[str, Any] = {
        "full_page": bool(opts.get("full_page", True)),
        "type": img_type,
    }
    if img_type == "jpeg":
        quality = opts.get("quality")
        with contextlib.suppress(TypeError, ValueError):
            if quality is not None:
                kwargs["quality"] = min(max(int(quality), 1), 100)
    if str(opts.get("scale") or "").lower() in ("css", "device"):
        kwargs["scale"] = str(opts["scale"]).lower()
    return kwargs


def output_suffix(options: dict | None = None) -> str:
    return ".jpg" if screenshot_kwargs(options)["type"] == "jpeg" else ".png"


# ============================================================
# 输出目录：渲染产物不是日志，单独放，且必须有上限
# ============================================================


def cache_dir() -> Path:
    d = _settings().RENDER_CACHE_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def prune_cache(directory: Path, keep: int, protect: Path | None = None) -> int:
    """只保留最近 keep 个渲染产物，返回删除数。

    每次渲染都会落一张几百 KB 的图，不清理会无声涨到几个 G。按 mtime 保留最近的
    而不是按时间窗：图片发出去之后就没用了，但 QQ 端可能还在读，留几十张足够。

    ``protect`` 是刚渲染好的那张，永不删除，且**先从候选里摘掉再算配额**。
    不能只是「遍历到它时跳过」——Windows 的 mtime 精度不足，刚写的文件常与旧文件
    同秒，排序结果里它有一半概率落进待删片段；那时跳过它就等于这一轮什么都没删，
    缓存永远不收缩（单测 test_prune_cache_is_deterministic_on_mtime_ties 抓的就是它）。
    """
    if keep <= 0:
        return 0
    try:
        files = sorted(
            (p for p in directory.iterdir() if p.is_file()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return 0
    # protect 自己占一个保留位，剩下的名额给其它文件
    budget = keep
    if protect is not None and protect in files:
        budget = keep - 1
        files = [p for p in files if p != protect]
    removed = 0
    for stale in files[max(budget, 0):]:
        with contextlib.suppress(OSError):
            stale.unlink()
            removed += 1
    return removed


def _output_path(html: str, options: dict | None) -> Path:
    """产物路径。用内容哈希命名，同样的输入重复渲染会覆盖同一个文件而不是堆积。"""
    digest = hashlib.sha256(f"{html}{options}".encode()).hexdigest()[:16]
    return cache_dir() / f"render_{digest}{output_suffix(options)}"


# ============================================================
# 浏览器：单实例复用 + 浏览器缺失时后台安装
# ============================================================

_playwright: Any = None
_browser: Any = None
_browser_lock: asyncio.Lock | None = None
_render_sem: asyncio.Semaphore | None = None
_install_task: asyncio.Task | None = None
_install_blocked_until: float = 0.0
_warned_unavailable = False


def _locks() -> tuple[asyncio.Lock, asyncio.Semaphore]:
    """惰性建锁：模块 import 时可能还没有事件循环（bot.py 顶层就会 import 兼容层）。"""
    global _browser_lock, _render_sem
    if _browser_lock is None:
        _browser_lock = asyncio.Lock()
    if _render_sem is None:
        _render_sem = asyncio.Semaphore(max(_settings().RENDER_MAX_CONCURRENCY, 1))
    return _browser_lock, _render_sem


def reset_state() -> None:
    """清空模块级状态（测试与热重载用）。不关浏览器，调用方自己保证。"""
    global _playwright, _browser, _browser_lock, _render_sem
    global _install_task, _install_blocked_until, _warned_unavailable
    _playwright = _browser = None
    _browser_lock = _render_sem = None
    _install_task = None
    _install_blocked_until = 0.0
    _warned_unavailable = False


def _is_missing_browser(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _MISSING_BROWSER_MARKERS)


async def _install_browser() -> None:
    """后台跑 ``playwright install chromium-headless-shell``（约 270MB，几分钟）。

    装 headless shell 而不是完整 ``chromium``：后者会把带界面的浏览器和 shell 一起
    拉下来，实测 ``playwright install chromium`` 在本机占 ~700MB（chromium 428MB +
    headless shell 272MB），而我们只截图、永远不需要界面。只装 shell 省一半多。

    期间渲染继续降级；装完下一次渲染自动生效，不用重启。
    失败要记冷却——否则每条带链接的消息都会重新拉一次几百 MB。
    """
    global _install_blocked_until
    cmd = [sys.executable, "-m", "playwright", "install", _INSTALL_TARGET]
    logger.warning(
        "🖼 [Render] 首次渲染：正在后台下载浏览器内核（约 270MB，视网络几分钟）。"
        "期间卡片类插件继续走纯文本降级，装好后自动生效，无需重启。",
    )
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await proc.communicate()
        if proc.returncode == 0:
            logger.warning("🖼 [Render] 浏览器内核下载完成，渲染已可用")
            return
        tail = (out or b"").decode("utf-8", "replace").strip().splitlines()[-5:]
        logger.error(
            f"❌ [Render] 浏览器内核安装失败（退出码 {proc.returncode}）: {' / '.join(tail)}",
        )
    except Exception as e:
        logger.error(f"❌ [Render] 浏览器内核安装未能启动: {e}")
    _install_blocked_until = time.time() + _settings().RENDER_INSTALL_RETRY_SECONDS


def _maybe_start_install() -> None:
    """确保安装任务最多同时跑一个，且失败后有冷却。"""
    global _install_task
    if not _settings().RENDER_AUTO_INSTALL:
        return
    if _install_task is not None and not _install_task.done():
        return
    if time.time() < _install_blocked_until:
        return
    with contextlib.suppress(RuntimeError):
        _install_task = asyncio.get_running_loop().create_task(_install_browser())


async def _get_browser() -> Any:
    """取（或启动）共享的浏览器实例；不可用时返回 None。

    复用一个 browser、每次渲染只开一个 page：冷启一次浏览器要 1~2 秒，
    而卡片渲染是聊天主链路上的同步等待。
    """
    global _playwright, _browser, _warned_unavailable
    lock, _ = _locks()
    async with lock:
        if _browser is not None and _browser.is_connected():
            return _browser
        # 驱动已经起过就别再 import：驱动在手时 import 结果无关紧要，
        # 而且这样单测可以直接注入一个假 _playwright（本机不装 playwright 也能测编排）。
        if _playwright is None:
            try:
                from playwright.async_api import async_playwright
            except ImportError:
                if not _warned_unavailable:
                    _warned_unavailable = True
                    logger.warning(
                        "🖼 [Render] 未安装 playwright，HTML 渲染不可用"
                        "（卡片类插件会走纯文本降级）。装它：pip install playwright",
                    )
                return None
            try:
                _playwright = await async_playwright().start()
            except Exception as e:
                if not _warned_unavailable:
                    _warned_unavailable = True
                    logger.warning(f"🖼 [Render] playwright 驱动启动失败，渲染降级: {e}")
                return None

        last_error: BaseException | None = None
        for channel in _LAUNCH_CHANNELS:
            kwargs: dict[str, Any] = {
                # 两个 flag 只在容器/CI 里必要（无 sandbox、/dev/shm 太小），
                # 桌面环境下无副作用，统一带上省得分平台判断。
                "args": ["--no-sandbox", "--disable-dev-shm-usage"],
            }
            if channel:
                kwargs["channel"] = channel
            try:
                _browser = await _playwright.chromium.launch(**kwargs)
                logger.info(f"🖼 [Render] 浏览器已启动（channel={channel or 'chromium'}）")
                return _browser
            except Exception as e:
                last_error = e
                _browser = None

        if last_error is not None and _is_missing_browser(last_error):
            _maybe_start_install()
        elif last_error is not None and not _warned_unavailable:
            _warned_unavailable = True
            logger.warning(f"🖼 [Render] 浏览器启动失败，渲染降级: {last_error}")
        return None


async def shutdown() -> None:
    """关掉浏览器与 playwright 驱动。进程退出前必须调，否则会留下孤儿进程。"""
    global _playwright, _browser
    with contextlib.suppress(Exception):
        if _browser is not None:
            await _browser.close()
    with contextlib.suppress(Exception):
        if _playwright is not None:
            await _playwright.stop()
    _browser = _playwright = None


# ============================================================
# 对外入口
# ============================================================


async def render_html(html: str, options: dict | None = None) -> Path | None:
    """把一段完整 HTML 截图成本地文件；不可用时返回 None（调用方降级）。"""
    s = _settings()
    if not s.RENDER_ENABLED or not (html or "").strip():
        return None
    browser = await _get_browser()
    if browser is None:
        return None

    _, sem = _locks()
    out = _output_path(html, options)
    try:
        async with sem:
            context = await browser.new_context(**context_kwargs(html, options))
            try:
                page = await context.new_page()
                # set_content + wait_until="load" 才会等图片/字体加载完；
                # 少了它头像和封面会渲成空白框（模板里的图都是远程 URL）。
                await page.set_content(html, wait_until="load")
                await page.wait_for_timeout(int(s.RENDER_SETTLE_MS))
                await page.screenshot(path=str(out), **screenshot_kwargs(options))
            finally:
                await context.close()
    except Exception as e:
        logger.warning(f"🖼 [Render] 渲染失败: {e}")
        return None

    if not out.is_file() or out.stat().st_size == 0:
        logger.warning("🖼 [Render] 渲染产物为空")
        return None
    prune_cache(out.parent, s.RENDER_CACHE_KEEP, protect=out)
    return out


def render_template_sync(tmpl: str, data: dict | None) -> str:
    """Jinja2 渲染模板字符串。纯函数，与浏览器无关，单独暴露便于单测。

    ``autoescape=False``：模板里普遍直接插 HTML 片段（``<br>`` 拼的多行文本、
    base64 图片），开转义会把它们变成字面量。这些数据来自插件自己组装的结构，
    不是用户直接输入——与上游行为一致。
    """
    from jinja2 import Template

    return Template(tmpl or "").render(**(data or {}))


async def render_template(
    tmpl: str,
    data: dict | None = None,
    options: dict | None = None,
) -> Path | None:
    """Jinja2 模板 + 数据 → 图片。``Star.html_render`` 的实际实现。"""
    try:
        html = render_template_sync(tmpl, data)
    except Exception as e:
        # 模板语法/变量错误是插件的问题，但不该让它以异常形式炸在主链路上
        logger.warning(f"🖼 [Render] 模板渲染失败: {e}")
        return None
    return await render_html(html, options)


# 纯文本转图的最小模板。刻意做得朴素：它的用途是「消息太长了发张图」，
# 不是排版展示；花哨的样式反而会让不同插件的输出风格不一致。
_TEXT_TEMPLATE = """<!DOCTYPE html><html><head><meta charset="UTF-8">
<meta name="viewport" content="width={width}">
<style>
body{{margin:0;background:#fff;}}
pre{{margin:0;padding:24px;font-size:16px;line-height:1.7;color:#1f2328;
white-space:pre-wrap;word-break:break-word;
font-family:"Microsoft YaHei","PingFang SC","Noto Sans CJK SC",sans-serif;}}
</style></head><body><pre>{body}</pre></body></html>"""


async def render_text(text: str, options: dict | None = None) -> Path | None:
    """纯文本 → 图片。``Star.text_to_image`` / ``t2i`` 的实现。"""
    import html as _html

    width = _settings().RENDER_TEXT_WIDTH
    page = _TEXT_TEMPLATE.format(width=int(width), body=_html.escape(text or ""))
    return await render_html(page, options)


__all__ = [
    "DEFAULT_VIEWPORT_WIDTH",
    "cache_dir",
    "context_kwargs",
    "output_suffix",
    "parse_viewport_width",
    "prune_cache",
    "render_html",
    "render_template",
    "render_template_sync",
    "render_text",
    "reset_state",
    "screenshot_kwargs",
    "shutdown",
]






