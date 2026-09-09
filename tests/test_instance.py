# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。

from config.instance import (
    launch_token_digest,
    manifest_for,
    read_manifest,
    resolve_instance_id,
    write_manifest,
)


def test_instance_id_is_stable_for_same_root_and_differs_for_other_root(tmp_path):
    first = tmp_path / "formal"
    second = tmp_path / "test"
    first.mkdir()
    second.mkdir()
    assert resolve_instance_id(first) == resolve_instance_id(first)
    assert resolve_instance_id(first) != resolve_instance_id(second)


def test_manifest_roundtrip_and_token_digest(tmp_path):
    path = tmp_path / "instance" / "ownership.json"
    payload = manifest_for(
        instance_id="demo",
        project_root=tmp_path,
        pid=123,
        launch_token="secret",
    )
    write_manifest(path, payload)
    assert read_manifest(path) == payload
    assert launch_token_digest("secret") != launch_token_digest("other")
