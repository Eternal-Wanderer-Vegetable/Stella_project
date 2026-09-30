# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""cometa WebUI API 基线（方案 §8.1 tests/webui/test_webui_cometa.py）。

覆盖：401、未启用 503、202 受理、幂等重放、任务/产物授权、事件游标补读、
审批 revision 冲突、下载只按 manifest 键。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cometa import runtime as cometa_runtime
from cometa.models import Outcome, TaskState, utc_now
from cometa.service import CometaService
from cometa.store import CometaStore

USER = {"username": "admin", "password": "correct horse battery"}


@pytest.fixture
def auth_header(client: TestClient) -> dict:
    resp = client.post("/api/v1/auth/setup", json=USER)
    return {"Authorization": f"Bearer {resp.json()['data']['token']}"}


@pytest.fixture
def wired_service(isolated_home, cometa_config):
    """装配一个 fake 后端的 cometa runtime（WebUI 进程视角）。"""
    from cometa.config import BackendConfig, ProfileConfig

    cometa_config.enabled = True
    cometa_config.backends["fake"] = BackendConfig(
        backend_id="fake", type="fake", enabled=True
    )
    cometa_config.profiles["coding"] = ProfileConfig(name="coding", backend="fake")
    service = CometaService(
        CometaStore(cometa_config.db_path), cometa_config, instance_id="inst-webui"
    )
    cometa_runtime.set_current(
        type("R", (), {"config": cometa_config, "store": service.store,
                       "service": service, "enabled": True})()
    )
    yield service
    cometa_runtime.set_current(None)


def _submit_via_api(client: TestClient, auth_header: dict, key: str = "k1") -> str:
    resp = client.post(
        "/api/v1/cometa/tasks",
        json=_submit_payload(idempotency_key=key),
        headers=auth_header,
    )
    assert resp.status_code == 202
    return resp.json()["data"]["task_id"]


def _submit_payload(**overrides) -> dict:
    payload = {
        "objective": "给 utils.py 补测试",
        "idempotency_key": "web-key-1",
        "request_id": "web-req-1",
    }
    payload.update(overrides)
    return payload


# ── 鉴权与启用门 ─────────────────────────────────────────


class TestGates:
    def test_requires_auth(self, client: TestClient):
        assert client.get("/api/v1/cometa/tasks").status_code == 401
        assert client.post("/api/v1/cometa/tasks", json={}).status_code == 401

    def test_unavailable_returns_503(self, client: TestClient, auth_header):
        resp = client.get("/api/v1/cometa/tasks", headers=auth_header)
        assert resp.status_code == 503
        assert resp.json()["status"] == "error"

    def test_health_reports_disabled(self, client: TestClient, auth_header):
        resp = client.get("/api/v1/cometa/health", headers=auth_header)
        assert resp.status_code == 200
        assert resp.json()["data"]["state"] == "disabled"


# ── 受理与幂等 ───────────────────────────────────────────


class TestSubmit:
    def test_submit_returns_202_with_idempotent_replay(
        self, client: TestClient, auth_header, wired_service
    ):
        first = client.post(
            "/api/v1/cometa/tasks", json=_submit_payload(), headers=auth_header
        )
        assert first.status_code == 202
        task_id = first.json()["data"]["task_id"]
        second = client.post(
            "/api/v1/cometa/tasks", json=_submit_payload(), headers=auth_header
        )
        assert second.status_code == 202
        assert second.json()["data"]["task_id"] == task_id  # 幂等：同一 key 原任务
        assert len(wired_service.store.list_tasks("inst-webui")) == 1

    def test_submit_conflicting_key_rejected(
        self, client: TestClient, auth_header, wired_service
    ):
        client.post("/api/v1/cometa/tasks", json=_submit_payload(), headers=auth_header)
        conflict = client.post(
            "/api/v1/cometa/tasks",
            json=_submit_payload(objective="完全不同的目标"),
            headers=auth_header,
        )
        assert conflict.status_code == 400

    def test_submit_empty_objective_rejected(
        self, client: TestClient, auth_header, wired_service
    ):
        resp = client.post(
            "/api/v1/cometa/tasks", json={"objective": " "}, headers=auth_header
        )
        assert resp.status_code == 422


