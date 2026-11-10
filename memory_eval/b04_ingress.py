# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Production-equivalent isolated ingestion for the B04 memory benchmark.

Unlike :class:`ReplayEnv`, this adapter writes fixture events through the real
admission policy, capture gate, transport event contract, and message writer.
It preserves the repository's configured batch thresholds and never forces a
partial consolidation batch.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from memory_eval.isolation import ReplayEnv


class ProductionReplayEnv(ReplayEnv):
    """An isolated replay adapter that exercises the production write gates."""

    def __init__(
        self,
        workdir: Path,
        scenario: dict[str, Any],
        *,
        capture_probe: Callable[[], Awaitable[tuple[bool, str]]] | None = None,
    ):
        super().__init__(workdir, scenario)
        self.capture_probe = capture_probe
        self.capture_gate: Any = None
        self.admission_counts = {"allowed": 0, "denied": 0}
        self.capture_counts = {"allowed": 0, "denied": 0}
        self._message_sequence = 0

    def setup(self) -> None:
        """Patch storage paths only; keep all production batch constants intact."""
        if self._setup_done:
            return

        import mneme.consolidator as consolidator_mod
        import mneme.memory_manager as memory_manager_mod
        import mneme.post_processors as post_processors
        import mneme.pre_processors as pre_processors
        import mneme.retrieval_v2 as retrieval_v2
        import mneme.retriever as retriever
        import mneme.schema as schema_mod
        from mneme.consolidator import MemoryConsolidator

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        try:
            MemoryConsolidator.__new__(MemoryConsolidator)._ensure_common_tables(conn)
            conn.execute(pre_processors._GROUP_MESSAGES_V16_DDL)
            schema_mod.create_memory_scope_versions_table(conn)
            conn.commit()
        finally:
            conn.close()

        for mod in (
            pre_processors,
            consolidator_mod,
            retriever,
            memory_manager_mod,
            retrieval_v2,
            schema_mod,
        ):
            self._patch(mod, "DB_PATH", self.db_path)
        self._patch(post_processors, "THOUGHT_LOG_PATH", self.thought_log_path)
        self._patch(consolidator_mod, "append_consolidation_log", lambda entry: None)
        self._patch(memory_manager_mod, "get_compressor", lambda: _NoCompressor())

        from mneme.capture_gate import CaptureGate

        self.capture_gate = CaptureGate(probe=self.capture_probe)
        self._setup_done = True

    def admission_capture_summary(self) -> dict[str, dict[str, int]]:
        """Reconstruct totals deterministically after checkpoint resume."""
        from core.transport.models import BotRef, SceneRef, UserRef
        from core.transport.normalizers import AdmissionPolicy, NormalizedEvent

        connection_id = f"benchmark-qq:{self.scenario.get('bot_id') or 'stella-bench'}"
        group_id = str(self.scenario["group_id"])
        policy = AdmissionPolicy()
        allowed = denied = 0
        for session in self.scenario.get("sessions") or []:
            for message in session.get("messages") or []:
                user_id = str(message.get("user_id") or "")
                event = NormalizedEvent(
                    bot_ref=BotRef(connection_id, "onebot-v11", "qq", connection_id.rsplit(":", 1)[-1]),
                    user_ref=UserRef("qq:client", user_id),
                    scene_ref=SceneRef("group", group_id),
                    text=str(message.get("text") or ""),
                    platform_message_id=str(message.get("dia_id") or ""),
                )
                if policy.decide(event, purpose="passive", enabled=True).allowed:
                    allowed += 1
                else:
                    denied += 1
        conn = sqlite3.connect(self.db_path)
        try:
            captured = int(conn.execute(
                "SELECT COUNT(*) FROM group_messages WHERE connection_id = ? "
                "AND conversation_key = ?",
                (connection_id, str(self.scenario["conversation_key"])),
            ).fetchone()[0])
        finally:
            conn.close()
        return {
            "admission": {"allowed": allowed, "denied": denied},
            "capture": {"allowed": captured, "denied": max(0, allowed - captured)},
        }

    async def open_capture_gate(self) -> bool:
        """Run the real gate probe path; production CLI uses its real backend."""
        if self.capture_gate is None:
            raise RuntimeError("ProductionReplayEnv.setup() 未调用")
        return await self.capture_gate.probe_once()

    async def record_fixture_session(
        self,
        session: dict[str, Any],
        *,
        event_kind: str = "create",
        platform_revision_id: str | None = None,
    ) -> dict[str, int]:
        """Admit and persist every message with its stable public source ID."""
        from core.context import ChatContext
        from core.transport.message_event import MessageEventV1, MessagePartV1
        from core.transport.models import BotRef, SceneRef, UserRef
        from core.transport.normalizers import AdmissionPolicy, NormalizedEvent
        from mneme.capture_gate import CAPTURE_RESULT_OK
        from mneme.pre_processors import record_message

        if not self._setup_done or self.capture_gate is None:
            raise RuntimeError("ProductionReplayEnv.setup() 未调用")

        conversation_key = str(self.scenario["conversation_key"])
        bot_id = str(self.scenario.get("bot_id") or "stella-bench")
        connection_id = f"benchmark-qq:{bot_id}"
        group_id = int(self.scenario["group_id"])
        policy = AdmissionPolicy()
        timestamp = datetime.strptime(str(session["ts"]), "%Y-%m-%d %H:%M:%S")
        timestamp = timestamp.replace(tzinfo=timezone.utc)
        admitted: dict[str, int] = {}

        for index, message in enumerate(session.get("messages") or []):
            source_id = str(message.get("dia_id") or "")
            if not source_id:
                raise ValueError("LoCoMo fixture message is missing dia_id")
            user_id = str(message.get("user_id") or "")
            text = str(message.get("text") or "")
            event = NormalizedEvent(
                bot_ref=BotRef(connection_id, "onebot-v11", "qq", bot_id),
                user_ref=UserRef("qq:client", user_id),
                scene_ref=SceneRef("group", str(group_id)),
                text=text,
                platform_message_id=source_id,
            )
            decision = policy.decide(event, purpose="passive", enabled=True)
            if not decision.allowed:
                self.admission_counts["denied"] += 1
                continue
            self.admission_counts["allowed"] += 1

            capture = self.capture_gate.decision()
            if not capture.allowed:
                self.capture_counts["denied"] += 1
                raise RuntimeError(
                    f"capture gate closed for source {source_id!r}: {capture.reason_code}"
                )
            self.capture_counts["allowed"] += 1

            occurred_at = timestamp + timedelta(seconds=index)
            transport_event = MessageEventV1(
                platform_message_id=source_id,
                occurred_at=occurred_at,
                components=(MessagePartV1(kind="text", text=text),),
                event_kind=event_kind,
                platform_revision_id=platform_revision_id,
            )
            self._message_sequence += 1
            ctx = ChatContext(
                user_id=user_id,
                group_id=group_id,
                msg_id=self._message_sequence,
                message=text,
                source_kind="PASSIVE",
                conversation_kind="group",
                conversation_key=conversation_key,
                bot_id=bot_id,
                peer_id=str(group_id),
                storage_session_id=group_id,
                group_shared_space=str(group_id),
                user_ref=event.user_ref,
                bot_ref=event.bot_ref,
                scene_ref=event.scene_ref,
                connection_id=connection_id,
                adapter_name="onebot-v11",
                platform_scope="qq",
                scene_kind="group",
                scene_id=str(group_id),
                platform_message_id=source_id,
                relation_version=1,
            )
            await record_message(ctx, capture=capture, message_event=transport_event)
            if ctx.capture_result != CAPTURE_RESULT_OK or ctx.recorded_row_id <= 0:
                raise RuntimeError(
                    "生产写路径未返回 captured source row "
                    f"(source_id={source_id!r}, result={ctx.capture_result!r})"
                )
            self.dia_to_row[source_id] = ctx.recorded_row_id
            admitted[source_id] = ctx.recorded_row_id
        return admitted

    async def record_source_deletion(self, source_id: str) -> int:
        """Replay a source deletion through the transport-aware message writer."""
        from core.context import ChatContext
        from core.transport.message_event import MessageEventV1
        from mneme.capture_gate import CAPTURE_RESULT_OK
        from mneme.pre_processors import record_message

        if not self._setup_done or self.capture_gate is None:
            raise RuntimeError("ProductionReplayEnv.setup() 未调用")
        row = self.db_path
        conn = sqlite3.connect(row)
        try:
            source = conn.execute(
                "SELECT id, group_id, user_id, conversation_key, bot_id, connection_id "
                "FROM group_messages WHERE platform_message_id = ? ORDER BY id LIMIT 1",
                (source_id,),
            ).fetchone()
        finally:
            conn.close()
        if source is None:
            raise KeyError(f"unknown source id: {source_id}")

        row_id, group_id, user_id, conversation_key, bot_id, connection_id = source
        occurred_at = datetime.now(timezone.utc)
        event = MessageEventV1(
            platform_message_id=source_id,
            occurred_at=occurred_at,
            event_kind="delete",
            platform_revision_id=f"b04-delete-{source_id}",
        )
        self._message_sequence += 1
        ctx = ChatContext(
            user_id=str(user_id),
            group_id=int(group_id),
            msg_id=self._message_sequence,
            message="",
            source_kind="PASSIVE",
            conversation_kind="group",
            conversation_key=str(conversation_key),
            bot_id=str(bot_id),
            peer_id=str(group_id),
            storage_session_id=int(group_id),
            connection_id=str(connection_id),
            platform_message_id=source_id,
        )
        await record_message(ctx, capture=self.capture_gate.decision(), message_event=event)
        if ctx.capture_result != CAPTURE_RESULT_OK:
            raise RuntimeError(f"source deletion failed: {ctx.capture_result}")
        return int(row_id)


class _NoCompressor:
    def maybe_compress(self, reason: str = "") -> None:
        return None

