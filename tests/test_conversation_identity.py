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
