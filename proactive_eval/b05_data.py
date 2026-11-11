# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 stella Project Contributors
"""B05 public-data adapters, memory conditions and paired statistics.

Pure module: no ``config``/``mneme`` import, so tests and the runner can load
it before the isolated ``STELLA_HOME`` is set.

Every adapted item is split into an ``actor`` view (what the reply model may
see) and a ``scorer`` view (gold used only by the judge/metrics). Memory
conditions follow plan §8.1:

- M0  no memory;
- M1  correct and relevant memory (oracle/gold upper bound);
- M2  reliable but not needed memory;
- MS  MemUse same-user prior-session summary store (realistic store; on
      ``memory_needed=false`` negatives it is the M2 condition);
- M3/M4/M5 stale / cross-scope / uncertain copies, checked deterministically at
      the retrieval-pack boundary;
- M6  real write-side product (production-equivalent ingest, smoke subset).
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

ADAPTER_VERSION = "b05-adapters/1"
MEMUSE_FILES = (
    "instances.test.jsonl",
    "negatives.test.jsonl",
    "sessions.train.jsonl",
    "users.jsonl",
)
CHMAP_CONFIGS = ("overall_dialouge_view", "dialogue_data", "topic_rank")
_THOUGHTS = re.compile(r"^Thoughts[：:](?P<body>.*?)(?P<label>yes|no)\s*$")
_SPEAKER = re.compile(r"^(?P<speaker>[^：:\n]{1,12})[：:](?P<text>.*)$")
_HEADER = re.compile(r"^(主题|细化主题)[：:](?P<value>.*)$")


class DataIntegrityError(ValueError):
    """A pinned public file is missing or does not match the registry hash."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _registry_entry(registry: Mapping[str, Any], dataset_id: str) -> Mapping[str, Any]:
    for entry in registry.get("datasets") or []:
        if entry.get("dataset_id") == dataset_id:
            return entry
    raise DataIntegrityError(f"dataset {dataset_id!r} is not in the registry")


def verify_memuse(registry: Mapping[str, Any], repo_root: Path) -> dict[str, Any]:
    """Check every pinned MemUse file against the registry; fail closed."""
    entry = _registry_entry(registry, "memuse")
    files = []
    for spec in entry.get("files") or []:
        path = repo_root / str(spec["path"])
        if not path.exists():
            raise DataIntegrityError(f"missing pinned file: {spec['path']}")
        digest = sha256_file(path)
        if digest != spec["sha256"]:
            raise DataIntegrityError(f"sha256 mismatch for {spec['path']}")
        files.append({"path": spec["path"], "sha256": digest, "records": spec.get("records")})
    if {Path(f["path"]).name for f in files} != set(MEMUSE_FILES):
        raise DataIntegrityError("MemUse registry file set changed")
    return {
        "dataset_id": "memuse",
        "revision": entry["source"]["revision"],
        "license": entry["license"],
        "files": files,
    }


def verify_chmap(registry: Mapping[str, Any], raw_root: Path) -> dict[str, Any]:
    entry = _registry_entry(registry, "chmap-data")
    configs = []
    for spec in entry.get("configurations") or []:
        path = raw_root / "chmap-data" / str(spec["name"]) / f"{spec['split']}.json"
        if not path.exists():
            raise DataIntegrityError(f"missing pinned ChMap config: {spec['name']}")
        digest = sha256_file(path)
        if digest != spec["sha256"]:
            raise DataIntegrityError(f"sha256 mismatch for ChMap {spec['name']}")
        configs.append({"name": spec["name"], "split": spec["split"], "sha256": digest,
                        "records": spec.get("records")})
    return {
        "dataset_id": "chmap-data",
        "revision": entry["source"]["revision"],
        "license": entry["license"],
        "configurations": configs,
    }


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def parse_memuse_date(value: str) -> str:
    """``2025/November/05`` → ``2025-11-05 12:00:00`` (noon; source has no clock time)."""
    return datetime.strptime(str(value).strip(), "%Y/%B/%d").strftime("%Y-%m-%d 12:00:00")


