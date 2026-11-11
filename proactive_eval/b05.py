# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 stella Project Contributors
"""B05 memory natural-use benchmark: joint memory conditions and content scoring.

Run with ``python -m proactive_eval.b05 --help``. Tasks (comma-separated):

- ``rank``      ChMap topic_rank through production retrieval (0 model calls);
- ``boundary``  M3/M4/M5 pack-boundary invariants on MemUse positives (0 calls);
- ``joint``     MemUse natural reply + ChMap callback under M0/M1/M2/MS (reply+judge);
- ``pairing``   MemUse direct-QA single-variable cells T0 / T3 / T0+sufficiency guard;
- ``m6``        real write-side smoke: production-equivalent ingest (B04 track) then
                natural reply from the resulting store.

Memory never influences Aoede's participation decision on this branch
(``ParticipationManager`` reads no memory content), so every model cell here is a
*fixed-decision content* measurement; decision-layer system benefit is reported
as structurally not applicable rather than as zero.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import random
import shutil
import sqlite3
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from proactive_eval import b05_data as data
from proactive_eval import b05_prompts as prompts

REPORT_SCHEMA = "stella-proactive-b05-report/1"
FINGERPRINT_SCHEMA = "proactive-b05-resume/1"
TASKS = ("rank", "boundary", "joint", "pairing", "m6")
MODEL_TASKS = {"joint", "pairing", "m6"}
GROUP_ID = 880500
CROSS_GROUP_ID = 880599
MEMORY_USER = "9300001"
_REPO = Path(__file__).resolve().parents[1]
_RAW = Path("memory/benchmark/_public/proactive_eval/raw")


class RunBudget:
    """Same contract as the B04 budget (calls + wall time), with B05 messages."""

    def __init__(self, max_calls: int, max_seconds: int):
        if int(max_calls) < 1 or int(max_seconds) < 1:
            raise ValueError("max_calls and max_runtime_seconds must be at least 1")
        self.max_calls = int(max_calls)
        self.max_seconds = int(max_seconds)
        self.started = time.monotonic()
        self.calls: list[dict[str, str]] = []
        self.truncated_generations: list[dict[str, str]] = []

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started

    @property
    def remaining_seconds(self) -> float:
        return max(0.0, self.max_seconds - self.elapsed)

    def reserve(self, role: str) -> None:
        from memory_eval.b04 import BudgetExceededError

        if self.remaining_seconds <= 0:
            raise BudgetExceededError("B05 runtime budget exhausted")
        if len(self.calls) >= self.max_calls:
            raise BudgetExceededError("B05 model-call budget exhausted")
        self.calls.append({"role": role, "reserved_at": _utcnow()})

    def check_time(self) -> None:
        from memory_eval.b04 import BudgetExceededError

        if self.remaining_seconds <= 0:
            raise BudgetExceededError("B05 runtime budget exhausted")

    def record_truncation(self, role: str) -> None:
        self.truncated_generations.append({"role": role, "observed_at": _utcnow()})


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _count_by_role(calls: list[dict[str, str]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for call in calls:
        counts[call["role"]] = counts.get(call["role"], 0) + 1
    return counts


def _validate_endpoint(value: str | None, option: str, *, require_v1: bool) -> str:
    text = str(value or "").strip()
    parts = urlsplit(text)
    if (parts.scheme not in ("http", "https") or not parts.netloc
            or parts.username or parts.password or parts.query or parts.fragment):
        raise ValueError(f"{option} must be an absolute http(s) URL without URL credentials/query")
    path = parts.path.rstrip("/")
    if require_v1 and not path.casefold().endswith("/v1"):
        raise ValueError(f"{option} must end in /v1")
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def validate_args(args: argparse.Namespace) -> tuple[list[str], list[str], set[str]]:
    """Validate the experiment boundary before loading application config."""
    tasks = [part.strip() for part in args.tasks.split(",") if part.strip()]
    if not tasks or len(tasks) != len(set(tasks)):
        raise ValueError("tasks must be non-empty and unique")
    unknown = sorted(set(tasks) - set(TASKS))
    if unknown:
        raise ValueError(f"unknown tasks: {unknown}")

    rank_channels = [part.strip() for part in args.rank_channels.split(",") if part.strip()]
    if len(rank_channels) != len(set(rank_channels)):
        raise ValueError("rank-channels must not contain duplicates")
    if (set(tasks) & {"rank", "boundary"}) and not rank_channels:
        raise ValueError("rank/boundary tasks require at least one --rank-channels entry")
    used = set(rank_channels) if set(tasks) & {"rank", "boundary"} else set()
    if MODEL_TASKS & set(tasks) and args.channel:
        used.add(args.channel)
    if set(rank_channels) - set(CHANNELS):
        raise ValueError(f"unknown rank channels: {sorted(set(rank_channels) - set(CHANNELS))}")

    if args.chmap_records < 0 or args.memuse_pairs < 0:
        raise ValueError("chmap-records and memuse-pairs must be non-negative")
    if args.bootstrap_replicates < 1:
        raise ValueError("bootstrap-replicates must be at least 1")
    if args.max_calls < 1 or args.max_runtime_seconds < 1:
        raise ValueError("max-calls and max-runtime-seconds must be at least 1")
    if MODEL_TASKS & set(tasks):
        if not args.channel:
            raise ValueError("model tasks require an explicit --channel")
        if not args.llm_model or not args.llm_base_url:
            raise ValueError("model tasks require explicit --llm-base-url and --llm-model")
        _validate_endpoint(args.llm_base_url, "--llm-base-url", require_v1=True)
        if args.max_reply_tokens < 1 or args.max_judge_tokens < 1:
            raise ValueError("reply and judge token caps must be at least 1")
    if "m6" in tasks:
        if args.m6_pairs < 1:
            raise ValueError("m6 requires at least one --m6-pairs pair")
        if not args.memory_base_url or not args.memory_model:
            raise ValueError("m6 requires explicit --memory-base-url and --memory-model")
        _validate_endpoint(args.memory_base_url, "--memory-base-url", require_v1=False)
        if args.max_consolidation_tokens < 1 or args.max_extract_tokens < 1:
            raise ValueError("memory role token caps must be at least 1")
    if used & EMBEDDING_CHANNELS:
        if not args.embedding_base_url or not args.embedding_model:
            raise ValueError("embedding/hybrid channels require --embedding-base-url and --embedding-model")
        _validate_endpoint(args.embedding_base_url, "--embedding-base-url", require_v1=False)
        if urlsplit(args.embedding_base_url).path.rstrip("/").casefold().endswith("/v1"):
            raise ValueError("--embedding-base-url must omit the /v1 path suffix")
    return tasks, rank_channels, used


def _list_endpoint_models(base_url: str, requested: list[str], api_key: str, *, memory: bool) -> dict[str, Any]:
    """Verify explicit model IDs against an OpenAI-compatible metadata endpoint."""
    parts = urlsplit(base_url)
    path = parts.path.rstrip("/")
    if memory and path.casefold().endswith("/v1"):
        path = path[:-3]
    models_url = urlunsplit((parts.scheme, parts.netloc, path, "", ""))
    models_url += "/v1/models" if memory else "/models"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    request = urllib.request.Request(models_url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=15.0) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise ValueError(f"model preflight failed: HTTP {exc.code}") from None
    except Exception as exc:
        raise ValueError(f"model preflight failed: {type(exc).__name__}") from None
    ids = sorted({str(row.get("id")) for row in (payload.get("data") or [])
                  if isinstance(row, dict) and row.get("id")}) if isinstance(payload, dict) else []
    if not ids:
        raise ValueError("model preflight failed: endpoint returned no model IDs")
    missing = sorted(set(requested) - set(ids))
    if missing:
        raise ValueError(f"model preflight failed: requested model IDs are not listed: {missing}")
    return {"requested_models": sorted(set(requested)), "available_model_ids": ids}


def _model_preflight(args: argparse.Namespace, tasks: list[str]) -> dict[str, Any]:
    if not (MODEL_TASKS & set(tasks)):
        return {"requested": False}
    result = {
        "requested": True,
        "reply": _list_endpoint_models(
            args.llm_base_url,
            [args.llm_model, args.judge_model or args.llm_model],
            args.llm_api_key,
            memory=False,
        ),
    }
    if "m6" in tasks:
        result["memory"] = _list_endpoint_models(
            args.memory_base_url, [args.memory_model], args.memory_api_key, memory=True
        )
    return result


def _retrieval_backend_identity() -> dict[str, Any]:
    from memory_rust.selector import resolve_backend

    decision, backend = resolve_backend()
    native = getattr(backend, "_native", None)
    native_path = getattr(native, "__file__", None)
    return {
        "requested": decision.requested,
        "selected": decision.selected,
        "result_backend": "python" if decision.shadow else decision.selected,
        "shadow": decision.shadow,
        "strict": decision.strict,
        "fallback_reason": decision.fallback_reason,
        "implementation": f"{type(backend).__module__}.{type(backend).__qualname__}",
        "api_version": getattr(backend, "api_version", None),
        "schema_version": getattr(backend, "schema_version", None),
        "native_binary_sha256": data.sha256_file(Path(native_path)) if native_path else None,
    }


# ── isolated memory store ─────────────────────────────────────────────────


class MemoryStore:
    """One isolated SQLite store per (task, item, condition); production schema."""

    def __init__(self, directory: Path):
        from memory_eval.isolation import ReplayEnv

        self.directory = directory
        self.env = ReplayEnv(directory, {"scenario_id": "store", "group_id": GROUP_ID, "sessions": []})
        self.db_path = self.env.db_path

    def __enter__(self) -> MemoryStore:  # noqa: PYI034 (concrete helper, not subclassed)
        if self.directory.exists():
            shutil.rmtree(self.directory)
        self.directory.mkdir(parents=True)
        self.env.setup()
        from mneme.schema import create_memory_candidates_table

        conn = sqlite3.connect(self.db_path)
        try:
            create_memory_candidates_table(conn)
            conn.commit()
        finally:
            conn.close()
        return self

    def __exit__(self, *exc: object) -> None:
        self.env.close()

    @staticmethod
    def space(group_id: int = GROUP_ID) -> str:
        from config.spaces import resolve_space

        return resolve_space(int(group_id))

    def add_memories(self, rows: list[dict[str, Any]]) -> list[str]:
        from mneme.retriever import _upsert_fts_record

        ids = []
        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.cursor()
            for row in rows:
                space = row.get("space") or self.space()
                user_id = str(row.get("user_id") or MEMORY_USER)
                ts = row.get("ts") or "2026-01-01 12:00:00"
                cur.execute(
                    "INSERT INTO memories (id, group_shared_space, user_id, type, content, status, "
                    "confidence, importance, visibility, created_at, updated_at, last_confirmed_at) "
                    "VALUES (?, ?, ?, 'FACT', ?, ?, 0.9, 0.6, ?, ?, ?, ?)",
                    (row["id"], space, user_id, row["content"], row.get("status", "active"),
                     row.get("visibility", "OPEN"), ts, ts, ts),
                )
                # Index every row (also archived/expired/cross-space): the status,
                # scope and visibility predicates must hold even when FTS matches.
                _upsert_fts_record(cur, row["id"], space, user_id, row["content"])
                ids.append(row["id"])
            conn.commit()
        finally:
            conn.close()
        return ids

    def add_candidate(
        self, cand_id: str, content: str, status: str = "observing", user_id: str = MEMORY_USER
    ) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "INSERT INTO memory_candidates (id, group_shared_space, user_id, type, content, "
                "importance, confidence, status, visibility) VALUES (?, ?, ?, 'FACT', ?, 0.6, 0.5, ?, 'OPEN')",
                (cand_id, self.space(), str(user_id), content, status),
            )
            conn.commit()
        finally:
            conn.close()


CHANNELS = ("rule", "fts", "embedding", "hybrid")
EMBEDDING_CHANNELS = {"embedding", "hybrid"}


class Retrieval:
    """Production retrieval per channel (same RAG/embedding matrix as ``memory_eval.answer``).

    ``rule``/``fts`` use ``retrieve_memories`` (no query-relevance term without an
    external semantic score); ``embedding``/``hybrid`` use ``retrieve_memories_emb``
    with a metered embedding service whose auto-start fallback is disabled. Each
    call reports how many embedding requests failed, so a silent rule fallback is
    visible per row.
    """

    def __init__(self, service: Any = None):
        self.service = service

    async def __call__(self, space: str, user_id: str | int, query: str,
                       channel: str) -> tuple[Any, dict[str, Any]]:
        import mneme.retrieval_v2 as rv2

        if channel not in CHANNELS:
            raise ValueError(f"unsupported B05 channel {channel!r}")
        if channel in EMBEDDING_CHANNELS and self.service is None:
            raise ValueError(f"channel {channel!r} requires --embedding-base-url/--embedding-model")
        before = self.service.summary() if self.service is not None else None
        old = (rv2.RAG_ENABLED, rv2.MEMORY_V2_ENABLED)
        try:
            rv2.RAG_ENABLED = channel in ("fts", "hybrid")
            rv2.MEMORY_V2_ENABLED = True
            rv2._CACHE.clear()
            if channel in EMBEDDING_CHANNELS:
                result = await rv2.retrieve_memories_emb(space, user_id, query, trigger="reply",
                                                         service=self.service)
            else:
                result = rv2.retrieve_memories(space, user_id, query, trigger="reply")
        finally:
            rv2.RAG_ENABLED, rv2.MEMORY_V2_ENABLED = old
            rv2._CACHE.clear()
        info: dict[str, Any] = {"embedding_failures": 0, "embedding_calls": 0}
        if before is not None and channel in EMBEDDING_CHANNELS:
            after = self.service.summary()
            info = {"embedding_failures": after["api_failures"] - before["api_failures"],
                    "embedding_calls": after["api_calls"] - before["api_calls"]}
            if after.get("budget_exhausted"):
                from memory_eval.b04 import BudgetExceededError

                raise BudgetExceededError("B05 embedding call budget exhausted")
        return result, info


def memory_section(result: Any) -> str:
    """The production-rendered ``memories`` section (empty when nothing is packed)."""
    from mneme.prompt_builder import build_v2_named_sections

    sections = build_v2_named_sections(
        "", "", result.conversation_memories, result.behavior_constraints,
        current_user_id=None, mode="CASUAL_REPLY",
    )
    return next((text for name, text in sections if name == "memories"), "") or ""


def _pack_ids(result: Any) -> list[str]:
    return [str(m.get("id")) for m in list(result.conversation_memories) + list(result.behavior_constraints)]


def _ranked_ids(result: Any) -> list[str]:
    return [str(r.get("id")) for r in (result.trace or {}).get("ranked_all") or [] if r.get("id")]


# ── checkpoint ────────────────────────────────────────────────────────────


class Checkpoint:
    def __init__(self, path: Path):
        self.path = path
        self.rows: dict[str, dict[str, Any]] = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                self.rows[row["key"]] = row

    def has(self, key: str) -> bool:
        return key in self.rows

    def add(self, row: dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        self.rows[row["key"]] = row

    def task_rows(self, task: str) -> list[dict[str, Any]]:
        return [r for r in self.rows.values() if r["task"] == task]


# ── task: rank ────────────────────────────────────────────────────────────


async def run_rank(items: list[dict[str, Any]], channels: list[str], root: Path, ckpt: Checkpoint,
                   retrieve: Retrieval) -> None:
    for channel in channels:
        for item in items:
            key = f"rank|{channel}|{item['item_id']}"
            if ckpt.has(key):
                continue
            id_of = {f"t{i:02d}": topic for i, topic in enumerate(item["actor"]["candidates"])}
            with MemoryStore(root / "stores" / "rank" / channel / item["item_id"]) as store:
                store.add_memories([{"id": mid, "content": text} for mid, text in id_of.items()])
                result, info = await retrieve(store.space(), MEMORY_USER, item["actor"]["query"], channel)
            scores = sorted({round(float(r.get("score") or 0.0), 6)
                             for r in (result.trace or {}).get("ranked_all") or []})
            ranked = [id_of.get(mid) for mid in _ranked_ids(result)]
            gold = item["scorer"]["gold"]
            rank = ranked.index(gold) + 1 if gold in ranked else None
            ckpt.add({
                "key": key, "task": "rank", "channel": channel, "item_id": item["item_id"],
                "scoreable": item["scorer"]["scoreable"], "gold_rank": rank,
                "ranked_count": len(ranked), "candidate_count": len(id_of),
                "packed_count": len(result.conversation_memories),
                "gold_packed": gold in {id_of.get(m) for m in _pack_ids(result)},
                "retrieval_mode": result.mode,
                "distinct_scores": len(scores),
                **info,
            })


# ── task: boundary ────────────────────────────────────────────────────────


async def run_boundary(items: list[dict[str, Any]], channels: list[str], root: Path, ckpt: Checkpoint,
                       retrieve: Retrieval) -> None:
    forbidden = {
        "m3-archived": "M3",
        "m3-expired": "M3",
        "m4-cross-space": "M4",
        "m4-internal": "M4",
    }
    for channel in channels:
        for item in items:
            if item["polarity"] != "positive":
                continue
            key = f"boundary|{channel}|{item['item_id']}"
            if ckpt.has(key):
                continue
            content = item["scorer"]["ground_truth"]
            with MemoryStore(root / "stores" / "boundary" / channel / item["item_id"]) as store:
                store.add_memories([
                    {"id": "m1-gold", "content": content},
                    {"id": "m3-archived", "content": content, "status": "archived"},
                    {"id": "m3-expired", "content": content, "status": "expired"},
                    {"id": "m4-cross-space", "content": content, "space": store.space(CROSS_GROUP_ID)},
                    {"id": "m4-internal", "content": content, "visibility": "INTERNAL"},
                ])
                store.add_candidate("m5-observing", content)
                result, info = await retrieve(store.space(), MEMORY_USER, item["actor"]["trigger"], channel)
            packed = _pack_ids(result)
            same_content = sum(
                1 for m in list(result.conversation_memories) + list(result.behavior_constraints)
                if str(m.get("content") or "") == content
            )
            violations = sorted({forbidden[m] for m in packed if m in forbidden})
            if "m5-observing" in packed or same_content > 1:
                violations.append("M5_OR_DUPLICATE")
            ckpt.add({
                "key": key, "task": "boundary", "channel": channel, "item_id": item["item_id"],
                "packed_ids": packed, "gold_packed": "m1-gold" in packed,
                "same_content_in_pack": same_content, "violations": violations,
                "retrieval_mode": result.mode, **info,
            })


# ── model clients ─────────────────────────────────────────────────────────


def _chat(llm: Any, budget: RunBudget, role: str, user: str, system: str | None,
          max_tokens: int) -> dict[str, Any]:
    from memory_eval.b04 import BudgetExceededError
    from memory_eval.llm import EvalLLMError

    try:
        out = llm.chat(user, system=system, max_tokens=max_tokens, temperature=0.0)
    except BudgetExceededError:
        raise
    except EvalLLMError as exc:
        return {"ok": False, "error": str(exc)[:300]}
    if out.get("completion_tokens", 0) >= max_tokens:
        budget.record_truncation(role)
    return {"ok": True, **out}


# ── task: joint ───────────────────────────────────────────────────────────


def _memuse_condition_rows(item: dict[str, Any], condition: str, corpus: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if condition == "M0":
        return []
    if condition == "M1":
        rows = data.memuse_gold_memory(item)
    elif condition == "MS":
        rows = data.memuse_summary_store(corpus, item["actor"]["user_id"], item["actor"]["trigger_session_idx"])
    else:
        raise ValueError(condition)
    return [{"id": r["memory_key"], "content": r["content"], "ts": r["ts"],
             "user_id": item["actor"]["user_id"]} for r in rows]


async def _generate_and_judge(
    *, task: str, key: str, item: dict[str, Any], condition: str, user_id: str | int, store_dir: Path,
    memories: list[dict[str, Any]], query: str, channel: str, reply_builder: Any,
    reply_turns: Any, judge_builder: Any, judge_fields: tuple[str, ...],
    llms: dict[str, Any], budget: RunBudget, args: argparse.Namespace, ckpt: Checkpoint,
    retrieve: Retrieval, extra: dict[str, Any] | None = None, space: str | None = None,
    existing_env: Any = None,
) -> None:
    if existing_env is None:
        with MemoryStore(store_dir) as store:
            store.add_memories(memories)
            result, info = await retrieve(store.space(), user_id, query, channel)
    else:
        result, info = await retrieve(space, user_id, query, channel)
    pack = memory_section(result)
    system, user = reply_builder(pack, reply_turns)
    reply = _chat(llms["reply"], budget, "reply", user, system, args.max_reply_tokens)
    row: dict[str, Any] = {
        "key": key, "task": task, "item_id": item["item_id"], "cluster": item["cluster"],
        "condition": condition, "channel": channel,
        "injected_count": len(memories), "packed_ids": _pack_ids(result),
        "pack_memory_count": len(result.conversation_memories), "pack_chars": len(pack),
        "retrieval_mode": result.mode, **info, **(extra or {}),
    }
    if not reply["ok"]:
        row.update({"generation": "FAILED", "error": reply["error"], "judge": {"parse_status": "not_run"}})
        ckpt.add(row)
        return
    text = reply["text"].strip()
    row.update({
        "generation": "GENERATED" if text else "EMPTY",
        "reply": text,
        "reply_prompt_tokens": reply["prompt_tokens"],
        "reply_completion_tokens": reply["completion_tokens"],
    })
    judge = _chat(llms["judge"], budget, "judge", judge_builder(item, text), None, args.max_judge_tokens)
    if judge["ok"]:
        row["judge"] = prompts.parse_judge(judge["text"], judge_fields)
        row["judge_raw"] = judge["text"][:400]
    else:
        row["judge"] = {**dict.fromkeys(judge_fields), "parse_status": "judge_failed"}
        row["judge_error"] = judge["error"]
    ckpt.add(row)


async def run_joint(memuse: list[dict[str, Any]], corpus: list[dict[str, Any]], chmap_points: list[dict[str, Any]],
                    args: argparse.Namespace, root: Path, ckpt: Checkpoint, llms: dict[str, Any],
                    budget: RunBudget, retrieve: Retrieval) -> None:
    for item in memuse:
        conditions = ("M0", "M1", "MS") if item["polarity"] == "positive" else ("M0", "MS")
        for condition in conditions:
            key = f"joint|memuse|{item['item_id']}|{condition}"
            if ckpt.has(key):
                continue
            fields = ("integration", "referenced", "fabricated") if item["polarity"] == "positive" \
                else ("unprompted_recall", "fabricated_recall")
            await _generate_and_judge(
                task="joint-memuse", key=key, item=item, condition=condition,
                user_id=item["actor"]["user_id"],
                store_dir=root / "stores" / "joint" / item["item_id"] / condition,
                memories=_memuse_condition_rows(item, condition, corpus),
                query=item["actor"]["trigger"], channel=args.channel,
                reply_builder=prompts.build_memuse_reply, reply_turns=item["actor"]["current_turns"],
                judge_builder=(prompts.build_memuse_judge_pos if item["polarity"] == "positive"
                               else prompts.build_memuse_judge_neg),
                judge_fields=fields, llms=llms, budget=budget, args=args, ckpt=ckpt, retrieve=retrieve,
                extra={"polarity": item["polarity"], "pair_id": item["pair_id"],
                       "fact_count": len(item["scorer"].get("sub_questions") or [])},
            )
    for point in chmap_points:
        for condition in ("M0", "M1", "M2"):
            key = f"joint|chmap|{point['item_id']}|{condition}"
            if ckpt.has(key):
                continue
            memories = [
                {"id": m["memory_key"], "content": m["content"]}
                for m in data.chmap_memories(point, condition)
            ]
            await _generate_and_judge(
                task="joint-chmap", key=key, item=point, condition=condition,
                user_id=MEMORY_USER,
                store_dir=root / "stores" / "joint" / point["item_id"] / condition,
                memories=memories, query=point["actor"]["turns"][-1]["text"], channel=args.channel,
                reply_builder=prompts.build_chmap_reply, reply_turns=point["actor"]["turns"],
                judge_builder=prompts.build_chmap_judge,
                judge_fields=("callback", "other_topic", "fabricated"),
                llms=llms, budget=budget, args=args, ckpt=ckpt, retrieve=retrieve,
                extra={"label": point["scorer"]["label"]},
            )


# ── task: pairing (T0 / T3 / guard) ──────────────────────────────────────


class _GuardedReplyLLM:
    """Add B05-only handling for retrieved memory without changing shared prompts."""

    def __init__(self, llm: Any, guard: str):
        self.llm = llm
        self.guard = guard

    def chat(self, user: str, system: str | None = None, **kwargs: Any) -> dict[str, Any]:
        return self.llm.chat(f"{self.guard}\n\n{user}", system=system, **kwargs)


def select_pairing_questions(memuse: list[dict[str, Any]], seed: int) -> list[dict[str, Any]]:
    rows = []
    for item in memuse:
        if item["polarity"] != "positive":
            continue
        subs = item["scorer"]["sub_questions"]
        rng = random.Random(f"{seed}:pairing:{item['item_id']}")
        index = rng.randrange(len(subs))
        rows.append({"item": item, "qid": f"{item['item_id']}-q{index}",
                     "question": subs[index]["question"], "gold_answer": subs[index]["answer"]})
    return rows


PAIRING_CELLS = {
    "T0": {"pack_level": "T0", "sufficiency_guard": False},
    "T3": {"pack_level": "T3", "sufficiency_guard": False},
    "T0_GUARD": {"pack_level": "T0", "sufficiency_guard": True},
}


async def run_pairing(questions: list[dict[str, Any]], corpus: list[dict[str, Any]],
                      args: argparse.Namespace, root: Path, ckpt: Checkpoint,
                      llms: dict[str, Any], budget: RunBudget, retrieve: Retrieval) -> None:
    from memory_eval.answer import answer_question
    from memory_eval.b04 import BudgetExceededError
    from memory_eval.judge import build_judge_prompt, parse_verdict
    from memory_eval.llm import EvalLLMError

    reply_llm = _GuardedReplyLLM(llms["reply"], prompts.ANSWER_MEMORY_GUARD)
    for q in questions:
        item = q["item"]
        scenario = {
            "group_id": GROUP_ID,
            "speakers": {"a": "the user"},
            "user_ids": {"a": str(item["actor"]["user_id"])},
        }
        for cell, opts in PAIRING_CELLS.items():
            key = f"pairing|{q['qid']}|{cell}"
            if ckpt.has(key):
                continue
            rows = _memuse_condition_rows(item, "MS", corpus)
            row: dict[str, Any] = {"key": key, "task": "pairing", "item_id": item["item_id"],
                                   "cluster": item["cluster"], "qid": q["qid"], "cell": cell,
                                   "channel": args.channel, "injected_count": len(rows)}
            with MemoryStore(root / "stores" / "pairing" / q["qid"] / cell) as store:
                store.add_memories(rows)
                try:
                    record = await answer_question(
                        store.env, scenario, {"qid": q["qid"], "question": q["question"]},
                        channel=args.channel, llm=reply_llm, service=retrieve.service,
                        user_id=item["actor"]["user_id"], **opts,
                    )
                except BudgetExceededError:
                    raise
                except EvalLLMError as exc:
                    row.update({"generation": "FAILED", "error": str(exc)[:300], "verdict": None})
                    ckpt.add(row)
                    continue
            row.update({
                "generation": "GENERATED",
                "answer": record["answer"],
                "sufficiency": record.get("sufficiency"),
                "pack_memory_count": record.get("pack_memory_count"),
                "retrieved_ids": [str(v) for v in record.get("retrieved_ids") or []],
            })
            judge = _chat(llms["judge"], budget, "judge",
                          build_judge_prompt(q["question"], q["gold_answer"], record["answer"]),
                          None, args.max_judge_tokens)
            row["verdict"] = parse_verdict(judge["text"])["verdict"] if judge["ok"] else None
            ckpt.add(row)


# ── task: m6 (real write side) ────────────────────────────────────────────


def memuse_scenario(item: dict[str, Any], raw_row: dict[str, Any], group_id: int) -> dict[str, Any]:
    """MemUse prior sessions as a LoCoMo-shaped two-member scenario for B04's production track."""
    speakers = {"a": "diary-user", "b": "diary-companion"}
    user_ids = {"a": "9310001", "b": "9310002"}
    sessions = []
    for session in raw_row["input"]["sessions"]:
        idx = int(session["session_idx"])
        messages = []
        for n, turn in enumerate(session.get("turns") or []):
            side = "a" if turn["role"] == "user" else "b"
            messages.append({"dia_id": f"S{idx}:{n + 1}", "speaker": speakers[side],
                             "user_id": user_ids[side], "text": str(turn["content"])})
        sessions.append({"session_id": idx + 1, "ts": data.parse_memuse_date(session["date"]),
                         "ts_source": "dataset", "messages": messages})
    sid = f"memuse-{item['item_id']}"
    return {
        "schema": "memory-eval-locomo-scenario/1", "scenario_id": sid, "sample_id": sid,
        "group_id": group_id, "conversation_key": f"qq:stella-bench:group:{group_id}",
        "bot_id": "stella-bench", "speakers": speakers, "user_ids": user_ids,
        "sessions": sessions, "qa": [],
    }


