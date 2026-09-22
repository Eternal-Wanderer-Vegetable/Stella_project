# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Skill 发现：扫描目录、受限 front matter 解析、路径/大小/符号链接校验。

边界纪律（plan §6.1）：

* 只解析 ``SKILL.md`` 的**有限 front matter**（必需 ``name``/``description``，
  白名单外键一律丢弃）和目录索引；scripts/ 与 references/ 留给命中后的
  loader，启动与匹配阶段不碰。
* front matter 用 ``yaml.safe_load``（PyYAML 已在 requirements.txt 锁定），
  且只接受标量值；PyYAML 不可用时退到逐行标量解析器。两条路都**不会**
  把 YAML 对象执行或展开进配置。
* 无效技能被**隔离记录**（返回隔离原因）而不是抛异常——一个写坏的技能
  不能拖垮整层扫描，更不能拖垮启动。
* 符号链接一律拒绝：技能目录与 ``SKILL.md`` 都必须是真实文件系统对象。
  越界 symlink 是把宿主任意文件伪装成技能正文的经典通道。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from skills.model import SkillManifest, SkillSource, skill_name_is_valid

# front matter 白名单：只接受这几个标量键。权限类字段（如 allowed-tools）
# 刻意不在列——信任等级由来源层决定，Skill 不得自我声明权限（plan §6.4）。
FRONT_MATTER_KEYS = frozenset({"name", "description", "license", "compatibility"})

# front matter 解析的行数上限：正经说明书的开头不会超过这个量。
_FRONT_MATTER_MAX_LINES = 64
# description 的字符上限：候选要进 Router/Context，超长描述本身就是预算污染。
_DESCRIPTION_MAX_CHARS = 1024


class Quarantine:
    """无效技能的隔离原因常量。进诊断日志与 catalog 状态，不影响其他技能。"""

    NAME_MISMATCH = "front matter name 与目录名不一致"
    NAME_INVALID = "技能名不合法"
    MISSING_FIELD = "front matter 缺少必需字段"
    TOO_LARGE = "SKILL.md 超过大小上限"
    NOT_UTF8 = "SKILL.md 不是有效 UTF-8"
    SYMLINK = "技能目录或 SKILL.md 是符号链接"
    NOT_A_DIR = "技能条目不是目录"
    READ_ERROR = "SKILL.md 读取失败"


def _yaml() -> Any | None:
    """延迟导入 PyYAML（已在 requirements.txt 锁定）；不可用返回 None。"""
    try:
        import yaml

        return yaml
    except Exception:
        return None


def _scalar_str(value: Any) -> str | None:
    """只接受标量；返回其字符串形态。dict/list/None 等复合值一律拒绝。"""
    if isinstance(value, str):
        return value
    if isinstance(value, (bool, int, float)):
        return str(value)
    return None


def _parse_scalar_mapping(block: str) -> dict[str, str]:
    """把 front matter 块解析成「标量键 → 字符串值」映射。

    优先 ``yaml.safe_load``（不执行任意构造器），复合值直接丢弃；PyYAML
    不可用时退到逐行 ``key: value`` 解析（缩进行视为嵌套，忽略）。
    """
    result: dict[str, str] = {}
    yaml = _yaml()
    if yaml is not None:
        try:
            loaded = yaml.safe_load(block)
        except Exception:
            loaded = None
        if isinstance(loaded, dict):
            for key, value in loaded.items():
                if not isinstance(key, str):
                    continue
                scalar = _scalar_str(value)
                if scalar is not None:
                    result[key] = scalar
            return result
        # safe_load 失败或非 dict（如纯标量文档）时退到行解析，容忍半伤文件
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or line[:1] in (" ", "\t"):
            continue  # 嵌套/注释/空行：一概不进映射
        key, sep, value = stripped.partition(":")
        if not sep:
            continue
        result[key.strip()] = value.strip().strip("\"'")
    return result


def parse_front_matter(text: str) -> dict[str, str]:
    """从 SKILL.md 文本中解析白名单内的 front matter 标量。

    缺 front matter 块、块未闭合、键不在白名单：都只意味着「拿不到这个
    字段」，由调用方按 ``MISSING_FIELD`` 隔离；本函数不抛异常。
    """
    body = text.lstrip("﻿")
    if not body.startswith("---"):
        return {}
    lines = body.splitlines()
    end: int | None = None
    for offset, line in enumerate(lines[1 : _FRONT_MATTER_MAX_LINES + 1], start=1):
        if line.strip() == "---":
            end = offset
            break
    if end is None:
        return {}
    raw = _parse_scalar_mapping("\n".join(lines[1:end]))
    return {k: v for k, v in raw.items() if k in FRONT_MATTER_KEYS}


