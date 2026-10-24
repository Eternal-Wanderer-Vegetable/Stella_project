# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""Exercise a real NoneBot Driver without allowing it to reread cwd dotenv files."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NONEBOT_SNAPSHOT_DRIVER_PROBE = r"""
import json
import os
from importlib.metadata import version
from pathlib import Path

import nonebot
from nonebot import logger
from nonebot.config import Config, Env
from nonebot.drivers import Driver

cwd = Path.cwd()
nonebot_version = version("nonebot2")
assert nonebot_version == "2.5.0", nonebot_version
logger.remove()

# Show why the normal defaults are unsafe in a managed generation, then build
# framework objects solely from the child process snapshot. NoneBot 2.5.0's
# init() calls Env() without an explicit source and `None` falls back to dotenv.
nonebot.init(_env_file=None)
default_driver = nonebot.get_driver()
assert default_driver.env == "prod"
assert default_driver.config.port == 19002
assert default_driver.config.stella_snapshot_marker == "from-file-before"
nonebot._driver = None

os.environ.update({
    "ENVIRONMENT": "dev",
    "PORT": "19001",
    "STELLA_SNAPSHOT_MARKER": "from-process-snapshot",
})
env = Env(_env_file=None)
config = Config(_env_file=None)
driver_type = nonebot._resolve_combine_expr(config.driver)
driver = driver_type(env, config)
nonebot._driver = driver
assert isinstance(driver, Driver)
assert nonebot.get_driver() is driver
assert getattr(config, "stella_snapshot_marker", None) is None

# Model edits to the project config while this generation is alive. The active
# Driver must continue to hold the env/config objects resolved from its snapshot.
Path(".env").write_text(
    "ENVIRONMENT=prod\nPORT=19002\nSTELLA_SNAPSHOT_MARKER=from-file-after\n",
    encoding="utf-8",
)
assert Path.cwd() == cwd
assert driver.env == "dev"
assert driver.config.port == 19001
assert getattr(driver.config, "stella_snapshot_marker", None) is None
print(json.dumps({
    "nonebot_version": nonebot_version,
    "driver_type": driver.type,
    "environment": driver.env,
    "port": driver.config.port,
    "default_marker": default_driver.config.stella_snapshot_marker,
    "snapshot_marker": getattr(driver.config, "stella_snapshot_marker", None),
    "cwd_preserved": Path.cwd() == cwd,
}))
"""


def test_locked_nonebot_driver_uses_process_snapshot_and_preserves_cwd(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "synthetic-project"
    project_root.mkdir()
    (project_root / ".env").write_text(
        "ENVIRONMENT=prod\nPORT=19002\nSTELLA_SNAPSHOT_MARKER=from-file-before\n",
        encoding="utf-8",
    )

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
        }
    )
    result = subprocess.run(
        [sys.executable, "-c", NONEBOT_SNAPSHOT_DRIVER_PROBE],
        cwd=project_root,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    data = json.loads(result.stdout.strip())

    lock = (ROOT / "requirements-platform.lock").read_text(encoding="utf-8")
    assert re.search(r"(?m)^nonebot2==2\.5\.0\s*$", lock)
    assert data == {
        "nonebot_version": "2.5.0",
        "driver_type": "fastapi",
        "environment": "dev",
        "port": 19001,
        "default_marker": "from-file-before",
        "snapshot_marker": None,
        "cwd_preserved": True,
    }
