# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""内部流程登记处（计划 §6.2 入口发现 / §6.5 流程族 / §6.3–§6.4 语义根）。

与 :mod:`core.observability.flow_catalog` 的分工：flow_catalog 是**画布
语义节点**（稳定 node_id、泳道、静态边）；本文件回答三个完整性问题——

1. **声明运行入口**（RUNTIME_ENTRY_INVENTORY）：当前构建里有哪些可能的
   运行 root，各自源码锚点与流程族归属。入口发现器新增入口必须归到
   流程族，不得因没有人工列举而静默遗漏（计划 §1）。
2. **流程族**（PROCESS_FAMILIES）：消息/Turn、整合与记忆、主动决策、
   回复效果与社交、后台维护、预约任务、知识导入、Cometa、生命周期。
3. **覆盖分母**（coverage_denominators）：目录完整度 / 运行观测完整度 /
   数据集覆盖度各自分母，任何一项不能冒充其他两项（计划 §1）。

边界归类：``boundary`` 标记显式外部/动态边界（NoneBot dispatch、
Rust 桥接、第三方 SDK），UNKNOWN 不得自动豁免（计划 §6.2 第 4 点）。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RuntimeEntry:
    """一个声明运行入口：身份、源码锚点、流程族与边界说明。"""

    entry_id: str
    family: str
    root_kind: str  # message_traces.root_kind；"" 表示尚未接入 flow root
    source: tuple[str, str]  # (file, qualified symbol)
    origin: str  # message | timer | worker | spawn | startup | api
    notes: str = ""
    boundary: str = ""  # 非空 = 显式边界（动态 dispatch / 跨语言 / 第三方）


@dataclass(frozen=True)
class ProcessFamily:
    """流程族：入口集合 + 覆盖分母键。"""

    family_id: str
    label: str
    description: str
    milestone: str  # 落地里程碑（M0..M6），诚实标注当前状态


PROCESS_FAMILIES: dict[str, ProcessFamily] = {
    fam.family_id: fam
    for fam in [
        ProcessFamily("message", "消息与轮次", "接入分流→闸门→Turn→生成→发送", "M1"),
        ProcessFamily("memory", "整合与记忆", "抽取→候选→晋升→维护→检索→验证", "M2"),
        ProcessFamily("proactive", "主动决策与发言", "参与评分→timer/主动@/群插话→效果", "M3"),
        ProcessFamily("social", "回复效果与社交", "效果窗口→社交 worker→证据", "M4"),
        ProcessFamily("maintenance", "后台维护", "idle/backlog/清理/压缩", "M4"),
        ProcessFamily("scheduling", "预约任务", "租约→到期→执行→投递", "M4"),
        ProcessFamily("knowledge", "知识导入与索引", "解析→版本→分块→索引", "M4"),
        ProcessFamily("cometa", "Cometa 任务", "受理→认领→执行→通知", "M1"),
        ProcessFamily("lifecycle", "启动关闭与观测健康", "注册/worker 启停/flush/loss", "M4"),
    ]
}


