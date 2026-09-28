# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 全文见项目根目录 LICENSE.
"""发布工具链锁定（release_assets/toolchain.json，WP06）的一致性测试。

锁定值一经发布即成为安装行为指纹的一部分：测试保证 CI 消费、产品
profile 与壳内常量同源，任何漂移在 PR 阶段就失败。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLCHAIN_PATH = REPO_ROOT / "release_assets" / "toolchain.json"
RELEASE_YML = REPO_ROOT / ".github" / "workflows" / "release.yml"


def _toolchain() -> dict:
    return json.loads(TOOLCHAIN_PATH.read_text(encoding="utf-8"))


def test_toolchain_pins_exact_versions():
    toolchain = _toolchain()
    assert re.fullmatch(r"\d+\.\d+\.\d+", toolchain["tauri_cli"]), (
        "tauri-cli 必须是精确版本，不许 ^/>= 浮动（NSIS 模板随版本漂移）"
    )
    assert re.fullmatch(r"\d+\.\d+(\.\d+)?", toolchain["maturin"])
    assert re.fullmatch(r"[0-9a-f]{40}", toolchain["llama_cpp_commit"])
    assert re.fullmatch(r"[0-9a-f]{40}", toolchain["embedding_commit"])
    assert re.fullmatch(r"\d+\.\d+\.\d+", toolchain["python"])


def test_toolchain_python_matches_shell_constants():
    toolchain = _toolchain()
    text = (REPO_ROOT / "desktop" / "src-tauri" / "src" / "python.rs").read_text(
        encoding="utf-8"
    )
    match = re.search(r'const PY_VER: &str = "([^"]+)"', text)
    assert match and match.group(1) == toolchain["python"], (
        "toolchain.json 的 Python 版本必须与壳内 PY_VER 一致"
    )


def test_toolchain_llama_commit_matches_release_workflow():
    toolchain = _toolchain()
    workflow = RELEASE_YML.read_text(encoding="utf-8")
    match = re.search(r"LLAMA_CPP_COMMIT: ([0-9a-f]{40})", workflow)
    assert match, "release.yml 必须继续钉住 llama.cpp 提交"
    assert match.group(1) == toolchain["llama_cpp_commit"]


def test_product_profiles_pin_embedding_to_toolchain_commit():
    toolchain = _toolchain()
    commit = toolchain["embedding_commit"]
    for name in ("oneclick-python.json", "oneclick-rust.json"):
        profile_path = REPO_ROOT / "release_assets" / "product-profiles" / name
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        source = profile["default_models"][0]["source"]
        assert f"/resolve/{commit}/" in source, (
            f"{name} 的 embedding source 必须钉在 toolchain.json 的提交上"
        )
        assert "/resolve/main/" not in source, (
            f"{name} 的 embedding source 不得指向浮动 main（WP06）"
        )


def test_release_workflow_consumes_toolchain_locks():
    workflow = RELEASE_YML.read_text(encoding="utf-8")
    assert "toolchain.json" in workflow, "release.yml 必须从 toolchain.json 读锁定值"
    assert "--version $toolchain.tauri_cli" in workflow, (
        "tauri-cli 必须按锁定版本安装（替换 ^2 浮动）"
    )
    assert "maturin==$($toolchain.maturin)" in workflow, (
        "maturin 必须按锁定版本安装（替换 --upgrade 浮动）"
    )
    installer_block = workflow.split("build-installer:")[1].split("build-rust-wheel:")[0]
    assert "setup-python" in installer_block, (
        "build-installer 必须显式 setup-python，不依赖 runner 默认 Python"
    )
    assert workflow.count("$LASTEXITCODE -ne 0") >= 3, (
        "Windows 关键 native 命令后必须立即检查退出码（防后续成功命令盖掉失败）"
    )
