# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
from __future__ import annotations

import dataclasses
import importlib.util
import json
import os
from pathlib import Path

import pytest

from cometa.policy_transport import (
    ClaimDirective,
    CometaPolicyEnvelope,
    CometaPolicyPublisher,
    WorkerPolicyReader,
    atomic_write_json,
    config_fingerprint,
    policy_paths,
    process_identity_digest,
    read_json_bounded,
)


def _load_gravitas_runtime_type():
    source = (
        Path(__file__).resolve().parents[2]
        / "stella_project"
        / "plugins"
        / "bot_main"
        / "gravitas_bootstrap.py"
    )
    spec = importlib.util.spec_from_file_location("gravitas_bootstrap_g09_test", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.GravitasRuntime


@dataclasses.dataclass
class _Config:
    endpoint: str = "https://example.invalid"
    token: str = "secret-for-hashing-only"


class _Clock:
    def __init__(self, mono: float = 10.0, wall: float = 1_000.0) -> None:
        self.mono = mono
        self.wall = wall


def _envelope(
    *,
    revision: int = 1,
    issued_utc: float = 1_000.0,
    instance_id: str = "instance-a",
    boot_id: str = "boot-a",
    worker_id: str = "worker-a",
    process_identity: str = "pid:worker-a",
    config_hash: str | None = None,
    claim_allowed: bool = True,
    claim_limit: int = 2,
) -> CometaPolicyEnvelope:
    return CometaPolicyEnvelope(
        schema_version=1,
        instance_id=instance_id,
        controller_boot_id=boot_id,
        worker_id=worker_id,
        process_identity_digest=process_identity_digest(process_identity),
        policy_revision=revision,
        config_hash=config_hash or config_fingerprint(_Config()),
        issued_utc=issued_utc,
        ttl_seconds=10.0,
        claim_allowed=claim_allowed,
        claim_limit=claim_limit,
    )


def _reader(paths, clock: _Clock, **overrides) -> WorkerPolicyReader:
    return WorkerPolicyReader(
        paths=paths,
        instance_id=overrides.get("instance_id", "instance-a"),
        controller_boot_id=overrides.get("boot_id", "boot-a"),
        worker_id=overrides.get("worker_id", "worker-a"),
        process_identity=overrides.get("process_identity", "pid:worker-a"),
        config_hash=overrides.get("config_hash", config_fingerprint(_Config())),
        monotonic=lambda: clock.mono,
        wall=lambda: clock.wall,
    )


def test_policy_paths_are_scoped_and_envelope_never_serializes_secret(tmp_path):
    paths_a = policy_paths(tmp_path, "instance-a")
    paths_b = policy_paths(tmp_path, "instance-b")
    assert paths_a.directory.parent == paths_b.directory.parent
    assert paths_a.directory != paths_b.directory
    assert "instance-a" not in str(paths_a.directory)
    envelope = _envelope()
    raw = json.dumps(envelope.to_dict())
    assert "secret-for-hashing-only" not in raw
    assert "https://example.invalid" not in raw
    assert envelope.config_hash.startswith("sha256:")


def test_envelope_rejects_schema_and_unknown_fields(tmp_path):
    payload = _envelope().to_dict()
    assert set(payload) == {
        "schema_version",
        "instance_id",
        "controller_boot_id",
        "worker_id",
        "process_identity_digest",
        "policy_revision",
        "config_hash",
        "issued_utc",
        "ttl_seconds",
        "claim_allowed",
        "claim_limit",
    }
    with pytest.raises(ValueError, match="schema"):
        CometaPolicyEnvelope.from_dict({**payload, "schema_version": True})
    with pytest.raises(ValueError, match="fields"):
        CometaPolicyEnvelope.from_dict({**payload, "extra": "untrusted"})


@pytest.mark.parametrize(
    ("expected", "envelope_field"),
    [
        ({"instance_id": "instance-b"}, "instance_id"),
        ({"boot_id": "boot-b"}, "controller_boot_id"),
        ({"worker_id": "worker-b"}, "worker_id"),
        ({"process_identity": "pid:worker-b"}, "process_identity_digest"),
        ({"config_hash": "sha256:" + "0" * 64}, "config_hash"),
    ],
)
def test_policy_identity_and_configuration_binding_fail_closed(
    tmp_path, expected, envelope_field
):
    paths = policy_paths(tmp_path, "instance-a")
    clock = _Clock()
    atomic_write_json(paths.policy, _envelope().to_dict())
    decision = _reader(paths, clock, **expected).evaluate()
    assert not decision.allowed
    assert decision.reason_code == "policy_binding_mismatch"


def test_policy_revision_ttl_and_duplicate_reads_use_monotonic_expiry(tmp_path):
    paths = policy_paths(tmp_path, "instance-a")
    clock = _Clock()
    atomic_write_json(paths.policy, _envelope().to_dict())
    reader = _reader(paths, clock)
    assert reader.evaluate().allowed

    clock.mono = 19.0
    clock.wall = 1_009.0
    assert reader.evaluate().allowed  # same revision cannot renew its original TTL
    clock.mono = 21.0
    clock.wall = 1_011.0
    expired = reader.evaluate()
    assert not expired.allowed
    assert expired.reason_code == "policy_replay_or_expired"


@pytest.mark.parametrize("issued_utc", [989.0, 1_003.0])
def test_new_revision_rejects_expired_or_future_utc_issue_time(tmp_path, issued_utc):
    paths = policy_paths(tmp_path, "instance-a")
    atomic_write_json(paths.policy, _envelope(issued_utc=issued_utc).to_dict())
    decision = _reader(paths, _Clock()).evaluate()
    assert not decision.allowed
    assert decision.reason_code == "policy_time_invalid"


def test_lower_revision_replay_and_wall_clock_jump_fail_closed(tmp_path):
    paths = policy_paths(tmp_path, "instance-a")
    clock = _Clock()
    reader = _reader(paths, clock)
    atomic_write_json(paths.policy, _envelope(revision=2).to_dict())
    assert reader.evaluate().allowed
    atomic_write_json(paths.policy, _envelope(revision=1).to_dict())
    replay = reader.evaluate()
    assert not replay.allowed
    assert replay.reason_code == "policy_replay"

    clock = _Clock()
    reader = _reader(paths, clock)
    atomic_write_json(paths.policy, _envelope().to_dict())
    assert reader.evaluate().allowed
    clock.mono += 1.0
    clock.wall += 5.0
    jumped = reader.evaluate()
    assert not jumped.allowed
    assert jumped.reason_code == "policy_clock_jump"
    atomic_write_json(paths.policy, _envelope(revision=2, issued_utc=clock.wall).to_dict())
    assert not reader.evaluate().allowed


def test_bad_json_missing_policy_and_ack_write_failure_deny_claims(tmp_path):
    paths = policy_paths(tmp_path, "instance-a")
    clock = _Clock()
    missing = _reader(paths, clock).evaluate()
    assert not missing.allowed and missing.reason_code == "policy_missing"

    paths.directory.mkdir(parents=True, exist_ok=True)
    paths.policy.write_text("{bad", encoding="utf-8")
    invalid = _reader(paths, clock).evaluate()
    assert not invalid.allowed and invalid.reason_code == "policy_invalid"

    atomic_write_json(paths.policy, _envelope().to_dict())
    paths.ack.unlink()
    paths.ack.mkdir()
    ack_failed = _reader(paths, _Clock()).evaluate()
    assert not ack_failed.allowed and ack_failed.reason_code == "ack_write_failed"


def test_matching_ack_is_required_for_publisher_status(tmp_path):
    paths = policy_paths(tmp_path, "instance-a")
    clock = _Clock()
    config = _Config()
    publisher = CometaPolicyPublisher(
        paths=paths,
        config=config,
        instance_id="instance-a",
        controller_boot_id="boot-a",
        worker_id=lambda: "worker-a",
        process_identity=lambda: "pid:worker-a",
        directive=lambda: ClaimDirective(True, 2),
        wall=lambda: clock.wall,
    )
    first = publisher.publish_once()
    assert first is not None
    assert publisher.status_snapshot()["applied"] is False
    assert _reader(paths, clock).evaluate().allowed
    assert publisher.status_snapshot()["applied"] is True

    second = publisher.publish_once()
    assert second is not None and second.policy_revision == first.policy_revision + 1
    status = publisher.status_snapshot()
    assert status["applied"] is False
    assert status["reason_code"] == "ack_not_received"


def test_policy_reader_rejects_non_regular_or_oversize_file(tmp_path):
    target = tmp_path / "policy.json"
    target.write_bytes(b"{}")
    with pytest.raises(ValueError, match="size"):
        read_json_bounded(target, max_bytes=1)
    if hasattr(os, "symlink"):
        link = tmp_path / "link.json"
        link.symlink_to(target)
        with pytest.raises(OSError):
            read_json_bounded(link, max_bytes=20)


def test_gravitas_status_reports_only_matching_cometa_ack():
    runtime_type = _load_gravitas_runtime_type()

    class _Controller:
        def status_snapshot(self):
            return {
                "assessment": {
                    "applied_ack": {
                        "state": "not_received",
                        "reason_code": "adapter_ack_not_wired",
                        "items": [],
                    }
                }
            }

    runtime = runtime_type(_Controller())
    initial = runtime.status_snapshot()
    assert "cometa_policy_ack" not in initial
    assert initial["assessment"]["applied_ack"]["reason_code"] == "adapter_ack_not_wired"

    runtime.record_cometa_policy_ack(
        {
            "state": "not_received",
            "reason_code": "ack_not_received",
            "policy_revision": 7,
            "applied": False,
            "claim_allowed": False,
            "claim_limit": 0,
        }
    )
    pending = runtime.status_snapshot()
    assert pending["cometa_policy_ack"]["applied"] is False
    assert pending["assessment"]["applied_ack"]["state"] == "not_received"

    runtime.record_cometa_policy_ack(
        {
            "state": "applied",
            "reason_code": "claims_paused",
            "policy_revision": 8,
            "applied": True,
            "claim_allowed": False,
            "claim_limit": 0,
        }
    )
    applied = runtime.status_snapshot()
    assert applied["cometa_policy_ack"]["policy_revision"] == 8
    assert applied["assessment"]["applied_ack"]["state"] == "partial"
    assert applied["assessment"]["applied_ack"]["items"][-1]["adapter"] == "cometa.worker"

