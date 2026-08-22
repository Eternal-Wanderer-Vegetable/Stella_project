# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""AstrBotConfig 与 _conf_schema.json 解析。"""

from __future__ import annotations

import json

from astrbot_compat.config import AstrBotConfig, load_conf_schema, schema_to_default


def test_all_upstream_types_get_correct_default_shape():
    schema = {
        "i": {"type": "int"},
        "f": {"type": "float"},
        "b": {"type": "bool"},
        "s": {"type": "string"},
        "t": {"type": "text"},
        "l": {"type": "list"},
        "fl": {"type": "file"},
        "tl": {"type": "template_list"},
        "d": {"type": "dict"},
        "o": {"type": "object", "items": {}},
    }
    assert schema_to_default(schema) == {
        "i": 0,
        "f": 0.0,
        "b": False,
        "s": "",
        "t": "",
        "l": [],
        "fl": [],
        "tl": [],
        "d": {},
        "o": {},
    }


def test_nested_objects_recurse_all_the_way_down():
    schema = {
        "obj": {
            "type": "object",
            "items": {
                "inner": {"type": "int", "default": 3},
                "deep": {"type": "object", "items": {"k": {"type": "string", "default": "v"}}},
            },
        },
    }
    assert schema_to_default(schema) == {"obj": {"inner": 3, "deep": {"k": "v"}}}


def test_mutable_defaults_are_not_shared():
    conf = schema_to_default({"a": {"type": "list"}, "b": {"type": "list"}})
    conf["a"].append(1)
    assert conf["b"] == []


def test_disk_values_override_defaults_and_missing_keys_are_filled(tmp_path):
    path = tmp_path / "demo_config.json"
    path.write_text(json.dumps({"a": 9}), encoding="utf-8")
    cfg = AstrBotConfig(str(path), {"a": {"type": "int", "default": 1}, "b": {"type": "int", "default": 2}})
    assert cfg["a"] == 9
    assert cfg["b"] == 2


def test_nested_disk_values_merge_with_defaults(tmp_path):
    path = tmp_path / "demo_config.json"
    path.write_text(json.dumps({"obj": {"x": 9}}), encoding="utf-8")
    schema = {
        "obj": {
            "type": "object",
            "items": {"x": {"type": "int", "default": 1}, "y": {"type": "int", "default": 2}},
        },
    }
    cfg = AstrBotConfig(str(path), schema)
    assert cfg["obj"] == {"x": 9, "y": 2}


def test_unknown_disk_keys_are_kept(tmp_path):
    path = tmp_path / "demo_config.json"
    path.write_text(json.dumps({"手写的": 1}), encoding="utf-8")
    cfg = AstrBotConfig(str(path), {"a": {"type": "int", "default": 1}})
    assert cfg["手写的"] == 1


def test_attribute_access():
    cfg = AstrBotConfig("", {"a": {"type": "int", "default": 5}})
    assert cfg.a == 5
    cfg.b = 7
    assert cfg["b"] == 7
    del cfg.b
    assert "b" not in cfg


def test_broken_config_is_renamed_not_fatal(tmp_path):
    path = tmp_path / "demo_config.json"
    path.write_text("{ 这不是 json", encoding="utf-8")
    cfg = AstrBotConfig(str(path), {"a": {"type": "int", "default": 1}})
    assert cfg["a"] == 1
    assert (tmp_path / "demo_config.json.bak").exists()


def test_save_config_roundtrip(tmp_path):
    path = tmp_path / "demo_config.json"
    cfg = AstrBotConfig(str(path), {"a": {"type": "int", "default": 1}})
    cfg["a"] = 42
    cfg.save_config()
    assert json.loads(path.read_text(encoding="utf-8")) == {"a": 42}
    assert not (tmp_path / "demo_config.json.tmp").exists()


def test_load_conf_schema(tmp_path):
    (tmp_path / "_conf_schema.json").write_text(
        json.dumps({"a": {"type": "int"}}),
        encoding="utf-8",
    )
    assert load_conf_schema(tmp_path) == {"a": {"type": "int"}}
    assert load_conf_schema(tmp_path / "missing") == {}
