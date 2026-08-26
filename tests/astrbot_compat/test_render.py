# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""HTML → 图片渲染的单测。

浏览器全程打桩（`_FakeBrowser`），不启真 Chromium——CI 里没有内核，而这里要测的是
**编排与降级**，不是 Chromium 的截图质量。真实出图靠人工验收（见
design_docs/test_checklist.md 的渲染一节）。

重点钉四件事：
1. **失败一律返回 None，绝不抛异常**——插件的 except 会吞掉异常再重试，
   2026-08-25 实测 bilibili 插件为此白等 3×2s；
2. **options → playwright 参数的映射**——quality 只有 jpeg 能带，png 传了会被拒；
3. **产物目录有上限**——每张几百 KB，不清理会无声涨到几个 G；
4. **浏览器缺失时的安装只跑一次且有冷却**——否则每条带链接的消息都拉一次几百 MB。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from astrbot_compat import render


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _clean_render_state(tmp_path, monkeypatch):
    """模块级缓存了浏览器与锁，用例之间必须清；产物目录也要隔离到 tmp。"""
    from config import settings

    monkeypatch.setattr(settings, "RENDER_CACHE_DIR", tmp_path / "render_cache")
    render.reset_state()
    yield
    render.reset_state()


# ============================================================
# 纯函数
# ============================================================


def test_parse_viewport_width_reads_meta():
    html = '<meta name="viewport" content="width=700">'
    assert render.parse_viewport_width(html) == 700


def test_parse_viewport_width_accepts_extra_attrs_and_quotes():
    html = "<meta charset='utf-8'><meta name='viewport' content='width=1080, scale=1'>"
    assert render.parse_viewport_width(html) == 1080


def test_parse_viewport_width_falls_back_without_meta():
    assert render.parse_viewport_width("<html></html>") == render.DEFAULT_VIEWPORT_WIDTH


def test_parse_viewport_width_rejects_absurd_values():
    """模板作者写 width=device-width 或离谱数值时不能把视口搞坏。"""
    assert render.parse_viewport_width('<meta name="viewport" content="width=device-width">') == (
        render.DEFAULT_VIEWPORT_WIDTH
    )
    assert render.parse_viewport_width('<meta name="viewport" content="width=99999">') == (
        render.DEFAULT_VIEWPORT_WIDTH
    )


def test_screenshot_kwargs_jpeg_keeps_quality():
    out = render.screenshot_kwargs(
        {"full_page": True, "type": "jpeg", "quality": 95, "scale": "device"},
    )
    assert out == {"full_page": True, "type": "jpeg", "quality": 95, "scale": "device"}


def test_screenshot_kwargs_png_drops_quality():
    """回归：png 带 quality 会被 playwright 直接报错，不是忽略。"""
    out = render.screenshot_kwargs({"type": "png", "quality": 95})
    assert "quality" not in out
    assert out["type"] == "png"


def test_screenshot_kwargs_clamps_quality_and_defaults():
    assert render.screenshot_kwargs({"type": "jpeg", "quality": 500})["quality"] == 100
    assert render.screenshot_kwargs({"type": "jpeg", "quality": 0})["quality"] == 1
    assert render.screenshot_kwargs(None) == {"full_page": True, "type": "png"}


def test_screenshot_kwargs_rejects_unknown_type_and_scale():
    out = render.screenshot_kwargs({"type": "webp", "scale": "bogus"})
    assert out["type"] == "png"
    assert "scale" not in out


def test_context_kwargs_maps_scale_level():
    html = '<meta name="viewport" content="width=700">'
    assert render.context_kwargs(html, {"device_scale_factor_level": "ultra"})[
        "device_scale_factor"
    ] == 3.0
    assert render.context_kwargs(html, {"device_scale_factor_level": "low"})[
        "device_scale_factor"
    ] == 1.0
    # 未知枚举回落到 medium，而不是崩
    assert render.context_kwargs(html, {"device_scale_factor_level": "??"})[
        "device_scale_factor"
    ] == 1.5


