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
            "正向 WS 用 ONEBOT_WS_URLS。参考 .env.example 顶部注释。",
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
            detail="TCP 连接 ONEBOT_WS_URLS 失败。",
            fix_hint="确认 NapCat 已开启「WS 服务端」且监听地址、端口与配置一致。",
        )
    if snap.onebot_forward_reachable is None:
        return CheckResult(
            id="onebot_forward",
            level="warn",
            title="无法探测正向 WS 地址",
            detail="URL 解析失败，无法做 TCP 探测。",
            fix_hint="检查 .env 里 ONEBOT_WS_URLS 是否为合法 ws:// 或 wss:// 地址。",
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
            title=f"未配置模型 ID（{env_key}）",
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
    """提取模型：不匹配 → warn（阶段 2 会静默回退阶段 1 候选）。

    为空时不报告：MEMORY_EXTRACT_LM_STUDIO_MODEL 默认继承 LM_STUDIO_MODEL，
    因此它为空只可能是聊天模型也为空——那已由 check_lm_model_chat 报出，
    再报一条是把同一个根因说两遍（不级联原则，与 lm_reachable 为假时
    跳过全部模型检查同理）。
    """
    if not snap.lm_model_extract:
        return None
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
    """数据库不存在时不报告——首次启动会自动建库，这是 100% 新用户的正常状态。

    一个对所有正确用法都会触发的警告，定义上就是噪音。真正的风险（目录不可写、
    路径配错）由 check_database_writable 覆盖：那一项会在无法创建 DB 时报 error。

    保留空实现而非删除函数：id 为 db_exists 的结果曾出现在输出里，
    GUI 侧可能已按它做过映射；留个函数体也便于将来需要时恢复判据。
    """
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
    """schema 版本不匹配 → error；DB 不存在 → 跳过（由 check_database_exists 负责）。"""
    # DB 还没建立时「版本未知」是必然的，不该再报一次——同一件事报两次
    # 会让首次配置的用户以为出了两个问题。
    if not snap.db_exists:
        return None
    if snap.schema_version is None:
        return CheckResult(
            id="schema_version",
            level="warn",
            title="数据库版本未知",
            detail="无法读取数据库 schema 版本。",
            fix_hint="若功能正常可忽略；异常时删除旧库重建。",
        )
    if snap.schema_version < snap.code_schema_version:
        return CheckResult(
            id="schema_version",
            level="warn",
            title="数据库版本偏低，启动时自动迁移",
            detail=(
                f"数据库版本 {snap.schema_version}，代码需要 "
                f"{snap.code_schema_version}。"
            ),
            fix_hint=(
                "Additive Migration（只加字段不删数据），首次迁移前自动备份，"
                "无需手动处理。"
            ),
        )
    if snap.schema_version > snap.code_schema_version:
        return CheckResult(
            id="schema_version",
            level="error",
            title="数据库版本比代码新",
            detail=(
                f"数据库版本 {snap.schema_version}，代码只支持 "
                f"{snap.code_schema_version}。"
            ),
            fix_hint="数据库比代码新，说明代码需要升级；用旧代码跑新库可能读不到新字段。",
        )
    return None


def check_legacy_group_id_tables(snap: Snapshot) -> CheckResult | None:
    """含遗留 group_id 列 → error（v8 之前的旧库，记忆读写会静默失败）。"""
    if snap.legacy_group_id_tables:
        return CheckResult(
            id="legacy_group_id_tables",
            level="error",
            title="数据库为 v8 之前的旧结构",
            detail=(
                "这些表仍使用已废弃的 group_id 列："
                + "、".join(snap.legacy_group_id_tables)
                + "。v8 起记忆按 group_shared_space 归属，"
                "旧结构会让全部记忆读写抛 no such column 并被静默吞掉——"
                "表现为「机器人一切正常但什么都不记」（2026-08-17 实测）。"
            ),
            fix_hint=(
                "v8 不做自动迁移。请停止程序，把 memory/agent_memory.db "
                "与 memory/stella_memory_backup.db 一起移出（两个都要，"
                "留着备份会让下次迁移跳过备份），重启后程序会建立 v8 新库。"
            ),
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
            fix_hint=(
                "历史数据从未写入 source_kind；若需修复可手动 "
                "UPDATE group_messages SET source_kind=... 补齐，或清库重建。"
            ),
        )
    return None


def check_at_mention_health(snap: Snapshot) -> CheckResult | None:
    """AT_MENTION 为 0 而 BOT_SELF > 0 → warn。

    这是「@ 消息未入库」唯一能自动发现的信号。2026-08-17 实测：落库监听器
    priority 排在 chat_handler(block=True) 之后时，@ 消息被拦截而永不入库——
    普通群聊正常记录，唯独最有价值的 @ 对话全部丢失，13 批整合共 270 条消息
    的 AT_MENTION 计数全为 0。这个错误不抛异常、不影响回复，只让记忆系统
    静默地学不到东西。
    """
    counts = snap.source_kind_counts or {}
    if not counts:
        return None
    if counts.get("AT_MENTION", 0) == 0 and counts.get("BOT_SELF", 0) > 0:
        return CheckResult(
            id="at_mention_health",
            level="warn",
            title="没有任何 AT_MENTION 消息记录",
            detail=(
                f"BOT_SELF={counts.get('BOT_SELF', 0)} 条但 AT_MENTION=0 条。"
                "Bot 在说话却没有任何「用户对它说」的记录，@ 消息可能未入库。"
            ),
            fix_hint=(
                "检查 ai_gateway.py 中 group_silent_listener 的 priority 是否为 0 "
                "且小于所有 block=True 的处理器；启动日志里的优先级自检会报这个问题。"
            ),
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
    """人格文件缺失或为空 → warn（与 ai_gateway 行为一致：warning + 继续运行）。"""
    if not snap.persona_exists:
        return CheckResult(
            id="persona_file",
            level="warn",
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
    """废弃键存在 → 通用 warn；含密码类键时再追加一条 secrets warn。

    结构统一为「总是返回通用条 + 有密码时追加 secrets 条」，两个分支
    行为一致，测试也好写。
    """
    keys = snap.deprecated_env_keys
    if not keys:
        return None
    secret_keys = [k for k in keys if "PASSWORD" in k.upper()]
    results: list[CheckResult] = [
        CheckResult(
            id="deprecated_env_keys",
            level="warn",
            title="检测到已废弃的环境变量",
            detail="已废弃：" + "、".join(keys),
            fix_hint=(
                "从 .env 删除这些键；影响已在新方案中说明"
                "（见 design_docs/deprecated_napcat_manager.md）。"
            ),
        )
    ]
    if secret_keys:
        results.append(
            CheckResult(
                id="deprecated_env_secrets",
                level="warn",
                title="检测到已废弃的密码配置",
                detail="密码相关键：" + "、".join(secret_keys) + "。",
                fix_hint="从 .env 删除；若仍生效说明有旧进程在跑。",
            )
        )
    return results


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
    check_at_mention_health,
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