def read_manifest_bytes(path: Path, *, max_bytes: int) -> tuple[bytes, str] | None:
    """读取 SKILL.md 字节（带大小上限与符号链接拒绝）。

    返回 ``(字节, 隔离原因)``：字节为空表示被隔离，原因说明为什么。
    """
    try:
        if path.is_symlink() or not path.is_file():
            return (
                b"",
                Quarantine.SYMLINK if path.is_symlink() else Quarantine.READ_ERROR,
            )
        size = path.stat().st_size
        if size > max_bytes:
            return b"", Quarantine.TOO_LARGE
        data = path.read_bytes()
    except OSError:
        return b"", Quarantine.READ_ERROR
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return b"", Quarantine.NOT_UTF8
    return data, ""


def build_manifest(
    skill_dir: Path,
    *,
    source: SkillSource,
    max_bytes: int,
    origin: str = "",
) -> tuple[SkillManifest | None, str]:
    """校验单个技能目录并构造 manifest；返回 ``(manifest, 隔离原因)``。

    ``manifest`` 为 None 时原因非空。目录名即技能名：front matter 里的
    ``name`` 必须与目录名一致（Anthropic Skills 的对齐要求，避免「目录
    叫 a、声明叫 b」的双重身份）。
    """
    name = skill_dir.name
    if not skill_name_is_valid(name):
        return None, Quarantine.NAME_INVALID
    try:
        if skill_dir.is_symlink() or not skill_dir.is_dir():
            return (
                None,
                Quarantine.SYMLINK if skill_dir.is_symlink() else Quarantine.NOT_A_DIR,
            )
    except OSError:
        return None, Quarantine.READ_ERROR
    body_path = skill_dir / "SKILL.md"
    data, reason = read_manifest_bytes(body_path, max_bytes=max_bytes)
    if not data:
        return None, reason or Quarantine.READ_ERROR
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None, Quarantine.NOT_UTF8
    fields = parse_front_matter(text)
    if fields.get("name") and fields["name"] != name:
        return None, Quarantine.NAME_MISMATCH
    description = (fields.get("description") or "").strip()
    if not description:
        return None, f"{Quarantine.MISSING_FIELD}: description"
    metadata = {
        k: v[:_DESCRIPTION_MAX_CHARS]
        for k, v in fields.items()
        if k in FRONT_MATTER_KEYS and k not in ("name", "description")
    }
    return (
        SkillManifest(
            name=name,
            description=description[:_DESCRIPTION_MAX_CHARS],
            source=source,
            root=skill_dir,
            body_size=len(data),
            content_digest=hashlib.sha256(data).hexdigest(),
            origin=origin,
            metadata=metadata,
        ),
        "",
    )


def scan_layer(
    root: Path,
    *,
    source: SkillSource,
    max_bytes: int,
    origin_of: Any = None,
) -> tuple[list[SkillManifest], list[str]]:
    """扫描一层技能根目录，返回 ``(manifests, 隔离记录)``。

    ``origin_of`` 把技能目录映射到 origin（插件层用：`<插件>/skills/<名>`
    的 origin 是插件目录名）；缺省 origin 为空。根目录不存在是正常态
    （未配置/未装插件），返回空而不是错误。
    """
    manifests: list[SkillManifest] = []
    quarantined: list[str] = []
    if not root.is_dir():
        return manifests, quarantined
    try:
        children = sorted(root.iterdir(), key=lambda p: str(p))
    except OSError as e:
        quarantined.append(f"{root}: 扫描失败 {e}")
        return manifests, quarantined
    for child in children:
        origin = str(origin_of(child)) if origin_of is not None else ""
        manifest, reason = build_manifest(
            child, source=source, max_bytes=max_bytes, origin=origin
        )
        if manifest is None:
            quarantined.append(f"{child}: {reason}")
        else:
            manifests.append(manifest)
    return manifests, quarantined


def scan_plugins(
    plugins_dir: Path,
    *,
    max_bytes: int,
) -> tuple[list[SkillManifest], list[str]]:
    """扫描插件层：``<插件目录>/skills/<name>/SKILL.md``。

    与 ``astrbot_compat.loader._plugin_dir_of`` 的目录语义对齐（插件即
    ``ASTRBOT_PLUGINS_DIR`` 下的一个目录）；本函数不 import 兼容层，
    避免目录发现依赖 Bot 运行时。刷新单个插件见 ``SkillCatalog.refresh_plugin``。
    """
    manifests: list[SkillManifest] = []
    quarantined: list[str] = []
    if not plugins_dir.is_dir():
        return manifests, quarantined
    try:
        plugin_dirs = sorted(plugins_dir.iterdir(), key=lambda p: str(p))
    except OSError as e:
        quarantined.append(f"{plugins_dir}: 扫描失败 {e}")
        return manifests, quarantined
    for plugin_dir in plugin_dirs:
        if not plugin_dir.is_dir() or plugin_dir.is_symlink():
            continue
        layer_root = plugin_dir / "skills"
        # origin 是**插件目录名**：refresh_plugin 按 origin 局部替换时以它为键
        plugin_name = plugin_dir.name
        found, reasons = scan_layer(
            layer_root,
            source=SkillSource.PLUGIN,
            max_bytes=max_bytes,
            origin_of=lambda _child, _name=plugin_name: _name,
        )
        manifests.extend(found)
        quarantined.extend(reasons)
    return manifests, quarantined
