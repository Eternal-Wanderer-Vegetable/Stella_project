# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Source-checkout Dashboard build used by the direct ``bot.py`` entrypoint."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path


def _run_command(
    command: list[str], dashboard_dir: Path, *, capture: bool = True
) -> subprocess.CompletedProcess[str]:
    """Run a package-manager command on POSIX and Windows batch shims."""
    if os.name == "nt":
        command_line = subprocess.list2cmdline(command)
        run_args = (command_line,)
        shell = True
    else:
        run_args = (command,)
        shell = False
    try:
        return subprocess.run(
            *run_args,
            cwd=dashboard_dir,
            check=True,
            shell=shell,
            capture_output=capture,
            text=capture,
        )
    except subprocess.CalledProcessError as exc:
        output = "\n".join(part for part in (exc.stdout, exc.stderr) if part)
        detail = f"\n{output[-4000:]}" if output else ""
        raise RuntimeError(
            f"{' '.join(command)} 失败，退出码 {exc.returncode}{detail}"
        ) from exc


def _pnpm_prefix(dashboard_dir: Path) -> list[str]:
    """Use a pnpm version that understands the repository's build allowlist."""
    if shutil.which("pnpm"):
        try:
            version = _run_command(["pnpm", "--version"], dashboard_dir, capture=True)
        except RuntimeError:
            version = None
        match = re.match(r"^(\d+)\.(\d+)", version.stdout.strip()) if version else None
        if match:
            major, minor = (int(part) for part in match.groups())
            if major >= 11 or (major == 10 and minor >= 26):
                return ["pnpm"]

    if shutil.which("npm"):
        return ["npm", "exec", "--yes", "--package=pnpm@10", "--", "pnpm"]
    raise RuntimeError(
        "源码启动需要 pnpm 10.26+ 或 pnpm 11（仓库构建白名单配置要求）；"
        "也可安装 Node.js/npm 以自动调用 pnpm 10"
    )


def rebuild_source_dashboard(
    project_root: Path | None = None, serve_dist: bool | None = None
) -> bool:
    """Build and sync Dashboard for a source checkout; return whether it ran.

    Release packages intentionally skip this path. Their assets are built by the
    release pipeline and, for Docker, copied from the dedicated Node build stage.
    """
    if project_root is None or serve_dist is None:
        from config.settings import PROJECT_ROOT, WEBUI_SERVE_DIST

        project_root = Path(PROJECT_ROOT) if project_root is None else project_root
        serve_dist = WEBUI_SERVE_DIST if serve_dist is None else serve_dist

    if not serve_dist:
        return False

    project_root = Path(project_root)
    dashboard_dir = project_root / "dashboard"
    if not (dashboard_dir / "package.json").is_file():
        return False
    is_source_checkout = (project_root / ".git").exists()
    has_release_asset_marker = (
        project_root / "webui" / "dist" / "assets" / "version"
    ).is_file()
    if not is_source_checkout and has_release_asset_marker:
        return False

    pnpm = _pnpm_prefix(dashboard_dir)
    print("[webui][boot] 正在重建 Dashboard 前端资源", flush=True)
    for args in (
        ("install", "--frozen-lockfile"),
        ("build",),
        ("sync:webui",),
    ):
        _run_command([*pnpm, *args], dashboard_dir, capture=True)

    if not (project_root / "webui" / "dist" / "index.html").is_file():
        raise RuntimeError("Dashboard 构建完成但 webui/dist/index.html 不存在")
    print("[webui][boot] Dashboard 前端资源已重建并同步", flush=True)
    return True