# ── MemUse ────────────────────────────────────────────────────────────────


def load_memuse(data_dir: Path) -> list[dict[str, Any]]:
    """Adapt 72 positives + 72 matched negatives into actor/scorer items."""
    positives = read_jsonl(data_dir / "instances.test.jsonl")
    negatives = read_jsonl(data_dir / "negatives.test.jsonl")
    items: list[dict[str, Any]] = []
    for row in positives:
        items.append(_memuse_item(row, polarity="positive", pair_id=str(row["instance_id"])))
    for row in negatives:
        items.append(_memuse_item(row, polarity="negative", pair_id=str(row["matched_positive"])))
    return items


def _memuse_item(row: Mapping[str, Any], *, polarity: str, pair_id: str) -> dict[str, Any]:
    current = row["input"]["current_session"]
    turns = [
        {"role": str(t["role"]), "content": str(t["content"])}
        for t in current.get("turns") or []
    ]
    if not turns or turns[-1]["role"] != "user":
        raise DataIntegrityError(f"{row['instance_id']}: current session must end with the user trigger")
    if turns[-1]["content"].strip() != str(row["input"]["trigger_quote"]).strip():
        raise DataIntegrityError(f"{row['instance_id']}: trigger is not the final user turn")
    target = row["target"]
    if polarity == "positive":
        scorer = {
            "memory_needed": True,
            "ground_truth": str(target["ground_truth"]),
            "sub_questions": [
                {"question": str(q["question"]), "answer": str(q["answer"])}
                for q in target.get("sub_questions") or []
            ],
            "judge_expected": str(target.get("judge_expected") or ""),
        }
    else:
        scorer = {
            "memory_needed": bool(target.get("memory_needed", False)),
            "prior_session_summaries": [
                {"session_idx": int(s["session_idx"]), "summary": str(s["summary"])}
                for s in target.get("prior_session_summaries") or []
            ],
        }
    return {
        "dataset": "memuse",
        "item_id": str(row["instance_id"]),
        "pair_id": pair_id,
        "cluster": str(row["user_id"]),
        "polarity": polarity,
        "event_type": str(row.get("event_type") or ""),
        "actor": {
            "user_id": str(row["user_id"]),
            "trigger_session_idx": int(row["trigger_session_idx"]),
            "current_date": parse_memuse_date(current["date"]),
            "current_turns": turns,
            "trigger": turns[-1]["content"],
        },
        "scorer": scorer,
    }


def memuse_summary_store(
    corpus: Iterable[Mapping[str, Any]], user_id: str, before_session_idx: int
) -> list[dict[str, Any]]:
    """MS store: the deployed system's own per-session summaries before the trigger.

    Only sessions strictly earlier than the trigger session are eligible, so no
    future information reaches the actor.
    """
    store = []
    for row in corpus:
        if str(row.get("user_id")) != user_id:
            continue
        idx = int(row["session_idx"])
        if idx >= before_session_idx:
            continue
        summary = str(row.get("summary") or "").strip()
        if not summary:
            continue
        store.append({
            "memory_key": f"ms-s{idx:03d}",
            "content": summary,
            "ts": parse_memuse_date(row["date"]),
            "session_idx": idx,
        })
    store.sort(key=lambda m: m["session_idx"])
    return store


def memuse_gold_memory(item: Mapping[str, Any]) -> list[dict[str, Any]]:
    """M1 oracle memory for a positive: the dataset's ground-truth statement."""
    if item["polarity"] != "positive":
        return []
    return [{
        "memory_key": "m1-gold",
        "content": item["scorer"]["ground_truth"],
        "ts": item["actor"]["current_date"],
    }]


# ── ChMap topic_rank ──────────────────────────────────────────────────────


def strip_dialogue(text: str) -> list[dict[str, str]]:
    """Parse ``speaker：text`` lines; drop topic headers and Thoughts annotations."""
    turns = []
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line or _HEADER.match(line) or _THOUGHTS.match(line) or line.startswith("Thoughts"):
            continue
        match = _SPEAKER.match(line)
        if match:
            turns.append({"speaker": match["speaker"].strip(), "text": match["text"].strip()})
    return turns


