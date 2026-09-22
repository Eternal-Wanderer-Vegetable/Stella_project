# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""插件管理写侧（方案 §6.5.1，M3）：启停 / 重载 / 配置 / 安装 / 卸载 / 市场。

- 启停：``data/plugins/.disabled.json``（禁用目录名集合），loader 在
  discover 阶段过滤（唯一的 astrbot_compat 侵入点）。禁用即重启后不加载；
  已加载的插件要卸载还需重载（受 ASTRBOT_PLUGIN_HOT_RELOAD_ENABLED 闸）。
- 安装：下载 zip → 解压到临时区 → ``plugin_check.collect/run_all`` 规范
  校验（Stella 比市场更严的闸）→ 通过才落到 data/plugins/。
- 市场：多源聚合（``config/plugin_sources.json``），源格式兼容 AstrBot
  市场 JSON；按 name+repo 去重，内存缓存 10 分钟。
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import time
import zipfile
from pathlib import Path

import httpx

import config.settings as settings
from webui.responses import ApiError

_MARKET_CACHE: dict = {"ts": 0.0, "payload": None}
_MARKET_TTL = 600.0


# ---------- 基础查询 ----------

def plugins_dir() -> Path:
    from astrbot_compat.loader import _plugins_dir

    return _plugins_dir()


def disabled_path() -> Path:
    return plugins_dir() / ".disabled.json"


def read_disabled() -> set[str]:
    from astrbot_compat.loader import disabled_plugin_names

    return disabled_plugin_names()


