# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""共享空间（人格载体）管理（方案 §6.8）。

空间 = ``STELLA_HOME/config/spaces/<name>.toml``（qq_groups 绑定）+
``STELLA_HOME/system_prompts/<space>.md``（人格正文）。任何写操作完成后
必须 ``config.spaces.reload()`` 清缓存——这是 spaces.py 注释里明确的
「将来的前端热重载」入口。

出厂默认人格（memory/SYSTEM.md，程序目录）只读：编辑请求一律 409，
提示新建空间。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import config.settings as settings
from webui.responses import ApiError

try:
    import tomllib
except ImportError:  # pragma: no cover - Python 3.10 需 tomli（同 space_map 兜底）
    import tomli as tomllib

_NAME_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")


def spaces_dir() -> Path:
    """空间 toml 目录。以 ``config.spaces.SPACES_DIR`` 为唯一事实源——
    测试夹具会隔离那个值，自算路径会读写到两个不同目录（实测踩过）。"""
    from config import spaces as spaces_mod

    return Path(spaces_mod.SPACES_DIR)


def prompts_dir() -> Path:
    return Path(settings.STELLA_HOME) / "system_prompts"


def _toml_path(name: str) -> Path:
    return spaces_dir() / f"{name}.toml"


def _load_toml(name: str) -> dict:
    path = _toml_path(name)
    if not path.exists():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_toml(name: str, data: dict) -> None:
    """手写最小 TOML（键固定两类；避免为两行配置引入 tomli_w 依赖）。"""
    path = _toml_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"qq_groups = {json.dumps([int(g) for g in data.get('qq_groups', [])])}"]
    if data.get("system_prompt"):
        # json.dumps 产生的带引号字符串是合法的 TOML basic string
        lines.append(f"system_prompt = {json.dumps(data['system_prompt'])}")
    tmp = path.with_suffix(".toml.tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(path)


def _reload() -> None:
    from config import spaces as spaces_mod

    spaces_mod.reload()


def _resolve_prompt_file(name: str, data: dict) -> Path:
    """空间人格正文固定在用户层 ``system_prompts/<name>.md``。

    不走 ``spaces_mod.prompt_path``：无绑定的空间会被 load_explicit_spaces
    整体忽略，那条例程会把我们带回到出厂 SYSTEM.md（实测踩过）。用户层
    固定路径 + toml 固定指向，语义最直白。
    """
    data["system_prompt"] = f"{name}.md"
    return prompts_dir() / f"{name}.md"


def _validate_name(name: str) -> None:
    if not _NAME_RE.fullmatch(name):
        raise ApiError("空间名只能包含字母、数字、下划线与连字符（≤64 字符）")


def list_spaces() -> list[dict]:
    """显式空间清单 = 枚举 toml 文件。

    刻意不走 ``spaces_mod.list_spaces()``：那基于 load_explicit_spaces，
    会**丢弃没有绑定群的空间**（space_map 语义），而管理界面恰恰要在
    「刚建好、还没绑群」时就看见它。也不触发自动分配（那是有副作用的写）。
    """
    from config import spaces as spaces_mod

    items = []
    for path in sorted(spaces_dir().glob("*.toml")):
        name = path.stem
        data = _load_toml(name)
        prompt = spaces_mod.prompt_text(name)
        items.append(
            {
                "name": name,
                "qq_groups": data.get("qq_groups", []),
                "prompt_chars": len(prompt),
                "prompt_preview": prompt[:80],
                "prompt_file": data.get("system_prompt") or f"{name}.md",
            }
        )
    return items


def create_space(name: str, *, system_prompt: str = "") -> dict:
    _validate_name(name)
    if _toml_path(name).exists():
        raise ApiError(f"空间 {name} 已存在", status_code=409)
    _write_toml(name, {"qq_groups": [], "system_prompt": f"{name}.md"})
    prompts_dir().mkdir(parents=True, exist_ok=True)
    (prompts_dir() / f"{name}.md").write_text(system_prompt, encoding="utf-8")
    _reload()
    return {"name": name}


def get_prompt(name: str) -> str:
    user_file = prompts_dir() / f"{name}.md"
    if user_file.exists():
        return user_file.read_text(encoding="utf-8")
    from config import spaces as spaces_mod

    return spaces_mod.prompt_text(name)


def put_prompt(name: str, text: str) -> dict:
    _validate_name(name)
    data = _load_toml(name)
    if not data and not _toml_path(name).exists():
        raise ApiError("空间不存在", status_code=404)
    data.setdefault("qq_groups", data.get("qq_groups", []))
    target = _resolve_prompt_file(name, data)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".md.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(target)
    _write_toml(name, data)
    _reload()
    return {"name": name, "prompt_file": str(target)}


def put_bindings(name: str, qq_groups: list[int]) -> dict:
    """upsert 语义：绑定向导输入「群 + 新空间名」即创建空间（不 404）。"""
    _validate_name(name)
    # 同群不得出现在两个空间：先从其它空间的绑定里摘掉
    for other in spaces_dir().glob("*.toml"):
        if other.stem == name:
            continue
        other_data = _load_toml(other.stem)
        others = [g for g in other_data.get("qq_groups", []) if int(g) not in {int(x) for x in qq_groups}]
        if len(others) != len(other_data.get("qq_groups", [])):
            other_data["qq_groups"] = others
            _write_toml(other.stem, other_data)
    data = _load_toml(name)
    data["qq_groups"] = [int(g) for g in qq_groups]
    _write_toml(name, data)
    _reload()
    return {"name": name, "qq_groups": data["qq_groups"]}


def delete_space(name: str) -> None:
    _validate_name(name)
    data = _load_toml(name)
    if data.get("qq_groups"):
        raise ApiError("空间仍绑定群组，请先解绑", status_code=409)
    path = _toml_path(name)
    if path.exists():
        path.unlink()
        _reload()


def default_prompt() -> dict:
    """出厂人格（程序目录 memory/SYSTEM.md），只读。"""
    from config import PROJECT_ROOT

    path = Path(PROJECT_ROOT) / "memory" / "SYSTEM.md"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    return {"text": text, "path": str(path)}