def load_chmap_rank(path: Path, *, seed: int) -> list[dict[str, Any]]:
    """Adapt topic_rank; candidates are de-duplicated and shuffled with a fixed seed.

    The released candidate order is position-biased (gold often first), so the
    adapter hides it. Rows whose gold sub-topic is absent from the candidates are
    kept with ``scoreable=False``: they enter the total, never the hit numerator.
    """
    items = []
    for index, row in enumerate(read_jsonl(path)):
        raw = row["rank_topics"]
        if isinstance(raw, str):
            raw = json.loads(raw)
        candidates: list[str] = []
        for topic in raw:
            topic = str(topic).strip()
            if topic and topic not in candidates:
                candidates.append(topic)
        gold = str(row["select_sub_topic"]).strip()
        rng = random.Random(f"{seed}:chmap-rank:{index}")
        shuffled = list(candidates)
        rng.shuffle(shuffled)
        prefix = _prefix_before_first_thought(str(row["round_dialogue"]))
        query_turns = strip_dialogue(prefix)
        items.append({
            "dataset": "chmap-data/topic_rank",
            "item_id": f"chmap-rank-{index:03d}",
            "cluster": f"chmap-rank-{index:03d}",
            "actor": {
                "candidates": shuffled,
                "query": "\n".join(t["text"] for t in query_turns),
            },
            "scorer": {
                "gold": gold,
                "scoreable": gold in candidates,
                "released_gold_index": raw.index(gold) if gold in raw else None,
                "released_candidate_count": len(raw),
                "duplicate_candidates_removed": len(raw) - len(candidates),
            },
        })
    return items


def _prefix_before_first_thought(text: str) -> str:
    lines = str(text or "").splitlines()
    for i, line in enumerate(lines):
        if line.strip().startswith("Thoughts"):
            return "\n".join(lines[:i])
    return "\n".join(lines)


def rank_metrics(rankings: Sequence[Mapping[str, Any]], ks: Sequence[int] = (1, 3, 5, 10)) -> dict[str, Any]:
    """Recall@K/MRR over scoreable rows; unscoreable rows stay in the total."""
    total = len(rankings)
    scoreable = [r for r in rankings if r["scoreable"]]
    n = len(scoreable)
    out: dict[str, Any] = {
        "total": total,
        "scoreable": n,
        "unscoreable_gold_absent": total - n,
        "mrr": None,
        "recall_at": {},
        "worst_case_recall_at": {},
    }
    if not n:
        return out
    rr = 0.0
    for row in scoreable:
        rank = row.get("gold_rank")
        if rank:
            rr += 1.0 / rank
    out["mrr"] = round(rr / n, 4)
    for k in ks:
        hits = sum(1 for r in scoreable if r.get("gold_rank") and r["gold_rank"] <= k)
        out["recall_at"][str(k)] = round(hits / n, 4)
        out["worst_case_recall_at"][str(k)] = round(hits / total, 4) if total else None
    out["gold_never_ranked"] = sum(1 for r in scoreable if not r.get("gold_rank"))
    return out


def random_rank_baseline(items: Sequence[Mapping[str, Any]], ks: Sequence[int] = (1, 3, 5, 10)) -> dict[str, Any]:
    """Expected Recall@K of a uniform random ranking over the de-duplicated candidates."""
    scoreable = [i for i in items if i["scorer"]["scoreable"]]
    if not scoreable:
        return {"scoreable": 0, "recall_at": {}, "mrr": None}
    recall = {}
    for k in ks:
        recall[str(k)] = round(
            sum(min(k, len(i["actor"]["candidates"])) / len(i["actor"]["candidates"]) for i in scoreable)
            / len(scoreable), 4)
    mrr = sum(
        sum(1.0 / r for r in range(1, len(i["actor"]["candidates"]) + 1)) / len(i["actor"]["candidates"])
        for i in scoreable
    ) / len(scoreable)
    return {"scoreable": len(scoreable), "recall_at": recall, "mrr": round(mrr, 4)}


