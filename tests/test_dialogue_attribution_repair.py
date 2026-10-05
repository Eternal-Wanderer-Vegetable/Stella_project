# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""对话归属修复 R8 - 单元测试集（计划 §6.8）。

按计划 §6.8，测试覆盖：
1. 身份解析器拒绝问句/否定/条件
2. 共享授权事务与版本推进
3. 主动验证桥接验证与变体选择
4. 归属守护证据验证与模式切换
5. 数据修复预览/应用/撤销
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from core.dialogue_attribution import (
    ReplyPlan,
    SourceEvidence,
    apply_guard_decision,
    build_evidence_table,
    check_risky_free_text,
    validate_evidence_references,
)
from memory.conversation_identity import (
    parse_self_alias,
    parse_third_person_correction,
)
from memory.personal_sharing import (
    detect_sharing_intent,
    grant_sharing_authorization,
)
from memory.proactive_contract import (
    BridgeEvidence,
    QuestionVariant,
    VerificationContract,
    select_question_variant,
    validate_bridge_event,
)
from tools.data_repair import (
    RepairRecord,
    apply_repairs,
    preview_wrong_space_records,
)

# ============================================================
# R4: Identity Parser Tests
# ============================================================


class TestIdentityParser:
    """R4 身份解析器测试。"""

    def test_parse_self_alias_accepts_valid(self):
        """接受有效的自我介绍。"""
        result = parse_self_alias("我是Nox")
        assert result is not None
        alias, supersedes = result
        assert alias == "Nox"
        assert supersedes is False

    def test_parse_self_alias_accepts_correction(self):
        """接受改名声明。"""
        result = parse_self_alias("我才是Lumi")
        assert result is not None
        alias, supersedes = result
        assert alias == "Lumi"
        assert supersedes is True

    def test_parse_self_alias_rejects_question(self):
        """拒绝问句。"""
        assert parse_self_alias("我是谁") is None
        assert parse_self_alias("是我吗") is None
        assert parse_self_alias("我是Nox吗") is None

    def test_parse_self_alias_rejects_negation(self):
        """拒绝否定句。"""
        assert parse_self_alias("不是我") is None
        assert parse_self_alias("这不是我") is None
        assert parse_self_alias("我不是Nox") is None

    def test_parse_self_alias_rejects_conditional(self):
        """拒绝条件句。"""
        assert parse_self_alias("如果我是Nox") is None
        assert parse_self_alias("要是我叫Lumi") is None

    def test_parse_self_alias_rejects_role(self):
        """拒绝角色表达。"""
        assert parse_self_alias("我是管理员") is None
        assert parse_self_alias("我是Bot") is None

    def test_parse_third_person_positive(self):
        """解析第三人肯定纠正。"""
        result = parse_third_person_correction("他才是Nox")
        assert result is not None
        alias, is_positive = result
        assert alias == "Nox"
        assert is_positive is True

    def test_parse_third_person_negative(self):
        """解析第三人否定纠正。"""
        result = parse_third_person_correction("Lumi不是他")
        assert result is not None
        alias, is_positive = result
        assert alias == "Lumi"
        assert is_positive is False


# ============================================================
# R3: Personal Sharing Tests
# ============================================================


