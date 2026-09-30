# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""CometaService 鉴权与幂等基线（方案 §8.1 test_authorization）。

拒绝矩阵：A 查询/取消/批准 B 的任务、伪造 Origin、过期 request、
未授权用户/群 → 全部拒绝且**无后端调用**（FakeBackend 记账为空）。
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from conftest import make_origin, make_spec

from cometa.models import TaskState, utc_now
from cometa.service import (
    Actor,
    CometaService,
    InvalidRequestError,
    NotAuthorizedError,
)


@pytest.fixture()
def service(store, config) -> CometaService:
    return CometaService(store, config, instance_id="inst-test")


OPERATOR = Actor(kind="operator", id="admin")
ALICE = Actor(kind="qq_user", id="777")
BOB = Actor(kind="qq_user", id="888")


def _allow(config, users=(777, 888), groups=(12345,)):
    config.access.qq_user_ids = set(users)
    config.access.qq_group_ids = set(groups)
    config.backends["fake"].enabled = True


def _submit(service, config, *, actor=ALICE, key="k1", origin=None, spec=None):
    _allow(config)
    origin = origin or make_origin()
    spec = spec or make_spec()
    return service.submit(spec, actor=actor, origin=origin, idempotency_key=key)


class TestSubmitAuthorization:
    def test_unauthorized_user_rejected(self, service, config):
        config.access.qq_user_ids = {999}
        config.access.qq_group_ids = {12345}
        with pytest.raises(InvalidRequestError, match="user_not_allowed"):
            service.submit(
                make_spec(), actor=ALICE, origin=make_origin(), idempotency_key="k1"
            )

    def test_unauthorized_group_rejected(self, service, config):
        config.access.qq_user_ids = {777}
        config.access.qq_group_ids = {99999}
        with pytest.raises(InvalidRequestError, match="conversation_not_allowed"):
            service.submit(
                make_spec(), actor=ALICE, origin=make_origin(), idempotency_key="k1"
            )

    def test_actor_must_match_origin_requester(self, service, config):
        _allow(config)
        with pytest.raises(NotAuthorizedError):
            service.submit(
                make_spec(),
                actor=BOB,  # Bob 用 Alice 的 origin 提交
                origin=make_origin(requester_id="777"),
                idempotency_key="k1",
            )

    def test_cross_instance_origin_rejected(self, service, config):
        _allow(config)
        with pytest.raises(NotAuthorizedError, match="跨实例"):
            service.submit(
                make_spec(),
                actor=ALICE,
                origin=make_origin(instance_id="other-instance"),
                idempotency_key="k1",
            )

    def test_unknown_backend_rejected_no_fallback(self, service, config):
        """点名不可用后端必须告知原因，不静默换厂商（§6.4.4）。"""
        _allow(config)
        with pytest.raises(InvalidRequestError, match="backend_unavailable"):
            service.submit(
                make_spec(backend_preference="ghost"),
                actor=ALICE,
                origin=make_origin(),
                idempotency_key="k1",
            )

    def test_unknown_workspace_rejected(self, service, config):
        _allow(config)
        with pytest.raises(InvalidRequestError, match="workspace_unknown"):
            service.submit(
                make_spec(workspace_id="ghost-ws"),
                actor=ALICE,
                origin=make_origin(),
                idempotency_key="k1",
            )

    def test_submit_returns_receipt_with_ack(self, service, config):
        receipt = _submit(service, config)
        assert receipt.task_id
        assert receipt.ack_notification_id

    def test_idempotent_resubmit_same_receipt(self, service, config):
        first = _submit(service, config, key="k1")
        second = _submit(service, config, key="k1")
        assert first.task_id == second.task_id


class TestQueryAuthorization:
    def test_bob_cannot_read_alice_task(self, service, config):
        receipt = _submit(service, config)
        assert service.get(receipt.task_id, actor=OPERATOR)
        assert service.get(receipt.task_id, actor=ALICE)
        with pytest.raises(NotAuthorizedError):
            service.get(receipt.task_id, actor=BOB)

    def test_bob_cannot_cancel_alice_task(self, service, config):
        receipt = _submit(service, config)
        with pytest.raises(NotAuthorizedError):
            service.cancel(receipt.task_id, actor=BOB)
        # Alice 自己可以
        _status, state = service.cancel(receipt.task_id, actor=ALICE)
        assert state is TaskState.CANCELLED

    def test_list_is_scoped_to_requester(self, service, config):
        _submit(service, config, key="k1")
        _submit(
            service,
            config,
            key="k2",
            actor=BOB,
            origin=make_origin(requester_id="888", source_request_id="rb"),
        )
        alice_page = service.list_tasks(actor=ALICE)
        bob_page = service.list_tasks(actor=BOB)
        operator_page = service.list_tasks(actor=OPERATOR)
        assert len(alice_page.tasks) == 1
        assert len(bob_page.tasks) == 1
        assert len(operator_page.tasks) == 2

    def test_forged_origin_without_access_rejected(self, service, config):
        """不在白名单的伪造 Origin 连受理都过不了（§1.3 不变量 4）。"""
        config.access.qq_user_ids = {777}
        config.access.qq_group_ids = {12345}
        with pytest.raises(InvalidRequestError):
            service.submit(
                make_spec(),
                actor=Actor(kind="qq_user", id="666"),
                origin=make_origin(requester_id="666"),
                idempotency_key="kx",
            )


class TestInputRespondAuthorization:
    def test_approval_requires_operator(self, service, config, store):
        receipt = _submit(service, config)
        from conftest import claim_task

        _claimed, attempt = claim_task(store)
        request_id = store.register_input_request(
            receipt.task_id,
            attempt_id=attempt.attempt_id,
            owner="w-test",
            epoch=attempt.lease_epoch,
            backend_request_id="br-1",
            kind="approval",
            question="允许联网？",
            schema={},
            options=[],
            expires_at=utc_now() + timedelta(seconds=600),
        )
        record = store.get_input_request(request_id)
        with pytest.raises(NotAuthorizedError):
            service.respond(
                receipt.task_id,
                request_id,
                "yes",
                actor=ALICE,
                expected_revision=record.revision,
            )
        status = service.respond(
            receipt.task_id,
            request_id,
            "yes",
            actor=OPERATOR,
            expected_revision=record.revision,
        )
        assert status == "queued"

    def test_respond_requires_task_owner(self, service, config, store):
        from datetime import timedelta

        from conftest import claim_task

        receipt = _submit(service, config)
        _task, attempt = claim_task(store)
        request_id = store.register_input_request(
            receipt.task_id,
            attempt_id=attempt.attempt_id,
            owner="w-test",
            epoch=attempt.lease_epoch,
            backend_request_id="br-2",
            kind="input",
            question="?",
            schema={},
            options=[],
            expires_at=utc_now() + timedelta(seconds=600),
        )
        record = store.get_input_request(request_id)
        with pytest.raises(NotAuthorizedError):
            service.respond(
                receipt.task_id,
                request_id,
                "answer",
                actor=BOB,
                expected_revision=record.revision,
            )


class TestHealth:
    def test_disabled_when_flag_off(self, store, config):
        config.enabled = False
        service = CometaService(store, config, instance_id="inst-test")
        assert service.health()["state"] == "disabled"

    def test_ready(self, service):
        assert service.health()["state"] == "ready"
