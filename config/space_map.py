# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""空间名解析的纯函数层：不依赖 ``config.settings``，也不依赖 ``nonebot``。

为什么要独立成一层：``config/spaces.py`` 在 import 时就会拉起 ``config.settings``
（进而 ``load_dotenv``），而数据迁移（``deploy migrate``）跑的时候目标 ``.env``
可能刚写好、常量已冻结为空值——这是 ``deploy/__main__.py:85-92`` 记录过的坑。
迁移需要「群号 → 空间名」这套判据，却不能承受那个副作用。

于是三级解析的**判据**放在这里（纯函数，参数进、结果出），``config/spaces.py``
负责把它接到运行时的路径与日志上，``deploy/`` 负责把它接到目标安装目录上。
两处调同一份代码，避免判据漂移——迁移写进 DB 的空间名与运行时查询用的空间名
不一致，会导致检索查不到、不报错、不抛异常（即「一切正常但什么都不记」）。

三级解析（与 ``config/spaces.py`` 的模块 docstring 一致）：

1. 显式空间：``config/spaces/*.toml`` 收录的群，空间名取文件名；
2. 自动账本：DB 旁的 ``.space_assignments.json``；
3. 分配新名 ``space_N``（N = 账本里已有的最大 N + 1）。

历史归属不明的行（群号为空、为 0、或群号已不在已知群集合里）归入
``legacy_<群号>`` / ``legacy_unknown``，**永不删除**：这类行数量通常不小，
静默丢弃事后无法解释也无法恢复。
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib
except ImportError:  # pragma: no cover - Python 3.10 需要 tomli 兜底
    import tomli as tomllib

# 自动命名账本的文件名（放在 DB 同目录）
LEDGER_FILENAME = ".space_assignments.json"
# 归属不明的行落到这个空间；它不参与检索，但保证数据不丢
LEGACY_UNKNOWN = "legacy_unknown"
LEGACY_PREFIX = "legacy_"
_AUTO_NAME_RE = re.compile(r"^space_(\d+)$")


@dataclass
class ExplicitSpaces:
    """``config/spaces/*.toml`` 的解析结果。

    ``conflicts`` / ``parse_errors`` 是人可读文本，**由调用方决定怎么记录**——
    运行时打 nonebot error，迁移时进报告。纯函数层不自己写日志。
    """

    qq_to_space: dict[int, str] = field(default_factory=dict)
    space_to_qq: dict[str, list[int]] = field(default_factory=dict)
    space_to_prompt: dict[str, str] = field(default_factory=dict)
    conflicts: list[str] = field(default_factory=list)
    parse_errors: list[str] = field(default_factory=list)


def load_explicit_spaces(spaces_dir: Path) -> ExplicitSpaces:
    """扫描 ``spaces_dir/*.toml``，构建群号→空间与空间→群号两张映射。

    目录不存在或没有 toml 时返回空结果（全自动命名）。排序遍历保证冲突处理
    确定性：同一个群出现在多个文件时采用文件名排序靠前的那个——静默取后者会让
    记忆在两次启动间落到不同空间，这种错乱事后极难发现。
    """
    result = ExplicitSpaces()
    if not spaces_dir.is_dir():
        return result
    for path in sorted(spaces_dir.glob("*.toml")):
        space = path.stem
        try:
            with path.open("rb") as f:
                data = tomllib.load(f)
        except Exception as e:
            result.parse_errors.append(f"解析 {path.name} 失败，跳过该文件: {e}")
            continue
        qq_groups = data.get("qq_groups")
        if not isinstance(qq_groups, list):
            result.parse_errors.append(f"{path.name} 缺少 qq_groups 列表，跳过该文件")
            continue
        prompt = data.get("system_prompt")
        if isinstance(prompt, str) and prompt.strip():
            result.space_to_prompt[space] = prompt.strip()
        for g in qq_groups:
            if not isinstance(g, int):
                result.parse_errors.append(f"{path.name} 中 {g!r} 不是整数群号，跳过")
                continue
            if g in result.qq_to_space:
                result.conflicts.append(
                    f"群 {g} 同时出现在空间 {result.qq_to_space[g]} 与 {space}，"
                    f"采用先者 {result.qq_to_space[g]}（按文件名排序）"
                )
                continue
            result.qq_to_space[g] = space
            result.space_to_qq.setdefault(space, []).append(g)
    return result


def load_ledger(path: Path) -> tuple[dict[int, str], str | None]:
    """读取自动命名账本，返回 ``(映射, 错误描述)``。

    文件不存在 → ``({}, None)``（正常首次运行）；解析失败 → ``({}, 错误)``。
    区分这两种情况是硬要求：**解析失败时调用方不得分配新名**，否则会覆盖一个
    存在但读不出的账本，两次启动分到不同名字，记忆归属错位且无声。
    """
    if not path.exists():
        return {}, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return {}, f"账本 {path} 读取失败: {e}"
    mapping: dict[int, str] = {}
    if isinstance(data, dict):
        for k, v in data.items():
            try:
                mapping[int(k)] = str(v)
            except (TypeError, ValueError):
                continue
    return mapping, None


def save_ledger(path: Path, mapping: Mapping[int, str]) -> str | None:
    """原子写账本（先写 ``.tmp`` 再 replace）。成功返回 None，失败返回错误描述。"""
    try:
        payload = {str(k): v for k, v in mapping.items()}
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
    except Exception as e:
        return f"账本 {path} 写入失败: {e}"
    return None


def allocate_space_name(ledger: Mapping[int, str]) -> str:
    """分配下一个自动命名 ``space_N``：N = 账本里已有 space_N 的最大 N + 1。

    绝不能现算编号（如按群号排序取下标）：加入一个群号更小的新群会让所有编号
    平移，全部记忆归属错位且无声无息。
    """
    max_n = 0
    for name in ledger.values():
        m = _AUTO_NAME_RE.match(str(name))
        if m:
            max_n = max(max_n, int(m.group(1)))
    return f"space_{max_n + 1}"


def legacy_space_name(raw: object) -> str:
    """把归属不明的旧值转成 ``legacy_<群号>``；空/非数字归 ``legacy_unknown``。"""
    text = str(raw).strip() if raw is not None else ""
    if not text or not text.isdigit() or int(text) <= 0:
        return LEGACY_UNKNOWN
    return f"{LEGACY_PREFIX}{text}"


def is_legacy_space(name: object) -> bool:
    """是否是 ``legacy_*`` 空间（不参与常规检索，但永不删除）。"""
    return str(name or "").startswith(LEGACY_PREFIX)


def is_auto_space(name: object) -> bool:
    """是否是自动分配的 ``space_N`` 名字。"""
    return bool(_AUTO_NAME_RE.match(str(name or "")))
