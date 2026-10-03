# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""数据集只读导出（计划 §6.7.3 dataset 合同）。

从生产记忆库 **只读** 导出 ``group_messages`` → ``manifest.json`` +
``messages.jsonl``，供隔离评测回放。纪律：

- **只读**：SQLite 以 read-only URI 打开，绝不做任何写操作（连 WAL/journal
  都不会产生）；不提供任何「默认回退生产路径」——库文件不存在直接报错。
- **稳定排序**：时间戳一律容错解析为 aware UTC 后排序，同秒按源 ``id``
  升序 tie-break；**不用** ``CAST(timestamp AS INTEGER)`` 排 ISO 日期
  （计划 §6.7.3 明确禁止）。
- **稳定 event_id**：``sha1(f"{group_id}|{msg_id}|{ts_utc}")[:16]``，重复
  event_id 只保留首条并把条数记入 manifest（处理政策显式记录）。
- **伪名**：``user_id`` 一律 sha1 哈希化（``u`` + 12 hex），原文不落盘。
- **cutoff 防泄漏**：``cutoff_utc`` 之后的消息在导出侧直接剔除，绝不出现
  在数据集里（计划 §6.7.3「snapshot 不能包含 cutoff 后的记忆/标签」）。
- **schema 事实**：生产 ``group_messages`` 没有 is_tome/@/reply target 列，
  manifest 如实记录该缺失，不伪称完整（计划 §6.7.3 乱序/缺失政策显式记录）。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

__all__ = [
    "DATASET_MANIFEST_NAME",
    "DATASET_MESSAGES_NAME",
    "DATASET_SCHEMA_VERSION",
    "DatasetMessage",
    "dataset_digest",
    "export_dataset",
    "load_dataset",
    "pseudonymize_user",
]

DATASET_MANIFEST_NAME = "manifest.json"
DATASET_MESSAGES_NAME = "messages.jsonl"
DATASET_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class DatasetMessage:
    """一条回放消息（字段合同见模块 docstring）。"""

    event_id: str
    sequence: int
    group_id: str
    msg_id: int
    source_kind: str
    scope: str
    user: str
    ts_utc: datetime
    content: str

    def to_jsonl(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "sequence": self.sequence,
            "group_id": self.group_id,
            "msg_id": self.msg_id,
            "source_kind": self.source_kind,
            "scope": self.scope,
            "user": self.user,
            "ts_utc": self.ts_utc.isoformat(),
            "content": self.content,
        }


