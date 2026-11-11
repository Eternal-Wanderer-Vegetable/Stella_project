# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Source-ID lineage extraction for the B04 memory benchmark."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }


def build_lineage(db_path: Path) -> dict[str, Any]:
    """Return source → candidate → promoted entity edges without source text."""
    if not db_path.exists():
        return {"sources": [], "retrieved_entity_sources": {}, "counts": {}}

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        tables = _tables(conn)
        latest_events: dict[tuple[str, str, str, str], tuple[str, int | None]] = {}
        if "transport_message_events" in tables:
            for row in conn.execute(
                "SELECT connection_id, conversation_key, direction, "
                "platform_message_id, event_kind, legacy_row_id "
                "FROM transport_message_events ORDER BY event_seq"
            ):
                key = (
                    str(row["connection_id"] or ""),
                    str(row["conversation_key"] or ""),
                    str(row["direction"] or ""),
                    str(row["platform_message_id"] or ""),
                )
                latest_events[key] = (
                    str(row["event_kind"] or ""),
                    int(row["legacy_row_id"]) if row["legacy_row_id"] is not None else None,
                )
        sources: dict[int, dict[str, Any]] = {}
        if "group_messages" in tables:
            for row in conn.execute(
                "SELECT id, platform_message_id, content, source_kind, connection_id, "
                "conversation_key FROM group_messages ORDER BY id"
            ):
                source_row_id = int(row["id"])
                source_id = str(row["platform_message_id"] or f"row:{source_row_id}")
                digest = hashlib.sha256(str(row["content"] or "").encode("utf-8")).hexdigest()
                direction = (
                    "outbound" if str(row["source_kind"] or "").upper() == "BOT_SELF"
                    else "inbound"
                )
                event_key = (
                    str(row["connection_id"] or ""),
                    str(row["conversation_key"] or ""),
                    direction,
                    str(row["platform_message_id"] or ""),
                )
                latest = latest_events.get(event_key) if row["platform_message_id"] else None
                if latest is None:
                    source_state = "legacy_unversioned"
                    source_effective = True
                elif latest[0] == "delete":
                    source_state = "deleted"
                    source_effective = False
                elif latest[1] == source_row_id:
                    source_state = "current"
                    source_effective = True
                else:
                    source_state = "superseded"
                    source_effective = False
                sources[source_row_id] = {
                    "source_id": source_id,
                    "source_row_id": source_row_id,
                    "source_digest": digest,
                    "source_state": source_state,
                    "source_effective": source_effective,
                    "candidate_ids": [],
                    "evidence_ids": [],
                    "evidence_statuses": [],
                    "promoted_entities": [],
                }

        candidates: dict[str, dict[str, Any]] = {}
        if "memory_candidates" in tables:
            for row in conn.execute(
                "SELECT id, status, source_message_ids FROM memory_candidates ORDER BY id"
            ):
                candidate_id = str(row["id"])
                candidates[candidate_id] = {"status": str(row["status"] or "")}
                try:
                    source_rows = json.loads(row["source_message_ids"] or "[]")
                except (TypeError, ValueError):
                    source_rows = []
                for source_row in source_rows if isinstance(source_rows, list) else []:
                    try:
                        target = sources.get(int(source_row))
                    except (TypeError, ValueError):
                        target = None
                    if target is not None:
                        target["candidate_ids"].append(candidate_id)

        if "memory_evidence" in tables:
            for row in conn.execute(
                "SELECT id, source_row_id, candidate_id, source_digest, verification_status "
                "FROM memory_evidence ORDER BY id"
            ):
                try:
                    target = sources.get(int(row["source_row_id"]))
                except (TypeError, ValueError):
                    target = None
                if target is None:
                    continue
                evidence_id = str(row["id"])
                target["evidence_ids"].append(evidence_id)
                candidate_id = str(row["candidate_id"] or "")
                if candidate_id and candidate_id not in target["candidate_ids"]:
                    target["candidate_ids"].append(candidate_id)
                target.setdefault("evidence", []).append({
                    "evidence_id": evidence_id,
                    "candidate_id": candidate_id,
                    "source_digest": str(row["source_digest"] or ""),
                    "verification_status": str(row["verification_status"] or ""),
                })
                target["evidence_statuses"].append({
                    "evidence_id": evidence_id,
                    "verification_status": str(row["verification_status"] or ""),
                })

        entity_sources: dict[str, set[int]] = {}
        stale_active_claim_links = 0
        if "memory_claim_links" in tables and "memory_evidence" in tables:
            for row in conn.execute(
                "SELECT l.entity_type, l.entity_id, l.status, e.source_row_id, "
                "e.verification_status "
                "FROM memory_claim_links AS l "
                "JOIN memory_evidence AS e ON e.id = l.evidence_id "
                "ORDER BY l.entity_type, l.entity_id, e.source_row_id"
            ):
                entity_type = str(row["entity_type"] or "")
                entity_id = str(row["entity_id"] or "")
                key = f"{entity_type}:{entity_id}"
                try:
                    source_row_id = int(row["source_row_id"])
                except (TypeError, ValueError):
                    continue
                source = sources.get(source_row_id)
                if source is not None:
                    claim_status = str(row["status"] or "")
                    verification_status = str(row["verification_status"] or "")
                    if (
                        claim_status == "active"
                        and not source["source_effective"]
                        and verification_status != "source_unavailable"
                    ):
                        stale_active_claim_links += 1
                    if (
                        claim_status == "active"
                        and source["source_effective"]
                        and verification_status != "source_unavailable"
                    ):
                        entity_sources.setdefault(key, set()).add(source_row_id)
                    source["promoted_entities"].append({
                        "entity_type": entity_type,
                        "entity_id": entity_id,
                        "claim_status": claim_status,
                        "verification_status": verification_status,
                    })

        retrieved_entity_sources = {
            key: sorted(row_ids) for key, row_ids in sorted(entity_sources.items())
        }
        for source in sources.values():
            source["candidate_ids"] = sorted(set(source["candidate_ids"]))
            source["evidence_ids"] = sorted(set(source["evidence_ids"]))
            source["evidence_statuses"] = sorted(
                source["evidence_statuses"],
                key=lambda item: (item["evidence_id"], item["verification_status"]),
            )
            source["promoted_entities"] = sorted(
                source["promoted_entities"],
                key=lambda item: (
                    item["entity_type"], item["entity_id"], item["claim_status"],
                    item["verification_status"],
                ),
            )
            source.pop("evidence", None)

        return {
            "sources": list(sources.values()),
            "retrieved_entity_sources": retrieved_entity_sources,
            "counts": {
                "sources": len(sources),
                "effective_sources": sum(bool(s["source_effective"]) for s in sources.values()),
                "superseded_sources": sum(s["source_state"] == "superseded" for s in sources.values()),
                "deleted_sources": sum(s["source_state"] == "deleted" for s in sources.values()),
                "sources_with_candidates": sum(bool(s["candidate_ids"]) for s in sources.values()),
                "sources_with_evidence": sum(bool(s["evidence_ids"]) for s in sources.values()),
                "sources_with_promoted_entities": sum(bool(s["promoted_entities"]) for s in sources.values()),
                "active_claim_links_with_noncurrent_sources": stale_active_claim_links,
                "candidates": len(candidates),
                "evidence_rows": conn.execute("SELECT COUNT(*) FROM memory_evidence").fetchone()[0]
                if "memory_evidence" in tables else 0,
                "claim_links": conn.execute("SELECT COUNT(*) FROM memory_claim_links").fetchone()[0]
                if "memory_claim_links" in tables else 0,
            },
        }
    finally:
        conn.close()