class TestPersonalSharing:
    """R3 个人记忆共享测试。"""

    def test_detect_sharing_intent_positive(self):
        """检测明确分享意图。"""
        is_sharing, reason = detect_sharing_intent(
            "以后在群里也记得我们CP的关系",
            sender_id=12345,
            conversation_key="private:12345",
        )
        assert is_sharing is True
        assert reason == "explicit_sharing"

    def test_detect_sharing_intent_negative(self):
        """拒绝否定句。"""
        is_sharing, reason = detect_sharing_intent(
            "别在群里说",
            sender_id=12345,
            conversation_key="private:12345",
        )
        assert is_sharing is False
        assert reason == "negative"

    def test_detect_sharing_intent_question(self):
        """拒绝问句。"""
        is_sharing, reason = detect_sharing_intent(
            "能在群里用吗？",
            sender_id=12345,
            conversation_key="private:12345",
        )
        assert is_sharing is False
        assert reason == "question"

    def test_grant_sharing_authorization_idempotent(self):
        """授权操作幂等（P3 起须真实来源行 + 规范 DDL）。"""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name

        conn = sqlite3.connect(db_path)
        try:
            # 必要表（规范形状：授权表 + 台账 + scope 版本 + 来源消息表 + 原件表）
            from memory.personal_sharing import (
                create_sharing_authorization_table,
                create_sharing_copies_table,
            )
            from memory.schema import (
                MEMORY_CANDIDATES_TABLE_DDL,
                create_memory_scope_versions_table,
            )
            create_sharing_authorization_table(conn)
            create_sharing_copies_table(conn)
            create_memory_scope_versions_table(conn)
            conn.execute(MEMORY_CANDIDATES_TABLE_DDL)
            conn.execute(
                "ALTER TABLE memory_candidates ADD COLUMN verification_contract_json TEXT"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS group_messages ("
                " id INTEGER PRIMARY KEY AUTOINCREMENT, group_id TEXT, user_id TEXT,"
                " content TEXT, source_kind TEXT DEFAULT 'PASSIVE',"
                " conversation_key TEXT, bot_id TEXT,"
                " timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)"
            )
            conn.execute(
                "INSERT INTO group_messages (id, user_id, content, source_kind,"
                " conversation_key, bot_id)"
                " VALUES (100, '12345', '在群里也记得', 'AT_MENTION',"
                " 'private:12345', '1001')"
            )
            conn.execute(
                "INSERT INTO memory_candidates (id, user_id, type, content, status,"
                " owner_type, owner_key, subject_key, audience, fact_key)"
                " VALUES ('c1', '12345', 'relation', 'fact', 'ACTIVE', 'PERSON',"
                " 'person:qq:1001:12345', 'qq:12345', 'PRIVATE_ONLY', 'fact_key_1')"
            )

            # 首次授权
            success1, reason1 = grant_sharing_authorization(
                conn, "qq", 1001, 12345, "fact_key_1", "private:12345", 100
            )
            assert success1 is True
            assert reason1 == "granted"

            # 重复授权应幂等
            success2, reason2 = grant_sharing_authorization(
                conn, "qq", 1001, 12345, "fact_key_1", "private:12345", 100
            )
            assert success2 is True
            assert reason2 == "already_active"

            conn.commit()
        finally:
            conn.close()
            Path(db_path).unlink(missing_ok=True)


# ============================================================
# R5: Proactive Contract Tests
# ============================================================


class TestProactiveContract:
    """R5 主动验证合同测试。"""

    def test_validate_bridge_event_not_required(self):
        """不需要桥接时自动通过。"""
        contract = VerificationContract(
            candidate_id=1,
            recording_author_id=12345,
            fact_subject_id=12345,
            fact_object_id=None,
            predicate_type="self_alias",
            polarity="positive",
            source_conversation_key="private:12345",
            source_row_ids=[100],
            candidate_content_digest="abc123",
            bridge_event_requirement=False,
        )

        is_valid, reason = validate_bridge_event(None, contract)
        assert is_valid is True
        assert reason == "not_required"

    def test_validate_bridge_event_missing(self):
        """需要桥接但缺失时拒绝。"""
        contract = VerificationContract(
            candidate_id=1,
            recording_author_id=12345,
            fact_subject_id=12345,
            fact_object_id=67890,
            predicate_type="relationship",
            polarity="positive",
            source_conversation_key="group:99999",
            source_row_ids=[200],
            candidate_content_digest="def456",
            bridge_event_requirement=True,
        )

        is_valid, reason = validate_bridge_event(None, contract)
        assert is_valid is False
        assert reason == "bridge_missing"

    def test_validate_bridge_event_target_mismatch(self):
        """桥接目标不匹配时拒绝。"""
        contract = VerificationContract(
            candidate_id=1,
            recording_author_id=12345,
            fact_subject_id=12345,
            fact_object_id=67890,
            predicate_type="relationship",
            polarity="positive",
            source_conversation_key="group:99999",
            source_row_ids=[200],
            candidate_content_digest="def456",
            bridge_event_requirement=True,
        )

        bridge = BridgeEvidence(
            target_user_id=11111,  # 不匹配
            conversation_key="group:99999",
            recent_message_ids=[300, 301],
            recent_event_digests=["event1"],
        )

        is_valid, reason = validate_bridge_event(bridge, contract)
        assert is_valid is False
        assert reason == "bridge_target_mismatch"

    def test_select_question_variant_prefers_matching(self):
        """选择匹配桥接要求的变体。"""
        contract = VerificationContract(
            candidate_id=1,
            recording_author_id=12345,
            fact_subject_id=12345,
            fact_object_id=None,
            predicate_type="self_alias",
            polarity="positive",
            source_conversation_key="private:12345",
            source_row_ids=[100],
            candidate_content_digest="abc123",
            question_variants=[
                QuestionVariant(
                    variant_id="A",
                    question_template="你是{name}吗？",
                    filled_question="你是Nox吗？",
                    requires_bridge=False,
                ),
                QuestionVariant(
                    variant_id="B",
                    question_template="刚才提到的{name}是你吗？",
                    filled_question="刚才提到的Nox是你吗？",
                    requires_bridge=True,
                ),
            ],
        )

        # 没有桥接，选择不需要桥接的变体
        variant = select_question_variant(contract, has_bridge=False)
        assert variant is not None
        assert variant.variant_id == "A"

        # 有桥接，选择需要桥接的变体
        variant = select_question_variant(contract, has_bridge=True)
        assert variant is not None
        assert variant.variant_id == "B"


# ============================================================
# R6: Attribution Guard Tests
# ============================================================


class TestAttributionGuard:
    """R6 归属守护测试。"""

    def test_build_evidence_table_priority(self):
        """证据表优先级正确。"""
        corrections = [{"id": "c1", "author_id": 12345, "text": "correction", "conversation_key": "test", "timestamp": "2026-10-05T10:00:00"}]
        facts = [{"id": "f1", "author_id": 12345, "content": "fact", "conversation_key": "test", "timestamp": "2026-10-05T09:00:00"}]
        messages = [{"id": "m1", "author_id": 12345, "text": "message", "conversation_key": "test", "timestamp": "2026-10-05T08:00:00"}]

        table = build_evidence_table(messages, facts, corrections, max_units=10)

        # 优先级：correction > fact > message
        ids = list(table.keys())
        assert ids[0].startswith("correction_")
        assert ids[1].startswith("fact_")
        assert ids[2].startswith("msg_")

    def test_check_risky_free_text_detects_patterns(self):
        """检测风险表达模式。"""
        is_safe, pattern = check_risky_free_text("你之前说过喜欢咖啡", set())
        assert is_safe is False
        assert "你之前说" in pattern

        is_safe, pattern = check_risky_free_text("你怎么忘了呢", set())
        assert is_safe is False
        assert "你怎么忘了" in pattern

    def test_validate_evidence_references_all_valid(self):
        """验证有效的证据引用。"""
        plan = ReplyPlan(
            current_response="好的",
            quote_references=["msg_1", "msg_2"],
            verified_fact_references=["fact_1"],
        )

        evidence = {
            "msg_1": SourceEvidence("msg_1", "message", 12345, None, "text1", "key", 100, "2026-10-05T10:00:00"),
            "msg_2": SourceEvidence("msg_2", "message", 12345, None, "text2", "key", 101, "2026-10-05T10:01:00"),
            "fact_1": SourceEvidence("fact_1", "verified_fact", 12345, None, "fact", "key", 200, "2026-10-05T09:00:00", is_verified=True),
        }

        budget = {"msg_1", "msg_2", "fact_1"}

        all_valid, invalid = validate_evidence_references(plan, evidence, budget)
        assert all_valid is True
        assert len(invalid) == 0

    def test_validate_evidence_references_invalid(self):
        """验证无效的证据引用。"""
        plan = ReplyPlan(
            current_response="好的",
            quote_references=["msg_999"],  # 不存在
        )

        evidence = {
            "msg_1": SourceEvidence("msg_1", "message", 12345, None, "text1", "key", 100, "2026-10-05T10:00:00"),
        }

        budget = {"msg_1"}

        all_valid, invalid = validate_evidence_references(plan, evidence, budget)
        assert all_valid is False
        assert len(invalid) == 1
        assert "msg_999:not_in_evidence" in invalid

    def test_apply_guard_decision_off_mode(self):
        """off 模式放行所有。"""
        decision = apply_guard_decision(None, {}, "off", 1)
        assert decision.decision == "pass"
        assert decision.guard_mode == "off"

    def test_apply_guard_decision_enforce_parse_failed(self):
        """enforce 模式拒绝解析失败。"""
        decision = apply_guard_decision(None, {}, "enforce", 1)
        assert decision.decision == "reject"
        assert decision.rejection_reason == "parse_failed"

    def test_apply_guard_decision_shadow_mode(self):
        """shadow 模式记录但放行。"""
        decision = apply_guard_decision(None, {}, "shadow", 1)
        assert decision.decision == "fallback"
        assert "shadow" in decision.rejection_reason


# ============================================================
# R7: Data Repair Tests
# ============================================================


class TestDataRepair:
    """R7 数据修复测试。"""

    def test_preview_wrong_space_records(self):
        """预览错误 SPACE 归属。"""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name

        try:
            conn = sqlite3.connect(db_path)

            # 创建测试表
            conn.execute("""
                CREATE TABLE memories (
                    id TEXT PRIMARY KEY,
                    audience TEXT,
                    owner_type TEXT,
                    owner_key TEXT,
                    user_id INTEGER,
                    fact_key TEXT,
                    status TEXT DEFAULT 'ACTIVE'
                )
            """)

            # 插入错误记录：PERSON 但标记为 SPACE
            conn.execute(
                "INSERT INTO memories (id, audience, owner_type, owner_key, user_id, fact_key, status) "
                "VALUES ('m1', 'SPACE', 'PERSON', 'user:12345', 12345, 'fk1', 'ACTIVE')"
            )

            conn.commit()

            records = preview_wrong_space_records(conn)
            assert len(records) == 1
            assert records[0].issue_type == "wrong_space"
            assert records[0].proposed_value == "PRIVATE_ONLY"

            conn.close()
        finally:
            Path(db_path).unlink(missing_ok=True)

    def test_apply_repairs_dry_run(self, monkeypatch):
        """dry_run 不修改数据。"""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name

        try:
            conn = sqlite3.connect(db_path)

            conn.execute("""
                CREATE TABLE memories (
                    id TEXT PRIMARY KEY,
                    status TEXT DEFAULT 'ACTIVE',
                    updated_at TEXT
                )
            """)

            conn.execute("INSERT INTO memories (id, status) VALUES ('m1', 'ACTIVE')")
            conn.commit()
            conn.close()

            # 工具按 CLI 设计连接全局 DB_PATH；测试把它指到临时库
            import tools.data_repair as data_repair_module
            monkeypatch.setattr(data_repair_module, "DB_PATH", db_path)

            # 准备修复记录
            records = [
                RepairRecord(
                    record_id="m1",
                    table_name="memories",
                    issue_type="wrong_space",
                    current_value="ACTIVE",
                    proposed_value="DEPRECATED",
                    reason="test",
                    affected_user_id=12345,
                    confidence=0.95,
                )
            ]

            # Dry run
            batch = apply_repairs(records, operator="test", dry_run=True)
            assert batch is None

            # 验证未修改
            conn = sqlite3.connect(db_path)
            row = conn.execute("SELECT status FROM memories WHERE id = 'm1'").fetchone()
            assert row[0] == "ACTIVE"
            conn.close()
        finally:
            Path(db_path).unlink(missing_ok=True)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