def _parse_utc(value: Any) -> datetime | None:
    """容错解析 SQLite 时间为 aware UTC；解析失败返回 None（计入丢弃）。"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    text = str(value).strip()
    normalized = text.replace("T", " ")
    for fmt in (
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    ):
        try:
            # SQLite CURRENT_TIMESTAMP 即 UTC，naive 一律按 UTC 解释（不取主机时区）
            return datetime.strptime(normalized[: len(fmt) + 2], fmt).replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def pseudonymize_user(user_id: str) -> str:
    """``user_id`` 单向哈希化为伪名（原文不出导出边界）。"""
    digest = hashlib.sha1(f"user|{user_id}".encode()).hexdigest()
    return "u" + digest[:12]


def _source_db_digest(db_path: Path) -> str:
    """源库文件 sha256（只读整文件，不改变 mtime/内容）。"""
    digest = hashlib.sha256()
    with db_path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def export_dataset(
    db_path: Path | str,
    out_dir: Path | str,
    *,
    cutoff_utc: datetime | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """只读导出 ``group_messages`` 为数据集；返回 manifest dict。

    参数：
        db_path: 源 SQLite 库路径（必须已存在；不存在直接报错，不回退任何
            生产默认路径）。
        out_dir: 数据集输出目录（自动创建）。
        cutoff_utc: 只保留 ``ts <= cutoff`` 的消息（防泄漏；None=不裁剪）。
        limit: 裁剪排序后只保留前 ``limit`` 条（None=全部）。
    """
    source = Path(db_path)
    if not source.is_file():
        msg = f"源库不存在（拒绝回退生产默认路径）: {source}"
        raise FileNotFoundError(msg)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    if cutoff_utc is not None and cutoff_utc.tzinfo is None:
        raise ValueError("cutoff_utc 必须是 aware datetime")

    # read-only URI 打开：SQLite 绝不写主库、不建 WAL/journal，生产库
    # mtime/内容逐字节不变（tests/evaluation/test_isolation.py 有验收）。
    conn = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT id, group_id, user_id, content, source_kind, msg_id, timestamp"
            " FROM group_messages ORDER BY id"
        ).fetchall()
    finally:
        conn.close()

    total_source_rows = len(rows)
    dropped_empty = 0
    dropped_bad_ts = 0
    dropped_after_cutoff = 0
    candidates: list[tuple[datetime, int, dict[str, Any]]] = []
    for row_id, group_id, user_id, content, source_kind, msg_id, ts_value in rows:
        text = "" if content is None else str(content)
        if not text.strip():
            dropped_empty += 1
            continue
        ts = _parse_utc(ts_value)
        if ts is None:
            dropped_bad_ts += 1
            continue
        if cutoff_utc is not None and ts > cutoff_utc:
            dropped_after_cutoff += 1
            continue
        group_text = "" if group_id is None else str(group_id)
        candidates.append(
            (
                ts,
                int(row_id),
                {
                    "group_id": group_text,
                    "msg_id": int(msg_id or 0),
                    "source_kind": str(source_kind or "PASSIVE"),
                    "user": pseudonymize_user("" if user_id is None else str(user_id)),
                    "ts_utc": ts,
                    "content": text,
                },
            )
        )

    # 稳定排序：UTC 时间戳 → 源 id tie-break（绝不用 CAST(timestamp AS INTEGER)）
    candidates.sort(key=lambda item: (item[0], item[1]))
    if limit is not None and limit >= 0:
        candidates = candidates[:limit]

    messages: list[DatasetMessage] = []
    seen_event_ids: set[str] = set()
    duplicates_skipped = 0
    for seq, (ts, _row_id, item) in enumerate(candidates, start=1):
        ts_key = ts.strftime("%Y-%m-%dT%H:%M:%S")
        event_id = hashlib.sha1(
            f"{item['group_id']}|{item['msg_id']}|{ts_key}".encode()
        ).hexdigest()[:16]
        if event_id in seen_event_ids:
            duplicates_skipped += 1
            continue
        seen_event_ids.add(event_id)
        messages.append(
            DatasetMessage(
                event_id=event_id,
                sequence=seq,
                group_id=item["group_id"],
                msg_id=item["msg_id"],
                source_kind=item["source_kind"],
                scope="group",
                user=item["user"],
                ts_utc=ts,
                content=item["content"],
            )
        )

    manifest: dict[str, Any] = {
        "schema_version": DATASET_SCHEMA_VERSION,
        "kind": "stella-evaluation-dataset",
        "source_db_name": source.name,
        "source_db_sha256": _source_db_digest(source),
        "exported_at_utc": datetime.now(timezone.utc).isoformat(),
        "cutoff_utc": cutoff_utc.isoformat() if cutoff_utc is not None else None,
        "limit": limit,
        "total_source_rows": total_source_rows,
        "exported": len(messages),
        "dropped_empty_content": dropped_empty,
        "dropped_bad_timestamp": dropped_bad_ts,
        "dropped_after_cutoff": dropped_after_cutoff,
        "duplicates_skipped": duplicates_skipped,
        "timestamp_policy": "SQLite CURRENT_TIMESTAMP 一律按 UTC 解释（naive 不取主机时区）",
        "sort_policy": "UTC 时间戳升序，同秒按源 id 升序 tie-break；禁止 CAST(timestamp AS INTEGER)",
        "event_id_policy": "sha1(f'{group_id}|{msg_id}|{ts_utc}')[:16]，重复只保留首条",
        "pseudonym_policy": "user_id 单向 sha1（u + 12 hex），原文不落盘",
        "schema_gaps": "生产 group_messages 无 is_tome/@/reply target 列，数据集如实缺失该字段",
    }

    (out / DATASET_MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with (out / DATASET_MESSAGES_NAME).open("w", encoding="utf-8") as fh:
        for message in messages:
            fh.write(json.dumps(message.to_jsonl(), ensure_ascii=False) + "\n")
    return manifest


def load_dataset(
    dataset_dir: Path | str,
) -> tuple[dict[str, Any], list[DatasetMessage]]:
    """读回数据集目录 → (manifest, 消息列表)；目录不完整直接报错。"""
    directory = Path(dataset_dir)
    manifest_path = directory / DATASET_MANIFEST_NAME
    messages_path = directory / DATASET_MESSAGES_NAME
    if not manifest_path.is_file() or not messages_path.is_file():
        msg = f"数据集目录不完整（缺 manifest.json 或 messages.jsonl）: {directory}"
        raise FileNotFoundError(msg)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    messages: list[DatasetMessage] = []
    for line in messages_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        item = json.loads(line)
        messages.append(
            DatasetMessage(
                event_id=str(item["event_id"]),
                sequence=int(item["sequence"]),
                group_id=str(item["group_id"]),
                msg_id=int(item.get("msg_id") or 0),
                source_kind=str(item.get("source_kind") or "PASSIVE"),
                scope=str(item.get("scope") or "group"),
                user=str(item.get("user") or ""),
                ts_utc=datetime.fromisoformat(item["ts_utc"]),
                content=str(item.get("content") or ""),
            )
        )
    messages.sort(key=lambda m: m.sequence)
    return manifest, messages


def dataset_digest(messages: list[DatasetMessage]) -> str:
    """数据集内容摘要（与导出时间/源库名无关，两次导出可比较）。"""
    view = [m.to_jsonl() for m in messages]
    payload = json.dumps(view, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()
