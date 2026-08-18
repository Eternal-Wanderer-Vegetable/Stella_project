# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""doctor 的判断层：每个检查一个纯函数，只读 Snapshot、不做 IO。

这样测试不需要真实环境——构造一个 Snapshot 即可覆盖所有分支。

``level`` 的语义：
- ``error`` = 阻塞启动，功能一定不工作
- ``warn`` = 可以运行但有隐患，或探测失败无法确定
- ``ok`` = 通过

**探测失败一律是 warn 而非 error**：分不清「确实有问题」和「我没测出来」时，
不该拦住用户启动。

个别检查（``check_deprecated_env_keys``）会返回多条结论，因此检查函数签名是
``-> CheckResult | Sequence[CheckResult] | None``；``None`` = 不适用，跳过。
"""

from __future__ import annotations

import difflib
from collections.abc import Callable, Sequence

from .models import CheckResult, Snapshot


def _suggest_model(configured: str, loaded: list[str]) -> str:
    """给出「你可能想写的是」建议。

    LM Studio 要求完整模型 ID（含 google/ 之类的前缀），最常见的错误就是
    漏掉前缀。difflib 能直接匹配出正确 ID，比让用户自己比对列表有效得多。
    """
    hits = difflib.get_close_matches(configured, loaded, n=3, cutoff=0.4)
    if hits:
        return "你可能想写的是：" + " / ".join(hits)
    return "当前已加载的模型：" + (" / ".join(loaded) if loaded else "（无）")


def check_python_version(snap: Snapshot) -> CheckResult | None:
    """<3.10 → error；==3.10 且缺 tomli → error；未知 → warn。"""
    v = snap.python_version
    if v is None or len(v) < 2:
        return CheckResult(
            id="python_version",
            level="warn",
            title="Python 版本未知",
            detail="无法探测当前 Python 版本。",
            fix_hint="请在终端运行 python --version 确认版本 >= 3.10。",
        )
    if (v[0], v[1]) < (3, 10):
        return CheckResult(
            id="python_version",
            level="error",
            title="Python 版本过低",
            detail=f"当前 Python {v[0]}.{v[1]}.{v[2] if len(v) > 2 else 0}，需要 3.10+。",
            fix_hint="升级到 Python 3.10 或更高版本后重试。",
        )
    if (v[0], v[1]) == (3, 10) and "tomli" in snap.missing_packages:
        return CheckResult(
            id="python_version",
            level="error",
            title="Python 3.10 缺少 tomli",
            detail="config/spaces.py 在 Python 3.10 下需要 tomli 解析 TOML 配置。",
            fix_hint="pip install tomli",
        )
    return None


def check_dependencies(snap: Snapshot) -> CheckResult | None:
    """missing_packages 非空 → error，列出包名。"""
    if snap.missing_packages:
        return CheckResult(
            id="dependencies",
            level="error",
            title="缺少依赖包",
            detail="缺失：" + "、".join(snap.missing_packages),
            fix_hint="在项目根目录执行 pip install -r requirements.txt",
        )
    return None


def check_env_file(snap: Snapshot) -> CheckResult | None:
    """.env 不存在 → error。"""
    if not snap.env_exists:
        return CheckResult(
            id="env_file",
            level="error",
            title="缺少 .env 配置文件",
            detail="项目根目录下没有 .env。",
            fix_hint="python -m deploy init 或 cp .env.example .env",
        )
    return None


def check_allowed_groups(snap: Snapshot) -> CheckResult | None:
    """ALLOWED_GROUPS 为空 → error。"""
    if not snap.allowed_groups:
        return CheckResult(
            id="allowed_groups",
            level="error",
            title="ALLOWED_GROUPS 为空",
            detail="症状是完全无反应——@ 机器人不会有任何回复（这是最难自查的错误）。",
            fix_hint="在 .env 里填写 ALLOWED_GROUPS=群号（多个用英文逗号分隔）。",
        )
    return None


def check_onebot_mode(snap: Snapshot) -> CheckResult | None:
    """连接方式 unknown → error。"""
    if snap.onebot_mode == "unknown":
        return CheckResult(
            id="onebot_mode",
            level="error",
            title="无法确定 OneBot 连接方式",
            detail="既没有配置正向 WS 地址，也没有可用的 HOST/PORT。",
            fix_hint="在 .env 顶部二选一：反向 WS 用 HOST/PORT（默认 0.0.0.0:8080），"
            "正向 WS 用 ONEBOT_V11_WS_URLS。参考 .env.example 顶部注释。",
        )
    return None


def check_onebot_reverse_port(snap: Snapshot) -> CheckResult | None:
    """仅反向 WS：端口被占 → warn；探测失败 → warn。"""
    if snap.onebot_mode != "reverse":
        return None
    if snap.onebot_port_in_use is True:
        return CheckResult(
            id="onebot_port",
            level="warn",
            title="反向 WS 端口可能被占用",
            detail=f"端口 {snap.onebot_port} 当前无法 bind。",
            fix_hint="若 Bot 正在运行，端口被自己占用属正常；"
            f"否则用 netstat -ano | findstr :{snap.onebot_port} 排查占用进程。",
        )
    if snap.onebot_port_in_use is None:
        return CheckResult(
            id="onebot_port",
            level="warn",
            title="无法探测反向 WS 端口",
            detail=f"探测端口 {snap.onebot_port} 占用情况失败。",
            fix_hint="可忽略；若 NapCat 连不上再检查端口是否被占用。",
        )
    return None


def check_onebot_forward(snap: Snapshot) -> CheckResult | None:
    """仅正向 WS：地址不可达 → error；探测失败 → warn。"""
    if snap.onebot_mode != "forward":
        return None
    if snap.onebot_forward_reachable is False:
        return CheckResult(
            id="onebot_forward",
            level="error",
            title="正向 WS 地址不可达",
            detail="TCP 连接 ONEBOT_V11_WS_URLS 失败。",
            fix_hint="确认 NapCat 已开启「WS 服务端」且监听地址、端口与配置一致。",
        )
    if snap.onebot_forward_reachable is None:
        return CheckResult(
            id="onebot_forward",
            level="warn",
            title="无法探测正向 WS 地址",
            detail="URL 解析失败，无法做 TCP 探测。",
            fix_hint="检查 .env 里 ONEBOT_V11_WS_URLS 是否为合法 ws:// 或 wss:// 地址。",
        )
    return None


def check_lm_studio_reachable(snap: Snapshot) -> CheckResult | None:
    """LM Studio 不可达 → error（带错误）；探测失败 → warn。"""
    if snap.lm_reachable is False:
        detail = f"错误：{snap.lm_error}" if snap.lm_error else "无法访问 /v1/models。"
        return CheckResult(
            id="lm_studio",
            level="error",
            title="LM Studio 不可达",
            detail=detail,
            fix_hint="启动 LM Studio 并打开 Local Server（默认 127.0.0.1:1234）。",
        )
    if snap.lm_reachable is None:
        return CheckResult(
            id="lm_studio",
            level="warn",
            title="无法探测 LM Studio",
            detail="探测 /v1/models 时发生未预期错误。",
            fix_hint="可先启动 Bot 观察日志；若模型相关功能异常再检查 LM Studio。",
        )
    return None


def _check_lm_model(
    snap: Snapshot,
    *,
    check_id: str,
    configured: str,
    env_key: str,
    level: str,
    fix_hint: str,
) -> CheckResult | None:
    """聊天/整合/提取三个模型检查的公共逻辑。"""
    if snap.lm_reachable is not True:
        return None
    if not configured:
        return CheckResult(
            id=check_id,
            level="warn",
            title="未配置模型 ID",
            detail=f"{env_key} 为空，将由服务端默认路由。",
            fix_hint="建议在 .env 里显式填写完整模型 ID。",
        )
    if configured not in snap.lm_models:
        return CheckResult(
            id=check_id,
            level=level,
            title="模型未加载",
            detail=f"配置的 {env_key}={configured} 不在 LM Studio 已加载列表。",
            fix_hint=fix_hint + " " + _suggest_model(configured, snap.lm_models),
        )
    return None


def check_lm_model_chat(snap: Snapshot) -> CheckResult | None:
    """聊天模型：不在已加载列表 → error + 模糊匹配建议。"""
    return _check_lm_model(
        snap,
        check_id="lm_model_chat",
        configured=snap.lm_model_chat,
        env_key="LM_STUDIO_MODEL",
        level="error",
        fix_hint="在 LM Studio 中加载该模型，或修正 LM_STUDIO_MODEL。",
    )


def check_lm_model_consolidation(snap: Snapshot) -> CheckResult | None:
    """整合模型：不在已加载列表 → error。"""
    return _check_lm_model(
        snap,
        check_id="lm_model_consolidation",
        configured=snap.lm_model_consolidation,
        env_key="CONSOLIDATION_LM_STUDIO_MODEL",
        level="error",
        fix_hint="在 LM Studio 中加载该模型，或修正 CONSOLIDATION_LM_STUDIO_MODEL；"
        "建议设 GPU Offload=0 走 CPU，与聊天模型并行。",
    )


def check_lm_model_extract(snap: Snapshot) -> CheckResult | None:
    """提取模型：不匹配 → warn（阶段 2 会静默回退阶段 1 候选）。"""
    return _check_lm_model(
        snap,
        check_id="lm_model_extract",
        configured=snap.lm_model_extract,
        env_key="MEMORY_EXTRACT_LM_STUDIO_MODEL",
        level="warn",
        fix_hint="提取模型默认继承聊天模型；不匹配时阶段 2 会静默回退阶段 1 候选，"
        "候选提取精度下降。请加载该模型或修正配置。",
    )


def check_lm_model_embedding(snap: Snapshot) -> CheckResult | None:
    """embedding：开关关 → None；ID 空或不在列表 → error。"""
    if not snap.embedding_enabled:
        return None
    if snap.lm_reachable is not True:
        return None
    if not snap.lm_model_embedding:
        return CheckResult(
            id="lm_model_embedding",
            level="error",
            title="未配置 embedding 模型",
            detail="MEMORY_EMBEDDING_MODEL 为空，但 MEMORY_EMBEDDING_ENABLED=true。",
            fix_hint="在 .env 里填写 MEMORY_EMBEDDING_MODEL（LM Studio 中加载的嵌入模型 ID）。",
        )
    if snap.lm_model_embedding not in snap.lm_models:
        return CheckResult(
            id="lm_model_embedding",
            level="error",
            title="embedding 模型未加载",
            detail=f"配置的 MEMORY_EMBEDDING_MODEL={snap.lm_model_embedding} "
            "不在 LM Studio 已加载列表。",
            fix_hint="在 LM Studio 中加载该嵌入模型，或修正配置。"
            " " + _suggest_model(snap.lm_model_embedding, snap.lm_models),
        )
    return None


def check_database_exists(snap: Snapshot) -> CheckResult | None:
    """数据库文件不存在 → warn（首次启动自动建库，不阻塞）。"""
    if not snap.db_exists:
        return CheckResult(
            id="db_exists",
            level="warn",
            title="数据库不存在",
            detail=f"{snap.db_path} 尚未创建（首次启动会自动建库）。",
            fix_hint="无需处理；启动后自动创建。若已有旧库请确认路径配置无误。",
        )
    return None


def check_database_writable(snap: Snapshot) -> CheckResult | None:
    """数据库不可写 → error；探测失败 → warn。"""
    if snap.db_writable is False:
        return CheckResult(
            id="db_writable",
            level="error",
            title="数据库不可写",
            detail=f"无法写入 {snap.db_path}（或其所在目录）。",
            fix_hint="检查目录写权限；若 DB 文件损坏，备份后删除让系统重建。",
        )
    if snap.db_writable is None:
        return CheckResult(
            id="db_writable",
            level="warn",
            title="无法确认数据库可写性",
            detail=f"探测 {snap.db_path} 写入权限失败。",
            fix_hint="可忽略；启动时若报写库错误再排查权限。",
        )
    return None


def check_schema_version(snap: Snapshot) -> CheckResult | None:
    """schema 不匹配 → error；无法读出版本 → warn。"""
    if snap.schema_version is None:
        return CheckResult(
            id="schema_version",
            level="warn",
            title="数据库版本未知",
            detail="无法读取数据库 schema 版本。",
            fix_hint="若功能正常可忽略；异常时删除旧库重建。",
        )
    if snap.schema_version != snap.code_schema_version:
        return CheckResult(
            id="schema_version",
            level="error",
            title="数据库 schema 版本不匹配",
            detail=f"数据库版本 {snap.schema_version}，代码需要 {snap.code_schema_version}。",
            fix_hint="通常升级版本后首次启动会自动迁移；若报迁移失败，"
            "备份数据库后联系维护者。",
        )
    return None


def check_legacy_group_id_tables(snap: Snapshot) -> CheckResult | None:
    """存在遗留 group_id 列的表 → warn（列早已废弃）。"""
    if snap.legacy_group_id_tables:
        return CheckResult(
            id="legacy_group_id_tables",
            level="warn",
            title="数据库含遗留 group_id 列",
            detail="这些表仍带已废弃的 group_id 列："
            + "、".join(snap.legacy_group_id_tables)
            + "。列已被淘汰，不再写入。",
            fix_hint="不影响运行；如需清理可在备份后手动删列。",
        )
    return None


def check_source_kind(snap: Snapshot) -> CheckResult | None:
    """group_messages 有数据但 source_kind 全是空字符串 → error。"""
    counts = snap.source_kind_counts or {}
    if not counts:
        return None
    total = sum(counts.values())
    empty = counts.get("", 0)
    if total > 0 and empty == total:
        return CheckResult(
            id="source_kind",
            level="error",
            title="历史记忆全部缺失来源类型",
            detail=f"group_messages 有 {total} 条记录，但 source_kind 全部为空。",
            fix_hint="运行迁移脚本 backfill_source_kind.py（见 migrations 目录）。",
        )
    return None


def check_spaces_conflicts(snap: Snapshot) -> CheckResult | None:
    """显式 toml 里同一群号分到多个空间 → error。"""
    if snap.space_conflicts:
        lines = [
            f"群 {c['group_id']} 同时出现在 {c['spaces'][0]} 与 {c['spaces'][1]}"
            for c in snap.space_conflicts
        ]
        return CheckResult(
            id="space_conflicts",
            level="error",
            title="群组空间配置冲突",
            detail="；".join(lines),
            fix_hint="每个群号只能属于一个空间，请修正 config/spaces/*.toml。",
        )
    return None


def check_space_assignment_mismatch(snap: Snapshot) -> CheckResult | None:
    """账本仍挂自动命名 space_N、而显式 toml 已改名 → warn。"""
    if snap.space_assignment_mismatch:
        lines = [
            f"群 {c['group_id']}：账本={c['ledger']}，显式={c['explicit']}"
            for c in snap.space_assignment_mismatch
        ]
        return CheckResult(
            id="space_assignment_mismatch",
            level="warn",
            title="群组空间分配与账本不一致",
            detail="；".join(lines),
            fix_hint="历史记忆仍挂在旧名空间下。可运行重分配脚本，"
            "或保留旧空间名以维持一致性。",
        )
    return None


def check_persona_file(snap: Snapshot) -> CheckResult | None:
    """人格文件不存在 → error；存在但为空 → warn。"""
    if not snap.persona_exists:
        return CheckResult(
            id="persona_file",
            level="error",
            title="人格文件缺失",
            detail="SYSTEM_PROMPT_PATH 指向的文件不存在。",
            fix_hint="创建该文件并写入人格设定，或修正 SYSTEM_PROMPT_PATH。",
        )
    if snap.persona_size <= 0:
        return CheckResult(
            id="persona_file",
            level="warn",
            title="人格文件为空",
            detail="SYSTEM_PROMPT_PATH 指向的文件大小为 0。",
            fix_hint="向文件写入人格设定内容。",
        )
    return None


def check_disk_space(snap: Snapshot) -> CheckResult | None:
    """磁盘剩余 < 500MB → error；< 2GB → warn；探测失败 → warn。"""
    if snap.disk_free_mb is None:
        return CheckResult(
            id="disk_space",
            level="warn",
            title="无法探测磁盘剩余空间",
            detail="查询数据库所在磁盘空间失败。",
            fix_hint="可忽略；若启动时出现磁盘写满错误再排查。",
        )
    if snap.disk_free_mb < 500:
        return CheckResult(
            id="disk_space",
            level="error",
            title="磁盘剩余空间不足",
            detail=f"剩余 {snap.disk_free_mb:.0f} MB，低于 500 MB。",
            fix_hint="清理磁盘空间（记忆与日志占用较大）。",
        )
    if snap.disk_free_mb < 2048:
        return CheckResult(
            id="disk_space",
            level="warn",
            title="磁盘剩余空间偏低",
            detail=f"剩余 {snap.disk_free_mb:.0f} MB，低于 2 GB。",
            fix_hint="留意记忆与日志增长，适时清理。",
        )
    return None


def check_db_cleanup_on_start(snap: Snapshot) -> CheckResult | None:
    """DB_CLEANUP_ON_START=true 但 DB 里已有记忆 → warn。"""
    if snap.db_cleanup_on_start and snap.db_exists:
        return CheckResult(
            id="db_cleanup",
            level="warn",
            title="启动时清库已开启",
            detail="DB_CLEANUP_ON_START=true，每次启动会清空数据库。",
            fix_hint="生产环境建议设为 false；若已积累记忆，请先备份再考虑关闭。",
        )
    return None


def check_deprecated_env_keys(
    snap: Snapshot,
) -> CheckResult | Sequence[CheckResult] | None:
    """废弃键存在 → warn；含密码类键时追加一条 secrets warn。"""
    keys = snap.deprecated_env_keys
    if not keys:
        return None
    secret_keys = [k for k in keys if "PASSWORD" in k.upper()]
    if len(keys) == 1 and secret_keys:
        return CheckResult(
            id="deprecated_env_secrets",
            level="warn",
            title="检测到已废弃的密码配置",
            detail=f"{secret_keys[0]} 已不再使用。",
            fix_hint="从 .env 删除；若它仍生效说明有旧进程在跑。",
        )
    return [
        CheckResult(
            id="deprecated_env_keys",
            level="warn",
            title="检测到已废弃的环境变量",
            detail="已废弃：" + "、".join(keys),
            fix_hint="从 .env 删除这些键；影响已在新方案中说明（见 README 迁移记录）。",
        ),
    ] + (
        [
            CheckResult(
                id="deprecated_env_secrets",
                level="warn",
                title="检测到已废弃的密码配置",
                detail="密码相关键：" + "、".join(secret_keys) + "。",
                fix_hint="从 .env 删除；若仍生效说明有旧进程在跑。",
            )
        ]
        if secret_keys
        else []
    )


_ALL_CHECKS: tuple[Callable[[Snapshot], CheckResult | Sequence[CheckResult] | None], ...] = (
    check_python_version,
    check_dependencies,
    check_env_file,
    check_allowed_groups,
    check_onebot_mode,
    check_onebot_reverse_port,
    check_onebot_forward,
    check_lm_studio_reachable,
    check_lm_model_chat,
    check_lm_model_consolidation,
    check_lm_model_extract,
    check_lm_model_embedding,
    check_database_exists,
    check_database_writable,
    check_schema_version,
    check_legacy_group_id_tables,
    check_source_kind,
    check_spaces_conflicts,
    check_space_assignment_mismatch,
    check_persona_file,
    check_disk_space,
    check_db_cleanup_on_start,
    check_deprecated_env_keys,
)


def run_all(snapshot: Snapshot) -> list[CheckResult]:
    """跑全部检查，按 error→warn→ok 排序（同级保持稳定顺序）。"""
    results: list[CheckResult] = []
    for check in _ALL_CHECKS:
        out = check(snapshot)
        if out is None:
            continue
        if isinstance(out, CheckResult):
            results.append(out)
        else:
            results.extend(out)
    order = {"error": 0, "warn": 1, "ok": 2}
    results.sort(key=lambda r: order.get(r.level, 3))
    return results