def released_order_baseline(items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Recall@1 if the released (unshuffled) order were trusted: a leakage indicator."""
    scoreable = [i for i in items if i["scorer"]["scoreable"]]
    first = sum(1 for i in scoreable if i["scorer"]["released_gold_index"] == 0)
    return {
        "scoreable": len(scoreable),
        "gold_at_released_index_0": first,
        "recall_at_1": round(first / len(scoreable), 4) if scoreable else None,
    }


# ── ChMap overall_dialouge_view (callback decision points) ───────────────


def _day_keys(row: Mapping[str, Any]) -> list[str]:
    return sorted((k for k in row if re.fullmatch(r"day\d+", k)), key=lambda k: int(k[3:]))


def day_topic(text: str) -> str | None:
    """The ``细化主题`` (or ``主题``) header of a past day: a topic-level memory."""
    topic = sub = None
    for raw in str(text or "").splitlines():
        match = _HEADER.match(raw.strip())
        if not match:
            continue
        if raw.strip().startswith("细化主题"):
            sub = match["value"].strip()
        else:
            topic = match["value"].strip()
    return sub or topic


def load_chmap_callback(path: Path) -> list[dict[str, Any]]:
    """Each Thoughts annotation in the final day is one decision point.

    Actor input = final-day turns strictly before the annotation (annotation
    lines removed) plus the memory store; the yes/no label and the callback day
    are scorer-only.
    """
    points: list[dict[str, Any]] = []
    for index, row in enumerate(read_jsonl(path)):
        days = _day_keys(row)
        current = days[-1]
        callback_day = str(row["callback_day"])
        if callback_day == current or callback_day not in days:
            raise DataIntegrityError(f"chmap overview {index}: callback day is not a past day")
        past = []
        for day in days[:-1]:
            topic = day_topic(row[day])
            if topic:
                past.append({"day": day, "topic": topic})
        callback_topic = next((p["topic"] for p in past if p["day"] == callback_day), None)
        if callback_topic is None:
            raise DataIntegrityError(f"chmap overview {index}: callback day has no topic header")
        lines = str(row[current]).splitlines()
        seen = 0
        for line_no, raw in enumerate(lines):
            match = _THOUGHTS.match(raw.strip())
            if not match:
                continue
            prefix_turns = strip_dialogue("\n".join(lines[:line_no]))
            if not prefix_turns:
                continue
            points.append({
                "dataset": "chmap-data/overall_dialouge_view",
                "item_id": f"chmap-ov-{index:03d}-p{seen}",
                "record_index": index,
                "cluster": f"chmap-ov-{index:03d}",
                "actor": {
                    "turns": prefix_turns,
                    "past_topics": [{"day": p["day"], "topic": p["topic"]} for p in past],
                },
                "scorer": {
                    "label": match["label"],
                    "callback_day": callback_day,
                    "callback_topic": callback_topic,
                    "other_topics": [p["topic"] for p in past if p["day"] != callback_day],
                },
            })
            seen += 1
    return points


def select_chmap_points(points: Sequence[Mapping[str, Any]], records: int, seed: int) -> list[dict[str, Any]]:
    """Per sampled record: first ``yes`` point, plus the last ``no`` point before it.

    Records with no ``yes`` contribute their first ``no`` point. Sampling is a
    seeded draw over record indices (not over points), so clusters stay whole.
    """
    by_record: dict[int, list[Mapping[str, Any]]] = {}
    for p in points:
        by_record.setdefault(int(p["record_index"]), []).append(p)
    indices = sorted(by_record)
    rng = random.Random(f"{seed}:chmap-ov-records")
    chosen = sorted(rng.sample(indices, min(records, len(indices)))) if records > 0 else indices
    selected: list[dict[str, Any]] = []
    for idx in chosen:
        rows = by_record[idx]
        first_yes = next((i for i, p in enumerate(rows) if p["scorer"]["label"] == "yes"), None)
        if first_yes is None:
            selected.append(dict(rows[0]))
            continue
        no_before = [p for p in rows[:first_yes] if p["scorer"]["label"] == "no"]
        if no_before:
            selected.append(dict(no_before[-1]))
        selected.append(dict(rows[first_yes]))
    return selected


def chmap_memories(point: Mapping[str, Any], condition: str) -> list[dict[str, Any]]:
    """M1 = callback-day topic only; M2 = the other past-day topics only.

    The memory text is the past day's topic header, which is what a topic
    summarizer would store (ChMap dialogue_data task). M1 uses the scorer's
    callback-day pointer and is therefore an oracle condition.
    """
    if condition == "M0":
        return []
    callback_day = point["scorer"]["callback_day"]
    rows = []
    for past in point["actor"]["past_topics"]:
        is_callback = past["day"] == callback_day
        if (condition == "M1" and is_callback) or (condition == "M2" and not is_callback):
            rows.append({"memory_key": f"topic-{past['day']}", "content": f"小明之前聊过：{past['topic']}"})
    return rows


# ── leakage guard ────────────────────────────────────────────────────────


def actor_leaks(actor: Mapping[str, Any], scorer: Mapping[str, Any]) -> list[str]:
    """Return scorer strings (≥12 chars) that appear verbatim in the actor view."""
    blob = json.dumps(actor, ensure_ascii=False)
    leaks = []
    for value in _strings(scorer):
        if len(value) >= 12 and value in blob:
            leaks.append(value[:60])
    return leaks


def _strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _strings(v)


# ── statistics ───────────────────────────────────────────────────────────


def binary_summary(values: Sequence[bool | None]) -> dict[str, Any]:
    """Rate over all items; ``None`` (unparseable/failed) is never counted as success.

    ``upper_bound`` counts every unscored item as YES; for harm metrics it is
    the worst case, for benefit metrics ``rate`` is already the worst case.
    """
    total = len(values)
    yes = sum(1 for v in values if v is True)
    unscored = sum(1 for v in values if v is None)
    return {
        "n": total,
        "yes": yes,
        "unscored": unscored,
        "rate": round(yes / total, 4) if total else None,
        "upper_bound": round((yes + unscored) / total, 4) if total else None,
    }


def paired_cluster_bootstrap(
    pairs: Sequence[tuple[str, float, float]],
    *,
    replicates: int,
    seed: int,
    confidence: float = 0.95,
) -> dict[str, Any]:
    """Paired difference (treatment − control) with a cluster bootstrap CI.

    ``pairs`` holds (cluster, control_value, treatment_value) per paired item.
    Clusters are resampled with replacement; the statistic is the mean paired
    difference over all items in the resampled clusters.
    """
    if not pairs:
        return {"n_items": 0, "n_clusters": 0, "difference": None, "ci": None,
                "status": "NOT_APPLICABLE_EMPTY"}
    clusters: dict[str, list[float]] = {}
    for cluster, control, treatment in pairs:
        clusters.setdefault(str(cluster), []).append(float(treatment) - float(control))
    keys = sorted(clusters)
    total_items = sum(len(v) for v in clusters.values())
    point = sum(sum(v) for v in clusters.values()) / total_items
    rng = random.Random(seed)
    stats = []
    for _ in range(int(replicates)):
        draw = [clusters[keys[rng.randrange(len(keys))]] for _ in keys]
        n = sum(len(d) for d in draw)
        stats.append(sum(sum(d) for d in draw) / n)
    stats.sort()
    alpha = (1.0 - confidence) / 2.0
    lo = stats[max(0, int(alpha * len(stats)))]
    hi = stats[min(len(stats) - 1, int((1.0 - alpha) * len(stats)) - 1)]
    return {
        "n_items": total_items,
        "n_clusters": len(keys),
        "difference": round(point, 4),
        "ci": [round(lo, 4), round(hi, 4)],
        "confidence": confidence,
        "replicates": int(replicates),
        "seed": seed,
        "status": "MEASURED",
    }
