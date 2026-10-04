# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""M0 合同夹具：ConversationRef / MemoryOwner / MemoryAccessScope / Origin v2。

计划 §6.1/§6.4/§6.8 的身份与归属合同。这里的矩阵是后续所有里程碑的行为
基线：同 QQ 不同 kind 隔离、WebChat -1 不被复用、v1 Origin 按历史解释、
v2 Origin 缺 kind 拒绝、scope 决定 PERSON 分支是否生成。
"""

import json
import sqlite3

import pytest

from core.conversation import (
    KIND_GROUP,
    KIND_PRIVATE,
    conversation_key,
    private_memory_space,
    qq_group_ref,
    qq_private_ref,
    ref_from_conversation_key,
    webchat_ref,
)
from memory.ownership import (
    AUDIENCE_PRIVATE_ONLY,
    AUDIENCE_USER_SHARED,
    OWNER_TYPE_PERSON,
    OWNER_TYPE_SPACE,
    normalize_audience,
    owner_scope_sql,
    person_compat_space,
    person_owner,
    scope_for_conversation,
    space_only_scope,
    space_owner,
)

# ── ConversationRef ──────────────────────────────────────────


class TestConversationRef:
    def test_group_ref_defaults_to_legacy_alias(self):
        ref = qq_group_ref("10000", 263402786)
        assert ref.conversation_key == "qq:10000:group:263402786"
        assert ref.storage_session_id == 263402786
        assert ref.runtime_key == "qq:263402786"
        assert ref.is_group and not ref.is_private
        assert ref.require_group_id() == 263402786

    def test_group_ref_rejects_nonpositive(self):
        with pytest.raises(ValueError):
            qq_group_ref("10000", 0)
        with pytest.raises(ValueError):
            qq_group_ref("10000", -1)

    def test_private_ref_allocated_negative_storage(self):
        ref = qq_private_ref("10000", 20001, storage_session_id=-3)
        assert ref.conversation_key == "qq:10000:private:20001"
        assert ref.runtime_key == "qq:10000:private:20001"
        assert ref.memory_space == "private:qq:10000:20001"
        assert ref.is_private
        with pytest.raises(ValueError):
            ref.require_group_id()  # 私聊没有群号可取

    def test_private_ref_rejects_positive_storage(self):
        # -user_id 捷径被禁止：正数存储 ID 会与真实群号冲突
        with pytest.raises(ValueError):
            qq_private_ref("10000", 20001, storage_session_id=20001)
        with pytest.raises(ValueError):
            qq_private_ref("10000", 20001, storage_session_id=0)

    def test_private_ref_rejects_invalid_user(self):
        with pytest.raises(ValueError):
            qq_private_ref("10000", 0, storage_session_id=-1)

    def test_webchat_ref_keeps_reservation(self):
        ref = webchat_ref(user_id=800_000_000)
        assert ref.storage_session_id == -1
        assert ref.conversation_key == "webchat:800000000"
        assert ref.memory_space == "webchat"
        with pytest.raises(ValueError):
            webchat_ref(user_id=1, storage_session_id=5)  # -1 不可挪用

    def test_same_integer_peer_different_kind_isolated(self):
        """peer=同一整数时 group 与 private 必须是完全不同的会话（§8.1）。"""
        g = qq_group_ref("10000", 123456)
        p = qq_private_ref("10000", 123456, storage_session_id=-9)
        assert g.conversation_key != p.conversation_key
        assert g.runtime_key != p.runtime_key
        assert g.storage_session_id != p.storage_session_id

    def test_multi_bot_same_user_isolated(self):
        a = qq_private_ref("10000", 20001, storage_session_id=-3)
        b = qq_private_ref("20000", 20001, storage_session_id=-4)
        assert a.conversation_key != b.conversation_key
        assert a.memory_space != b.memory_space

    def test_key_roundtrip(self):
        for ref in (
            qq_group_ref("10000", 263402786),
            qq_private_ref("10000", 20001, storage_session_id=-3),
            qq_private_ref("20000", 1, storage_session_id=-100),
        ):
            restored = ref_from_conversation_key(
                ref.conversation_key, storage_session_id=ref.storage_session_id
            )
            assert restored.conversation_key == ref.conversation_key
            assert restored.memory_space == ref.memory_space

    def test_key_roundtrip_group_alias(self):
        restored = ref_from_conversation_key(
            "qq:10000:group:263402786", storage_session_id=263402786, runtime_key="qq:263402786"
        )
        assert restored.runtime_key == "qq:263402786"

    def test_key_roundtrip_rejects_garbage(self):
        with pytest.raises(ValueError):
            ref_from_conversation_key("not-a-key", storage_session_id=-1)
        with pytest.raises(ValueError):
            ref_from_conversation_key("qq:10000:unknown:1", storage_session_id=-1)

    def test_helpers(self):
        assert conversation_key("qq", "10000", KIND_GROUP, "1") == "qq:10000:group:1"
        assert conversation_key("qq", "10000", KIND_PRIVATE, "1") == "qq:10000:private:1"
        assert (
            private_memory_space("qq", "10000", "20001") == "private:qq:10000:20001"
        )


# ── MemoryOwner / MemoryAccessScope ──────────────────────────


class TestOwnership:
    def test_owner_validation(self):
        space = space_owner("space_1")
        assert space.owner_type == OWNER_TYPE_SPACE
        assert space.owner_key == "space:space_1"
        person = person_owner("qq", "10000", 20001)
        assert person.owner_type == OWNER_TYPE_PERSON
        assert person.owner_key == "person:qq:10000:20001"
        assert person.subject_key == "qq:20001"
        assert person.validated()
        # 校验规则：PERSON 必带 subject、SPACE 不带 subject、type 合法
        from memory.ownership import MemoryOwner

        with pytest.raises(ValueError):
            MemoryOwner(OWNER_TYPE_PERSON, "person:qq:1:2").validated()
        with pytest.raises(ValueError):
            MemoryOwner(OWNER_TYPE_SPACE, "space:s", subject_key="qq:2").validated()
        with pytest.raises(ValueError):
            MemoryOwner("OTHER", "x").validated()

    def test_scope_group_gets_user_shared_only(self):
        scope = scope_for_conversation(
            kind="group", memory_space="space_1", platform="qq", bot_id="10000", user_id=20001
        )
        assert scope.has_person
        assert scope.person_audiences == (AUDIENCE_USER_SHARED,)
        assert AUDIENCE_PRIVATE_ONLY not in scope.person_audiences

    def test_scope_private_gets_private_and_shared(self):
        scope = scope_for_conversation(
            kind="private",
            memory_space=private_memory_space("qq", "10000", "20001"),
            platform="qq",
            bot_id="10000",
            user_id=20001,
        )
        assert scope.person_audiences == (AUDIENCE_PRIVATE_ONLY, AUDIENCE_USER_SHARED)

    def test_scope_untrusted_subject_is_space_only(self):
        for bad in (0, -5):
            scope = scope_for_conversation(
                kind="private", memory_space="s", platform="qq", bot_id="1", user_id=bad
            )
            assert not scope.has_person
        scope = scope_for_conversation(
            kind="webchat", memory_space="webchat", platform="webchat", bot_id="", user_id=800_000_000
        )
        assert not scope.has_person  # webchat 第一版不进入 QQ 个人层

    def test_space_only_scope(self):
        scope = space_only_scope("space_1")
        assert not scope.has_person
        assert scope.space_key == "space:space_1"

    def test_fingerprint_changes_with_scope(self):
        a = space_only_scope("space_1")
        b = scope_for_conversation(
            kind="group", memory_space="space_1", platform="qq", bot_id="1", user_id=2
        )
        c = scope_for_conversation(
            kind="group", memory_space="space_1", platform="qq", bot_id="1", user_id=3
        )
        assert a.fingerprint() != b.fingerprint()
        assert b.fingerprint() != c.fingerprint()

    def test_compat_namespace_never_matches_real_space(self):
        compat = person_compat_space("person:qq:10000:20001", AUDIENCE_USER_SHARED)
        assert compat.startswith("personal:")
        assert compat != "space_1" and not compat.startswith("space:")

    def test_normalize_audience(self):
        assert normalize_audience("user_shared") == AUDIENCE_USER_SHARED
        assert normalize_audience(None) == "CURRENT_SPACE"
        assert normalize_audience("bogus") == "CURRENT_SPACE"


class TestScopeSql:
    def test_space_only_fragment(self):
        frag, params = owner_scope_sql(space_only_scope("space_1"))
        assert "owner_type = 'SPACE'" in frag
        assert "PERSON" not in frag
        assert params == ["space:space_1"]

    def test_person_fragment_filters_by_audience(self):
        scope = scope_for_conversation(
            kind="private", memory_space="s", platform="qq", bot_id="1", user_id=2
        )
        frag, params = owner_scope_sql(scope)
        assert "owner_type = 'PERSON'" in frag
        # 位置参数：space → person → subject → audiences（计划 §6.6 谓词顺序）
        assert params == [
            "space:s",
            "person:qq:1:2",
            "qq:2",
            AUDIENCE_PRIVATE_ONLY,
            AUDIENCE_USER_SHARED,
        ]

    def test_fragment_against_sqlite(self):
        """片段在真实 SQLite 上按 owner/audience 过滤（候选池权限下推）。"""
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE t (id INTEGER PRIMARY KEY, group_shared_space TEXT,"
            " owner_type TEXT, owner_key TEXT, subject_key TEXT, audience TEXT)"
        )
        rows = [
            (1, "space_1", OWNER_TYPE_SPACE, "space:space_1", "", "CURRENT_SPACE"),
            (2, "space_2", OWNER_TYPE_SPACE, "space:space_2", "", "CURRENT_SPACE"),
            (3, "personal:x", OWNER_TYPE_PERSON, "person:qq:1:2", "qq:2", AUDIENCE_USER_SHARED),
            (4, "personal:y", OWNER_TYPE_PERSON, "person:qq:1:2", "qq:2", AUDIENCE_PRIVATE_ONLY),
            (5, "personal:z", OWNER_TYPE_PERSON, "person:qq:1:3", "qq:3", AUDIENCE_USER_SHARED),
        ]
        conn.executemany("INSERT INTO t VALUES (?,?,?,?,?,?)", rows)

        def run(scope):
            frag, params = owner_scope_sql(scope)
            return sorted(
                r[0]
                for r in conn.execute(
                    "SELECT id FROM t WHERE 1=1" + frag + " ORDER BY id", params
                )
            )

        assert run(space_only_scope("space_1")) == [1]
        group_scope = scope_for_conversation(
            kind="group", memory_space="space_1", platform="qq", bot_id="1", user_id=2
        )
        assert run(group_scope) == [1, 3]  # PRIVATE_ONLY 对群不可见
        private_scope = scope_for_conversation(
            kind="private", memory_space="s", platform="qq", bot_id="1", user_id=2
        )
        assert run(private_scope) == [3, 4]
        other_user = scope_for_conversation(
            kind="private", memory_space="s", platform="qq", bot_id="1", user_id=3
        )
        assert run(other_user) == [5]


# ── Origin v2 ────────────────────────────────────────────────


class TestOriginV2:
    def _v1_qq(self):
        return {
            "schema_version": 1,
            "instance_id": "inst",
            "platform": "qq",
            "bot_id": "10000",
            "conversation_id": "263402786",
            "requester_id": "20001",
            "source_request_id": "msg-1",
            "reply_to_message_id": "1",
            "conversation_generation": 1,
        }

    def test_v1_qq_legacy_parses_as_group(self):
        from cometa.models import Origin

        origin = Origin.from_dict(self._v1_qq())
        assert origin.conversation_kind == "group"
        assert origin.peer_id == "263402786"
        # legacy 行推导出规范键（roundtrip 闭环，见 from_dict）
        assert origin.conversation_key == "qq:10000:group:263402786"

    def test_v1_webchat_legacy_parses_as_webchat(self):
        from cometa.models import Origin

        data = self._v1_qq()
        data.update({"platform": "webchat", "conversation_id": "webchat", "bot_id": "webui"})
        origin = Origin.from_dict(data)
        assert origin.conversation_kind == "webchat"
        assert origin.peer_id == "webchat"

    def test_v2_roundtrip(self):
        from cometa.models import ORIGIN_SCHEMA_VERSION, Origin

        origin = Origin(
            instance_id="inst",
            platform="qq",
            bot_id="10000",
            conversation_id="qq:10000:private:20001",
            requester_id="20001",
            conversation_kind="private",
            peer_id="20001",
            conversation_key="qq:10000:private:20001",
        )
        data = origin.to_dict()
        assert data["origin_schema_version"] == ORIGIN_SCHEMA_VERSION == 2
        # 旧字段一个不少：旧读端仍能拿到 conversation_id 等
        for key in self._v1_qq():
            assert key in data
        restored = Origin.from_dict(data)
        assert restored == origin

    def test_v2_missing_kind_rejected(self):
        from cometa.models import Origin

        data = self._v1_qq()
        data["origin_schema_version"] = 2  # 声称 v2 却缺 kind —— 数据损坏
        with pytest.raises(ValueError):
            Origin.from_dict(data)

    def test_v2_missing_conversation_key_is_derived(self):
        """conversation_key 是其余字段的规范函数：缺失时推导（roundtrip 闭环），
        不作猜测——kind/peer 缺失才拒绝。"""
        from cometa.models import Origin

        data = self._v1_qq()
        data.update(
            {"origin_schema_version": 2, "conversation_kind": "private", "peer_id": "20001"}
        )
        origin = Origin.from_dict(data)
        assert origin.conversation_key == "qq:10000:private:20001"

    def test_invalid_kind_rejected_at_construction(self):
        from cometa.models import Origin

        with pytest.raises(ValueError):
            Origin(
                instance_id="i", platform="qq", bot_id="b", conversation_id="c",
                requester_id="r", conversation_kind="channel",
            )

    def test_target_builder_v2_aware(self):
        """_target_from_task_row：private 的 group_id 必须为空（计划 §6.8）。"""
        from cometa.models import Origin
        from cometa.store import CometaStore

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE tasks (task_id TEXT PRIMARY KEY, origin_json TEXT)"
        )
        v2_private = Origin(
            instance_id="inst", platform="qq", bot_id="10000",
            conversation_id="qq:10000:private:20001", requester_id="20001",
            conversation_kind="private", peer_id="20001",
            conversation_key="qq:10000:private:20001",
        )
        conn.execute(
            "INSERT INTO tasks VALUES (?, ?)",
            ("t1", json.dumps(v2_private.to_dict())),
        )
        conn.execute("INSERT INTO tasks VALUES (?, ?)", ("t2", json.dumps(self._v1_qq())))
        target = CometaStore._target_from_task_row(conn, "t1")
        assert target["conversation_kind"] == "private"
        assert target["peer_id"] == "20001"
        assert target["group_id"] == ""  # 私聊绝不填群号
        legacy = CometaStore._target_from_task_row(conn, "t2")
        assert legacy["conversation_kind"] == "group"
        assert legacy["group_id"] == "263402786"  # 旧行为不变


# ── 会话内身份声明与纠错（多人身份修复计划 §6.3，T03–T06/T15） ─────────
# 追加段：解析规则、本人声明、第三人纠正、事务原子性、capsule 语义。

import sqlite3 as _sqlite3

import memory.conversation_identity as identity
from core.context import ChatContext
from memory.conversation_identity import (
    build_identity_capsule,
    get_identity_revision,
    parse_self_alias,
    parse_third_person_correction,
    process_message_identity,
    record_self_alias_claim,
    record_third_person_correction,
    resolve_correction_target,
    subject_alias,
)


@pytest.fixture()
def ident_db(tmp_path, monkeypatch):
    db = tmp_path / "agent_memory.db"
    monkeypatch.setattr(identity, "DB_PATH", db)
    return db


def _msg_ctx(**kw):
    base = {
        "user_id": 2001, "group_id": 7777, "msg_id": 1, "message": "我是阿呆",
        "source_kind": "AT_MENTION",
        "conversation_kind": "group",
        "conversation_key": "qq:10000:group:7777",
        "bot_id": "10000", "peer_id": "7777", "storage_session_id": 7777,
        "recorded_row_id": 42,
    }
    base.update(kw)
    return ChatContext(**base)


# ── 有界解析规则 ──────────────────────────────────────────────────────


def test_self_alias_patterns_bounded():
    assert parse_self_alias("阿呆是我") == ("阿呆", False)
    assert parse_self_alias("我是阿呆") == ("阿呆", False)
    assert parse_self_alias("我才是allest") == ("allest", True)
    assert parse_self_alias("那我改名叫Allets") == ("Allets", True)
    assert parse_self_alias("以后叫我阿呆") == ("阿呆", False)
    # 引号/转述 → ambiguous
    assert parse_self_alias("「我是阿呆」") is None
    assert parse_self_alias("他说：我是阿呆") is None
    # 多个自称 → ambiguous
    assert parse_self_alias("我是阿呆，我也是呆呆") is None
    # 角色权限表达 → 不产生身份
    assert parse_self_alias("我是管理员") is None
    assert parse_self_alias("我是机器人") is None
    # 超长 → ambiguous
    assert parse_self_alias("我是" + "x" * 40) is None
    # 空串
    assert parse_self_alias("") is None


def test_third_person_patterns_bounded():
    assert parse_third_person_correction("他才是Allets") == ("Allets", True)
    assert parse_third_person_correction("Allets不是他") == ("Allets", False)
    assert parse_third_person_correction("他不叫Allets") == ("Allets", False)
    # 引号转述 → ambiguous
    assert parse_third_person_correction("「他才是Allets」") is None
    # 角色表达 → 拒绝
    assert parse_third_person_correction("他才是管理员") is None


# ── T04：本人声明即时生效 + revision 推进 ─────────────────────────────


def test_self_claim_persists_and_bumps_revision(ident_db):
    key = "qq:10000:group:7777"
    assert get_identity_revision(key) == 0
    ok = record_self_alias_claim(
        key, "10000", "2001", "阿呆",
        supersedes=False, source_row_id=42, evidence_excerpt="我是阿呆",
    )
    assert ok
    assert subject_alias(key, "2001") == "阿呆"
    assert get_identity_revision(key) == 1
    # 同名重复声明幂等：不再写行、不再 bump
    ok2 = record_self_alias_claim(
        key, "10000", "2001", "阿呆",
        supersedes=False, source_row_id=43, evidence_excerpt="阿呆是我",
    )
    assert not ok2
    assert get_identity_revision(key) == 1


def test_rename_supersedes_old_alias_next_turn_visible(ident_db):
    key = "qq:10000:group:7777"
    record_self_alias_claim(key, "10000", "2001", "阿呆",
                            supersedes=False, source_row_id=1, evidence_excerpt="我是阿呆")
    record_self_alias_claim(key, "10000", "2001", "Allets",
                            supersedes=True, source_row_id=2, evidence_excerpt="那我改名叫Allets")
    # 最新更名生效；旧别名不再 active
    assert subject_alias(key, "2001") == "Allets"
    assert get_identity_revision(key) == 2
    # capsule 下一轮立即看到新名
    ctx = _msg_ctx(message="我是谁")
    assert "Allets" in build_identity_capsule(ctx)


def test_process_message_identity_hook_end_to_end(ident_db):
    ctx = _msg_ctx(message="阿呆是我")
    process_message_identity(ctx)
    key = ctx.conversation_key
    assert subject_alias(key, "2001") == "阿呆"
    # 第三人无目标纠正：不写任何映射
    ctx2 = _msg_ctx(user_id=2003, msg_id=2, recorded_row_id=43, message="他才是Allets")
    process_message_identity(ctx2)
    assert get_identity_revision(ctx2.conversation_key) == 1  # 只有本人声明那次


# ── T03/T05：第三人纠正有来源、不串身份、别名冲突不合并 ────────────────


def test_third_correction_with_target_keeps_author_separate(ident_db):
    key = "qq:10000:group:7777"
    ok = record_third_person_correction(
        key, "10000", author_user_id="2003", target_user_id="2001",
        alias="Allets", is_positive=True, source_row_id=44,
        evidence_excerpt="他才是Allets",
    )
    assert ok
    # 作者没有获得该身份；subject 是被指认者；版本推进
    assert subject_alias(key, "2003") == ""
    assert subject_alias(key, "2001") == ""  # 纠正≠本人确认
    assert get_identity_revision(key) == 1


def test_alias_collision_keeps_distinct_uids(ident_db):
    key = "qq:10000:group:7777"
    record_self_alias_claim(key, "10000", "2001", "阿呆",
                            supersedes=False, source_row_id=1, evidence_excerpt="我是阿呆")
    record_self_alias_claim(key, "10000", "2002", "阿呆",
                            supersedes=False, source_row_id=2, evidence_excerpt="我是阿呆")
    # 两个稳定 uid 各自保留，不合并
    assert subject_alias(key, "2001") == "阿呆"
    assert subject_alias(key, "2002") == "阿呆"


def test_third_positive_marks_same_alias_conflicted(ident_db):
    key = "qq:10000:group:7777"
    record_self_alias_claim(key, "10000", "2001", "Allets",
                            supersedes=False, source_row_id=1, evidence_excerpt="我是Allets")
    record_third_person_correction(
        key, "10000", author_user_id="2003", target_user_id="2002",
        alias="Allets", is_positive=True, source_row_id=2,
        evidence_excerpt="他才是Allets",
    )
    # 2001 的同名声明进入争议；capsule 提示争议
    claims = identity.active_claims(key)
    conflicted = [c for c in claims if c["status"] == identity.STATUS_CONFLICTED]
    assert conflicted and conflicted[0]["subject_user_id"] == "2001"
    capsule = build_identity_capsule(_msg_ctx(user_id=2002, recorded_row_id=9))
    assert "争议" in capsule
    assert "Allets" in capsule


def test_resolve_correction_target_priority():
    # 显式 @ 唯一目标优先
    assert resolve_correction_target(
        author_user_id="2003", mentioned_user_ids=("2001", "10000"),
        bot_id="10000",
    ) == "2001"
    # 多个 @ → unknown
    assert resolve_correction_target(
        author_user_id="2003", mentioned_user_ids=("2001", "2002"),
    ) == ""
    # reply target 次之
    assert resolve_correction_target(
        author_user_id="2003", reply_target_user_id="2001",
    ) == "2001"
    # 作者本人不能是目标
    assert resolve_correction_target(
        author_user_id="2001", mentioned_user_ids=("2001",),
    ) == ""
    # 无目标 → unknown
    assert resolve_correction_target(author_user_id="2003") == ""


def _bot_bubble_db(conn):
    """Bot 气泡表（v16 形状：带 canonical 会话列）。"""
    conn.execute(
        "CREATE TABLE group_messages (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " group_id TEXT, user_id TEXT, content TEXT,"
        " source_kind TEXT DEFAULT 'PASSIVE', msg_id INTEGER,"
        " timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,"
        " conversation_key TEXT, bot_id TEXT,"
        " reply_recipient_user_id TEXT)"
    )
    conn.execute(
        "INSERT INTO group_messages (group_id, user_id, content, source_kind,"
        " msg_id, conversation_key, bot_id, reply_recipient_user_id)"
        " VALUES ('7777', '10000', '你好', 'BOT_SELF', 900,"
        " 'qq:10000:group:7777', '10000', '2002')"
    )
    conn.commit()


def test_reply_to_bot_bubble_recipient_is_candidate(ident_db):
    # Bot 气泡记录了收件人 2002；C 回复该气泡纠正
    conn = _sqlite3.connect(ident_db)
    _bot_bubble_db(conn)
    conn.close()
    target = resolve_correction_target(
        author_user_id="2003", reply_to_msg_id="900",
        bot_id="10000", conversation_key="qq:10000:group:7777",
        group_key="7777",
    )
    assert target == "2002"


def test_bot_bubble_recipient_scope_and_signed_guards(ident_db):
    """canonical scope 强制校验；负数 ID 解析；旧库缺列保守 unknown。"""
    conn = _sqlite3.connect(ident_db)
    _bot_bubble_db(conn)
    conn.close()
    good = {
        "bot_id": "10000",
        "conversation_key": "qq:10000:group:7777",
        "group_key": "7777",
    }
    # 另一个 Bot 的同号会话：canonical 不匹配 → unknown（不再跨 Bot 取收件人）
    assert resolve_correction_target(
        author_user_id="2003", reply_to_msg_id="900",
        bot_id="20000", conversation_key="qq:20000:group:7777", group_key="7777",
    ) == ""
    # 缺 conversation_key 参数 → 无法校验 scope，保守 unknown
    assert resolve_correction_target(
        author_user_id="2003", reply_to_msg_id="900", bot_id="10000", group_key="7777",
    ) == ""
    # 负数平台 ID：气泡行 msg_id=-900 时同样解析（有符号修复）
    conn = _sqlite3.connect(ident_db)
    conn.execute(
        "INSERT INTO group_messages (group_id, user_id, content, source_kind,"
        " msg_id, conversation_key, bot_id, reply_recipient_user_id)"
        " VALUES ('7777', '10000', '在的', 'BOT_SELF', -900,"
        " 'qq:10000:group:7777', '10000', '2001')"
    )
    conn.commit()
    conn.close()
    assert resolve_correction_target(
        author_user_id="2003", reply_to_msg_id="-900", **good,
    ) == "2001"
    # 旧库（无 conversation_key 列）→ 保守降级，不凭 group_key 推断
    legacy = _sqlite3.connect(ident_db)
    legacy.execute("DROP TABLE group_messages")
    legacy.execute(
        "CREATE TABLE group_messages (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " group_id TEXT, user_id TEXT, content TEXT,"
        " source_kind TEXT DEFAULT 'PASSIVE', msg_id INTEGER,"
        " timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,"
        " reply_recipient_user_id TEXT)"
    )
    legacy.execute(
        "INSERT INTO group_messages (group_id, user_id, content, source_kind,"
        " msg_id, reply_recipient_user_id) VALUES ('7777', '10000', '你好',"
        " 'BOT_SELF', 900, '2002')"
    )
    legacy.commit()
    legacy.close()
    assert resolve_correction_target(
        author_user_id="2003", reply_to_msg_id="900",
        bot_id="10000", conversation_key="qq:10000:group:7777", group_key="7777",
    ) == ""


def test_reply_to_bot_resolves_to_bubble_recipient_not_bot(ident_db):
    """G5：引用 Bot 气泡时作者解析结果是 Bot，纠正目标必须是收件人 A。"""
    conn = _sqlite3.connect(ident_db)
    _bot_bubble_db(conn)
    conn.close()
    # reply_target 已被解析为 Bot（作者）——绝不能把 Bot 当纠正主体
    assert resolve_correction_target(
        author_user_id="2003",
        reply_target_user_id="10000",
        reply_to_msg_id="900",
        bot_id="10000",
        conversation_key="qq:10000:group:7777",
        group_key="7777",
    ) == "2002"
    # 收件人不可知（气泡不存在）→ unknown，而不是退化成 Bot
    assert resolve_correction_target(
        author_user_id="2003",
        reply_target_user_id="10000",
        reply_to_msg_id="404",
        bot_id="10000",
        conversation_key="qq:10000:group:7777",
        group_key="7777",
    ) == ""
    # 兜底：Bot 永远不能是纠正目标
    assert resolve_correction_target(
        author_user_id="2003",
        reply_target_user_id="10000",
        bot_id="10000",
    ) == ""


# ── T06：称呼偏好不被绕过 ────────────────────────────────────────────


def test_preference_table_never_touched_by_claims(ident_db):
    key = "qq:10000:group:7777"
    record_self_alias_claim(key, "10000", "2001", "阿呆",
                            supersedes=False, source_row_id=1, evidence_excerpt="我是阿呆")
    record_third_person_correction(
        key, "10000", author_user_id="2003", target_user_id="2001",
        alias="阿呆", is_positive=True, source_row_id=2,
        evidence_excerpt="他才是阿呆",
    )
    conn = _sqlite3.connect(ident_db)
    try:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
                " AND name='user_address_preferences'"
            )
        ]
    finally:
        conn.close()
    # 声明路径根本不建偏好表（更不会写它）；称呼命令仍走原权限链
    assert tables == []


# ── T15：事务失败无半条 claim/version ────────────────────────────────


def test_claim_transaction_atomic_on_failure(ident_db, monkeypatch):
    key = "qq:10000:group:7777"

    class _BoomError(Exception):
        pass

    real_connect = identity._connect

    class _FailingConn:
        def __init__(self, inner):
            self._inner = inner

        def execute(self, sql, *a, **kw):
            if "INSERT INTO conversation_identity_claims" in sql:
                raise _BoomError("sqlite lock")
            return self._inner.execute(sql, *a, **kw)

        def __getattr__(self, name):
            return getattr(self._inner, name)

    def failing_connect():
        return _FailingConn(real_connect())

    monkeypatch.setattr(identity, "_connect", failing_connect)
    ok = record_self_alias_claim(key, "10000", "2001", "阿呆",
                                 supersedes=False, source_row_id=1, evidence_excerpt="x")
    assert not ok
    monkeypatch.setattr(identity, "_connect", real_connect)
    # 无半条声明、版本未前进
    assert subject_alias(key, "2001") == ""
    assert get_identity_revision(key) == 0
    # 重试幂等成功
    assert record_self_alias_claim(key, "10000", "2001", "阿呆",
                                   supersedes=False, source_row_id=2, evidence_excerpt="x")


# ── capsule 语义 ──────────────────────────────────────────────────────


def test_capsule_without_evidence_says_unknown():
    capsule = build_identity_capsule(_msg_ctx(user_id=2999))
    assert "不确定" in capsule
    assert "2999" in capsule


def test_capsule_never_borrows_other_member_name(ident_db):
    key = "qq:10000:group:7777"
    record_self_alias_claim(key, "10000", "2001", "阿呆",
                            supersedes=False, source_row_id=1, evidence_excerpt="x")
    # 2002 无声明 → 明确不确定，不借阿呆
    capsule = build_identity_capsule(_msg_ctx(user_id=2002, recorded_row_id=9))
    assert "阿呆" not in capsule.split("不确定")[0]


def test_capsule_reply_target_attribution():
    ctx = _msg_ctx(user_id=2002, reply_target_user_id="2001", recorded_row_id=9)
    capsule = build_identity_capsule(ctx)
    assert "回复" in capsule and "2001" in capsule


def test_identity_question_direct_reply_rules(ident_db):
    from memory.conversation_identity import identity_question_reply

    # 无声明 → 不直复（LLM + capsule 走「不确定」）
    assert identity_question_reply(_msg_ctx(message="我是谁", recorded_row_id=0)) == ""
    # 复合问题 → 永不直复
    assert identity_question_reply(
        _msg_ctx(message="我是谁，今天天气如何", recorded_row_id=0)) == ""
    # 有已验证声明 → 直复带 alias
    record_self_alias_claim(
        "qq:10000:group:7777", "10000", "2001", "阿呆",
        supersedes=False, source_row_id=1, evidence_excerpt="我是阿呆",
    )
    reply = identity_question_reply(_msg_ctx(message="我是谁", recorded_row_id=0))
    assert "阿呆" in reply and "2001" in reply
    # 整条匹配才命中（带问候语不算）
    assert identity_question_reply(
        _msg_ctx(message="你知道我是谁吗", recorded_row_id=0)) == ""
