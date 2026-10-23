# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""Lock down configuration file, process-environment, and restart semantics."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _isolated_env(home: Path, **overrides: str) -> dict[str, str]:
    """Pass only runtime necessities and synthetic configuration into the child."""
    env = {
        key: os.environ[key]
        for key in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP")
        if os.environ.get(key)
    }
    env.update(
        {
            "PYTHONPATH": str(ROOT),
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "STELLA_HOME": str(home),
            "NO_PROXY": "127.0.0.1,localhost",
        }
    )
    env.update(overrides)
    return env


def _run_python(code: str, env: dict[str, str]) -> str:
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    return result.stdout.strip()


def test_dotenv_changes_apply_to_fresh_processes_but_not_inherited_snapshots(
    tmp_path: Path,
) -> None:
    home = tmp_path / "stella-home"
    home.mkdir()
    env_file = home / ".env"
    env_file.write_text("LLM_TIMEOUT=11\n", encoding="utf-8")

    parent_probe = r"""
import json
import os
import subprocess
import sys
from pathlib import Path
from config import settings

env_file = Path(os.environ["STELLA_HOME"]) / ".env"
parent_value = settings.LLM_TIMEOUT
env_file.write_text("LLM_TIMEOUT=22\n", encoding="utf-8")
successor = subprocess.run(
    [sys.executable, "-c", "from config.settings import LLM_TIMEOUT; print(LLM_TIMEOUT)"],
    env=os.environ.copy(), check=True, capture_output=True, text=True, timeout=20,
)
print(json.dumps({
    "parent": parent_value,
    "file_after_edit": 22,
    "inherited_successor": float(successor.stdout.strip()),
}))
"""
    inherited = json.loads(_run_python(parent_probe, _isolated_env(home)))
    assert inherited == {
        "parent": 11.0,
        "file_after_edit": 22,
        "inherited_successor": 11.0,
    }

    fresh = float(
        _run_python(
            "from config.settings import LLM_TIMEOUT; print(LLM_TIMEOUT)",
            _isolated_env(home),
        )
    )
    assert fresh == 22.0

    env_file.write_text("", encoding="utf-8")
    deleted = float(
        _run_python(
            "from config.settings import LLM_TIMEOUT; print(LLM_TIMEOUT)",
            _isolated_env(home),
        )
    )
    assert deleted == 90.0

    env_file.write_text("LLM_TIMEOUT=22\n", encoding="utf-8")
    external = float(
        _run_python(
            "from config.settings import LLM_TIMEOUT; print(LLM_TIMEOUT)",
            _isolated_env(home, LLM_TIMEOUT="44"),
        )
    )
    assert external == 44.0

    (home / ".env.prod").write_text("LLM_TIMEOUT=33\n", encoding="utf-8")
    overlay = float(
        _run_python(
            "from config.settings import LLM_TIMEOUT; print(LLM_TIMEOUT)",
            _isolated_env(home, ENVIRONMENT="prod", LLM_TIMEOUT="44"),
        )
    )
    assert overlay == 33.0


def test_legacy_bootstrap_import_and_source_build_order_is_preserved() -> None:
    source = (ROOT / "bot.py").read_text(encoding="utf-8")
    markers = (
        '_os.environ["STELLA_LAUNCH_TOKEN"]',
        'if __name__ == "__main__":',
        "rebuild_source_dashboard()",
        "raise SystemExit(1) from _e",
        "replace_running()",
        "nonebot.init()",
        "register_enabled_adapters(\n",
        'nonebot.load_builtin_plugins("echo", "single_session")',
        'nonebot.load_from_toml("pyproject.toml")',
        "setup_webui(status_source=status_api.collect_status)",
    )
    positions = [source.index(marker) for marker in markers]
    assert positions == sorted(positions)