def select_m6_pairs(memuse: list[dict[str, Any]], raw: dict[str, dict[str, Any]], pairs: int) -> list[str]:
    """Smallest-history positive/negative pairs first (bounded smoke cost)."""
    by_pair: dict[str, int] = {}
    for item in memuse:
        turns = sum(len(s.get("turns") or []) for s in raw[item["item_id"]]["input"]["sessions"])
        by_pair[item["pair_id"]] = by_pair.get(item["pair_id"], 0) + turns
    ordered = sorted(by_pair, key=lambda p: (by_pair[p], p))
    return ordered[:max(0, pairs)]


async def run_m6(memuse: list[dict[str, Any]], raw: dict[str, dict[str, Any]], args: argparse.Namespace,
                 root: Path, ckpt: Checkpoint, llms: dict[str, Any], budget: RunBudget,
                 meta: dict[str, Any], retrieve: Retrieval) -> list[dict[str, Any]]:
    from memory_eval.b04 import _run_track, _save_meta
    from memory_eval.b04_ingress import ProductionReplayEnv

    chosen = set(select_m6_pairs(memuse, raw, args.m6_pairs))
    track_args = argparse.Namespace(
        stage="ingest", mode="rule", pack_mode="auto", consolidation="oracle",
        embedding_base_url=None, embedding_model=None,
    )
    summaries = []
    m6_root = root / "m6"
    m6_root.mkdir(parents=True, exist_ok=True)
    meta.setdefault("m6", {"inserted_sessions": {}, "backend_roles": {}, "capture_gates": {}})
    for offset, item in enumerate(i for i in memuse if i["pair_id"] in chosen):
        group_id = 881000 + offset
        scenario = memuse_scenario(item, raw[item["item_id"]], group_id)
        track = await _run_track(track_args, scenario, "production", m6_root, meta["m6"], budget,
                                 None, None, [])
        _save_meta(root, meta)
        summaries.append({
            "item_id": item["item_id"], "polarity": item["polarity"], "pair_id": item["pair_id"],
            "sessions": track["inserted_sessions"], "funnel": track["funnel"],
            "admission_capture_counts": track["admission_capture_counts"],
            "capture_gate_state": (track.get("capture_gate") or {}).get("state"),
            "messages": sum(len(s["messages"]) for s in scenario["sessions"]),
        })
        key = f"m6|{item['item_id']}|M6"
        if ckpt.has(key):
            continue
        env = ProductionReplayEnv(m6_root / "production" / scenario["scenario_id"], scenario)
        with env.session():
            from config.spaces import resolve_space

            fields = ("integration", "referenced", "fabricated") if item["polarity"] == "positive" \
                else ("unprompted_recall", "fabricated_recall")
            await _generate_and_judge(
                task="m6", key=key, item=item, condition="M6", store_dir=env.workdir,
                user_id="9310001",
                memories=[], query=item["actor"]["trigger"], channel=args.channel,
                reply_builder=prompts.build_memuse_reply, reply_turns=item["actor"]["current_turns"],
                judge_builder=(prompts.build_memuse_judge_pos if item["polarity"] == "positive"
                               else prompts.build_memuse_judge_neg),
                judge_fields=fields, llms=llms, budget=budget, args=args, ckpt=ckpt, retrieve=retrieve,
                extra={"polarity": item["polarity"], "pair_id": item["pair_id"],
                       "fact_count": len(item["scorer"].get("sub_questions") or []),
                       "store_memories_active": track["funnel"].get("memories_active")},
                space=resolve_space(group_id), existing_env=env,
            )
    return summaries


