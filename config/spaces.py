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

隐式空间规则：未被任何 ``.toml`` 收录的 QQ 群，空间名即其群号字符串。
单群部署零配置，行为与改造前完全一致。

配置示例（``persona`` / ``[proactive]`` 预告 M3/M4 会用，现在不解析，但先定下
格式避免将来要改已写好的文件）：:

    # config/spaces/casual.toml —— 空间名取文件名 "casual"
    qq_groups = [263402786, 123456789]
    persona = "casual"        # M4 使用，当前忽略
    [proactive]               # M3 使用，当前忽略
    cooldown = 600
"""

from __future__ import annotations

try:
    import tomllib
except ImportError:  # pragma: no cover - Python 3.10 需要 tomli 兜底（pyproject requires-python >=3.10）
    import tomli as tomllib

from config.settings import ALLOWED_GROUPS, PROJECT_ROOT

# 共享空间配置文件目录：config/spaces/*.toml
SPACES_DIR = PROJECT_ROOT / "config" / "spaces"

# 模块级缓存：群号 → 空间名 / 空间名 → 群号列表
_qq_to_space: dict[int, str] | None = None
_space_to_qq: dict[str, list[int]] = {}


def _load() -> None:
    """扫描 ``config/spaces/*.toml``，构建群号→空间与空间→群号两张映射。

    目录不存在或无 ``.toml`` 时正常返回（全隐式空间）。排序遍历保证冲突
    处理确定性；单个文件解析失败只跳过该文件，不中断其余加载。
    """
    from nonebot import logger

    global _qq_to_space, _space_to_qq
    qq_to_space: dict[int, str] = {}
    space_to_qq: dict[str, list[int]] = {}
    if not SPACES_DIR.is_dir():
        _qq_to_space = qq_to_space
        _space_to_qq = space_to_qq
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


def resolve_space(qq_group_id: int) -> str:
    """把真实 QQ 群号解析为共享空间名；未收录时返回群号字符串（隐式空间）。

    隐式空间规则：未被任何 ``.toml`` 收录的群，空间名即其群号字符串——
    单群部署零配置，行为与改造前完全一致。
    """
    global _qq_to_space
    if _qq_to_space is None:
        _load()
    return _qq_to_space.get(qq_group_id, str(qq_group_id))


def list_spaces() -> list[str]:
    """列出全部空间：显式空间 + ``ALLOWED_GROUPS`` 中未被收录的群各自的隐式空间。

    去重、排序，供 M5 遍历使用。
    """
    global _qq_to_space
    if _qq_to_space is None:
        _load()
    spaces = set(_space_to_qq)
    for g in ALLOWED_GROUPS:
        if g not in _qq_to_space:
            spaces.add(str(g))
    return sorted(spaces)


def qq_groups_of(space: str) -> list[int]:
    """取某空间包含的 QQ 群列表。

    显式空间查 ``_space_to_qq``；若 ``space`` 本身是群号字符串且不属于任何
    显式空间（即隐式空间），返回 ``[int(space)]``。
    """
    global _qq_to_space
    if _qq_to_space is None:
        _load()
    if space in _space_to_qq:
        return list(_space_to_qq[space])
    if space.isdigit():
        g = int(space)
        if g not in _qq_to_space:
            return [g]
    return []


def reload() -> None:
    """清空缓存，下次调用重新扫描 ``config/spaces/*.toml``。

    供测试与将来的前端热重载使用。
    """
    global _qq_to_space, _space_to_qq
    _qq_to_space = None
    _space_to_qq = {}
