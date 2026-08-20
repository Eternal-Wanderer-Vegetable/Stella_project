# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""共享空间（Shared Space）解析。

两层归属的分界线：

「当下这场对话的状态」按 **QQ 群**：消息尾巴、整合 checkpoint、短期话题、
会话压缩、静音开关、@ 配额。
「对人的长期认知与身份」按 **共享空间**：用户画像、长期记忆、人格（system prompt）、
发言策略。

为什么不能反过来：把 A 群和 B 群的最近消息混进同一条尾巴，Bot 会在 A 群回应
B 群的对话——这比记忆串味严重得多。

空间名解析（三级）：

1. **显式空间**：``config/spaces/*.toml`` 里收录的 QQ 群，空间名取文件名；
2. **自动账本**：DB 旁的 JSON 状态文件（``.space_assignments.json``）里记录的名字；
3. **分配新名**：都没命中时分配 ``space_N``（N = 账本最大编号 + 1）并落盘。

自动命名**分配一次、持久记录**——绝不能现算编号（如按 ALLOWED_GROUPS 排序后的
下标），否则加入一个群号更小的新群会让所有编号平移，全部记忆归属错位且无声无息。
账本文件是程序自己的账本（不是人/前端编辑的 TOML 配置）。

硬约束：**显式配置改名不自动迁移记忆**。若某群先在账本里拿到 ``space_N``、后来
又被显式配置改名，历史记忆仍挂在旧名下——resolve_space 会打 error 告警，需按提示
手工跑 ``UPDATE memories SET group_shared_space=...``（同理 memory_candidates /
user_profiles / atomic_facts / memories_fts）。改名是无声丢记忆的最大来源。

配置示例（``persona`` / ``[proactive]`` 预告 M3/M4 会用，现在不解析，但先定下
格式避免将来要改已写好的文件）：:

    # config/spaces/casual.toml —— 空间名取文件名 "casual"
    qq_groups = [263402786, 123456789]
    persona = "casual"        # M4 使用，当前忽略
    [proactive]               # M3 使用，当前忽略
    cooldown = 600
"""

from __future__ import annotations

import json
import re
from pathlib import Path

try:
    import tomllib
except ImportError:  # pragma: no cover - Python 3.10 需要 tomli 兜底（pyproject requires-python >=3.10）
    import tomli as tomllib

from config.settings import ALLOWED_GROUPS, DB_PATH, PROJECT_ROOT, SYSTEM_PROMPT_PATH

# 共享空间配置文件目录：config/spaces/*.toml
SPACES_DIR = PROJECT_ROOT / "config" / "spaces"
PROMPTS_DIR = PROJECT_ROOT / "system_prompts"
# 自动命名账本（程序自己的状态文件，放在 DB 旁边，不是人/前端编辑的 TOML 配置）。
# 结构：{"263402786": "space_1", "987654321": "space_2"}
_AUTO_FILE = DB_PATH.parent / ".space_assignments.json"

# 模块级缓存：群号 → 空间名 / 空间名 → 群号列表
_qq_to_space: dict[int, str] | None = None
_space_to_qq: dict[str, list[int]] = {}
_space_to_prompt: dict[str, str] = {}
# 自动账本缓存 + 最近一次加载是否失败（失败时不得分配新名）
_auto_ledger: dict[int, str] | None = None
_auto_load_failed: bool = False


def _load() -> None:
    """扫描 ``config/spaces/*.toml``，构建群号→空间与空间→群号两张映射。

    目录不存在或无 ``.toml`` 时正常返回（全自动/隐式命名）。排序遍历保证冲突
    处理确定性；单个文件解析失败只跳过该文件，不中断其余加载。
    """
    from nonebot import logger

    global _qq_to_space, _space_to_qq, _space_to_prompt
    qq_to_space: dict[int, str] = {}
    space_to_qq: dict[str, list[int]] = {}
    space_to_prompt: dict[str, str] = {}
    if not SPACES_DIR.is_dir():
        _qq_to_space = qq_to_space
        _space_to_qq = space_to_qq
        _space_to_prompt = space_to_prompt
        return
    # 排序保证冲突处理确定性：同群出现在多个文件时采用文件名排序靠前的那个
    for path in sorted(SPACES_DIR.glob("*.toml")):
        space = path.stem
        try:
            with path.open("rb") as f:
                data = tomllib.load(f)
        except Exception as e:
            logger.error(f"⚠️ [Spaces] 解析 {path.name} 失败，跳过该文件: {e}")
            continue
        qq_groups = data.get("qq_groups")
        if not isinstance(qq_groups, list):
            logger.warning(f"⚠️ [Spaces] {path.name} 缺少 qq_groups 列表，跳过该文件")
            continue
        prompt = data.get("system_prompt")
        if isinstance(prompt, str) and prompt.strip():
            space_to_prompt[space] = prompt.strip()
        for g in qq_groups:
            if not isinstance(g, int):
                logger.warning(f"⚠️ [Spaces] {path.name} 中 {g!r} 不是整数群号，跳过")
                continue
            if g in qq_to_space:
                # 静默取后者会让记忆在两次启动间落到不同空间，这种错乱事后极难发现，
                # 因此冲突必须显式报错，且采用文件名排序靠前的那个保证结果确定性。
                logger.error(
                    f"⚠️ [Spaces] 群 {g} 同时出现在空间 {qq_to_space[g]} 与 {space}，"
                    f"采用先者 {qq_to_space[g]}（按文件名排序）"
                )
                continue
            qq_to_space[g] = space
            space_to_qq.setdefault(space, []).append(g)
    _qq_to_space = qq_to_space
    _space_to_qq = space_to_qq
    _space_to_prompt = space_to_prompt


def prompt_path(space: str) -> Path:
    """返回空间 prompt 路径；未指定或不存在时回退旧默认人格文件。"""
    prompt = _space_to_prompt.get(space)
    if prompt:
        candidate = (PROMPTS_DIR / prompt).resolve()
        if candidate.parent == PROMPTS_DIR.resolve() and candidate.is_file():
            return candidate
    if SYSTEM_PROMPT_PATH.is_file():
        return SYSTEM_PROMPT_PATH
    return PROJECT_ROOT / "memory" / "SYSTEM.md"


def prompt_text(space: str) -> str:
    path = prompt_path(space)
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _load_auto() -> dict[int, str]:
    """读取自动命名账本（DB 旁的 JSON 状态文件）。

    文件不存在返回 ``{}``；解析失败打 error 日志并返回 ``{}``，同时置位
    ``_auto_load_failed``——调用方此时**不得分配新名**，否则会覆盖一个可能存在
    但读不出的账本（两次启动分到不同名字，记忆归属错位且无声）。
    """
    from nonebot import logger

    global _auto_load_failed
    if not _AUTO_FILE.exists():
        _auto_load_failed = False
        return {}
    try:
        raw = _AUTO_FILE.read_text(encoding="utf-8")
        data = json.loads(raw)
        mapping: dict[int, str] = {}
        if isinstance(data, dict):
            for k, v in data.items():
                try:
                    mapping[int(k)] = str(v)
                except (TypeError, ValueError):
                    continue
        _auto_load_failed = False
        return mapping
    except Exception as e:
        _auto_load_failed = True
        logger.error(f"⚠️ [Spaces] 自动命名账本 {_AUTO_FILE} 读取失败，本次不分配新名: {e}")
        return {}


def _save_auto(mapping: dict[int, str]) -> None:
    """把自动命名账本原子写盘（先写 ``.tmp`` 再 ``replace``），失败只打 warning。"""
    from nonebot import logger

    try:
        payload = {str(k): v for k, v in mapping.items()}
        tmp = _AUTO_FILE.with_suffix(_AUTO_FILE.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(_AUTO_FILE)
    except Exception as e:
        logger.warning(f"⚠️ [Spaces] 自动命名账本写入失败: {e}")


def _get_auto_ledger() -> dict[int, str]:
    """取自动账本（懒加载缓存）。加载失败时返回空 dict 且 ``_auto_load_failed`` 置位。"""
    global _auto_ledger, _auto_load_failed
    if _auto_ledger is None:
        _auto_ledger = _load_auto()
    return _auto_ledger


def _allocate_new(ledger: dict[int, str]) -> str:
    """分配下一个自动命名 ``space_N``：N = 账本里已有 space_N 的最大 N + 1。"""
    max_n = 0
    for name in ledger.values():
        m = re.match(r"^space_(\d+)$", str(name))
        if m:
            max_n = max(max_n, int(m.group(1)))
    return f"space_{max_n + 1}"


def resolve_space(qq_group_id: int) -> str:
    """把真实 QQ 群号解析为群组共享空间名（三级解析，见模块 docstring）。

    1. **显式空间**（``config/spaces/*.toml``）命中 → 返回该空间名；若该群在自动
       账本里也有记录且与显式名不同，打 error 告警（历史记忆仍挂在旧名下，
       需按提示手工迁移）；
    2. **自动账本**（DB 旁的 JSON 状态文件）命中 → 返回记录的名字；
    3. 都没有 → 分配新名 ``space_N``（N = 账本最大 N + 1）并落盘。

    自动命名分配一次、持久记录，绝不能现算编号。账本读取失败时不分配新名
    （否则可能覆盖读不出的账本），回退到群号字符串并打 error。
    """
    from nonebot import logger

    global _qq_to_space
    if _qq_to_space is None:
        _load()

    # 第 1 级：显式空间
    explicit = _qq_to_space.get(qq_group_id)
    if explicit is not None:
        recorded = _get_auto_ledger().get(qq_group_id)
        if recorded is not None and recorded != explicit:
            # 改名是无声丢记忆的最大来源：历史记忆还挂在旧名下，必须显式告警
            logger.error(
                f"⚠️ [Spaces] 群 {qq_group_id} 的空间已从 `{recorded}` 改为 `{explicit}`，"
                f"历史记忆仍挂在 `{recorded}` 下，需手工迁移："
                f"UPDATE memories SET group_shared_space='{explicit}' "
                f"WHERE group_shared_space='{recorded}'"
                f"（同理 memory_candidates / user_profiles / atomic_facts / memories_fts）"
            )
        return explicit

    # 第 2 级：自动账本
    ledger = _get_auto_ledger()
    recorded = ledger.get(qq_group_id)
    if recorded is not None:
        return recorded

    # 第 3 级：分配新名。账本读取失败时不能分配——否则可能覆盖一个存在但读不出的
    # 账本，两次启动分到不同名字。回退到群号字符串，宁丑不错。
    if _auto_load_failed:
        logger.error(
            f"⚠️ [Spaces] 自动命名账本读取失败，群 {qq_group_id} 回退到群号字符串命名；"
            f"请检查 {_AUTO_FILE} 后重启（否则可能出现命名不一致）"
        )
        return str(qq_group_id)

    space = _allocate_new(ledger)
    ledger[qq_group_id] = space
    _save_auto(ledger)
    return space


def list_spaces() -> list[str]:
    """列出全部空间：显式空间 + ``ALLOWED_GROUPS`` 中未被显式收录的群各自的空间。

    未被收录的群用 ``resolve_space(g)`` 取名——会走自动账本/分配并持久化，
    而不是直接 ``str(g)``。去重、排序，供 M5 遍历使用。
    """
    global _qq_to_space
    if _qq_to_space is None:
        _load()
    spaces = set(_space_to_qq)
    for g in ALLOWED_GROUPS:
        if g not in _qq_to_space:
            spaces.add(resolve_space(g))
    return sorted(spaces)


def qq_groups_of(space: str) -> list[int]:
    """取某空间包含的 QQ 群列表。

    显式空间查 ``_space_to_qq``；自动空间反查自动账本；``space`` 本身是群号字符串
    且不属于任何显式空间时（历史/回退命名），返回 ``[int(space)]``。
    """
    global _qq_to_space
    if _qq_to_space is None:
        _load()
    if space in _space_to_qq:
        return list(_space_to_qq[space])
    auto = [g for g, name in _get_auto_ledger().items() if name == space]
    if auto:
        return auto
    if space.isdigit():
        g = int(space)
        if g not in _qq_to_space:
            return [g]
    return []


def reload() -> None:
    """清空缓存（含自动账本），下次调用重新扫描配置与账本。

    供测试与将来的前端热重载使用。
    """
    global _qq_to_space, _space_to_qq, _space_to_prompt, _auto_ledger, _auto_load_failed
    _qq_to_space = None
    _space_to_qq = {}
    _space_to_prompt = {}
    _auto_ledger = None
    _auto_load_failed = False