def retrieval_source_alignment(
    lineage: dict[str, Any],
    retrieved_ids: list[str],
    gold_source_ids: list[str],
) -> dict[str, Any]:
    """Resolve exact source ancestry; leave answer support unresolved."""
    source_by_id = {str(row["source_id"]): row for row in lineage.get("sources", [])}
    source_by_row = {int(row["source_row_id"]): row for row in lineage.get("sources", [])}
    gold_rows = {
        int(source_by_id[source_id]["source_row_id"])
        for source_id in gold_source_ids
        if source_id in source_by_id
    }
    entity_sources = lineage.get("retrieved_entity_sources") or {}
    per_ref = []
    aligned_refs = []
    for memory_id in retrieved_ids:
        source_rows = entity_sources.get(f"memory:{memory_id}", [])
        source_ids = [
            source_by_row[row_id]["source_id"]
            for row_id in source_rows
            if row_id in source_by_row
        ]
        matches = sorted(gold_rows.intersection(int(v) for v in source_rows))
        per_ref.append({
            "packed_ref": str(memory_id),
            "source_ids": sorted(source_ids),
            "gold_source_match": bool(matches),
        })
        if matches:
            aligned_refs.append(str(memory_id))
    return {
        "packed_refs": [str(value) for value in retrieved_ids],
        "memory_source_lineage": per_ref,
        "gold_source_alignment": "aligned" if aligned_refs else "ALIGNMENT_UNRESOLVED",
        "aligned_packed_refs": aligned_refs,
        "answer_support_status": "ALIGNMENT_UNRESOLVED",
    }

