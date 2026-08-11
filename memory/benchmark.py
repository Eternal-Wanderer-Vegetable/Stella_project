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
import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from config import MEMORY_BENCHMARK_DIR
from memory.policy import detect_mode, normalize_mode


def _mem_dict(mid: str, data: dict[str, Any]) -> dict[str, Any]:
    """把 benchmark 用例里的记忆定义转成 memory dict。"""
    mem = dict(data)
    mem["id"] = mid
    if "usage_tags" not in mem:
        mem["usage_tags"] = []
    return mem


def load_cases(benchmark_dir: Path = MEMORY_BENCHMARK_DIR) -> list[dict[str, Any]]:
    """递归加载 benchmark 目录下所有 .json 用例。"""
    cases: list[dict[str, Any]] = []
    if not benchmark_dir.exists():
        return cases
    for path in sorted(benchmark_dir.rglob("*.json")):
        # _fixtures 目录放向量/文本数据，不是用例（否则 fixture 会被当成一条
        # id="?" 的伪用例混进对照表与指标）
        if "_fixtures" in path.parts:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            items = data if isinstance(data, list) else [data]
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
      ``group_id`` / ``user_id`` → 模拟"这条记忆属于别人"（测跨用户泄漏）；
      ``last_accessed_at``       → 测"新记忆压过旧记忆"的排序维度。
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
                "INSERT INTO memories (id, group_id, user_id, type, content, importance, "
                "confidence, status, usage_tags, visibility, trigger_data, behavior_rule, "
                "last_accessed_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?)",
                (
                    mid,
                    str(mem.get("group_id", group_id)),
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
                ),
            )
        conn.commit()
    finally:
        conn.close()
    return group_id, user_id


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
        declared_mode = normalize_mode(case.get("mode", "CASUAL_REPLY"))

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
                group_id, user_id, query, trigger=trigger, semantic_scores=semantic_scores
            )
        finally:
            retrieval_v2.DB_PATH = old_db
            retrieval_v2.MEMORY_V2_ENABLED = old_v2
            retrieval_v2.RAG_ENABLED = old_rag

        detected_mode = result.mode or detect_mode(query, trigger=trigger)
        conversation = result.conversation_memories
        behavior = result.behavior_constraints

        final_ids = {m["id"] for m in conversation}
        behavior_ids = {m["id"] for m in behavior}
        expected = set(case.get("expected_memory") or [])
        expected_behavior = set(case.get("expected_behavior_memory") or [])
        forbidden = set(case.get("forbidden_memory") or [])

        # 期望记忆必须进会话；期望行为约束记忆必须进行为约束、且不得泄漏进会话
        found_expected = final_ids & expected
        found_behavior = behavior_ids & expected_behavior
        behavior_leaked = final_ids & expected_behavior
        activated_forbidden = final_ids & forbidden

        # 超召回容忍度：用例可声明 max_retrieved 精确控制容忍上限；未声明时
        # 退化为“期望数 × 2”（只对带期望记忆的用例生效，行为约束用例不计）。
        # 防止“把所有合法候选都塞进去”式的刷 metrics 行为。
        over_recall = False
        if expected:
            max_retrieved = int(case.get("max_retrieved") or (len(expected) * 2))
            over_recall = len(final_ids) > max_retrieved

        # 会话记忆的排序分（用于 --verbose 观察期望/噪音分数分布，别拍脑袋定阈值）
        scores = {m["id"]: round(float(m.get("_score") or 0.0), 3) for m in conversation}
        # 分量分解（ctx/usg/sem/rec/conf/imp）：判断“为什么这条记忆排这么高/低”
        parts = {
            m["id"]: m.get("_score_parts") or {}
            for m in conversation
            if m.get("_score_parts")
        }
        # 全部进入排序的候选（含被 mode_limit 截断的）：id → (score, cut, parts)
        ranked_all = {
            item["id"]: item
            for item in (result.trace or {}).get("ranked_all") or []
            if item.get("id")
        }

        # 正/噪音综合分间隔（separation_margin）：按用例算
        # “正样本最低综合分 − 噪音最高综合分”，取最差；只对进入排序的候选统计。
        def _label(mid: str) -> str:
            if mid in expected or mid in expected_behavior:
                return "positive"
            if mid in forbidden:
                return "forbidden"
            return "noise"

        pos_scores = [item["score"] for mid, item in ranked_all.items() if _label(mid) == "positive"]
        noise_scores = [item["score"] for mid, item in ranked_all.items() if _label(mid) == "noise"]
        separation_margin = None
        if pos_scores and noise_scores:
            separation_margin = round(min(pos_scores) - max(noise_scores), 4)

        return {
            "id": case.get("id", "?"),
            "declared_mode": declared_mode,
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
    finally:
        if manager is not None:
            manager.cleanup()


def run_benchmark(
    benchmark_dir: Path = MEMORY_BENCHMARK_DIR,
    embedding_fixture: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """运行全部用例，汇总核心指标。

    ``embedding_fixture`` 不为 None 时，用 fixture 里的向量算查询↔记忆余弦分
    （embedding 路径）；缺省走规则版语义分。
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

    total = len(results)
    ok_count = sum(1 for r in results if r["ok"])
    cases_with_expected = sum(1 for r in results if r["expected"])
    total_expected = sum(len(r["expected"]) + len(r["expected_behavior"]) for r in results)
    total_expected_behavior = sum(len(r["expected_behavior"]) for r in results)
    total_found_expected = sum(len(r["found_expected"]) + len(r["found_behavior"]) for r in results)
    total_found_behavior = sum(len(r["found_behavior"]) for r in results)
    # 分母 = 会话召回 + 行为约束召回：行为约束里的期望记忆是“正确激活”（Behavior Guard），
    # 不能只算分子不算分母，否则会把 precision 虚高甚至推到 100% 以上。
    total_retrieved = sum(len(r["final"]) + len(r["behavior"]) for r in results)
    total_behavior_leaked = sum(len(r["behavior_leaked"]) for r in results)
    total_forbidden = sum(len(r["forbidden"]) for r in results)
    total_activated_forbidden = sum(len(r["activated_forbidden"]) for r in results)
    mode_correct = sum(1 for r in results if r["declared_mode"] == r["detected_mode"])

    # Precision 的分母是“实际召回条数”，Recall 的分母才是“期望条数”
    precision_pct = round(total_found_expected / max(1, total_retrieved) * 100, 1)

    # separation_margin：所有带正/噪音对照的用例里，最差的“正最低 − 噪音最高”
    margins = [r["separation_margin"] for r in results if r["separation_margin"] is not None]
    separation_margin = min(margins) if margins else None

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
        "separation_margin": separation_margin,
        "results": results,
    }


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
    args = parser.parse_args()

    if args.embedding_fixture is not None:
        fixture = load_embedding_fixture(args.embedding_fixture)
        metrics_emb = run_benchmark(args.dir, embedding_fixture=fixture)
        _print_summary(metrics_emb, f"[embedding {fixture.get('model', '?')}]")
        if args.verbose:
            _print_verbose(metrics_emb["results"])
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
        metrics_emb = run_benchmark(args.dir, embedding_fixture=fixture)
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


if __name__ == "__main__":
    main()
