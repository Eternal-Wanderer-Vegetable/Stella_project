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
from pathlib import Path

from config import state

from . import env_keys
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
    """仅反向 WS：端口被占 → warn；探测失败 → warn。

    Bot 自己在运行时端口必然被占用，这是最常见的情况——把它报成警告会
    误导用户去排查一个不存在的问题（2026-08-19 反馈）。状态接口可达即可
    确认占用者是 Stella 自己：接口挂在同一个 HTTP 服务器上，能连上就说明
    监听者就是它。
    """
    if snap.onebot_mode != "reverse":
        return None
    # 端口被自己占用：正常状态，不报告
    if snap.status_api_reachable:
        return None
    if snap.onebot_port_in_use is True:
        return CheckResult(
            id="onebot_port",
            level="warn",
            title="反向 WS 端口被其他程序占用",
            detail=f"端口 {snap.onebot_port} 无法 bind，且 Stella 的状态接口不可达"
            "——说明占用者不是 Stella 自己。",
            fix_hint=f"用 netstat -ano | findstr :{snap.onebot_port} 找出占用进程，"
            "或在 .env 里改 PORT（改后记得同步修改 NapCat 侧的 WS 客户端地址）。",
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
    """聊天模型：不在已加载列表 → error + 模糊匹配建议。切在线后跳过。"""
    if _role_is_online(snap, "chat"):
        return None
    return _check_lm_model(
        snap,
        check_id="lm_model_chat",
        configured=snap.lm_model_chat,
        env_key="LM_STUDIO_MODEL",
        level="error",
        fix_hint="在 LM Studio 中加载该模型，或修正 LM_STUDIO_MODEL。",
    )


def check_lm_model_consolidation(snap: Snapshot) -> CheckResult | None:
    """整合模型：不在已加载列表 → error。切在线后跳过。"""
    if _role_is_online(snap, "consolidation"):
        return None
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
    if not snap.lm_model_extract or _role_is_online(snap, "extract"):
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
    """embedding：开关关 → None；ID 空或不在列表 → error。

    「已加载列表」来自 ``LM_STUDIO_BASE_URL``，所以 embedding 被指到另一个地址时
    这个比对不成立，直接跳过——那种配置的可用性由 check_embedding_locality 与
    实际调用负责，拿别的实例的模型列表去判「未加载」只会误报。
    """
    if not snap.embedding_enabled:
        return None
    if snap.lm_reachable is not True:
        return None
    if snap.embedding_base_url.strip().rstrip("/") != snap.lm_base_url.strip().rstrip("/"):
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
    """含遗留 group_id 列 → warn（启动时会自动迁移，但迁移前不该跑业务）。

    2026-08-27 之前这里是 error，修复提示是「把 db 移出去让程序重建」——等于让存量
    用户丢掉全部记忆。现在 v5 → 最新版全自动（`memory/migrations.py`），所以降级为
    warn：告诉用户会自动迁移、以及怎样先看预览。
    """
    if snap.legacy_group_id_tables:
        return CheckResult(
            id="legacy_group_id_tables",
            level="warn",
            title="数据库是 v8 之前的旧结构，将自动迁移",
            detail=(
                "这些表仍使用旧的 group_id 列："
                + "、".join(snap.legacy_group_id_tables)
                + "。v8 起记忆按 group_shared_space（共享空间）归属，"
                "启动时会自动完成列改名与值重写（并在迁移前备份为 "
                "agent_memory.db.pre-vN-<时间戳>.bak）。"
                "迁移完成前不要让 Bot 处理消息——旧结构下记忆读写会抛 "
                "no such column 并被静默吞掉，表现为「机器人一切正常但什么都不记」"
                "（2026-08-17 实测）。"
            ),
            fix_hint=(
                "想先看预览：python -m deploy migrate --dry-run"
                "（在 agent_memory.db 的副本上真跑一遍并出报告，不动原库）；"
                "直接升级：启动 Stella 即自动迁移，或运行 python -m deploy migrate。"
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


def _is_inside(child: str, parent: str) -> bool:
    """``child`` 是否在 ``parent`` 目录之内（纯字符串路径比较，不碰磁盘）。

    doctor 的所有检查都只读 Snapshot、不做 IO——这样它们在测试里可以用构造的快照
    穷举每个分支，也不会因为某个路径此刻不存在而给出不同结论。
    """
    if not child or not parent:
        return False
    try:
        return Path(parent).resolve() in Path(child).resolve().parents
    except (OSError, ValueError):
        return False


def check_stella_home(snap: Snapshot) -> CheckResult | None:
    """用户数据目录的位置与可发现性。

    数据目录搬出安装目录之后，「我的记忆库在哪」必须能一眼看到——用户要备份、要
    排查、要确认升级有没有接上老数据。而更要紧的是**可发现性**：新解压的程序靠机器级
    指针文件找到数据目录，指针没了就只能靠环境变量或手工指定，「升级只需一步」当场失效。
    """
    if not snap.stella_home:
        return None
    if snap.stella_home == snap.program_root:
        return CheckResult(
            id="stella_home",
            level="ok",
            title="用户数据在安装目录内（旧布局）",
            detail=(
                f"数据目录：{snap.stella_home}（{snap.stella_home_source}）。"
                "升级到新目录时用 python -m deploy migrate 把数据带过去。"
            ),
        )
    if _is_inside(snap.stella_home, snap.program_root):
        # 便携模式：用户显式在程序目录里建了 StellaData。这不是错误配置，但代价必须说清楚
        # ——程序目录是升级时被整体替换、也会被当作「旧版本」删掉的那个。这里刻意**不**
        # 提指针文件：便携副本绝不该去改写机器级指针，那会让它劫持本机的正常安装。
        return CheckResult(
            id="stella_home",
            level="ok",
            title="用户数据在程序目录内（便携模式）",
            detail=(
                f"数据目录：{snap.stella_home}（{snap.stella_home_source}）。"
                "整个目录可以拷走，但它会跟着程序目录一起被替换或删除。"
            ),
            fix_hint=(
                "升级前先用 python -m deploy migrate 把数据导入新版本，或手工备份该目录；"
                "不想要这个行为就删掉它，程序会改用程序目录同级的 StellaData。"
            ),
        )
    if not snap.home_pointer_exists:
        return CheckResult(
            id="stella_home",
            level="warn",
            title="用户数据目录缺少指针文件",
            detail=(
                f"数据目录：{snap.stella_home}（{snap.stella_home_source}），"
                "但机器级指针文件不存在。下次把新版本解压到别处时，程序将找不到这份数据。"
            ),
            fix_hint="运行 python -m deploy init 或 python -m deploy migrate 会重写指针文件。",
        )
    return CheckResult(
        id="stella_home",
        level="ok",
        title="用户数据目录已与程序分离",
        detail=(
            f"数据目录：{snap.stella_home}（{snap.stella_home_source}）；"
            f"程序目录：{snap.program_root}。升级时只替换程序目录即可。"
        ),
    )


def check_version_marks(snap: Snapshot) -> CheckResult | None:
    """版本标记：这份数据上次是被哪个版本跑过的。

    只看当前版本号看不出「用户刚换了包」——那个事实只存在于「上次运行版本」与
    「当前版本」的差值里（见 ``config/state.py``）。doctor 把它显示出来，是为了让
    两类静默故障变得可见：

    - **降级**：新版本写过的库被旧代码打开（schema 更高、列更多），表现为莫名其妙的
      报错，用户完全不会想到是自己解压错了目录；
    - **数据没接上**：解压新版后 doctor 显示「首次运行」，就说明这份数据目录是全新的，
      老记忆还留在旧目录里，此时应该去跑 ``deploy migrate`` 而不是直接开聊。
    """
    if snap.state_file_error:
        return CheckResult(
            id="version_marks",
            level="warn",
            title="版本标记读取失败",
            detail=snap.state_file_error,
            fix_hint=(
                "不影响运行，但升级判定会失效。删除 STELLA_HOME/.stella-state.json "
                "后重新启动一次即可重建。"
            ),
        )
    if not snap.program_version:
        return None
    if snap.version_transition == state.DOWNGRADE:
        return CheckResult(
            id="version_marks",
            level="warn",
            title="当前版本低于上次运行的版本",
            detail=(
                f"这份数据上次由 v{snap.last_run_version} 运行，当前程序是 "
                f"v{snap.program_version}。数据可能已被新版本改写（schema 更高），"
                "旧代码读它可能报错或行为异常。"
            ),
            fix_hint=f"改用 v{snap.last_run_version} 或更新的程序目录启动。",
        )
    if snap.version_transition == state.FIRST_RUN:
        return CheckResult(
            id="version_marks",
            level="ok",
            title=f"首次在此数据目录运行（v{snap.program_version}）",
            detail=(
                "这份数据目录还没有被任何版本跑过。若你是从旧版本升级过来的，"
                "老数据还留在旧目录里。"
            ),
            fix_hint="有旧安装目录的话，运行 python -m deploy migrate 把数据导入过来。",
        )
    if snap.version_transition == state.UPGRADE:
        return CheckResult(
            id="version_marks",
            level="ok",
            title=f"已从 v{snap.last_run_version} 升级到 v{snap.program_version}",
            detail="数据目录已接上，schema 迁移会在启动时自动完成。",
        )
    return CheckResult(
        id="version_marks",
        level="ok",
        title=f"版本未变（v{snap.program_version}）",
        detail=f"数据目录：上次运行版本 v{snap.last_run_version or snap.program_version}。",
    )


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


def check_render_backend(snap: Snapshot) -> CheckResult | None:
    """渲染后端缺失 → warn（不是 error：只影响卡片类插件，主链路照常）。

    这条检查存在的理由是**降级是静默的**：插件收不到图就发纯文本，用户只会觉得
    「这插件的图怎么没了」，不会想到是浏览器没装。2026-08-25 之前 html_render 干脆
    没实现，实测每次都回「渲染图片失败了」+ 纯文本，查了很久才定位到兼容层。
    """
    if not snap.render_enabled:
        return None
    if not snap.playwright_installed:
        return CheckResult(
            id="render_backend",
            level="warn",
            title="未安装 playwright，插件卡片无法出图",
            detail=(
                "依赖 Star.html_render 的插件（B 站卡片、动态推送等）会降级为纯文本。"
                "主链路对话不受影响。"
            ),
            fix_hint="pip install -r requirements.txt（playwright 已在其中）",
        )
    if snap.chromium_installed is False:
        return CheckResult(
            id="render_backend",
            level="warn",
            title="Chromium 内核未下载，插件卡片暂时无法出图",
            detail=(
                "playwright 已装但缺浏览器内核（headless shell 约 270MB）。RENDER_AUTO_INSTALL=true 时"
                "首次需要渲染会自动后台下载，期间照常降级为纯文本。"
            ),
            fix_hint="想立刻装好：python -m playwright install chromium-headless-shell",
        )
    if snap.chromium_installed is None:
        return CheckResult(
            id="render_backend",
            level="warn",
            title="无法确认 Chromium 内核是否已下载",
            detail="按浏览器缓存目录启发式判断，本机取不到该目录。渲染本身失败即降级，不影响主链路。",
            fix_hint="不确定时直接跑一次：python -m playwright install chromium-headless-shell（已装则秒退）",
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


def _role_kind(snap: Snapshot, role: str) -> str:
    """角色绑定的端点是本地还是在线（``local`` / ``online``；空串 = 没绑上）。"""
    return str((snap.llm_roles.get(role) or {}).get("kind") or "")


def _role_is_online(snap: Snapshot, role: str) -> bool:
    """角色是否已切到在线端点。

    三条旧的 LM Studio 模型检查（聊天 / 整合 / 提取）读的是 ``LM_STUDIO_MODEL``
    那一族旧键，只有在该角色仍走本地时才成立。角色切到在线之后，那些键的值
    不再被使用，还拿「LM Studio 里没加载这个模型」去报错就是纯噪音——真正该
    检查的是在线端点那边的模型 ID，由 :func:`check_llm_role_model` 负责。
    """
    return _role_kind(snap, role) == "online"


def check_llm_config_issues(
    snap: Snapshot,
) -> CheckResult | Sequence[CheckResult] | None:
    """把 ``registry.validate()` 的结论原样搬进 doctor（error / warn 各汇总一条）。

    doctor **不自己再判一遍**端点/角色配置：解析规则只该有一份，
    重写必然漂移，到时候 doctor 说没问题而 Bot 起不来，比没有 doctor 更糟。
    一个级别合成一条而不是一条条列：同一个 .env 写错时往往一次冒出好几条，
    27 项检查里塞进十几条同类结论，用户就再也看不到别的问题了。
    """
    if not snap.llm_issues:
        return None
    specs = (
        ("error", "llm_config", "端点 / 角色配置有错"),
        ("warn", "llm_config_warn", "端点 / 角色配置有隐患"),
    )
    results: list[CheckResult] = []
    for level, check_id, title in specs:
        msgs = [
            str(issue.get("message") or "")
            for issue in snap.llm_issues
            if str(issue.get("level") or "") == level
        ]
        msgs = [m for m in msgs if m]
        if not msgs:
            continue
        results.append(
            CheckResult(
                id=check_id,
                level=level,
                title=title,
                detail="；".join(msgs),
                fix_hint="按上面每条的说明改 .env 里的 LLM_ENDPOINT_* / LLM_ROLE_* "
                "然后重启（配置在进程启动时解析一次，改完必须重启才生效）。",
            )
        )
    return results or None


def check_llm_endpoint_reachable(
    snap: Snapshot,
) -> CheckResult | Sequence[CheckResult] | None:
    """逐槽报「地址不通」：本地 → error，在线 → warn。

    在线端点刻意只到 warn：``/v1/models`` 是可选接口，不少服务商压根不开放、
    或者要另一种鉴权，探不到并不代表 chat 调用不通。为一条探测失败拦住一个
    其实能用的部署，比漏报更糟。

    与 :func:`check_lm_studio_reachable` 同地址的槽跳过——那是同一个服务没起来，
    说两遍只会让用户以为有两个问题。
    """
    results: list[CheckResult] = []
    for slot, ep in snap.llm_endpoints.items():
        base = str(ep.get("base_url") or "").strip()
        if not base or snap.llm_endpoint_reachable.get(slot) is not False:
            continue  # 没启用、探通了、或没探（None）都不报
        if base.rstrip("/") == snap.lm_base_url.rstrip("/"):
            continue
        local = str(ep.get("kind") or "") == "local"
        err = snap.llm_endpoint_error.get(slot, "")
        detail = f"{base} 的 /v1/models 请求失败。" + (f"错误：{err}" if err else "")
        results.append(
            CheckResult(
                id=f"llm_endpoint_{slot.lower()}",
                level="error" if local else "warn",
                title=f"端点 {slot} 不可达",
                detail=detail,
                fix_hint=(
                    f"确认该本地服务已启动，或修正 LLM_ENDPOINT_{slot}_BASE_URL。"
                    if local
                    else f"确认 LLM_ENDPOINT_{slot}_BASE_URL 与 API_KEY 正确、网络可达。"
                    "若该服务商本就不开放 /v1/models，本条可以忽略——"
                    "真正的验证是发一次对话。"
                ),
            )
        )
    return results or None


def check_llm_role_model(
    snap: Snapshot,
) -> CheckResult | Sequence[CheckResult] | None:
    """在线角色的模型 ID 不在该端点列出的模型里 → warn。

    只到 warn 且只在拿到了模型列表时才报：``/v1/models`` 未必列全（有的服务商
    只列你已开通的、有的按套餐过滤），据此判 error 会误伤能用的配置。
    模型 ID 为空的情况不在这里报——``registry.validate()` 已经把它记成 error 了，
    再报一条是同一个根因说两遍。
    """
    results: list[CheckResult] = []
    for role, binding in snap.llm_roles.items():
        if str(binding.get("kind") or "") != "online":
            continue
        model = str(binding.get("model") or "").strip()
        slot = str(binding.get("slot") or "")
        listed = snap.llm_endpoint_models.get(slot) or []
        if not model or not listed or model in listed:
            continue
        results.append(
            CheckResult(
                id=f"llm_role_model_{role}",
                level="warn",
                title=f"角色 {role} 的模型 ID 可能写错了",
                detail=f"LLM_ROLE_{role.upper()}_MODEL={model} 不在端点 {slot} "
                f"列出的模型里。{_suggest_model(model, listed)}",
                fix_hint=f"核对服务商文档里的模型 ID 并修正 LLM_ROLE_{role.upper()}_MODEL；"
                "若该服务商的 /v1/models 本就不列全，本条可以忽略。",
            )
        )
    return results or None


def check_embedding_locality(snap: Snapshot) -> CheckResult | None:
    """R2：embedding 恒定本地。地址指到在线端点 → warn。

    这不只是省钱：语义检索会把**用户的原始提问**逐条发出去，而且量远大于对话
    （每次检索都要算一次向量）。切端点的人往往只想换对话模型，顺手把 embedding
    也指过去时不会意识到这一层。
    """
    if not snap.embedding_enabled:
        return None
    embed = snap.embedding_base_url.strip().rstrip("/")
    if not embed:
        return None
    for slot, ep in snap.llm_endpoints.items():
        if str(ep.get("kind") or "") != "online":
            continue
        if str(ep.get("base_url") or "").strip().rstrip("/") != embed:
            continue
        return CheckResult(
            id="embedding_locality",
            level="warn",
            title="embedding 指向了在线端点",
            detail=f"MEMORY_EMBEDDING_BASE_URL={snap.embedding_base_url} "
            f"与在线端点槽 {slot} 是同一个地址。",
            fix_hint="按设计 embedding 应恒定本地：把 MEMORY_EMBEDDING_BASE_URL 改回"
            "本机地址（默认 http://127.0.0.1:1234）。确实想用在线向量服务时"
            "请注意每次语义检索都会把提问原文发给该服务商。",
        )
    return None


def check_superseded_env_keys(snap: Snapshot) -> CheckResult | None:
    """.env 里仍留着已被新键取代的键 → warn，并点名新键。

    与 :func:`check_deprecated_env_keys` 分开报：废弃键是「代码已经不读了，删掉即可」，
    而这些键**代码还在读**，留着不会立刻出错，但它和新键说的是同一件事，
    以后改新键会出现「改了没反应」。``deploy migrate`` 会自动换算，
    手工升级的用户则需要这条提示。
    """
    keys = snap.superseded_env_keys
    if not keys:
        return None
    pairs = [f"{key} → {env_keys.superseded_by(key) or '新键'}" for key in keys]
    return CheckResult(
        id="superseded_env_keys",
        level="warn",
        title="检测到已被新键取代的环境变量",
        detail="、".join(pairs),
        fix_hint="改用箭头右侧的新键后删掉旧键；或直接跑 deploy migrate，"
        "它会把旧键的值自动换算过去。",
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
    check_at_mention_health,
    check_spaces_conflicts,
    check_space_assignment_mismatch,
    check_persona_file,
    check_stella_home,
    check_version_marks,
    check_disk_space,
    check_db_cleanup_on_start,
    check_render_backend,
    check_deprecated_env_keys,
    check_superseded_env_keys,
    check_llm_config_issues,
    check_llm_endpoint_reachable,
    check_llm_role_model,
    check_embedding_locality,
)


def total_checks() -> int:
    """检查项总数。report 层用它推算通过数：
    检查通过时返回 None（不产生 CheckResult），因此「通过了多少项」
    无法从结果列表反推，必须由这里提供分母。"""
    return len(_ALL_CHECKS)


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