# ── aggregation ───────────────────────────────────────────────────────────


def _judge_value(row: dict[str, Any], field: str) -> bool | None:
    if row.get("generation") != "GENERATED":
        return None
    return (row.get("judge") or {}).get(field)


def _paired(rows: list[dict[str, Any]], control: str, treatment: str, field: str,
            args: argparse.Namespace, *, filt: Any = None, cond_key: str = "condition") -> dict[str, Any]:
    by_item: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        if filt is not None and not filt(row):
            continue
        by_item.setdefault(row.get("qid") or row["item_id"], {})[row[cond_key]] = row
    pairs = []
    unscored = 0
    for cells in by_item.values():
        if control not in cells or treatment not in cells:
            continue
        a = _judge_value(cells[control], field) if field != "verdict" else _verdict(cells[control])
        b = _judge_value(cells[treatment], field) if field != "verdict" else _verdict(cells[treatment])
        if a is None or b is None:
            unscored += 1
            continue
        pairs.append((cells[control]["cluster"], float(a), float(b)))
    out = data.paired_cluster_bootstrap(pairs, replicates=args.bootstrap_replicates, seed=args.seed)
    out.update({"control": control, "treatment": treatment, "metric": field,
                "pairs_excluded_unscored": unscored})
    return out


def _verdict(row: dict[str, Any]) -> bool | None:
    v = row.get("verdict")
    return None if v not in ("correct", "incorrect") else v == "correct"


