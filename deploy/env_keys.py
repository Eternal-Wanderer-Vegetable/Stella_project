# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""``.env`` 键的生命周期登记表：废弃、改名、敏感。

**全项目关于「这个键还算不算数」的单一真相源**：`deploy doctor` 的废弃提示、
升级时的 `.env` 合并器、将来 GUI 的配置页都从这里读。散落两份必然对不上——
一处删了、另一处还在提示，用户会收到互相矛盾的建议。

判据只有一条：**代码是否还在读它**。只要 `config/settings.py` 不再读某个键，它就
必须登记在这里，否则用户的 `.env` 里会留着一行完全不生效的配置，而他以为改了。
"""

from __future__ import annotations

from collections.abc import Callable

# 已废弃的键 → 废弃原因（会写进升级报告，所以要写成人话）
DEPRECATED: dict[str, str] = {
    "NAPCAT_SHELL_PATH": "启动流程已与 NapCat 完全分离，Bot 只连现成的 OneBot 端点",
    "NAPCAT_AUTO_START": "同上：不再由 Stella 拉起 NapCat",
    "NAPCAT_QQ_ACCOUNT": "同上：登录由 NapCat 自己完成（需人工扫码）",
    "NAPCAT_QQ_PASSWORD": "同上，且明文密码本不该出现在配置文件里",
    "NAPCAT_QQ_PASSWORD_MD5": "同上",
    "NAPCAT_LAUNCH_LOG_PATH": "同上：不再有 NapCat 启动日志",
    "NAPCAT_SHOW_WINDOW": "同上",
    "MEMORY_COMPRESS_LOG_FILENAME": (
        "2026-08-25 日志统一到 LOG_DIR 后改为完整路径 MEMORY_COMPRESS_LOG_PATH；"
        "语义从「文件名」变成「完整路径」，旧值不能直接沿用"
    ),
    "MEMORY_RECENCY_HALF_LIFE_DAYS": (
        "recency 衰减已改为统一的指数衰减（τ=30 天，见 memory/policy.py），"
        "不再按类型取半衰期；本键自 2026-08-11 起代码不再读取"
    ),
    "MEMORY_AT_MENTION_CONFIDENCE_BONUS": (
        "从未接线：AT_MENTION 的强证据语义由 MEMORY_PROMOTE_AT_MENTION_SINGLE_SHOT"
        "（单次晋升门槛）承担"
    ),
    "PROACTIVE_TOPIC_WARMUP_SECONDS": (
        "话题预热由参与评分层承担：config/participation/thresholds.toml 的 "
        "warmup_messages（按条数，不是秒数）"
    ),
    "PROACTIVE_COLDSTART_TOPICS": (
        "主动 @ 已收敛为「只验证记忆候选」：无可验证候选时不再用日常话题冷启动搭话，"
        "无记忆锚点的闲聊由参与评分层（config/participation/*.toml）承担"
    ),
}

# 已废弃的键前缀 → 原因
DEPRECATED_PREFIXES: dict[str, str] = {
    "NAPCAT_WATCHDOG_": "NapCat 看护逻辑已移除",
}

# 改名且**值可以直接沿用**的键（旧名 → 新名）。
# 语义也变了的不要放这里（如 MEMORY_COMPRESS_LOG_FILENAME），那种只能提示重填。
#
# 为什么这张表现在还是空的：2026-08-28 的端点/角色改造**没有改名任何旧键**，
# 而是让新键继承旧键（config/settings.py 里的 _env_inherit）。这不是偷懒——
# LM_STUDIO_BASE_URL / _MODEL / _API_KEY 各有 4~5 个继承子键，而合并器改名时
# 是「把值搬到新键、旧键那行恢复模板默认值」，一改名就等于把那 4~5 个子键悄悄
# 重置回默认地址。旧键的收敛改走下面 SUPERSEDED 的换算迁移（2026-09-18 起），
# 这里保持为空。
RENAMED: dict[str, str] = {}

# 已被新键取代、但**代码仍在兼容读取**的键（旧名 → 新名）。
#
# 与 DEPRECATED 的分工：那张表是「代码已经不读了」，所以只能提示用户删掉；
# 这张表是「代码还读，只是不该再由用户来填」——于是三个消费方各取所需：
#   - deploy/env_schema.py：从 GUI schema 里剔掉旧键，界面上只留新键；
#   - deploy/env_merge.py：升级时把值换算成新键的值，旧键那行随之消失；
#   - deploy doctor：对还留着旧键的 .env 给出改法提示。
# 值怎么换算见 migrate_value()——表本身保持纯数据，好让 GUI 直接读。
#
# 2026-09-18 的三代键收敛：LM_STUDIO_* / CONSOLIDATION_LM_STUDIO_* /
# MEMORY_EXTRACT_LM_STUDIO_* / ASTRBOT_LLM_* 的连接参数整体迁入
# LLM_ENDPOINT_* / LLM_ROLE_*。全部 1:1 值直接沿用（targets 的语义论证见
# 该提交与 config/settings.py 端点段的注释）；config/settings.py 的兼容读与
# registry 的三级模型解析**本轮保留**——deploy upgrade 只换程序树不跑合并，
# 没走过 init/migrate 的存量 .env 靠它们保持原行为。这批键转入 DEPRECATED
# （即删除兼容读）要等迁移发版一个弃用窗口之后。
SUPERSEDED: dict[str, str] = {
    "LLM_SCHEDULER_GATE_EMBEDDING": "MEMORY_EMBEDDING_GATE",
    # ── 第一代：本机 LM Studio ──
    "LM_STUDIO_BASE_URL": "LLM_ENDPOINT_LOCAL_BASE_URL",
    "LM_STUDIO_API_KEY": "LLM_ENDPOINT_LOCAL_API_KEY",
    "LM_STUDIO_MODEL": "LLM_ENDPOINT_LOCAL_MODEL",
    # ── 第二代：整合（EXTRA 槽 + CONSOLIDATION 角色）──
    "CONSOLIDATION_LM_STUDIO_BASE_URL": "LLM_ENDPOINT_EXTRA_BASE_URL",
    "CONSOLIDATION_LM_STUDIO_API_KEY": "LLM_ENDPOINT_EXTRA_API_KEY",
    "CONSOLIDATION_LM_STUDIO_MODEL": "LLM_ROLE_CONSOLIDATION_MODEL",
    "CONSOLIDATION_LM_STUDIO_TEMPERATURE": "LLM_ROLE_CONSOLIDATION_TEMPERATURE",
    # ── 第二代：候选提取（EXTRACT 角色）──
    "MEMORY_EXTRACT_LM_STUDIO_MODEL": "LLM_ROLE_EXTRACT_MODEL",
    "MEMORY_EXTRACT_LM_STUDIO_TEMPERATURE": "LLM_ROLE_EXTRACT_TEMPERATURE",
    "MEMORY_EXTRACT_LM_STUDIO_MAX_TOKENS": "LLM_ROLE_EXTRACT_MAX_TOKENS",
    # ── 第二代：AstrBot 插件 LLM（PLUGIN 角色）──
    "ASTRBOT_LLM_MODEL": "LLM_ROLE_PLUGIN_MODEL",
    "ASTRBOT_LLM_TEMPERATURE": "LLM_ROLE_PLUGIN_TEMPERATURE",
    "ASTRBOT_LLM_MAX_TOKENS": "LLM_ROLE_PLUGIN_MAX_TOKENS",
}

# 敏感键：报告里只说「已沿用」，绝不打印值。
# 发布包的日志与报告都可能被贴进 issue，凭据一旦泄露无法收回。
SENSITIVE: frozenset[str] = frozenset(
    {
        "ONEBOT_ACCESS_TOKEN",
        "NAPCAT_QQ_PASSWORD",
        "NAPCAT_QQ_PASSWORD_MD5",
        "LM_STUDIO_API_KEY",
        "OPENAI_API_KEY",
    }
)


def deprecation_reason(key: str) -> str | None:
    """键是否已废弃；是则返回原因，否则 None。"""
    if key in DEPRECATED:
        return DEPRECATED[key]
    for prefix, reason in DEPRECATED_PREFIXES.items():
        if key.startswith(prefix):
            return reason
    return None


def is_sensitive(key: str) -> bool:
    """是否敏感键（报告与日志里不打印其值）。"""
    upper = key.upper()
    return upper in SENSITIVE or any(
        marker in upper for marker in ("TOKEN", "PASSWORD", "SECRET", "API_KEY")
    )


def superseded_by(key: str) -> str | None:
    """键是否已被新键取代；是则返回新键名，否则 None。"""
    return SUPERSEDED.get(key)


def _bool(value: str) -> bool:
    """与 ``config/settings.py`` 里布尔键的解析口径保持一致。"""
    return value.strip().strip("\"'").lower() in ("true", "1", "yes")


def _gate_embedding_to_enum(value: str) -> str:
    """``LLM_SCHEDULER_GATE_EMBEDDING`` 布尔 → ``MEMORY_EMBEDDING_GATE`` 枚举。

    ``true`` → ``auto`` 而不是 ``LOCAL``：旧键的真实语义是「embedding 与主聊天同
    实例，得跟它排一条队」，而主聊天现在可能已经切到在线端点了。``auto`` 恰好
    把这句话表达成与端点无关的判据（地址相同且 KIND=local 才共用闸门），
    所以纯本地用户升级后行为不变，切在线的用户也不会让本地 embedding 去排
    在线调用的队。``false`` → ``none``（独立不排队）是逐字等价。
    """
    return "auto" if _bool(value) else "none"


# 旧键 → 值换算函数。没有登记的旧键按「值可以直接沿用」处理。
_VALUE_MIGRATIONS: dict[str, Callable[[str], str]] = {
    "LLM_SCHEDULER_GATE_EMBEDDING": _gate_embedding_to_enum,
}


def migrate_value(key: str, value: str) -> tuple[str, str] | None:
    """把旧键的一行换算成新键的一行；``key`` 不是被取代的旧键时返回 None。

    返回 ``(新键名, 新键的值)``。调用方（``deploy/env_merge.py``）负责决定
    「新键已经被用户显式设过」时不覆盖——换算只管值本身，不管优先级。
    """
    target = SUPERSEDED.get(key)
    if not target:
        return None
    convert = _VALUE_MIGRATIONS.get(key)
    return target, convert(value) if convert else value
