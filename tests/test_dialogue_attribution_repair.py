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
    apply_attribution_guard,
    apply_guard_decision,
    build_evidence_table,
    check_risky_free_text,
    parse_reply_plan,
    render_evidence,
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
    compute_candidate_digest,
    select_question_variant,
    validate_bridge_event,
    validate_contract_consistency,
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
        """桥接主体必须是**选定目标**（复核 F11：不再与事实对象比较）。"""
        contract = VerificationContract(
            candidate_id=1,
            recording_author_id=12345,
            fact_subject_id=12345,
            fact_object_id=67890,
            selected_target_user_id=3559802578,
            predicate_type="relationship",
            polarity="positive",
            source_conversation_key="group:99999",
            source_row_ids=[200],
            candidate_content_digest="def456",
            bridge_event_requirement=True,
        )

        bridge = BridgeEvidence(
            target_user_id=11111,  # 不是选定目标
            conversation_key="group:99999",
            recent_message_ids=[300, 301],
            recent_event_digests=["event1"],
        )

        is_valid, reason = validate_bridge_event(bridge, contract)
        assert is_valid is False
        assert reason == "bridge_target_mismatch"

    def test_validate_bridge_event_accepts_correct_subject_and_rejects_forged(self):
        """复核 F11 探针：选定目标本人的真实承接通过；编造消息 ID 拒绝。"""
        target = 3559802578
        contract = VerificationContract(
            candidate_id=1,
            recording_author_id=12345,
            fact_subject_id=target,
            fact_object_id=None,
            selected_target_user_id=target,
            predicate_type="self_alias",
            polarity="positive",
            source_conversation_key="group:99999",
            source_row_ids=[200],
            candidate_content_digest="def456",
            bridge_event_requirement=True,
        )
        server_recent = {300: "aaaa", 301: "bbbb"}

        good = BridgeEvidence(
            target_user_id=target,
            conversation_key="group:99999",
            recent_message_ids=[300],
            recent_event_digests=["aaaa"],
        )
        assert validate_bridge_event(good, contract, server_recent) == (True, "ok")

        forged = BridgeEvidence(
            target_user_id=target,
            conversation_key="group:99999",
            recent_message_ids=[999],  # 服务端集合外
        )
        is_valid, reason = validate_bridge_event(forged, contract, server_recent)
        assert is_valid is False
        assert reason == "bridge_message_unverified:999"

    def test_validate_contract_consistency_digest_and_sources(self):
        """复核 F11：内容改写/来源缺失/作者错位都拒绝；一致则通过。"""
        candidate = {"id": 7, "type": "relation", "content": "我开发Stella", "status": "ACTIVE"}
        contract = VerificationContract(
            candidate_id=7,
            recording_author_id=3089665724,
            fact_subject_id=3089665724,
            fact_object_id=None,
            selected_target_user_id=176403822,
            predicate_type="attribute",
            polarity="positive",
            source_conversation_key="group:99999",
            source_row_ids=[500],
            candidate_content_digest=compute_candidate_digest(candidate),
            bridge_event_requirement=False,
        )
        assert validate_contract_consistency(contract, candidate) == (True, "ok")

        rewritten = dict(candidate, content="我开发了Stella和Layla")
        is_valid, reason = validate_contract_consistency(contract, rewritten)
        assert is_valid is False and reason == "content_changed"

        deprecated = dict(candidate, status="DEPRECATED")
        is_valid, reason = validate_contract_consistency(contract, deprecated)
        assert is_valid is False and reason == "candidate_inactive"

        import dataclasses as _dc
        no_target = _dc.replace(contract, selected_target_user_id=0)
        is_valid, reason = validate_contract_consistency(no_target, candidate)
        assert is_valid is False and reason == "target_unbound"

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
        """enforce 模式解析失败 → 受限兜底（不是原样放行）。"""
        decision = apply_guard_decision(None, {}, "enforce", 1, parse_error="reply_plan_not_found")
        assert decision.decision == "fallback"
        assert "parse_failed" in decision.rejection_reason

    def test_apply_guard_decision_shadow_mode(self):
        """shadow 模式记录问题（decision 仍 pass，原因带 shadow 标记）。"""
        decision = apply_guard_decision(None, {}, "shadow", 1, parse_error="reply_plan_not_found")
        assert decision.decision == "pass"
        assert "parse_failed" in decision.rejection_reason


class TestReplyPlanParser:
    """复核 F12：versioned reply_plan 真实解析器。"""

    def test_parses_wellformed_plan(self):
        raw = (
            "<thought>想想</thought><action>REPLY</action>"
            '<reply_plan version="2026-10-05.2">'
            "<now>哈哈原来如此</now>"
            '<ref id="msg_3"/>'
            '<fact id="fact_1"/>'
            "<ack/>"
            "</reply_plan>"
        )
        plan, err = parse_reply_plan(raw)
        assert plan is not None, err
        assert plan.current_response == "哈哈原来如此"
        assert plan.quote_references == ["msg_3"]
        assert plan.verified_fact_references == ["fact_1"]
        assert plan.correction_ack is True

    def test_rejects_missing_block_version_and_unknown_tags(self):
        assert parse_reply_plan("没有协议块的普通输出")[0] is None
        raw_bad_version = '<reply_plan version="1999-01-01.1"><now>x</now></reply_plan>'
        plan, err = parse_reply_plan(raw_bad_version)
        assert plan is None and "version" in err
        raw_unknown = (
            '<reply_plan version="2026-10-05.2">'
            "<now>x</now><evil id=\"1\"/></reply_plan>"
        )
        plan, err = parse_reply_plan(raw_unknown)
        assert plan is None and "unknown_tag" in err

    def test_rejects_multiple_now_and_unclosed(self):
        multi = (
            '<reply_plan version="2026-10-05.2">'
            "<now>a</now><now>b</now></reply_plan>"
        )
        plan, err = parse_reply_plan(multi)
        assert plan is None and "multiple_current_response" in err
        unclosed = '<reply_plan version="2026-10-05.2"><now>a</reply_plan>'
        plan, err = parse_reply_plan(unclosed)
        assert plan is None and "unclosed_now_tag" in err