def test_context_kwargs_accepts_raw_factor_and_clamps():
    html = "<html></html>"
    assert render.context_kwargs(html, {"device_scale_factor": 9})["device_scale_factor"] == 4.0
    assert render.context_kwargs(html, {"device_scale_factor": 0.1})["device_scale_factor"] == 1.0


def test_output_suffix_follows_type():
    assert render.output_suffix({"type": "jpeg"}) == ".jpg"
    assert render.output_suffix({"type": "png"}) == ".png"
    assert render.output_suffix(None) == ".png"


def test_render_template_sync_does_not_escape_html():
    """模板里普遍直接插 HTML 片段（<br> 拼的多行文本、base64 图），开转义会变字面量。"""
    out = render.render_template_sync("<p>{{ body }}</p>", {"body": "a<br>b"})
    assert out == "<p>a<br>b</p>"


# ============================================================
# 产物目录：必须有上限
# ============================================================


def test_prune_cache_keeps_newest(tmp_path):
    import os
    import time

    for i in range(6):
        f = tmp_path / f"r{i}.png"
        f.write_bytes(b"x")
        os.utime(f, (time.time() + i, time.time() + i))
    assert render.prune_cache(tmp_path, keep=2) == 4
    assert sorted(p.name for p in tmp_path.iterdir()) == ["r4.png", "r5.png"]


def test_prune_cache_keep_zero_is_noop(tmp_path):
    (tmp_path / "a.png").write_bytes(b"x")
    assert render.prune_cache(tmp_path, keep=0) == 0
    assert list(tmp_path.iterdir())


def test_prune_cache_survives_missing_dir(tmp_path):
    assert render.prune_cache(tmp_path / "nope", keep=3) == 0


# ============================================================
# 编排：浏览器打桩
# ============================================================


class _FakePage:
    def __init__(self, recorder: dict) -> None:
        self._rec = recorder

    async def set_content(self, html: str, **kw: Any) -> None:
        self._rec["html"] = html
        self._rec["set_content_kwargs"] = kw

    async def wait_for_timeout(self, ms: int) -> None:
        self._rec["settle_ms"] = ms

    async def screenshot(self, path: str, **kw: Any) -> None:
        self._rec["shot_kwargs"] = kw
        self._rec["path"] = path
        # 真 playwright 会落盘，桩也要落，否则「产物为空」分支会误判
        Path(path).write_bytes(b"\x89PNG fake image payload")


class _FakeContext:
    def __init__(self, recorder: dict) -> None:
        self._rec = recorder
        self.closed = False

    async def new_page(self) -> _FakePage:
        return _FakePage(self._rec)

    async def close(self) -> None:
        self.closed = True
        self._rec["context_closed"] = True


class _FakeBrowser:
    def __init__(self, recorder: dict) -> None:
        self._rec = recorder

    def is_connected(self) -> bool:
        return True

    async def new_context(self, **kw: Any) -> _FakeContext:
        self._rec["context_kwargs"] = kw
        return _FakeContext(self._rec)

    async def close(self) -> None:
        self._rec["browser_closed"] = True


@pytest.fixture
def fake_browser(monkeypatch):
    rec: dict = {}

    async def _get(*_a, **_k):
        return _FakeBrowser(rec)

    monkeypatch.setattr(render, "_get_browser", _get)
    return rec


def test_render_html_writes_file_and_passes_options(fake_browser):
    out = _run(
        render.render_html(
            '<meta name="viewport" content="width=700"><b>hi</b>',
            {"full_page": True, "type": "jpeg", "quality": 95,
             "device_scale_factor_level": "ultra"},
        ),
    )
    assert out is not None and out.is_file()
    assert out.suffix == ".jpg"
    assert fake_browser["shot_kwargs"]["type"] == "jpeg"
    assert fake_browser["shot_kwargs"]["quality"] == 95
    assert fake_browser["context_kwargs"]["viewport"]["width"] == 700
    assert fake_browser["context_kwargs"]["device_scale_factor"] == 3.0
    # 上下文必须关掉，否则每渲染一次泄一个 Chromium 上下文
    assert fake_browser["context_closed"] is True


