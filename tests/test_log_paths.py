# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""日志落点的统一性护栏。

2026-08-25 之前每个日志各自拼路径，散落在项目根目录：排查要在一堆源码里翻，
每加一个日志就多一条 .gitignore，而 `deploy status` 还自己又拼了一份
`logs/stella.jsonl`（与 STELLA_JSON_LOG_PATH 脱钩，用户一改配置就读到空文件、
且只显示「暂无日志」不报错）。

这里钉两件事：
1. 所有运行期日志都在 LOG_DIR 下——加新日志时忘了这条，测试会挂；
2. 读侧（deploy）与写侧（Bot）用的是**同一个**配置，不是各拼一份。
"""

from __future__ import annotations

import importlib

import config.settings as settings


def test_all_log_paths_live_under_log_dir():
    """新增日志请一并加进这个列表——它是「日志都在一个地方」的唯一执行点。"""
    for name in (
        "THOUGHT_LOG_PATH",
        "CONSOLIDATION_LOG_PATH",
        "MEMORY_COMPRESS_LOG_PATH",
        "STELLA_JSON_LOG_PATH",
        "BOOT_DIAG_LOG_PATH",
    ):
        path = getattr(settings, name)
        assert path.parent == settings.LOG_DIR, f"{name} 不在 LOG_DIR 下: {path}"


def test_log_dir_defaults_into_project_root_logs():
    assert settings.LOG_DIR == settings.PROJECT_ROOT / "logs"


def test_log_dir_override_moves_every_log(monkeypatch, tmp_path):
    """改 LOG_DIR 一处就能把全部日志搬走（含还不存在的多级目录）。"""
    target = tmp_path / "deep" / "nested" / "logs"
    monkeypatch.setenv("LOG_DIR", str(target))
    reloaded = importlib.reload(settings)
    try:
        assert target == reloaded.LOG_DIR
        for name in (
            "THOUGHT_LOG_PATH",
            "CONSOLIDATION_LOG_PATH",
            "MEMORY_COMPRESS_LOG_PATH",
            "STELLA_JSON_LOG_PATH",
            "BOOT_DIAG_LOG_PATH",
        ):
            assert getattr(reloaded, name).parent == target, name
    finally:
        # 全局模块，必须还原——否则后续用例读到的是临时目录
        monkeypatch.delenv("LOG_DIR", raising=False)
        importlib.reload(settings)


def test_deploy_reads_the_configured_json_log_path():
    """回归：deploy 侧不许再自己拼 logs/stella.jsonl。"""
    import deploy.process as process

    assert process.LOG_FILE == settings.STELLA_JSON_LOG_PATH
    assert process.PID_FILE.parent == settings.LOG_DIR


def test_compress_log_setting_is_a_path_not_a_filename():
    """旧的 MEMORY_COMPRESS_LOG_FILENAME 是文件名（只能落在项目根），已换成完整路径。"""
    assert not hasattr(settings, "MEMORY_COMPRESS_LOG_FILENAME")
    assert settings.MEMORY_COMPRESS_LOG_PATH.is_absolute()


def test_deprecated_compress_log_key_is_flagged():
    """旧键留在 .env 里不会报错、也完全不生效，必须由 deploy doctor 点名。"""
    from deploy.probe import _DEPRECATED_KEYS

    assert "MEMORY_COMPRESS_LOG_FILENAME" in _DEPRECATED_KEYS