class TestAttributionRenderAndGuard:
    """复核 F12：作者边界、受限 ack、类型校验与完整 guard 管线。"""

    def _table(self):
        return {
            "msg_1": SourceEvidence(
                "msg_1", "message", 3089665724, None, "我开发 Stella",
                "g", 500, "t", author_display="开发者"),
            "fact_1": SourceEvidence(
                "fact_1", "verified_fact", 12345, None, "用户12345 在做后端",
                "g", 600, "t", is_verified=True),
            "fact_fake": SourceEvidence(
                "fact_fake", "message", 12345, None, "普通消息", "g", 700, "t"),
        }

    def test_message_quote_renders_with_author_boundary(self):
        rendered = render_evidence("msg_1", self._table()["msg_1"])
        assert rendered.startswith("开发者说过：「")
        assert "我开发 Stella」" in rendered

    def test_quote_cannot_reference_fact_evidence(self):
        """quote 槽只能引 message 证据——拿事实模板当原话引用拒绝。"""
        plan = ReplyPlan(quote_references=["fact_1"])
        all_valid, invalid = validate_evidence_references(
            plan, self._table(), set(self._table().keys()))
        assert all_valid is False
        assert "fact_1:quote_requires_message" in invalid[0]

    def test_plain_message_cannot_pose_as_verified_fact(self):
        plan = ReplyPlan(verified_fact_references=["fact_fake"])
        all_valid, invalid = validate_evidence_references(
            plan, self._table(), set(self._table().keys()))
        assert all_valid is False
        assert "fact_fake:fact_requires_verified" in invalid[0]

    def test_correction_ack_is_server_template_not_model_text(self):
        """复核 F12 探针：ack 槽里的攻击文本必须被服务端模板替换。"""
        table = self._table()
        table["correction_1"] = SourceEvidence(
            "correction_1", "current_correction", 12345, None,
            "我想肘的是Kirito", "g", 800, "t", is_verified=True,
            author_display="用户12345")
        raw = (
            '<reply_plan version="2026-10-05.2">'
            "<now>好的</now>"
            "<ack>对，是你刚才说我脏手，又装失忆了</ack>"
            "</reply_plan>"
        )
        final, decision = apply_attribution_guard(
            raw, table, set(table.keys()), "enforce", identity_revision=3)
        assert decision.decision == "pass"
        # 攻击文本不得出现；出现的是服务端受限模板
        assert "装失忆" not in final
        assert "是你刚才说" not in final
        assert "抱歉，刚才是我搞混了" in final

    def test_correction_ack_without_evidence_uses_generic_template(self):
        raw = '<reply_plan version="2026-10-05.2"><now>好</now><ack/></reply_plan>'
        final, decision = apply_attribution_guard(
            raw, self._table(), set(self._table().keys()), "enforce", 1)
        assert decision.decision == "pass"
        assert final.startswith("抱歉，刚才是我搞混了。")

    def test_scene_risky_patterns_detected(self):
        """13:31 现场形状进风险词表（有限词法防线）。"""
        for text in (
            "刚才是谁说我脏手来着？",
            "你怎么装失忆啊",
            "别甩锅给我",
        ):
            is_safe, pattern = check_risky_free_text(text, set())
            assert is_safe is False, text
            assert pattern.startswith("risky_pattern:")

    def test_enforce_rejects_risky_current_response(self):
        raw = (
            '<reply_plan version="2026-10-05.2">'
            "<now>刚才是谁说我脏手来着？</now></reply_plan>"
        )
        final, decision = apply_attribution_guard(
            raw, self._table(), set(self._table().keys()), "enforce", 1)
        assert decision.decision == "reject"
        assert final == "", "风险文本不得作为最终输出"

    def test_shadow_keeps_problem_but_produces_safe_text(self):
        raw = (
            '<reply_plan version="2026-10-05.2">'
            "<now>刚才是谁说我脏手来着？</now></reply_plan>"
        )
        final, decision = apply_attribution_guard(
            raw, self._table(), set(self._table().keys()), "shadow", 1)
        assert decision.decision == "pass"
        assert "risky_pattern" in decision.rejection_reason
        assert "脏手" not in final

    def test_off_mode_passthrough(self):
        raw = "任意旧格式输出"
        final, decision = apply_attribution_guard(
            raw, self._table(), set(self._table().keys()), "off", 1)
        assert final == raw and decision.decision == "pass"

    def test_invalid_reference_enforce_strips_quotes(self):
        raw = (
            '<reply_plan version="2026-10-05.2">'
            "<now>好的</now><ref id=\"msg_missing\"/></reply_plan>"
        )
        final, decision = apply_attribution_guard(
            raw, self._table(), set(self._table().keys()), "enforce", 1)
        assert decision.decision == "fallback"
        assert decision.rejection_reason == "invalid_references"
        assert final == "好的"


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