# ── 查询 / 事件 / 取消 ───────────────────────────────────


class TestQueryAndControl:
    def test_get_task_and_list(self, client, auth_header, wired_service):
        task_id = _submit_via_api(client, auth_header)
        got = client.get(f"/api/v1/cometa/tasks/{task_id}", headers=auth_header)
        assert got.status_code == 200
        assert got.json()["data"]["state"] == "queued"
        listed = client.get("/api/v1/cometa/tasks", headers=auth_header)
        assert listed.json()["data"]["tasks"][0]["task_id"] == task_id

    def test_get_missing_task_404(self, client, auth_header, wired_service):
        resp = client.get("/api/v1/cometa/tasks/nope", headers=auth_header)
        assert resp.status_code == 404

    def test_events_cursor_pagination(self, client, auth_header, wired_service):
        task_id = _submit_via_api(client, auth_header)
        first = client.get(
            f"/api/v1/cometa/tasks/{task_id}/events?limit=1", headers=auth_header
        )
        data = first.json()["data"]
        assert len(data["events"]) == 1
        assert data["next_sequence"] >= 1
        second = client.get(
            f"/api/v1/cometa/tasks/{task_id}/events"
            f"?after_sequence={data['next_sequence']}",
            headers=auth_header,
        )
        second_ids = [e["sequence"] for e in second.json()["data"]["events"]]
        assert all(s > data["next_sequence"] for s in second_ids)

    def test_cancel_then_state(self, client, auth_header, wired_service):
        task_id = _submit_via_api(client, auth_header)
        resp = client.post(
            f"/api/v1/cometa/tasks/{task_id}/cancel",
            json={"idempotency_key": "c1"},
            headers=auth_header,
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["state"] == "cancelled"
        again = client.post(
            f"/api/v1/cometa/tasks/{task_id}/cancel",
            json={"idempotency_key": "c1"},
            headers=auth_header,
        )
        assert again.status_code == 200  # 幂等重放


# ── 审批答复 ─────────────────────────────────────────────


class TestInputs:
    def _pending_request(self, wired_service, task_id: str):
        from datetime import timedelta

        task = wired_service.store.get_task(task_id)
        # 直接造 attempt（模拟 worker 已认领）
        import sqlite3

        conn = sqlite3.connect(str(wired_service.store.db_path))
        attempt_id = "att-test-1"
        conn.execute(
            "INSERT OR REPLACE INTO attempts (attempt_id, task_id, attempt_no,"
            " launch_phase, lease_owner, lease_epoch, lease_until_utc, created_utc)"
            " VALUES (?, ?, 1, 'running', 'w-test', 1, ?, ?)",
            (
                attempt_id,
                task_id,
                (utc_now() + timedelta(seconds=600)).isoformat(),
                utc_now().isoformat(),
            ),
        )
        conn.execute(
            "UPDATE tasks SET state = 'running', current_attempt = ? WHERE task_id = ?",
            (attempt_id, task_id),
        )
        conn.commit()
        conn.close()
        request_id = wired_service.store.register_input_request(
            task_id,
            attempt_id=attempt_id,
            owner="w-test",
            epoch=1,
            backend_request_id="br-1",
            kind="approval",
            question="允许联网？",
            schema={},
            options=[],
            expires_at=utc_now() + timedelta(seconds=600),
        )
        _ = task
        return request_id

    def test_respond_with_stale_revision_conflicts(
        self, client, auth_header, wired_service
    ):
        task_id = _submit_via_api(client, auth_header, key="k-approve")
        request_id = self._pending_request(wired_service, task_id)
        resp = client.post(
            f"/api/v1/cometa/tasks/{task_id}/inputs/{request_id}",
            json={"answer": "yes", "expected_revision": 99},
            headers=auth_header,
        )
        assert resp.status_code == 400
        record = wired_service.store.get_input_request(request_id)
        good = client.post(
            f"/api/v1/cometa/tasks/{task_id}/inputs/{request_id}",
            json={"answer": "yes", "expected_revision": record.revision},
            headers=auth_header,
        )
        assert good.status_code == 200
        # 重复答复相同内容 → 幂等；不同内容 → 冲突
        dup = client.post(
            f"/api/v1/cometa/tasks/{task_id}/inputs/{request_id}",
            json={"answer": "yes", "expected_revision": record.revision},
            headers=auth_header,
        )
        assert dup.status_code == 200
        conflict = client.post(
            f"/api/v1/cometa/tasks/{task_id}/inputs/{request_id}",
            json={"answer": "no", "expected_revision": record.revision},
            headers=auth_header,
        )
        assert conflict.status_code == 400


# ── 结果与产物下载 ───────────────────────────────────────


class TestResultsAndArtifacts:
    def _finish_with_artifact(self, wired_service, task_id: str, tmp_path):
        from cometa.artifacts import ArtifactCollector
        from tests.cometa_helpers import claim_task

        _task, attempt = claim_task(wired_service.store, instance_id="inst-webui")
        collector = ArtifactCollector(wired_service.config.artifacts_dir)
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "patch.diff").write_bytes(b"diff --git a/x b/x\n")
        collected = collector.collect(task_id, "patch.diff", workspace_path=ws)
        wired_service.store.finish_task(
            task_id,
            attempt_id=attempt.attempt_id,
            owner="w-test",
            epoch=attempt.lease_epoch,
            outcome=Outcome.SUCCEEDED,
            state=TaskState.SUCCEEDED,
            summary="done",
            final_text_ref=collector.save_final_text(task_id, "完整文本"),
            artifacts=[
                {
                    "artifact_id": collected.artifact_id,
                    "relative_storage_key": collected.relative_storage_key,
                    "sha256": collected.sha256,
                    "size": collected.size,
                    "mime": collected.mime,
                    "display_name": collected.display_name,
                }
            ],
            manifest_ref=collector.collect_manifest(task_id, [collected]),
        )
        return collected

    def test_result_dto_and_download(self, client, auth_header, wired_service, tmp_path):
        task_id = _submit_via_api(client, auth_header, key="k-art")
        collected = self._finish_with_artifact(wired_service, task_id, tmp_path)
        result = client.get(f"/api/v1/cometa/tasks/{task_id}/result", headers=auth_header)
        assert result.status_code == 200
        data = result.json()["data"]
        assert data["outcome"] == "succeeded"
        assert data["artifacts"][0]["artifact_id"] == collected.artifact_id
        download = client.get(
            f"/api/v1/cometa/tasks/{task_id}/artifacts/{collected.artifact_id}",
            headers=auth_header,
        )
        assert download.status_code == 200
        assert download.content == b"diff --git a/x b/x\n"

    def test_download_missing_artifact_404(self, client, auth_header, wired_service):
        task_id = _submit_via_api(client, auth_header, key="k-art2")
        resp = client.get(
            f"/api/v1/cometa/tasks/{task_id}/artifacts/nope", headers=auth_header
        )
        assert resp.status_code == 404

    def test_download_rejects_storage_key_traversal(
        self, client, auth_header, wired_service, tmp_path
    ):
        task_id = _submit_via_api(client, auth_header, key="k-art3")
        collected = self._finish_with_artifact(wired_service, task_id, tmp_path)
        # 用 artifact 的 task_id 但请求另一个任务的路径形态：只按 manifest 键取
        resp = client.get(
            f"/api/v1/cometa/tasks/{task_id}/artifacts/{collected.artifact_id}",
            headers=auth_header,
        )
        assert resp.status_code == 200
        # 篡改 DB 里的存储键为穿越形态 → 404/400，绝不能读到任意文件
        import sqlite3

        conn = sqlite3.connect(str(wired_service.store.db_path))
        conn.execute(
            "UPDATE artifacts SET relative_storage_key = '../../secret.txt'"
            " WHERE artifact_id = ?",
            (collected.artifact_id,),
        )
        conn.commit()
        conn.close()
        evil = client.get(
            f"/api/v1/cometa/tasks/{task_id}/artifacts/{collected.artifact_id}",
            headers=auth_header,
        )
        assert evil.status_code in (400, 404)
