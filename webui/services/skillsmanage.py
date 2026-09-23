# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""Skills 管理（方案 §6.5.3）：目录/正文/上传/删除；内置层只读。

「用户可写」= USER/WORKSPACE 层（``STELLA_HOME/data/skills``）；写入后
必须 ``catalog.refresh()``（原子重扫）。manifest 不含正文——正文在
SKILL.md，由 loader.load_skill 按需读取。
"""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

import config.settings as settings
from webui.responses import ApiError


def _catalog():
    """新开 catalog（M3 管理面不依赖运行时是否装配过 Skills）。"""
    from skills.catalog import SkillCatalog

    catalog = SkillCatalog.from_settings()
    catalog.refresh()
    return catalog


def user_skills_dir() -> Path:
    return Path(settings.SKILLS_USER_DIR)


def list_skills() -> dict:
    catalog = _catalog()
    items = catalog.snapshot.candidates_metadata()
    sandbox = None
    try:
        from skills import runtime as skills_runtime
        from skills.sandbox import executor_status

        rt = skills_runtime.current()
        sandbox = executor_status(getattr(rt.orchestrator, "_executor", None) if rt else None)
    except Exception:
        sandbox = None
    return {"skills": items, "status": catalog.status(), "sandbox": sandbox}


def _find_manifest(name: str):
    catalog = _catalog()
    for manifest in catalog.snapshot.manifests():
        if manifest.name == name:
            return manifest
    raise ApiError("技能不存在", status_code=404)


def _is_user_layer(manifest) -> bool:
    source = getattr(manifest, "source", None)
    value = getattr(source, "value", str(source))
    return str(value).lower() in ("user", "workspace")


def get_skill(name: str) -> dict:
    from skills.loader import load_skill

    manifest = _find_manifest(name)
    loaded = load_skill(manifest, body_max_chars=200_000, asset_max_bytes=1_000_000)
    return {
        "name": manifest.name,
        "description": getattr(manifest, "description", ""),
        "source": str(getattr(manifest, "source", "")),
        "editable": _is_user_layer(manifest),
        "body": loaded.body,
        "body_truncated": loaded.body_truncated,
        "root": str(getattr(manifest, "root", "")),
    }


def save_skill_body(name: str, body: str) -> dict:
    manifest = _find_manifest(name)
    if not _is_user_layer(manifest):
        raise ApiError(
            "内置/插件层技能只读；请把目录复制到 data/skills/ 后修改", status_code=409
        )
    manifest_dir = Path(manifest.root)
    (manifest_dir / "SKILL.md").write_text(body, encoding="utf-8")
    return {"name": name, "saved": True}


def upload_zip(data: bytes) -> dict:
    if len(data) > 50 * 1024 * 1024:
        raise ApiError("技能包超过 50MB 上限", status_code=413)
    user_dir = user_skills_dir()
    user_dir.mkdir(parents=True, exist_ok=True)
    workdir = Path(user_dir) / ".upload-tmp"
    shutil.rmtree(workdir, ignore_errors=True)
    workdir.mkdir(parents=True)
    try:
        with zipfile.ZipFile(workdir / "s.zip") as zf:  # type: ignore[arg-type]
            for member in zf.namelist():
                target = (workdir / "x" / member).resolve()
                if not str(target).startswith(str((workdir / "x").resolve())):
                    raise ApiError("压缩包含越界路径，已拒绝", status_code=400)
            zf.extractall(workdir / "x")
        root = workdir / "x"
        if not (root / "SKILL.md").exists():
            subdirs = [d for d in root.iterdir() if d.is_dir() and (d / "SKILL.md").exists()]
            if len(subdirs) == 1:
                root = subdirs[0]
            else:
                raise ApiError("压缩包里找不到 SKILL.md")
        # 目录名必须等于 front matter name（discovery 的硬规则）
        name = _front_matter_name(root / "SKILL.md")
        target = user_dir / name
        if target.exists():
            raise ApiError(f"技能 {name} 已存在", status_code=409)
        shutil.move(str(root), str(target))
        return {"name": name, "installed": True}
    except zipfile.BadZipFile:
        raise ApiError("不是合法的 zip 包") from None
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _front_matter_name(skill_md: Path) -> str:
    for line in skill_md.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith("name:"):
            value = line.split(":", 1)[1].strip().strip("\"'")
            if value:
                return value
    raise ApiError("SKILL.md front matter 缺少 name 字段")


def delete_skill(name: str) -> dict:
    manifest = _find_manifest(name)
    if not _is_user_layer(manifest):
        raise ApiError("内置/插件层技能不可删除", status_code=409)
    shutil.rmtree(Path(manifest.root))
    return {"name": name, "deleted": True}