# ---- 声明运行入口（计划 §6.2 第 1 点：入口 inventory）----
# 锚点全部经源码核验（HEAD 4b089b5）；新增入口必须登记到这里并归类。
RUNTIME_ENTRY_INVENTORY: tuple[RuntimeEntry, ...] = tuple([
    # 消息/Turn（M1 已接入 flow root）
    RuntimeEntry("gateway.record_group_chat", "message", "qq_passive",
                 ("stella_project/plugins/bot_main/ai_gateway.py", "record_group_chat"),
                 "message", "每条群消息最早处理点（pre/postprocessor 链）"),
    RuntimeEntry("gateway.handle_chat", "message", "qq_chat",
                 ("stella_project/plugins/bot_main/ai_gateway.py", "handle_chat"),
                 "message", "@ 对话主链（root 缺失时兜底）"),
    RuntimeEntry("gateway.handle_command", "message", "qq_command",
                 ("stella_project/plugins/bot_main/ai_gateway.py", "handle_chat"),
                 "message", "slash 命令分流"),
    RuntimeEntry("webui.chat_ingress", "message", "webchat",
                 ("webui/chat_ingress.py", "run_turn"),
                 "message", "WebChat 轮次"),
    # 主动决策（M3）
    RuntimeEntry("gateway.proactive_speak_job", "proactive", "proactive_timer",
                 ("stella_project/plugins/bot_main/ai_gateway.py", "proactive_speak_job"),
                 "timer", "APScheduler interval；群循环/主动@/群插话"),
    RuntimeEntry("gateway.proactive_at_user", "proactive", "proactive_at",
                 ("stella_project/plugins/bot_main/ai_gateway.py", "_proactive_at_user"),
                 "spawn", "周期任务里的主动 @ 验证路径"),
    RuntimeEntry("gateway.proactive_speak_for_group", "proactive", "proactive",
                 ("stella_project/plugins/bot_main/ai_gateway.py", "_proactive_speak_for_group"),
                 "spawn", "参与度 ALLOW 派生的群插话"),
    # 记忆（M2）
    RuntimeEntry("consolidator.consolidate_group", "memory", "memory_consolidate",
                 ("memory/consolidator.py", "MemoryConsolidator.consolidate_group"),
                 "spawn", "整合批次（按群锁；消费消息窗口）"),
    RuntimeEntry("memory.process_new_candidates", "memory", "memory_promotion",
                 ("memory/memory_manager.py", "MemoryManager.process_new_candidates"),
                 "spawn", "晋升批处理（backend/逐候选 gate/事务）"),
    RuntimeEntry("compressor.run_weekly", "memory", "memory_maintenance",
                 ("memory/compressor.py", "MemoryCompressor.run_weekly"),
                 "timer", "周度维护（压缩/去重/衰减）"),
    # 效果与社交（M4）
    RuntimeEntry("social.run_due_jobs", "social", "social_worker",
                 ("memory/social_worker.py", "run_due_jobs"),
                 "worker", "租约→handler→done/retry/dead"),
    RuntimeEntry("reply_effect.resolve", "social", "effect",
                 ("memory/reply_effect_service.py", "resolve_effect"),
                 "worker", "回复窗口结算"),
    # 后台维护（M4）
    RuntimeEntry("session_compact.compact_once", "maintenance", "compact",
                 ("memory/session_compact.py", "compact_once"),
                 "spawn", "回复后压缩"),
    RuntimeEntry("gateway.idle_maintenance", "maintenance", "",
                 ("stella_project/plugins/bot_main/ai_gateway.py", "_proactive_speak_impl"),
                 "timer", "idle/backlog/清理 sweep（锚点：gateway 后台任务区）",
                 boundary="noop/清理路径尚未逐一接入 flow root"),
    # 预约调度（M4）
    RuntimeEntry("scheduling.tick_once", "scheduling", "scheduled_task",
                 ("stella_project/plugins/bot_main/scheduling/runtime.py", "tick_once"),
                 "worker", "租约/恢复/到期/执行/投递"),
    # 知识导入（M4）
    RuntimeEntry("knowledge.ingest_content", "knowledge", "knowledge_ingest",
                 ("knowledge/ingest.py", "ingest_content"),
                 "api", "导入→解析→版本→分块→索引"),
    # Cometa（M1 已有 task/attempt 协议）
    RuntimeEntry("cometa.worker.tick", "cometa", "cometa_task",
                 ("cometa/worker.py", "CometaWorker._tick"),
                 "worker", "认领→执行→结果→通知"),
    # 启动关闭（M4）
    RuntimeEntry("bot_main.startup", "lifecycle", "",
                 ("stella_project/plugins/bot_main/ai_gateway.py", "record_group_chat"),
                 "startup", "on-startup 钩子注册 worker/调度器",
                 boundary="NoneBot driver 生命周期，未接入独立 root"),
    # 显式边界（UNKNOWN 不豁免，计划 §6.2 第 4 点）
    RuntimeEntry("nonebot.matcher_dispatch", "message", "",
                 ("stella_project/plugins/bot_main/ai_gateway.py", "record_group_chat"),
                 "message", "NoneBot 动态 matcher 派发不可静态展开",
                 boundary="nonebot"),
    RuntimeEntry("rust.promotion", "memory", "",
                 ("memory_rust/native/src/promotion.rs", "promote"),
                 "spawn", "Rust 晋升事务（跨语言边界）",
                 boundary="rust"),
])


def entries_for_family(family: str) -> list[RuntimeEntry]:
    return [e for e in RUNTIME_ENTRY_INVENTORY if e.family == family]


def coverage_denominators() -> dict[str, dict[str, int | str]]:
    """三层完整度各自的分母（计划 §6.2 第 7 点 / §13.3）。

    - catalog：画布目录分母（flow_catalog 节点/边/源码解析）。
    - runtime：声明运行入口分母（本 inventory）与 root 接入数。
    - dataset：数据集覆盖度由 core/evaluation 报告，这里只声明口径。
    """
    from core.observability import flow_catalog

    entries = RUNTIME_ENTRY_INVENTORY
    return {
        "catalog": {
            "nodes": len(flow_catalog.NODES),
            "edges": len(flow_catalog.EDGES),
            "source_anchored": sum(1 for n in flow_catalog.NODES.values() if n.source),
            "opaque": sum(1 for n in flow_catalog.NODES.values() if n.opaque),
            "derived": sum(1 for n in flow_catalog.NODES.values() if n.derived),
            "note": "静态目录完整度；不冒充运行观测或数据集覆盖",
        },
        "runtime": {
            "declared_entries": len(entries),
            "with_flow_root": sum(1 for e in entries if e.root_kind),
            "explicit_boundaries": sum(1 for e in entries if e.boundary),
            "families": len(PROCESS_FAMILIES),
            "note": "运行入口 inventory；抽样 flow 不构成全集",
        },
        "dataset": {
            "denominator": "declared_expected_cases",
            "note": "由 experiments 报告；0 样本不允许 PASS",
        },
    }


def validate_inventory() -> list[str]:
    """inventory 自检：流程族存在、源码文件存在、root_kind 在目录登记。"""
    from pathlib import Path

    problems: list[str] = []
    root = Path(__file__).resolve().parents[2]
    for entry in RUNTIME_ENTRY_INVENTORY:
        if entry.family not in PROCESS_FAMILIES:
            problems.append(f"{entry.entry_id}: unknown family {entry.family}")
        file_path = root / entry.source[0]
        if not file_path.exists():
            problems.append(f"{entry.entry_id}: source file missing {entry.source[0]}")
        if entry.root_kind and entry.root_kind not in _ROOT_KINDS():
            problems.append(
                f"{entry.entry_id}: root_kind {entry.root_kind} not in flow_catalog.ENTRY_ROOTS")
    return problems


def _ROOT_KINDS() -> set[str]:
    from core.observability.flow_catalog import ENTRY_ROOTS

    return set(ENTRY_ROOTS)