def aggregate(ckpt: Checkpoint, args: argparse.Namespace, rank_items: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    rank_rows = ckpt.task_rows("rank")
    if rank_rows:
        out["chmap_topic_rank"] = {
            channel: {
                **data.rank_metrics([r for r in rank_rows if r["channel"] == channel]),
                "gold_packed": sum(1 for r in rank_rows if r["channel"] == channel and r["gold_packed"]),
                "mean_ranked_count": round(
                    sum(r["ranked_count"] for r in rank_rows if r["channel"] == channel)
                    / max(1, sum(1 for r in rank_rows if r["channel"] == channel)), 2),
            }
            for channel in sorted({r["channel"] for r in rank_rows})
        }
        out["chmap_topic_rank_baselines"] = {
            "uniform_random_expected": data.random_rank_baseline(rank_items),
            "released_order_leakage_indicator": data.released_order_baseline(rank_items),
        }
    b_rows = ckpt.task_rows("boundary")
    if b_rows:
        out["boundary"] = {
            channel: {
                "items": sum(1 for r in b_rows if r["channel"] == channel),
                "items_with_violation": sum(1 for r in b_rows if r["channel"] == channel and r["violations"]),
                "violations_by_family": _family_counts([r for r in b_rows if r["channel"] == channel]),
                "gold_packed": sum(1 for r in b_rows if r["channel"] == channel and r["gold_packed"]),
            }
            for channel in sorted({r["channel"] for r in b_rows})
        }
    mu = ckpt.task_rows("joint-memuse") + ckpt.task_rows("m6")
    if mu:
        out["memuse_natural"] = _memuse_summary(mu, args)
    ch = ckpt.task_rows("joint-chmap")
    if ch:
        out["chmap_callback"] = _chmap_summary(ch, args)
    pr = ckpt.task_rows("pairing")
    if pr:
        cells = {}
        for cell in PAIRING_CELLS:
            rows = [r for r in pr if r["cell"] == cell]
            cells[cell] = {
                **data.binary_summary([_verdict(r) for r in rows]),
                "sufficiency": _counts(r.get("sufficiency") for r in rows if cell == "T0_GUARD"),
                "mean_pack_memory_count": round(
                    sum(r.get("pack_memory_count") or 0 for r in rows) / max(1, len(rows)), 2),
            }
        out["direct_qa_pairing"] = {
            "cells": cells,
            "T3_minus_T0": _paired(pr, "T0", "T3", "verdict", args, cond_key="cell"),
            "GUARD_minus_T0": _paired(pr, "T0", "T0_GUARD", "verdict", args, cond_key="cell"),
            "abstention_benefit": "NOT_APPLICABLE: MemUse sub-questions are all answerable",
        }
    return out


def _counts(values: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in values:
        out[str(v)] = out.get(str(v), 0) + 1
    return out


def _family_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    out = {"M3": 0, "M4": 0, "M5_OR_DUPLICATE": 0}
    for r in rows:
        for v in r["violations"]:
            out[v] = out.get(v, 0) + 1
    return out


def _memuse_summary(rows: list[dict[str, Any]], args: argparse.Namespace) -> dict[str, Any]:
    out: dict[str, Any] = {"positive": {}, "negative": {}}
    for polarity in ("positive", "negative"):
        prow = [r for r in rows if r.get("polarity") == polarity]
        for cond in sorted({r["condition"] for r in prow}):
            crow = [r for r in prow if r["condition"] == cond]
            cell: dict[str, Any] = {
                "generation": _counts(r.get("generation") for r in crow),
                "judge_parse": _counts((r.get("judge") or {}).get("parse_status") for r in crow),
                "mean_pack_memory_count": round(sum(r["pack_memory_count"] for r in crow) / len(crow), 2),
                "packed_any": sum(1 for r in crow if r["pack_memory_count"] > 0),
            }
            if polarity == "positive":
                cell["integration"] = data.binary_summary([_judge_value(r, "integration") for r in crow])
                cell["fabricated"] = data.binary_summary([_judge_value(r, "fabricated") for r in crow])
                facts = sum(r.get("fact_count") or 0 for r in crow)
                referenced = sum(
                    len([i for i in ((r.get("judge") or {}).get("referenced") or [])
                         if 1 <= i <= (r.get("fact_count") or 0)])
                    for r in crow if r.get("generation") == "GENERATED"
                )
                cell["fact_reference"] = {"facts": facts, "referenced": referenced,
                                          "rate": round(referenced / facts, 4) if facts else None}
            else:
                cell["unprompted_recall"] = data.binary_summary([_judge_value(r, "unprompted_recall") for r in crow])
                cell["fabricated_recall"] = data.binary_summary([_judge_value(r, "fabricated_recall") for r in crow])
                cell["overuse_any"] = data.binary_summary([_overuse(r) for r in crow])
            out[polarity][cond] = cell
    pos = [r for r in rows if r.get("polarity") == "positive"]
    neg = [r for r in rows if r.get("polarity") == "negative"]
    neg_over = [{**r, "judge": {**(r.get("judge") or {}), "overuse_any": _overuse(r)}} for r in neg]
    out["paired"] = {
        "integration_M1_minus_M0": _paired(pos, "M0", "M1", "integration", args),
        "integration_MS_minus_M0": _paired(pos, "M0", "MS", "integration", args),
        "integration_M6_minus_M0": _paired(pos, "M0", "M6", "integration", args),
        "overuse_MS_minus_M0_negatives": _paired(neg_over, "M0", "MS", "overuse_any", args),
        "overuse_M6_minus_M0_negatives": _paired(neg_over, "M0", "M6", "overuse_any", args),
    }
    return out


def _overuse(row: dict[str, Any]) -> bool | None:
    a = _judge_value(row, "unprompted_recall")
    b = _judge_value(row, "fabricated_recall")
    if a is True or b is True:
        return True
    if a is None or b is None:
        return None
    return False


def _chmap_summary(rows: list[dict[str, Any]], args: argparse.Namespace) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for label in ("yes", "no"):
        lrow = [r for r in rows if r.get("label") == label]
        out[f"label_{label}"] = {
            cond: {
                "callback": data.binary_summary([_judge_value(r, "callback") for r in lrow if r["condition"] == cond]),
                "other_topic": data.binary_summary([_judge_value(r, "other_topic") for r in lrow if r["condition"] == cond]),
                "fabricated": data.binary_summary([_judge_value(r, "fabricated") for r in lrow if r["condition"] == cond]),
                "judge_parse": _counts((r.get("judge") or {}).get("parse_status") for r in lrow if r["condition"] == cond),
            }
            for cond in ("M0", "M1", "M2")
        }
    yes = [r for r in rows if r.get("label") == "yes"]
    no = [r for r in rows if r.get("label") == "no"]
    out["paired"] = {
        "callback_on_yes_M1_minus_M0": _paired(yes, "M0", "M1", "callback", args),
        "premature_callback_on_no_M1_minus_M0": _paired(no, "M0", "M1", "callback", args),
        "irrelevant_topic_intrusion_M2_minus_M0": _paired(rows, "M0", "M2", "other_topic", args),
    }
    return out


# ── run ───────────────────────────────────────────────────────────────────


def _effective_config(args: argparse.Namespace, tasks: list[str], datasets: dict[str, Any],
                      selection: dict[str, Any], retrieval_backend: dict[str, Any],
                      model_preflight: dict[str, Any]) -> dict[str, Any]:
    from memory_eval.b04 import _safe_endpoint, _sha256

    code = {name: _sha256(Path(__file__).with_name(name)) for name in ("b05.py", "b05_data.py", "b05_prompts.py")}
    for name in ("answer.py", "judge.py", "sufficiency.py", "pack_representation.py",
                 "b04.py", "b04_ingress.py", "isolation.py"):
        code[f"memory_eval/{name}"] = _sha256(_REPO / "memory_eval" / name)
    for name in ("mneme/retrieval_v2.py", "mneme/retriever.py", "mneme/prompt_builder.py",
                 "memory_rust/selector.py", "memory_rust/backend.py", "memory_rust/python_backend.py"):
        code[name] = _sha256(_REPO / name)
    cfg: dict[str, Any] = {
        "fingerprint_schema": FINGERPRINT_SCHEMA,
        "adapter_version": data.ADAPTER_VERSION,
        "tasks": tasks,
        "datasets": datasets,
        "selection": selection,
        "retrieval_backend": retrieval_backend,
        "model_preflight": model_preflight,
        "channel": args.channel,
        "rank_channels": args.rank_channels,
        "embedding_model": {"base_url": _safe_endpoint(args.embedding_base_url), "model": args.embedding_model},
        "seed": args.seed,
        "bootstrap_replicates": args.bootstrap_replicates,
        "prompt_sha256": prompts.prompt_digest(),
        "budget": {"max_model_calls": args.max_calls, "max_runtime_seconds": args.max_runtime_seconds},
        "code_fingerprint": code,
    }
    if MODEL_TASKS & set(tasks):
        cfg["reply_model"] = {"base_url": _safe_endpoint(args.llm_base_url), "model": args.llm_model,
                              "reasoning_effort": args.llm_reasoning_effort,
                              "max_tokens": args.max_reply_tokens}
        cfg["judge_model"] = {"model": args.judge_model or args.llm_model,
                              "max_tokens": args.max_judge_tokens,
                              "same_as_reply_model": (args.judge_model or args.llm_model) == args.llm_model}
    if "m6" in tasks:
        from memory_eval.b04 import _memory_backend_identity

        cfg["m6"] = {"pairs": args.m6_pairs, "memory_backend": _memory_backend_identity(args)}
    return cfg


def _check_meta(workdir: Path, fingerprint: str, resume: bool) -> dict[str, Any]:
    path = workdir / "meta.json"
    if not path.exists():
        if resume:
            raise ValueError("--resume requires an existing B05 meta.json")
        if workdir.exists() and any(path.name != "home" for path in workdir.iterdir()):
            raise ValueError("workdir is not empty; use --resume or choose a new directory")
        return {"schema": FINGERPRINT_SCHEMA, "fingerprint": fingerprint, "created_at": _utcnow()}
    if not resume:
        raise ValueError("workdir already contains a run; pass --resume")
    meta = json.loads(path.read_text(encoding="utf-8"))
    if meta.get("schema") != FINGERPRINT_SCHEMA or meta.get("fingerprint") != fingerprint:
        raise ValueError("resume fingerprint mismatch; start a new workdir")
    return meta


async def run(args: argparse.Namespace) -> int:
    from memory_eval.b04 import BudgetExceededError, _json_digest, _save_meta
    from memory_eval.isolation import ensure_eval_home

    workdir = args.workdir.resolve()
    if workdir == _REPO or _REPO in workdir.parents:
        raise ValueError("workdir must be outside the repository (per-case outputs stay unpublished)")
    tasks, rank_channels, used = validate_args(args)
    if args.resume:
        if not (workdir / "meta.json").is_file():
            raise ValueError("--resume requires an existing B05 meta.json")
    elif workdir.exists() and any(workdir.iterdir()):
        raise ValueError("workdir is not empty; use --resume or choose a new directory")

    registry = json.loads((_REPO / "proactive_eval" / "dataset-registry.json").read_text(encoding="utf-8"))
    datasets = {"memuse": data.verify_memuse(registry, _REPO),
                "chmap": data.verify_chmap(registry, _REPO / _RAW)}
    memuse_dir = _REPO / _RAW / "memuse" / "data"
    memuse = data.load_memuse(memuse_dir)
    for item in memuse:
        leaks = data.actor_leaks(item["actor"], item["scorer"])
        if leaks:
            raise data.DataIntegrityError(f"{item['item_id']}: scorer text leaks into actor view")
    corpus = data.read_jsonl(memuse_dir / "sessions.train.jsonl")
    raw_rows = {
        str(r["instance_id"]): r
        for name in ("instances.test.jsonl", "negatives.test.jsonl")
        for r in data.read_jsonl(memuse_dir / name)
    }
    rank_items = data.load_chmap_rank(_REPO / _RAW / "chmap-data" / "topic_rank" / "test.json", seed=args.seed)
    all_points = data.load_chmap_callback(_REPO / _RAW / "chmap-data" / "overall_dialouge_view" / "test.json")
    chmap_points = data.select_chmap_points(all_points, args.chmap_records, args.seed)
    memuse_sel = memuse if args.memuse_pairs <= 0 else [
        i for i in memuse if i["pair_id"] in sorted({x["pair_id"] for x in memuse})[:args.memuse_pairs]
    ]
    pairing_questions = select_pairing_questions(memuse_sel, args.seed)
    selection = {
        "memuse_items": [i["item_id"] for i in memuse_sel],
        "chmap_points": [p["item_id"] for p in chmap_points],
        "chmap_records_requested": args.chmap_records,
        "chmap_points_total": len(all_points),
        "pairing_qids": [q["qid"] for q in pairing_questions],
        "rank_items": len(rank_items),
    }
    model_preflight = _model_preflight(args, tasks)

    # Must happen before importing modules that may load config or memory paths.
    ensure_eval_home(workdir)
    retrieval_backend = _retrieval_backend_identity()
    effective = _effective_config(args, tasks, datasets, selection, retrieval_backend, model_preflight)
    fingerprint = _json_digest(effective)
    meta = _check_meta(workdir, fingerprint, args.resume)
    workdir.mkdir(parents=True, exist_ok=True)
    _save_meta(workdir, meta)

    if "m6" in tasks:
        from memory_eval.b04 import (
            _apply_memory_backend_overrides,
            _memory_backend_overrides,
        )

        _apply_memory_backend_overrides(_memory_backend_overrides(args))
    budget = RunBudget(args.max_calls, args.max_runtime_seconds)
    llms: dict[str, Any] = {}
    if MODEL_TASKS & set(tasks):
        from memory_eval.b04 import BudgetedEvalLLM
        from memory_eval.llm import EvalLLM

        inner = EvalLLM(args.llm_base_url, args.llm_model, args.llm_api_key, timeout=300.0)
        judge_inner = inner if not args.judge_model or args.judge_model == args.llm_model else EvalLLM(
            args.llm_base_url, args.judge_model, args.llm_api_key, timeout=300.0)
        llms["reply"] = BudgetedEvalLLM(inner, budget, "reply", args.max_reply_tokens,
                                        reasoning_effort=args.llm_reasoning_effort)
        llms["judge"] = BudgetedEvalLLM(judge_inner, budget, "judge", args.max_judge_tokens,
                                        reasoning_effort=args.llm_reasoning_effort)

    service = None
    if used & EMBEDDING_CHANNELS:
        from memory_eval.b04 import BudgetedEmbeddingService

        service = BudgetedEmbeddingService(args.embedding_base_url, args.embedding_model, budget)
    retrieve = Retrieval(service)
    ckpt = Checkpoint(workdir / "results.jsonl")
    errors: list[dict[str, str]] = []
    m6_summary: list[dict[str, Any]] = []
    task_status: dict[str, str] = {}
    for task in tasks:
        try:
            budget.check_time()
            if task == "rank":
                await run_rank(rank_items, rank_channels, workdir, ckpt, retrieve)
            elif task == "boundary":
                await run_boundary(memuse_sel, rank_channels, workdir, ckpt, retrieve)
            elif task == "joint":
                await run_joint(memuse_sel, corpus, chmap_points, args, workdir, ckpt, llms, budget, retrieve)
            elif task == "pairing":
                await run_pairing(pairing_questions, corpus, args, workdir, ckpt, llms, budget, retrieve)
            elif task == "m6":
                m6_summary = await run_m6(memuse_sel, raw_rows, args, workdir, ckpt, llms, budget, meta,
                                          retrieve)
            task_status[task] = "COMPLETE"
        except BudgetExceededError as exc:
            task_status[task] = "PARTIAL_BUDGET"
            errors.append({"task": task, "error_type": type(exc).__name__, "message": str(exc)[:300]})
            break
        except Exception as exc:
            task_status[task] = "FAILED"
            errors.append({"task": task, "error_type": type(exc).__name__, "message": str(exc)[:300]})
            break
        finally:
            _save_meta(workdir, meta)
    for task in tasks:
        task_status.setdefault(task, "NOT_RUN")

    report = {
        "report_schema": REPORT_SCHEMA,
        "generated_at": _utcnow(),
        "git_head": _git_head(),
        "run_fingerprint": fingerprint,
        "fingerprint_inputs": effective,
        "status": "MEASURED_IN_SCOPE" if not errors else "PARTIAL",
        "task_status": task_status,
        "errors": errors,
        "retrieval_backend": retrieval_backend,
        "model_preflight": model_preflight,
        "embedding": service.summary() if service is not None else {"requested": False},
        "budget": {
            "max_model_calls": budget.max_calls,
            "model_calls_reserved": len(budget.calls),
            "model_calls_by_role": _count_by_role(budget.calls),
            "truncated_generations_by_role": _count_by_role(budget.truncated_generations),
            "max_runtime_seconds": budget.max_seconds,
            "elapsed_seconds": round(budget.elapsed, 3),
        },
        "reply_model": llms["reply"].cost_summary() if llms else None,
        "results": aggregate(ckpt, args, rank_items),
        "m6_write_side": m6_summary or None,
        "rows_by_task": _counts(r["task"] for r in ckpt.rows.values()),
        "structural_notes": [
            "Aoede ParticipationManager reads no memory content (only an embedding similarity service), "
            "so memory cannot change the speak/silent decision; decision-layer system benefit is "
            "NOT_APPLICABLE on this branch and every model cell is a fixed-decision content measurement.",
        ],
        "limitations": [
            "Reply/judge prompts are evaluation-only (versioned and hashed); they are not the production "
            "reply prompt and load no persona or user configuration.",
            "The judge is the same local model as the replier unless --judge-model differs: self-evaluation "
            "bias is possible; no human agreement study was run (B06).",
            "MemUse is English and its official judge (GPT-5.4-nano) was not used; numbers are not comparable "
            "to the dataset card's reference table.",
            "M1 conditions read scorer gold (MemUse ground truth, ChMap callback-day pointer): oracle upper bounds, "
            "never product scores.",
            "MS is the deployed diary system's own per-session summaries before the trigger session, retrieved "
            "by production retrieval; whether the needed fact is inside a summary is not adjudicated.",
            "ChMap callback memories are past-day topic headers; naturalness is not scored here (B06 blind review).",
            "Endpoint model IDs were checked with a metadata-only /models request; server revision and quantization are not exposed by this contract.",
            "M6 replays a 1:1 diary as a two-member group (companion turns as the second member); BOT_SELF "
            "semantics are not modelled.",
            "LoCoMo-Conv stays BLOCKED_DATA (license unresolved); ChMap dialogue_data (topic summarisation) is "
            "out of the memory-use scope and NOT_RUN.",
        ],
    }
    out_dir = (args.out or (workdir / "report")).resolve()
    path = out_dir / "proactive_b05_report.json"
    report_sha256 = _write_report(path, report)
    print(f"B05 report: {path} sha256={report_sha256}")
    return 0 if not errors else 1


def _write_report(path: Path, report: dict[str, Any]) -> str:
    from jsonschema import Draft202012Validator

    schema_path = Path(__file__).with_name("schemas") / "stella-proactive-b05-report-1.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(report)
    payload = (json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        Path(temp_name).replace(path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise
    return hashlib.sha256(payload).hexdigest()


def _git_head() -> str | None:
    from memory_eval.b04 import _git_head as head

    return head()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="B05 memory natural-use benchmark")
    p.add_argument("--workdir", type=Path, required=True)
    p.add_argument("--out", type=Path, default=None)
    p.add_argument("--tasks", default="rank,boundary")
    p.add_argument("--channel", choices=CHANNELS, default=None,
                   help="explicit retrieval channel for joint/pairing/m6 cells")
    p.add_argument("--rank-channels", default="rule,fts")
    p.add_argument("--embedding-base-url", default=None, help="explicit base URL without /v1")
    p.add_argument("--embedding-model", default=None)
    p.add_argument("--chmap-records", type=int, default=30)
    p.add_argument("--memuse-pairs", type=int, default=0, help="0 = all 72 pairs")
    p.add_argument("--m6-pairs", type=int, default=2)
    p.add_argument("--seed", type=int, default=20261104)
    p.add_argument("--bootstrap-replicates", type=int, default=2000)
    p.add_argument("--llm-base-url", default=None)
    p.add_argument("--llm-model", default=None)
    p.add_argument("--judge-model", default=None)
    p.add_argument("--llm-api-key", default="")
    p.add_argument("--llm-reasoning-effort", default="none")
    p.add_argument("--max-reply-tokens", type=int, default=400)
    p.add_argument("--max-judge-tokens", type=int, default=200)
    p.add_argument("--memory-base-url", default=None)
    p.add_argument("--memory-model", default=None)
    p.add_argument("--memory-kind", choices=("local", "online"), default="local")
    p.add_argument("--memory-api-key", default="")
    p.add_argument("--max-consolidation-tokens", type=int, default=1200)
    p.add_argument("--max-extract-tokens", type=int, default=1000)
    p.add_argument("--max-calls", type=int, default=200)
    p.add_argument("--max-runtime-seconds", type=int, default=30 * 60)
    p.add_argument("--resume", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(run(args))
    except Exception as exc:
        print(f"B05 failed closed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
