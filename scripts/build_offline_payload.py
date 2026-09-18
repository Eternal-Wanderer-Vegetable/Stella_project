#!/usr/bin/env python3
"""Build the offline payload embedded by the OneClick Offline installers.

OneClick Offline 把「安装期要联网下载的所有产物」在发布时预取进安装包：

- 嵌入式 Python 运行时 zip（哈希与 python.rs 的 PY_VER/PY_SHA256 同源，直接从
  源码解析，杜绝两处常量漂移）；
- get-pip.py（自带完整 pip wheel，安装器配合 --no-index 离线装 pip）；
- requirements.txt 的完整 wheel 闭包（`pip wheel` 现场构建——不能用
  `pip download --only-binary`，因为存在只有 sdist 的依赖，如 qrcode_terminal）；
- package catalog 声明的全部组件（llama.cpp backend / NapCat / 默认 embedding 模型）；
- playwright 的 chromium-headless-shell（随包内核，运行期零下载）。

产物目录布局（由 build_release_package.py --offline-payload 原样拷进安装包
resources/stella/offline）：

    offline/
    ├── python-<ver>-embed-amd64.zip
    ├── get-pip.py
    ├── MANIFEST.json            # 文件级 sha256，安装器（python.rs）校验用
    ├── wheels/*.whl             # requirements.txt 依赖闭包
    ├── packages/<artifact>      # catalog 组件，文件名 = catalog 的 artifact 字段
    └── playwright-browsers/     # playwright 默认布局，revision 与本 requirements
                                 # 解析出的 playwright 版本严格一致

完整性边界：packages/ 以 catalog 的 checksum/size 为准（与在线安装共用同一条
校验路径）；MANIFEST.json 只登记 catalog 管不到的 python zip 与 get-pip.py。
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from deploy.acquire import AcquireError, download_verified, verify_local_artifact
from deploy.packages import _validate_record

PYTHON_RS = REPO_ROOT / "stella-installer" / "src-tauri" / "src" / "python.rs"
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"
PYTHON_ZIP_MIRRORS = (
    "https://www.python.org/ftp/python/{version}/python-{version}-embed-amd64.zip",
    "https://mirrors.huaweicloud.com/python/{version}/python-{version}-embed-amd64.zip",
)
INSTALL_TARGET = "chromium-headless-shell"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_runtime_constants() -> tuple[str, str]:
    """从 python.rs 解析 PY_VER / PY_SHA256——安装器常量是唯一事实来源。"""
    text = PYTHON_RS.read_text(encoding="utf-8")
    version_match = re.search(r'const PY_VER: &str = "([^"]+)"', text)
    sha_match = re.search(r'const PY_SHA256: &str =\s*"([0-9A-Fa-f]{64})"', text)
    if not version_match or not sha_match:
        raise SystemExit(f"无法从 {PYTHON_RS} 解析 PY_VER / PY_SHA256")
    return version_match.group(1), sha_match.group(1)


def fetch_python_zip(output: Path, version: str, expected_sha: str, prebuilt: Path | None) -> Path:
    zip_name = f"python-{version}-embed-amd64.zip"
    destination = output / zip_name
    if prebuilt is not None:
        if not prebuilt.is_file():
            raise SystemExit(f"--python-zip 指定的文件不存在：{prebuilt}")
        destination.write_bytes(prebuilt.read_bytes())
    else:
        last_error = ""
        for mirror in PYTHON_ZIP_MIRRORS:
            url = mirror.format(version=version)
            with tempfile.NamedTemporaryFile(delete=False, dir=output) as tmp:
                temp_path = Path(tmp.name)
            try:
                with urllib.request.urlopen(url, timeout=300) as response, temp_path.open("wb") as out:
                    for chunk in iter(lambda: response.read(1024 * 1024), b""):
                        out.write(chunk)
                temp_path.replace(destination)
                break
            except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
                last_error = f"{url}: {exc}"
                temp_path.unlink(missing_ok=True)
        else:
            raise SystemExit(f"下载 Python 运行时失败（所有镜像均不可用）：{last_error}")
    actual = _sha256(destination)
    if actual.lower() != expected_sha.lower():
        destination.unlink(missing_ok=True)
        raise SystemExit(
            f"Python 运行时校验失败\n期望: {expected_sha}\n实际: {actual}"
        )
    print(f"[payload] {zip_name} 校验通过（{destination.stat().st_size} 字节）")
    return destination


def fetch_get_pip(output: Path, prebuilt: Path | None) -> Path:
    destination = output / "get-pip.py"
    if prebuilt is not None:
        if not prebuilt.is_file():
            raise SystemExit(f"--get-pip 指定的文件不存在：{prebuilt}")
        destination.write_bytes(prebuilt.read_bytes())
    else:
        with urllib.request.urlopen(GET_PIP_URL, timeout=120) as response:
            destination.write_bytes(response.read())
    if destination.stat().st_size < 500_000:
        raise SystemExit("get-pip.py 下载不完整")
    return destination


def build_wheels(requirements: Path, wheels_dir: Path) -> None:
    wheels_dir.mkdir(parents=True, exist_ok=True)
    # 显式带上 setuptools/wheel：pip wheel 只构建 requirements 的闭包，
    # 而安装器的 ensure_build_tools 也从离线仓取这两个包。
    # 注意 --no-warn-script-location 是 pip install 的选项，pip wheel 没有。
    command = [
        sys.executable, "-m", "pip", "wheel",
        "-r", str(requirements),
        "setuptools", "wheel",
        "-w", str(wheels_dir),
    ]
    subprocess.run(command, check=True)
    wheels = sorted(wheels_dir.glob("*.whl"))
    if not wheels:
        raise SystemExit("pip wheel 未产出任何 wheel")
    total = sum(wheel.stat().st_size for wheel in wheels)
    print(f"[payload] wheels 闭包完成：{len(wheels)} 个，共 {total} 字节")


def fetch_catalog_packages(
    catalog_path: Path,
    packages_dir: Path,
    local_artifacts: Path | None = None,
) -> None:
    """按 catalog 把组件归档取齐到 packages/。

    `local_artifacts` 是 CI 里已经下好的归档目录（文件名 = catalog 的 artifact）。
    必须支持它：llama-cpu 记录的 source 是自指的 Release URL，而 payload 构建时
    Release 还没发布（在线安装器不受影响——用户安装时 Release 已存在），所以
    backend zip 必须用 CI artifact 就地取用。本地文件与下载走同一条
    checksum/size 校验（verify_local_artifact），绝不因为省一次下载就放过校验。
    """
    payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise SystemExit("package catalog schema_version 不受支持")
    packages_dir.mkdir(parents=True, exist_ok=True)
    for item in payload.get("packages", []):
        try:
            record = _validate_record(item)
        except Exception as exc:
            raise SystemExit(f"catalog record 非法：{exc}") from exc
        artifact = str(record.get("artifact") or Path(record["path"]).name)
        destination = packages_dir / artifact
        if destination.is_file():
            print(f"[payload] {artifact} 已存在，跳过下载")
            continue
        checksum = str(record["checksum"])
        size = int(record["size"]) if record.get("size") is not None else None
        local = local_artifacts / artifact if local_artifacts else None
        if local is not None and local.is_file():
            try:
                verify_local_artifact(local, checksum=checksum, size=size)
            except AcquireError as exc:
                raise SystemExit(f"{artifact} 本地归档校验未通过：{exc.message}") from exc
            shutil.copyfile(local, destination)
            print(
                f"[payload] {artifact} 采用 CI 本地归档，校验通过"
                f"（{destination.stat().st_size} 字节）"
            )
            continue
        try:
            download_verified(
                str(record["source"]),
                destination,
                checksum=checksum,
                size=size,
            )
        except AcquireError as exc:
            raise SystemExit(f"{artifact} 下载失败：{exc.message}") from exc
        print(f"[payload] {artifact} 下载并校验通过（{destination.stat().st_size} 字节）")


def install_browsers(browsers_dir: Path) -> str:
    """让 playwright 自己把内核装进离线仓（布局/标记与它运行期期望的完全一致）。"""
    probe = subprocess.run(
        [sys.executable, "-m", "playwright", "--version"],
        capture_output=True,
    )
    if probe.returncode != 0:
        raise SystemExit(
            "playwright 不可用，无法预装浏览器内核。先执行 pip install -r requirements.txt"
        )
    env = os.environ.copy()
    env["PLAYWRIGHT_BROWSERS_PATH"] = str(browsers_dir)
    subprocess.run(
        [sys.executable, "-m", "playwright", "install", INSTALL_TARGET],
        check=True,
        env=env,
    )
    installed = sorted(browsers_dir.glob("chromium_headless_shell-*"))
    for candidate in installed:
        if (candidate / "INSTALLATION_COMPLETE").is_file():
            revision = candidate.name.rsplit("-", 1)[-1]
            print(f"[payload] chromium-headless-shell 就绪（revision={revision}）")
            return revision
    raise SystemExit("playwright install 完成，但离线仓里找不到完整的 chromium_headless_shell-*")


def write_manifest(output: Path, version: str, files: dict[str, Path]) -> None:
    manifest = {
        "schema_version": 1,
        "python_version": version,
        "files": {name: _sha256(path) for name, path in sorted(files.items())},
    }
    (output / "MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    # 固定 UTF-8：Windows 下 stdout/stderr 被重定向（GH Actions runner 的管道
    # 默认 cp1252）时 Python 改用 ANSI 代码页，打印中文进度直接 UnicodeEncodeError。
    # stderr 也要：SystemExit 的中文错误信息走 stderr，否则真出错时会反过来
    # 被一个编码异常盖掉真实原因。与 deploy/__main__.py 的做法一致。
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            with contextlib.suppress(Exception):
                stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, required=True, help="payload 输出目录")
    parser.add_argument("--catalog", type=Path, required=True,
                        help="package-catalog-windows-amd64.json（build_release_catalog.py 产物）")
    parser.add_argument("--requirements", type=Path,
                        default=REPO_ROOT / "requirements.txt")
    parser.add_argument("--python-zip", type=Path,
                        help="已下载好的嵌入式 Python zip（跳过下载，仍做哈希校验）")
    parser.add_argument("--get-pip", type=Path,
                        help="已下载好的 get-pip.py（跳过下载）")
    parser.add_argument("--local-artifacts", type=Path,
                        help="已下载好的组件归档目录（文件名 = catalog artifact），"
                             "命中即校验后采用。llama-cpu 的 source 是自指 Release URL，"
                             "payload 构建时该 Release 尚未发布，必须用 CI artifact 就地取用")
    parser.add_argument("--skip-wheels", action="store_true",
                        help="跳过 pip wheel（仅调试 payload 脚本本身时用）")
    parser.add_argument("--skip-browsers", action="store_true",
                        help="跳过 playwright 内核预装（仅调试 payload 脚本本身时用）")
    args = parser.parse_args()

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    version, expected_sha = parse_runtime_constants()
    print(f"[payload] 嵌入式 Python {version}（常量来自 python.rs）")

    python_zip = fetch_python_zip(output, version, expected_sha, args.python_zip)
    get_pip = fetch_get_pip(output, args.get_pip)
    if not args.skip_wheels:
        build_wheels(args.requirements.resolve(), output / "wheels")
    fetch_catalog_packages(
        args.catalog.resolve(),
        output / "packages",
        local_artifacts=args.local_artifacts.resolve() if args.local_artifacts else None,
    )

    browsers_revision = None
    if not args.skip_browsers:
        browsers_revision = install_browsers(output / "playwright-browsers")

    write_manifest(output, version, {
        python_zip.name: python_zip,
        "get-pip.py": get_pip,
    })
    total = sum(path.stat().st_size for path in output.rglob("*") if path.is_file())
    print(f"[payload] 完成：{output}（总计 {total} 字节，browsers revision={browsers_revision}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