def test_render_html_waits_for_load(fake_browser):
    """回归：不等 load 的话头像/封面（远程 URL）会渲成空白框。"""
    _run(render.render_html("<b>hi</b>"))
    assert fake_browser["set_content_kwargs"]["wait_until"] == "load"
    assert fake_browser["settle_ms"] > 0


def test_render_html_skipped_when_disabled(monkeypatch, fake_browser):
    from config import settings

    monkeypatch.setattr(settings, "RENDER_ENABLED", False)
    assert _run(render.render_html("<b>hi</b>")) is None


def test_render_html_rejects_blank_html(fake_browser):
    assert _run(render.render_html("   ")) is None


def test_render_html_returns_none_when_browser_unavailable(monkeypatch):
    async def _none(*_a, **_k):
        return None

    monkeypatch.setattr(render, "_get_browser", _none)
    assert _run(render.render_html("<b>hi</b>")) is None


def test_render_html_swallows_screenshot_errors(monkeypatch, fake_browser):
    """截图炸了也只能返回 None——异常会被插件 except 吞掉再重试。"""

    async def _boom(self, path: str, **kw: Any) -> None:
        raise RuntimeError("Target closed")

    monkeypatch.setattr(_FakePage, "screenshot", _boom)
    assert _run(render.render_html("<b>hi</b>")) is None


def test_render_html_prunes_cache(monkeypatch, fake_browser):
    from config import settings

    monkeypatch.setattr(settings, "RENDER_CACHE_KEEP", 1)
    first = _run(render.render_html("<b>one</b>"))
    second = _run(render.render_html("<b>two</b>"))
    assert second is not None
    assert second.is_file()
    assert not first.is_file()   # 被裁掉了


def test_same_input_reuses_one_file(fake_browser):
    """内容哈希命名：重复渲染覆盖同一个文件而不是堆积。"""
    a = _run(render.render_html("<b>same</b>"))
    b = _run(render.render_html("<b>same</b>"))
    assert a == b


def test_render_template_renders_then_shoots(fake_browser):
    out = _run(render.render_template("<p>{{ name }}</p>", {"name": "凯特"}))
    assert out is not None
    assert fake_browser["html"] == "<p>凯特</p>"


def test_render_template_returns_none_on_template_error(fake_browser):
    """模板语法错是插件的问题，但不该以异常形式炸在聊天主链路上。"""
    assert _run(render.render_template("{% for %}", {})) is None


def test_render_text_escapes_and_wraps(fake_browser):
    out = _run(render.render_text("<script>x</script>"))
    assert out is not None
    assert "&lt;script&gt;" in fake_browser["html"]
    assert "<pre>" in fake_browser["html"]


def test_prune_cache_is_deterministic_on_mtime_ties(tmp_path):
    """回归：Windows 的 mtime 精度不足，刚写的文件常与旧文件同秒。

    早先的实现是「遍历到 protect 时跳过」，于是 protect 落进待删片段的那一半概率里
    这一轮什么都删不掉，缓存永远不收缩（实测 6/6 次 removed=0）。
    正确做法是先把 protect 摘出候选、再算配额。
    """
    import os

    keep_me = tmp_path / "zzz_new.png"
    other = tmp_path / "aaa_old.png"
    for f in (other, keep_me):
        f.write_bytes(b"x")
        os.utime(f, (1000.0, 1000.0))   # 故意同一 mtime
    assert render.prune_cache(tmp_path, keep=1, protect=keep_me) == 1
    assert keep_me.is_file()
    assert not other.is_file()


