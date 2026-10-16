# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""Memory Benchmark 运行器（Evaluation & Debug）。

对应设计文档《Evaluation & Debug Specification v1.0》：
- 读取 ``memory/benchmark/<category>/*.json`` 用例。每个用例可标注：
  ``expected_memory``（必须进会话 / conversation）、``expected_behavior_memory``
  （必须进行为约束 / behavior，且不得进会话）、``forbidden_memory``（绝不能激活）；
- 对每个用例把记忆写入临时 SQLite，调 ``memory.retrieval_v2.retrieve_memories()``
  走**生产检索路径**（含 SQL Visibility 预过滤 / Usage 过滤 / Ranking / Behavior Guard），
  最后对比实际选中的记忆与期望/禁止记忆；
- 输出核心指标：Memory Precision、Memory Recall、Forbidden Activation、
  Memory Pollution Rate、Mode 检测准确率、Behavior Guard Hit。

期望记忆分两种"正确"，不能混淆（进 conversation 与进 behavior 语义完全不同）：
  ``expected_memory`` 进会话才算命中；``expected_behavior_memory`` 进行为约束才算命中，
  且一旦泄漏进会话（behavior_leaked）即判失败。

核心指标：
    Metric 1  Memory Precision        = 找到的期望记忆 /（会话召回 + 行为约束召回）
    Metric 2  Memory Recall           = 找到的期望记忆 / 应该找到的记忆
    Metric 3  Forbidden Activation    = 被错误激活的禁止记忆次数（目标 ≈ 0）
    Metric 4  Memory Pollution Rate   = 1 - Precision（会话中无用记忆比例）
    Metric 5  Mode Detection Accuracy = 检测到的 mode 与用例标注一致的占比
    Metric 6  Behavior Guard Hit      = 期望行为约束记忆被 Behavior Guard 命中（且未泄漏）的比例
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import MEMORY_BENCHMARK_DIR
from memory.policy import detect_mode, normalize_mode

# ── 报告契约（M0）────────────────────────────────────────────
# schema 升级即破坏性变更：读方必须按 schema 字段分发，不得假设键集固定。
REPORT_SCHEMA = "memory-benchmark-report/1"
BASELINE_SCHEMA = "memory-benchmark-baseline/1"
# 指标语义版本：新增键不升版；改口径/改分母/改判定规则必须升版并重生成基线。
METRIC_DEFINITIONS_VERSION = "1"
# 用例时间的注入时钟锚点：temporal 偏移字段按它换算绝对时间戳（M1），
# 与用例 DB 的缺省时间戳（见 _write_case_db）同一纪元，保证跨机器可复现。
CLOCK_ANCHOR = "2026-08-09 12:00:00"
# 双硬零门禁：任何泄漏/误激活即失败，不允许容差，也不进平均分。
HARD_ZERO_METRICS = ("forbidden_activation_rate", "cross_scope_leak_rate")


def _mem_dict(mid: str, data: dict[str, Any]) -> dict[str, Any]:
    """把 benchmark 用例里的记忆定义转成 memory dict。"""
    mem = dict(data)
    mem["id"] = mid
    if "usage_tags" not in mem:
        mem["usage_tags"] = []
    return mem


def load_cases(benchmark_dir: Path = MEMORY_BENCHMARK_DIR) -> list[dict[str, Any]]:
    """递归加载 benchmark 目录下所有 .json 用例。

    任何以 ``_`` 开头的路径段都不是用例（``_fixtures``/``_public``/``_replay``/
    ``_baselines`` 等数据与制品目录），一律跳过——否则向量 fixture 会被当成
    id="?" 的伪用例混进对照表与指标。
    每条用例附带 ``_source_path``（相对 benchmark_dir 的来源文件路径），
    供报告按分类目录聚合；运行器与检索路径不读该键。
    """
    cases: list[dict[str, Any]] = []
    if not benchmark_dir.exists():
        return cases
    for path in sorted(benchmark_dir.rglob("*.json")):
        if any(part.startswith("_") for part in path.parts):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            items = data if isinstance(data, list) else [data]
            rel = path.relative_to(benchmark_dir).as_posix()
            for item in items:
                if isinstance(item, dict):
                    item["_source_path"] = rel
            cases.extend(items)
        except (ValueError, OSError) as e:
            print(f"⚠️ 用例解析失败 {path}: {e}")
    # id 缺失/重复是标注事故：尽早报错，避免静默 fallback 成 "?" 后把不同用例的
    # 期望/禁止混在一起，或与其他用例在对照表里撞 id
    seen: set[str] = set()
    for c in cases:
        cid = c.get("id")
        if not cid:
            raise ValueError(f"benchmark 用例缺少 id: {c!r}")
        if cid in seen:
            raise ValueError(f"benchmark 用例 id 重复: {cid!r}")
        seen.add(cid)
    return cases


def _scenario_ids(case: dict[str, Any]) -> tuple[int, int]:
    """从用例 scenario 里取群/用户 ID（用于写临时库并启动检索）。"""
    scenario = case.get("scenario") or {}
    try:
        group_id = int(scenario.get("group_id", 1))
    except (TypeError, ValueError):
        group_id = 1
    try:
        user_id = int(scenario.get("user_id", 0))
    except (TypeError, ValueError):
        user_id = 0
    return group_id, user_id


def _write_case_db(db_path: Path, case: dict[str, Any]) -> tuple[int, int]:
    """把用例记忆写进临时 SQLite，返回 (group_id, user_id)。

    背景：evaluate_case 必须走生产路径，即 retrieval_v2._fetch_candidates 内的
    SQL Visibility 预过滤（_allowed_visibility_clause）。否则 RESTRICTED 记忆会在
    普通模式绕过 SQL 直接进 rank_memories，测的是一条比生产更宽松的路径。
    memories 表直接复用 memory.schema 的规范 DDL，避免与生产 schema 漂移。

    单条记忆可覆盖 scenario 的归属与访问时间：
      ``group_shared_space`` / ``group_id`` → 模拟"这条记忆属于别的空间/群"（测跨空间泄漏）；
        用例可用 ``group_shared_space`` 或（兼容）``group_id`` 覆盖归属；
      ``last_accessed_at``       → 测"新记忆压过旧记忆"的排序维度。同一个值会同时
        写入 ``last_confirmed_at``：排序读的是证据新鲜度（policy._mem_timestamp
        优先 last_confirmed_at），而 last_accessed_at 会被检索命中刷新
        （retrieval_v2._touch_accessed），只写它会让同一用例跑第二遍时新鲜度变了。
    """
    db_path.unlink(missing_ok=True)
    group_id, user_id = _scenario_ids(case)
    conn = sqlite3.connect(db_path)
    try:
        from memory import schema

        schema.create_memories_table(conn)
        for mid, data in (case.get("memories") or {}).items():
            mem = _mem_dict(mid, data)
            # trigger_data 在 schema 里是 TEXT(JSON)，用例里写成对象时自动序列化，
            # 保证 rank_memories._trigger_topic_match 能读到统一形态。
            trigger_data = mem.get("trigger_data")
            if isinstance(trigger_data, (dict, list)):
                trigger_data = json.dumps(trigger_data, ensure_ascii=False)
            conn.execute(
                "INSERT INTO memories (id, group_shared_space, user_id, type, content, importance, "
                "confidence, status, usage_tags, visibility, trigger_data, behavior_rule, "
                "last_accessed_at, last_confirmed_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?)",
                (
                    mid,
                    str(mem.get("group_shared_space", mem.get("group_id", group_id))),
                    str(mem.get("user_id", user_id)),
                    mem.get("type") or "FACT",
                    mem.get("content") or "",
                    0.5 if mem.get("importance") is None else mem["importance"],
                    0.7 if mem.get("confidence") is None else mem["confidence"],
                    json.dumps(mem.get("usage_tags") or [], ensure_ascii=False),
                    mem.get("visibility") or "OPEN",
                    trigger_data,
                    mem.get("behavior_rule"),
                    mem.get("last_accessed_at", "2026-08-09 10:00:00"),
                    mem.get("last_accessed_at", "2026-08-09 10:00:00"),
                ),
            )
        conn.commit()
    finally:
        conn.close()
    return group_id, user_id


def write_case_db(
    db_path: Path,
    case: dict[str, Any],
    *,
    with_schema_meta: bool = False,
) -> tuple[int, int]:
    """Write a benchmark case and optionally add the native schema marker."""
    group_id, user_id = _write_case_db(db_path, case)
    if with_schema_meta:
        from memory.schema import SCHEMA_VERSION

        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_meta "
                "(k TEXT PRIMARY KEY, version INTEGER)"
            )
            conn.execute(
                "INSERT INTO schema_meta (k, version) VALUES ('version', ?) "
                "ON CONFLICT(k) DO UPDATE SET version = excluded.version",
                (SCHEMA_VERSION,),
            )
            conn.commit()
        finally:
            conn.close()
    return group_id, user_id


def evaluate_retrieval_result(
    case: dict[str, Any],
    result: Any,
) -> dict[str, Any]:
    """Normalize any backend RetrievalResult into the benchmark result shape."""
    query = case.get("input") or ""
    trigger = case.get(
        "trigger",
        "proactive" if case.get("mode") == "ACTIVE_JOIN" else "reply",
    )
    detected_mode = result.mode or detect_mode(query, trigger=trigger)
    conversation = result.conversation_memories
    behavior = result.behavior_constraints

    final_ids = {m["id"] for m in conversation}
    behavior_ids = {m["id"] for m in behavior}
    expected = set(case.get("expected_memory") or [])
    expected_behavior = set(case.get("expected_behavior_memory") or [])
    forbidden = set(case.get("forbidden_memory") or [])

    found_expected = final_ids & expected
    found_behavior = behavior_ids & expected_behavior
    behavior_leaked = final_ids & expected_behavior
    activated_forbidden = final_ids & forbidden

    over_recall = False
    if expected:
        max_retrieved = int(case.get("max_retrieved") or (len(expected) * 2))
        over_recall = len(final_ids) > max_retrieved

    scores = {m["id"]: round(float(m.get("_score") or 0.0), 3) for m in conversation}
    parts = {
        m["id"]: m.get("_score_parts") or {}
        for m in conversation
        if m.get("_score_parts")
    }
    ranked_all = {
        item["id"]: item
        for item in (result.trace or {}).get("ranked_all") or []
        if item.get("id")
    }

    def _label(mid: str) -> str:
        if mid in expected or mid in expected_behavior:
            return "positive"
        if mid in forbidden:
            return "forbidden"
        return "noise"

    pos_scores = [
        item["score"]
        for mid, item in ranked_all.items()
        if _label(mid) == "positive"
    ]
    noise_scores = [
        item["score"]
        for mid, item in ranked_all.items()
        if _label(mid) == "noise"
    ]
    separation_margin = None
    if pos_scores and noise_scores:
        separation_margin = round(min(pos_scores) - max(noise_scores), 4)

    return {
        "id": case.get("id", "?"),
        "category": category_of(case),
        "declared_mode": normalize_mode(case.get("mode", "CASUAL_REPLY")),
        "detected_mode": detected_mode,
        "expected": sorted(expected),
        "expected_behavior": sorted(expected_behavior),
        "forbidden": sorted(forbidden),
        "final": sorted(final_ids),
        "behavior": sorted(behavior_ids),
        "scores": scores,
        "parts": parts,
        "ranked_all": ranked_all,
        "separation_margin": separation_margin,
        "found_expected": sorted(found_expected),
        "found_behavior": sorted(found_behavior),
        "behavior_leaked": sorted(behavior_leaked),
        "activated_forbidden": sorted(activated_forbidden),
        "over_recall": over_recall,
        "ok": bool(
            found_expected == expected
            and found_behavior == expected_behavior
            and not behavior_leaked
            and not activated_forbidden
            and not over_recall
        ),
    }


def evaluate_case(
    case: dict[str, Any],
    work_dir: Path | None = None,
    seq: int = 0,
    semantic_scores: dict[str, float] | None = None,
) -> dict[str, Any]:
    """对单个用例跑生产检索路径，返回期望/禁止/实际的命中情况。

    生产路径：写入临时库后调 memory.retrieval_v2.retrieve_memories()，
    真实走一遍 SQL Visibility 预过滤 + Usage 过滤 + Ranking + Behavior Guard。
    mode 由检索入口自行检测，检测结果用于排序（不再用用例标注的 declared_mode）。
    seq 用于保证 temp 库文件名唯一，避免 id 缺失/重名的用例共用同一 db 路径。
    ``semantic_scores`` 为可选外部语义分（如从 embedding fixture 计算的余弦分），
    传给 retrieve_memories 走 embedding 路径；缺省为规则版。
    """
    import memory.retrieval_v2 as retrieval_v2

    manager: Any = None
    if work_dir is None:
        manager = tempfile.TemporaryDirectory(prefix="stella_benchmark_")
        work_dir = Path(manager.name)
    try:
        db_path = work_dir / f"case_{seq}_{case.get('id', 'case')}.db"
        group_id, user_id = _write_case_db(db_path, case)
        query = case.get("input") or ""
        trigger = case.get("trigger", "proactive" if case.get("mode") == "ACTIVE_JOIN" else "reply")
        # 临时把 retrieval_v2 指向本用例的临时库，结束后恢复现场
        old_db, old_v2, old_rag = (
            retrieval_v2.DB_PATH,
            retrieval_v2.MEMORY_V2_ENABLED,
            retrieval_v2.RAG_ENABLED,
        )
        try:
            retrieval_v2.DB_PATH = db_path
            retrieval_v2.MEMORY_V2_ENABLED = True
            # 故意关掉 RAG/FTS：保证 benchmark 结果可复现（注意 FTS 分支是盲区）
            retrieval_v2.RAG_ENABLED = False
            # _CACHE 按 (db 路径, 群, 用户, trigger, mode) 全局缓存 5 分钟，
            # 用例之间必须清空，否则同名/缺失 id 的用例会吃到上一用例的缓存。
            retrieval_v2._CACHE.clear()
            result = retrieval_v2.retrieve_memories(
                # 用例的 group_id 直接当作空间标识（等价于隐式空间），因为用例测的是
                # 检索逻辑，不涉及多群映射——不需要走 config.spaces.resolve_space。
                str(group_id),
                user_id,
                query,
                trigger=trigger,
                semantic_scores=semantic_scores,
            )
        finally:
            retrieval_v2.DB_PATH = old_db
            retrieval_v2.MEMORY_V2_ENABLED = old_v2
            retrieval_v2.RAG_ENABLED = old_rag

        return evaluate_retrieval_result(case, result)
    finally:
        if manager is not None:
            manager.cleanup()


def _aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    """把逐例结果聚合成核心指标（run_benchmark 与分类聚合共用同一口径）。"""
    total = len(results)
    ok_count = sum(1 for r in results if r["ok"])
    cases_with_expected = sum(1 for r in results if r["expected"])
    total_expected = sum(len(r["expected"]) + len(r["expected_behavior"]) for r in results)
    total_expected_behavior = sum(len(r["expected_behavior"]) for r in results)
    total_found_expected = sum(len(r["found_expected"]) + len(r["found_behavior"]) for r in results)
    total_found_behavior = sum(len(r["found_behavior"]) for r in results)
    total_retrieved = sum(len(r["final"]) + len(r["behavior"]) for r in results)
    total_behavior_leaked = sum(len(r["behavior_leaked"]) for r in results)
    total_forbidden = sum(len(r["forbidden"]) for r in results)
    total_activated_forbidden = sum(len(r["activated_forbidden"]) for r in results)
    mode_correct = sum(1 for r in results if r["declared_mode"] == r["detected_mode"])

    # Precision 的分母是“实际召回条数”，Recall 的分母才是“期望条数”
    precision_pct = round(total_found_expected / max(1, total_retrieved) * 100, 1)

    # separation_margin：所有带正/噪音对照的用例里，最差的“正最低 − 噪音最高”
    margins = [r["separation_margin"] for r in results if r["separation_margin"] is not None]

    return {
        "cases_total": total,
        "cases_ok": ok_count,
        "cases_ok_rate": round(ok_count / total * 100, 1) if total else 0.0,
        # 分母透出：不显示样本量的百分比会误导（空召回用例对 recall 贡献为 0）
        "cases_with_expected": cases_with_expected,
        "total_expected": total_expected,
        "total_expected_behavior": total_expected_behavior,
        "total_retrieved": total_retrieved,
        "total_forbidden": total_forbidden,
        "memory_precision": precision_pct,
        "memory_recall": round(total_found_expected / max(1, total_expected) * 100, 1),
        # Metric 4 Memory Pollution Rate = 1 - Precision（会话中无用记忆比例）
        "memory_pollution_rate": round(max(0.0, 100.0 - precision_pct), 1),
        # Metric 5 Mode Detection Accuracy：检测到的 mode 是否与用例标注一致
        "mode_accuracy": round(mode_correct / total * 100, 1) if total else 0.0,
        # Metric 6 Behavior Guard Hit：期望行为约束记忆被命中（且未泄漏）的比例
        "behavior_guard_hit_rate": round(total_found_behavior / max(1, total_expected_behavior) * 100, 1),
        "behavior_leaks": total_behavior_leaked,
        "forbidden_activation_rate": round(total_activated_forbidden / max(1, total_forbidden) * 100, 1),
        "forbidden_activations": total_activated_forbidden,
        "separation_margin": min(margins) if margins else None,
    }


def category_of(case_or_result: dict[str, Any]) -> str:
    """用例/结果所属分类目录（_source_path 首段；根目录用例归 "root"）。"""
    source = case_or_result.get("_source_path") or ""
    parts = source.split("/")
    return parts[0] if len(parts) > 1 else "root"


def run_benchmark(
    benchmark_dir: Path = MEMORY_BENCHMARK_DIR,
    embedding_fixture: dict[str, Any] | None = None,
    *,
    retrieval_mode: str = "rule",
) -> dict[str, Any]:
    """运行全部用例，汇总核心指标。

    ``embedding_fixture`` 不为 None 时，用 fixture 里的向量算查询↔记忆余弦分
    （embedding 路径）；缺省走规则版语义分。
    ``retrieval_mode`` 记录本次运行使用的检索形态（M2 起支持 rule/embedding/
    fts/hybrid 矩阵；rule 为历史缺省形态），只进报告与 fingerprint，不改变
    返回形状的既有键。
    """
    cases = load_cases(benchmark_dir)
    with tempfile.TemporaryDirectory(prefix="stella_benchmark_") as tmp:
        work_dir = Path(tmp)
        results = [
            evaluate_case(
                c,
                work_dir,
                i,
                semantic_scores=(
                    fixture_semantic_scores(c, embedding_fixture) if embedding_fixture else None
                ),
            )
            for i, c in enumerate(cases)
        ]

    metrics = _aggregate(results)
    # 返回形状向后兼容：以下均为新增键（报告契约 v1，只增不改）
    metrics["results"] = results
    metrics["retrieval_mode"] = retrieval_mode
    metrics["metric_definitions_version"] = METRIC_DEFINITIONS_VERSION
    metrics["dataset_digest"] = dataset_digest(benchmark_dir, cases)
    metrics["clock_anchor"] = CLOCK_ANCHOR
    metrics["category_metrics"] = _category_metrics(results)
    return metrics


def _category_metrics(results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """按分类目录聚合（目录 = 数据集根下第一级路径段）。"""
    by_category: dict[str, list[dict[str, Any]]] = {}
    for r in results:
        by_category.setdefault(r.get("category") or category_of(r), []).append(r)
    return {cat: _aggregate(items) for cat, items in sorted(by_category.items())}


# ── 报告 / 基线 / 证据 manifest（M0）─────────────────────────


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def dataset_digest(benchmark_dir: Path, cases: list[dict[str, Any]] | None = None) -> str:
    """数据集内容摘要：排序后的（相对路径, 文件 sha256）规范 JSON 的 sha256。

    同一数据集内容 → 同一摘要；与加载顺序无关。用例不是来自文件（合成用例）
    时退化为对用例 id + 规范 JSON 的摘要，保证函数总可用。
    """
    entries: list[dict[str, str]] = []
    files = True
    for c in cases or []:
        rel = c.get("_source_path")
        if not rel:
            files = False
            break
        path = benchmark_dir / rel
        try:
            entries.append({"path": rel, "sha256": _sha256_bytes(path.read_bytes())})
        except OSError:
            files = False
            break
    if not files:
        # 合成用例（tests）：以用例本身的内容为准
        payload = json.dumps(
            [{k: v for k, v in c.items() if not k.startswith("_")} for c in cases or []],
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        )
        return _sha256_bytes(payload.encode("utf-8"))
    canonical = json.dumps(sorted(entries, key=lambda e: e["path"]),
                           ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _sha256_bytes(canonical.encode("utf-8"))


def _code_version() -> str:
    """git HEAD 短哈希（不可用时 "unknown"）。仅作指纹成分，不作正确性依据。"""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5, check=True,
        )
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _source_digest() -> str:
    """检索路径关键源码的内容摘要：捕获未提交改动对结果的影响。"""
    root = Path(__file__).resolve().parent
    files = [root / "benchmark.py", root / "retrieval_v2.py", root / "policy.py", root / "schema.py"]
    entries = []
    for f in sorted(files):
        try:
            entries.append({"path": f.name, "sha256": _sha256_bytes(f.read_bytes())})
        except OSError:
            entries.append({"path": f.name, "sha256": "missing"})
    canonical = json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _sha256_bytes(canonical.encode("utf-8"))


def build_run_fingerprint(
    benchmark_dir: Path,
    cases: list[dict[str, Any]],
    *,
    backend: str,
    retrieval_mode: str,
) -> tuple[str, dict[str, Any]]:
    """run_fingerprint：代码版本 + 源码摘要 + 数据集摘要 + 后端 + 检索模式 + 时钟锚点。

    同输入（同一代码树 + 同一数据集 + 同一后端/模式）→ 同指纹；
    墙钟时间等不可复现量一律不进指纹（报告里的 generated_at 单独记录）。
    """
    components = {
        "code_version": _code_version(),
        "source_digest": _source_digest(),
        "dataset_sha256": dataset_digest(benchmark_dir, cases),
        "backend": backend,
        "retrieval_mode": retrieval_mode,
        "clock_anchor": CLOCK_ANCHOR,
        "metric_definitions_version": METRIC_DEFINITIONS_VERSION,
    }
    canonical = json.dumps(components, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _sha256_bytes(canonical.encode("utf-8")), components


def build_report_document(
    benchmark_dir: Path,
    metrics: dict[str, Any],
    *,
    backend: str = "python",
) -> dict[str, Any]:
    """把 run_benchmark 返回聚合成报告契约文档（memory-benchmark-report/1）。"""
    fingerprint, components = build_run_fingerprint(
        benchmark_dir,
        metrics["results"],
        backend=backend,
        retrieval_mode=metrics.get("retrieval_mode", "rule"),
    )
    aggregate = {k: v for k, v in metrics.items() if k != "results"}
    return {
        "schema": REPORT_SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "run_fingerprint": fingerprint,
        "fingerprint_components": components,
        "metric_definitions_version": metrics.get("metric_definitions_version", METRIC_DEFINITIONS_VERSION),
        "metrics": aggregate,
        "results": metrics["results"],
    }


def write_evidence_manifest(report_dir: Path, extra_files: list[Path] | None = None) -> Path:
    """按证据目录惯例写 manifest.json（path + sha256，不含 manifest 自身）。"""
    artifacts = []
    for f in sorted(report_dir.iterdir()):
        if f.is_file() and f.name != "manifest.json":
            artifacts.append({"path": f.name, "sha256": _sha256_bytes(f.read_bytes())})
    manifest = {
        "captured_local_date": datetime.now().strftime("%Y-%m-%d"),
        "artifact_kind": "memory-benchmark-report",
        "metric_definitions_version": METRIC_DEFINITIONS_VERSION,
        "artifacts": artifacts,
    }
    path = report_dir / "manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


# 逐指标缺省容差（绝对百分点/绝对值）。确定性套件默认 0：数值漂移必须显式可见；
# 个别指标确有环境噪声时由基线文件 tolerances 显式放宽（硬零指标不可放宽）。
DEFAULT_TOLERANCES: dict[str, float] = {}
# 基线对比只看聚合指标，不含逐例明细与诊断字段。
_BASELINE_COMPARE_METRICS = (
    "cases_total", "cases_ok", "cases_ok_rate", "cases_with_expected",
    "total_expected", "total_expected_behavior", "total_retrieved", "total_forbidden",
    "memory_precision", "memory_recall", "memory_pollution_rate", "mode_accuracy",
    "behavior_guard_hit_rate", "behavior_leaks", "forbidden_activation_rate",
    "forbidden_activations", "separation_margin",
)


def build_baseline_document(metrics: dict[str, Any], *, note: str = "") -> dict[str, Any]:
    """从 run_benchmark 返回构造基线快照文档（不含逐例明细，保持可评审体量）。"""
    aggregate = {k: metrics[k] for k in _BASELINE_COMPARE_METRICS if k in metrics}
    return {
        "schema": BASELINE_SCHEMA,
        "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": note,
        "retrieval_mode": metrics.get("retrieval_mode", "rule"),
        "metric_definitions_version": metrics.get("metric_definitions_version", METRIC_DEFINITIONS_VERSION),
        "dataset_digest": metrics.get("dataset_digest", ""),
        "metrics": aggregate,
        "dimensions": metrics.get("dimensions", {}),
        # 允许按指标显式放宽（绝对值）；硬零指标不在此列，填了也不生效
        "tolerances": {},
    }


def compare_baseline(
    metrics: dict[str, Any],
    baseline_path: Path,
) -> tuple[bool, list[dict[str, Any]]]:
    """逐指标对比基线，返回 (是否全部在容差内, 漂移表)。

    - 当前运行多出的新指标：报告为 "new"，不算漂移（基线随后补快照即可）；
    - 基线有而当前缺失：视为漂移（指标被删除/改名必须显式过审）；
    - 硬零指标（HARD_ZERO_METRICS）：容差强制 0，任何非零即失败。
    """
    baseline = json.loads(Path(baseline_path).read_text(encoding="utf-8"))
    if baseline.get("schema") != BASELINE_SCHEMA:
        raise ValueError(f"未知基线 schema: {baseline.get('schema')!r}（期望 {BASELINE_SCHEMA}）")
    base_metrics = baseline.get("metrics") or {}
    tolerances = dict(DEFAULT_TOLERANCES)
    tolerances.update(baseline.get("tolerances") or {})
    current = {k: metrics[k] for k in _BASELINE_COMPARE_METRICS if k in metrics}

    drift: list[dict[str, Any]] = []
    all_ok = True
    for name in sorted(set(base_metrics) | set(current)):
        base_v = base_metrics.get(name)
        cur_v = current.get(name)
        if cur_v is None:
            all_ok = False
            drift.append({"metric": name, "baseline": base_v, "current": None,
                          "delta": None, "tolerance": 0.0, "ok": False, "status": "missing"})
            continue
        if base_v is None:
            drift.append({"metric": name, "baseline": None, "current": cur_v,
                          "delta": None, "tolerance": None, "ok": True, "status": "new"})
            continue
        tol = 0.0 if name in HARD_ZERO_METRICS else float(tolerances.get(name, 0.0))
        delta = round(float(cur_v) - float(base_v), 6)
        ok = abs(delta) <= tol
        if not ok:
            all_ok = False
        drift.append({"metric": name, "baseline": base_v, "current": cur_v,
                      "delta": delta, "tolerance": tol, "ok": ok,
                      "status": "ok" if ok else "drift"})
    return all_ok, drift


def print_baseline_drift(drift: list[dict[str, Any]]) -> None:
    print("────── 基线漂移表（baseline vs current） ──────")
    for row in drift:
        mark = "✅" if row["ok"] else "❌"
        if row["status"] == "new":
            print(f"  {mark} {row['metric']:<28} 新指标（基线无此键） current={row['current']}")
        elif row["status"] == "missing":
            print(f"  {mark} {row['metric']:<28} 当前运行缺失 baseline={row['baseline']}")
        else:
            print(f"  {mark} {row['metric']:<28} baseline={row['baseline']:<8} "
                  f"current={row['current']:<8} delta={row['delta']:+} tol={row['tolerance']}")


def _text_digest(text: str) -> str:
    """文本的 sha256（与 build_embedding_fixture 一致，作 fixture 向量索引）。"""
    import hashlib

    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def fixture_semantic_scores(case: dict[str, Any], fixture: dict[str, Any]) -> dict[str, float]:
    """从 fixture 查 query 与每条记忆的向量，返回 {mem_id: 余弦分}。

    fixture 结构：{model, dim, dtype, normalized, keys, data: {sha256: base64(float16)}}。
    缺失向量的记忆跳过（rule-only 兜底）。
    """
    import base64

    import numpy as np

    vecs = fixture.get("_vecs")
    if vecs is None:
        vecs = {}
        raw = fixture.get("data") or {}
        for key, b64 in raw.items():
            vecs[key] = np.frombuffer(base64.b64decode(b64), dtype=np.float16).astype(np.float32)
        fixture["_vecs"] = vecs

    qv = vecs.get(_text_digest(case.get("input") or ""))
    if qv is None:
        return {}
    qn = float(np.linalg.norm(qv))
    scores: dict[str, float] = {}
    for mid, mem in (case.get("memories") or {}).items():
        mv = vecs.get(_text_digest(mem.get("content") or ""))
        if mv is None:
            continue
        nn = float(np.linalg.norm(mv))
        if qn == 0.0 or nn == 0.0:
            continue
        s = float(np.dot(qv, mv) / (qn * nn))
        scores[mid] = max(0.0, min(1.0, s))
    return scores


def load_embedding_fixture(path: Path) -> dict[str, Any]:
    """读取 embedding fixture JSON，返回含 _vecs 的 dict。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "data" not in data:
        raise ValueError(f"非法 embedding fixture: {path}")
    return data


def _print_summary(metrics: dict[str, Any], label: str = "") -> None:
    """打印汇总指标（label 注明是 rule-only 还是 embedding）。"""
    print("=" * 56)
    print(f"Memory Benchmark {metrics['cases_total']} 个用例（{metrics['cases_with_expected']} 个带期望） {label}")
    print("=" * 56)
    print(f"  通过用例       : {metrics['cases_ok']}/{metrics['cases_total']} ({metrics['cases_ok_rate']}%)")
    print(f"  Memory Precision : {metrics['memory_precision']}%")
    print(f"  Memory Recall    : {metrics['memory_recall']}%")
    print(f"  Pollution Rate   : {metrics['memory_pollution_rate']}%")
    print(f"  Behavior Guard   : {metrics['behavior_guard_hit_rate']}%")
    print(f"  Mode 检测准确率  : {metrics['mode_accuracy']}%")
    print(f"  Forbidden 激活   : {metrics['forbidden_activation_rate']}% "
          f"({metrics['forbidden_activations']} 次)  （目标 ≈ 0%）")
    if metrics.get("separation_margin") is not None:
        print(f"  Separation Margin: {metrics['separation_margin']:+.4f}  （正最低 − 噪音最高，最差用例）")
    print(f"  样本分母        : 期望 {metrics['total_expected']}（行为 {metrics['total_expected_behavior']}）"
          f" / 召回 {metrics['total_retrieved']} / 禁止 {metrics['total_forbidden']}")
    print("=" * 56)


def _print_verbose(results: list[dict[str, Any]]) -> None:
    """打印每个用例明细：全部进入排序的候选 + 截断标记 + _score_parts。"""
    for r in results:
        status = "✅" if r["ok"] else "❌"
        mode_flag = (
            "" if r["declared_mode"] == r["detected_mode"]
            else f" ⚠️mode: 标注={r['declared_mode']} 实测={r['detected_mode']}"
        )
        over_flag = " ⚠️超召回" if r["over_recall"] else ""
        # 全部进入排序的候选（含被截断的），按分数降序，带 ✓ / ✗limit / ✗thresh / →beh 标记
        cands = sorted(r["ranked_all"].values(), key=lambda x: x["score"], reverse=True)
        lines = []
        for item in cands:
            mid = item["id"]
            c = item.get("cut")
            if c in (False, "", None):
                mark = "✓"
            elif c == "thresh":
                mark = "✗thresh"  # 低于 MEMORY_SCORE_MIN
            elif c == "behavior":
                mark = "→beh"  # 被路由为行为约束
            else:
                mark = "✗limit"  # 超 mode_limit 截断
            parts = item.get("parts") or {}
            parts_str = "[" + " ".join(f"{k}:{parts.get(k, 0):.3f}" for k in ("ctx", "usg", "sem", "rec", "conf", "imp")) + "]"
            lines.append(f"      {mid:<12} {item['score']:+.4f} {mark} {parts_str}")
        print(
            f"{status} {r['id']} [{r['detected_mode']}] "
            f"期望={r['expected']} 期望行为={r['expected_behavior']} 实际={r['final']} "
            f"行为约束={r['behavior']} 违规激活={r['activated_forbidden']}"
            f"{mode_flag}{over_flag}"
            + (f"\n  间隔 {r['separation_margin']:+.4f}" if r["separation_margin"] is not None else "")
        )
        print("\n".join(lines) if lines else "      （无候选）")


def main() -> None:
    parser = argparse.ArgumentParser(description="Stella Memory Benchmark")
    parser.add_argument("--dir", type=Path, default=MEMORY_BENCHMARK_DIR, help="benchmark 数据集目录")
    parser.add_argument("--verbose", action="store_true", help="打印每个用例的明细")
    parser.add_argument("--embedding-fixture", type=Path, default=None,
                        help="从 fixture 取向量算语义分（embedding 路径，不发 HTTP），缺省 rule-only")
    parser.add_argument("--compare", action="store_true",
                        help="同一套用例跑 rule-only 与 embedding 两遍，输出对照表")
    parser.add_argument("--report", type=Path, default=None,
                        help="把报告契约文档（report.json + manifest.json）写入该目录")
    parser.add_argument("--compare-baseline", type=Path, default=None,
                        help="对比基线快照（memory-benchmark-baseline/1），漂移超出容差非零退出")
    args = parser.parse_args()

    if args.embedding_fixture is not None:
        fixture = load_embedding_fixture(args.embedding_fixture)
        metrics_emb = run_benchmark(args.dir, embedding_fixture=fixture, retrieval_mode="embedding")
        _print_summary(metrics_emb, f"[embedding {fixture.get('model', '?')}]")
        if args.verbose:
            _print_verbose(metrics_emb["results"])
        _emit_report_and_baseline(args, metrics_emb)
        return

    if args.compare:
        fixture = None
        metrics_rule = run_benchmark(args.dir)
        _print_summary(metrics_rule, "[rule-only]")
        print("\n")
        # 尝试找默认 fixture；找不到就只跑 rule-only 并提示
        default_fixtures = sorted((Path(__file__).resolve().parent / "benchmark" / "_fixtures").glob("embeddings_*.json"))
        if not default_fixtures:
            print("⚠️ 未找到 embedding fixture（先运行 scripts/build_embedding_fixture.py）。仅输出 rule-only。")
            if args.verbose:
                _print_verbose(metrics_rule["results"])
            return
        fixture = load_embedding_fixture(default_fixtures[0])
        metrics_emb = run_benchmark(args.dir, embedding_fixture=fixture, retrieval_mode="embedding")
        _print_summary(metrics_emb, f"[embedding {fixture.get('model', '?')}]")
        print("\n────── 对照表（rule-only vs embedding） ──────")
        rmap = {r["id"]: r for r in metrics_rule["results"]}
        for r in metrics_emb["results"]:
            rr = rmap.get(r["id"], {})
            print(f"  {r['id']:<22} rule={'✅' if rr.get('ok') else '❌'}  "
                  f"emb={'✅' if r['ok'] else '❌'}  "
                  f"margin rule={rr.get('separation_margin')!s:>8}  "
                  f"emb={r['separation_margin']!s:>8}")
        return

    metrics = run_benchmark(args.dir)
    _print_summary(metrics)
    if args.verbose:
        _print_verbose(metrics["results"])
    _emit_report_and_baseline(args, metrics)


def _emit_report_and_baseline(args: argparse.Namespace, metrics: dict[str, Any]) -> None:
    """落盘报告契约文档并按需对比基线（--report / --compare-baseline 共用）。"""
    if args.report is not None:
        report_dir = args.report
        report_dir.mkdir(parents=True, exist_ok=True)
        document = build_report_document(args.dir, metrics)
        report_path = report_dir / "report.json"
        report_path.write_text(
            json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        write_evidence_manifest(report_dir)
        print(f"📄 报告已写入 {report_path}")
    if args.compare_baseline is not None:
        all_ok, drift = compare_baseline(metrics, args.compare_baseline)
        print_baseline_drift(drift)
        if not all_ok:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