def write_disabled(names: set[str]) -> None:
    path = disabled_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(sorted(names), ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def _registry_meta(plugin_id: str | None = None, root_dir: str | None = None):
    """按 plugin_id 或目录名找已注册插件元数据（找不到返回 None）。"""
    from astrbot_compat import registry as compat_registry

    for md in compat_registry.star_registry:
        if plugin_id and md.plugin_id == plugin_id:
            return md
        if root_dir and md.root_dir_name == root_dir:
            return md
    return None


def _resolve_dir(plugin_id: str) -> Path:
    """plugin_id / 目录名 → 插件目录。两段式 id（author/name）先查注册表。"""
    md = _registry_meta(plugin_id=plugin_id)
    if md is not None and md.root_dir_name:
        return plugins_dir() / md.root_dir_name
    if "/" in plugin_id:
        plugin_id = plugin_id.split("/")[-1]
    path = plugins_dir() / plugin_id
    if path.is_dir():
        return path
    raise ApiError("插件不存在", status_code=404)


# ---------- 启停 / 重载 / 卸载 ----------

def set_enabled(plugin_id: str, *, enabled: bool) -> dict:
    disabled = read_disabled()
    target_dir = _resolve_dir(plugin_id)
    if enabled:
        disabled.discard(target_dir.name)
    else:
        disabled.add(target_dir.name)
    write_disabled(disabled)
    return {
        "plugin_id": plugin_id,
        "enabled": enabled,
        # 禁用/启用只改标记：正在运行的插件要「卸下」或「装回」需重载或重启
        "needs_reload_or_restart": True,
    }


async def reload(plugin_id: str) -> dict:
    import astrbot_compat.loader as loader

    md = _registry_meta(plugin_id=plugin_id) or _registry_meta(root_dir=plugin_id)
    dir_name = md.root_dir_name if md else plugin_id
    result = await loader.reload_plugin(dir_name)
    if result is None:
        reason = loader.get_failed_plugins().get(dir_name, "")
        hot_reload_enabled = bool(
            getattr(settings, "ASTRBOT_PLUGIN_HOT_RELOAD_ENABLED", False)
        )
        if not hot_reload_enabled:
            raise ApiError(
                "重载未生效：热重载未开启（ASTRBOT_PLUGIN_HOT_RELOAD_ENABLED=false）。"
                "开启后可免重启热重载，否则请重启 Bot。",
                status_code=409,
            )
        raise ApiError(f"重载未生效：{reason or '未知原因'}", status_code=409)
    return {"plugin_id": plugin_id, "reloaded": True}


def uninstall(plugin_id: str, *, remove_config: bool = False, remove_data: bool = False) -> dict:
    md = _registry_meta(plugin_id=plugin_id)
    dir_name = md.root_dir_name if md else (plugin_id.split("/")[-1] if "/" in plugin_id else plugin_id)
    target = plugins_dir() / dir_name
    if not target.is_dir():
        raise ApiError("插件目录不存在", status_code=404)
    if md is not None and md.reserved:
        raise ApiError("内置插件不可卸载", status_code=409)
    # 禁用名单里也摘掉（目录都没了，留着是脏数据）
    disabled = read_disabled()
    disabled.discard(dir_name)
    write_disabled(disabled)
    shutil.rmtree(target)
    plugin_cfg = Path(settings.ASTRBOT_PLUGIN_CONFIG_DIR) / f"{dir_name}_config.json"
    if remove_config and plugin_cfg.exists():
        plugin_cfg.unlink()
    data_dir = Path(settings.ASTRBOT_PLUGINS_DIR).parent / "plugin_data" / dir_name
    if remove_data and data_dir.exists():
        shutil.rmtree(data_dir)
    return {"plugin_id": plugin_id, "removed": dir_name}


# ---------- 配置 ----------

def plugin_config(plugin_id: str) -> dict:
    from astrbot_compat.config import AstrBotConfig, load_conf_schema

    md = _registry_meta(plugin_id=plugin_id)
    dir_name = md.root_dir_name if md else plugin_id.split("/")[-1]
    plugin_dir = plugins_dir() / dir_name
    schema = load_conf_schema(plugin_dir)
    if md is not None and getattr(md, "config", None) is not None:
        current = dict(md.config)
    else:
        current = dict(AstrBotConfig(dir_name))
    return {"plugin_id": plugin_id, "schema": schema, "config": current}


def save_plugin_config(plugin_id: str, config: dict) -> dict:
    from astrbot_compat.config import AstrBotConfig

    md = _registry_meta(plugin_id=plugin_id)
    dir_name = md.root_dir_name if md else plugin_id.split("/")[-1]
    if not (plugins_dir() / dir_name).is_dir():
        raise ApiError("插件不存在", status_code=404)
    if md is not None and getattr(md, "config", None) is not None:
        live = md.config
        live.clear()
        live.update(config)
        live.save_config()
        return {"plugin_id": plugin_id, "saved": "live"}
    AstrBotConfig(dir_name).save_config(replace_config=config)
    return {"plugin_id": plugin_id, "saved": "file"}


def readme(plugin_id: str) -> str:
    md = _registry_meta(plugin_id=plugin_id)
    dir_name = md.root_dir_name if md else plugin_id.split("/")[-1]
    plugin_dir = plugins_dir() / dir_name
    for candidate in ("README.md", "README.txt", "readme.md"):
        path = plugin_dir / candidate
        if path.exists():
            return path.read_text(encoding="utf-8", errors="replace")
    return ""


# ---------- 安装 ----------

_SAFE_NAME = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")


def install_from_zip_bytes(data: bytes, *, suggested_name: str | None = None) -> dict:
    """zip → 临时区解压 → 规范校验 → 落位。任何一步失败都不污染插件目录。"""
    if len(data) > 100 * 1024 * 1024:
        raise ApiError("插件包超过 100MB 上限", status_code=413)
    workdir = Path(tempfile.mkdtemp(prefix="stella-plugin-"))
    try:
        zip_path = workdir / "plugin.zip"
        zip_path.write_bytes(data)
        with zipfile.ZipFile(zip_path) as zf:
            for member in zf.namelist():
                target = (workdir / "extracted" / member).resolve()
                if not str(target).startswith(str((workdir / "extracted").resolve())):
                    raise ApiError("压缩包含越界路径，已拒绝", status_code=400)
            zf.extractall(workdir / "extracted")
        return _finalize_install(workdir / "extracted", suggested_name)
    except zipfile.BadZipFile:
        raise ApiError("不是合法的 zip 包") from None
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def install_from_url(url: str) -> dict:
    if not url.startswith(("http://", "https://")):
        raise ApiError("URL 必须是 http(s)")
    with httpx.Client(timeout=60, trust_env=False, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return install_from_zip_bytes(resp.content)


def install_from_github(repo: str) -> dict:
    repo = repo.strip().removeprefix("https://github.com/").strip("/")
    if not re.fullmatch(r"[\w.\-]+/[\w.\-]+", repo):
        raise ApiError("GitHub 仓库形如 owner/name")
    return install_from_url(f"https://github.com/{repo}/archive/refs/heads/master.zip")


def _finalize_install(extracted: Path, suggested_name: str | None) -> dict:
    """定位插件根目录（解压根或单层子目录）→ 规范校验 → 落位。"""
    root = extracted
    if not (root / "main.py").exists():
        subdirs = [d for d in root.iterdir() if d.is_dir()]
        if len(subdirs) == 1 and (subdirs[0] / "main.py").exists():
            root = subdirs[0]
    if not (root / "main.py").exists():
        raise ApiError("压缩包里找不到 main.py（插件必须解压成目录，含 main.py）")
    from deploy import plugin_check

    facts = plugin_check.collect(root)
    results = plugin_check.run_all(facts)
    report = plugin_check.to_json(facts, results)
    blocking = [
        r for r in (results if isinstance(results, list) else results.get("results", []))
        if isinstance(r, dict) and r.get("level") in ("error", "blocking")
    ]
    if blocking:
        return {"ok": False, "stage": "plugin-check", "report": report, "blocking": blocking}
    name = suggested_name or root.name
    if not _SAFE_NAME.fullmatch(name):
        name = re.sub(r"[^A-Za-z0-9_\-]", "_", name)[:64]
    target = plugins_dir() / name
    if target.exists():
        raise ApiError(f"插件目录 {name} 已存在（先卸载旧版）", status_code=409)
    shutil.move(str(root), str(target))
    return {"ok": True, "name": name, "report": report}


# ---------- 市场多源 ----------

def sources_path() -> Path:
    return Path(settings.STELLA_HOME) / "config" / "plugin_sources.json"


def _default_sources() -> dict:
    return {
        "sources": [
            {
                "id": "astrbot-official",
                "name": "AstrBot 官方市场",
                "url": "https://raw.githubusercontent.com/AstrBotDevs/AstrBot/master/master/packages.json",
                "enabled": True,
            }
        ]
    }


def list_sources() -> list[dict]:
    path = sources_path()
    if not path.exists():
        data = _default_sources()
    else:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = _default_sources()
    return data.get("sources", [])


def save_sources(sources: list[dict]) -> dict:
    for src in sources:
        if not re.fullmatch(r"[\w\-]{1,64}", str(src.get("id", ""))):
            raise ApiError(f"非法源 id: {src.get('id')}")
        if not str(src.get("url", "")).startswith(("http://", "https://")):
            raise ApiError(f"源 {src.get('id')} 的 URL 非法")
    path = sources_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"sources": sources}, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)
    _MARKET_CACHE["ts"] = 0.0
    return {"sources": sources}