def test_prune_cache_protect_counts_toward_budget(tmp_path):
    """protect 自己占一个保留位：keep=2 时只再留 1 个旧文件。"""
    import os

    keep_me = tmp_path / "new.png"
    olds = [tmp_path / f"old{i}.png" for i in range(3)]
    for i, f in enumerate([*olds, keep_me]):
        f.write_bytes(b"x")
        os.utime(f, (1000.0 + i, 1000.0 + i))
    assert render.prune_cache(tmp_path, keep=2, protect=keep_me) == 2
    assert keep_me.is_file()
    assert sum(1 for f in olds if f.is_file()) == 1


# ============================================================
# 浏览器获取：渠道回退与按需安装
# ============================================================


class _FakeChromium:
    """记录每次 launch 的 channel；按 fail_channels 决定哪些渠道要失败。"""

    def __init__(self, fail_channels: set, error: str = "boom") -> None:
        self.fail_channels = fail_channels
        self.error = error
        self.tried: list = []

    async def launch(self, **kw: Any):
        channel = kw.get("channel")
        self.tried.append(channel)
        if channel in self.fail_channels:
            raise RuntimeError(self.error)
        return _FakeBrowser({})


class _FakePlaywright:
    def __init__(self, chromium: _FakeChromium) -> None:
        self.chromium = chromium

    async def stop(self) -> None:
        pass


def _patch_playwright(monkeypatch, chromium: _FakeChromium) -> None:
    monkeypatch.setattr(render, "_playwright", _FakePlaywright(chromium))


def test_get_browser_prefers_headless_shell(monkeypatch):
    """只截图就够用 headless shell，它比完整 chromium 小一半多。"""
    chromium = _FakeChromium(fail_channels=set())
    _patch_playwright(monkeypatch, chromium)
    assert _run(render._get_browser()) is not None
    assert chromium.tried == ["chromium-headless-shell"]


def test_get_browser_falls_back_to_full_chromium(monkeypatch):
    """老 playwright 没这个 channel，或用户装的是完整版——都要能跑起来。"""
    chromium = _FakeChromium(fail_channels={"chromium-headless-shell"})
    _patch_playwright(monkeypatch, chromium)
    assert _run(render._get_browser()) is not None
    assert chromium.tried == ["chromium-headless-shell", None]


def test_get_browser_triggers_install_when_binary_missing(monkeypatch):
    """内核没下载时启动后台安装，本次仍降级。"""
    chromium = _FakeChromium(
        fail_channels={"chromium-headless-shell", None},
        error="Executable doesn't exist at ...\nplaywright install",
    )
    _patch_playwright(monkeypatch, chromium)
    started: list[int] = []
    monkeypatch.setattr(render, "_maybe_start_install", lambda: started.append(1))
    assert _run(render._get_browser()) is None
    assert started == [1]


def test_get_browser_does_not_install_on_other_errors(monkeypatch):
    """启动失败不等于没装——别为一次崩溃去拉几百 MB。"""
    chromium = _FakeChromium(fail_channels={"chromium-headless-shell", None}, error="权限不足")
    _patch_playwright(monkeypatch, chromium)
    started: list[int] = []
    monkeypatch.setattr(render, "_maybe_start_install", lambda: started.append(1))
    assert _run(render._get_browser()) is None
    assert started == []


def test_install_respects_disabled_switch(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "RENDER_AUTO_INSTALL", False)
    render._maybe_start_install()
    assert render._install_task is None


def test_install_respects_cooldown(monkeypatch):
    """失败后要冷却，否则每条带链接的消息都会重新拉一次几百 MB。"""
    import time as _t

    from config import settings

    monkeypatch.setattr(settings, "RENDER_AUTO_INSTALL", True)
    monkeypatch.setattr(render, "_install_blocked_until", _t.time() + 999)
    render._maybe_start_install()
    assert render._install_task is None