def fetch_market(source_id: str | None = None) -> dict:
    """聚合启用源的插件清单，按 (name, repo) 去重。失败源降级为空 + error 标记。"""
    now = time.monotonic()
    if _MARKET_CACHE["payload"] is not None and now - _MARKET_CACHE["ts"] < _MARKET_TTL:
        payload = _MARKET_CACHE["payload"]
    else:
        merged: dict[tuple, dict] = {}
        errors: dict[str, str] = {}
        for src in list_sources():
            if not src.get("enabled"):
                continue
            try:
                with httpx.Client(timeout=15, trust_env=False, follow_redirects=True) as client:
                    resp = client.get(src["url"])
                    resp.raise_for_status()
                    raw = resp.json()
                items = raw if isinstance(raw, list) else raw.get("plugins", [])
                for item in items:
                    key = (str(item.get("name", "")), str(item.get("repo", "")))
                    existing = merged.get(key)
                    if existing is None or str(item.get("updated", "")) >= str(
                        existing.get("updated", "")
                    ):
                        merged[key] = {
                            "name": item.get("name", ""),
                            "desc": item.get("desc", ""),
                            "author": item.get("author", ""),
                            "version": item.get("version", ""),
                            "repo": item.get("repo", ""),
                            "updated": item.get("updated", ""),
                            "source_id": src["id"],
                        }
            except Exception as e:
                errors[src["id"]] = str(e)
        payload = {"plugins": list(merged.values()), "source_errors": errors}
        _MARKET_CACHE["ts"] = now
        _MARKET_CACHE["payload"] = payload
    plugins = payload["plugins"]
    if source_id:
        plugins = [p for p in plugins if p["source_id"] == source_id]
    return {"plugins": plugins, "source_errors": payload["source_errors"]}
