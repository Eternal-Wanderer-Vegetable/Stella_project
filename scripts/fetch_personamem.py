# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""获取 PersonaMem 公开测试集（M3）：revision pin + sha256 清单 + 显式失败。

数据集：HF ``bowen-upenn/PersonaMem-v2``（CC-BY-4.0）。只取 ``benchmark/text`` 的
评测文件与说明文档（benchmark.csv ≈ 42MB），**不镜像** 4.58GB 全库（32k/128k
聊天历史不做端到端全量）。

可靠性契约（计划 §9）：
- revision 固定 pin，逐文件 sha256 入 manifest——内容漂移即失败；
- 主站不可达时回落 HF_ENDPOINT / hf-mirror.com（网络环境差异），回落事实入报告；
- 下载失败必须显式报告非零退出，绝不静默绿（skip 也留痕：exit 3 = 网络不可达）。

用法：
    python scripts/fetch_personamem.py                 # 下载到 memory/benchmark/_public/personamem/
    python scripts/fetch_personamem.py --check         # 校验现有文件与 manifest 一致
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = PROJECT_ROOT / "memory" / "benchmark" / "_public" / "personamem"

# revision pin：内容变更 = 数据集换版，必须有意识地更新这里与测试冻结值
PINNED_REVISION = "ed956dea41521fc4499acbc63f966e0fd3c053ba"
DEFAULT_BASE = "https://huggingface.co"
FALLBACK_BASE = "https://hf-mirror.com"
# 只取检索层评测需要的文件（全库 4.58GB 不镜像）
FILES = (
    "README.md",
    "column_descriptions.md",
    "benchmark/text/benchmark.csv",
)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _bases() -> list[str]:
    """优先 HF_ENDPOINT，其次主站，最后镜像（国内网络可达性实测）。"""
    bases = []
    env = os.environ.get("HF_ENDPOINT")
    if env:
        bases.append(env.rstrip("/"))
    bases.append(DEFAULT_BASE)
    if FALLBACK_BASE not in bases:
        bases.append(FALLBACK_BASE)
    return bases


def _download(base: str, revision: str, remote: str, dest: Path) -> None:
    import httpx

    url = f"{base}/datasets/bowen-upenn/PersonaMem-v2/resolve/{revision}/{remote}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with httpx.stream("GET", url, timeout=120, follow_redirects=True) as r:
        r.raise_for_status()
        with dest.open("wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)


def write_notice(out_dir: Path, revision: str, base_used: str) -> Path:
    """CC-BY-4.0 attribution 与已知偏差声明（数据卡自述 GPT-5 生成）。"""
    notice = out_dir / "NOTICE.md"
    notice.write_text(
        f"""# PersonaMem 数据来源声明（NOTICE）

- 数据集: bowen-upenn/PersonaMem-v2（Hugging Face Datasets）
- Revision (pinned): `{revision}`
- 获取端点: `{base_used}`
- 许可证: **CC-BY-4.0** —— 本仓库按其条款以 attribution 方式使用；本目录内容
  （含再加工的适配用例）不入库（.gitignore），分发需附带本声明。
- 已知偏差: 数据卡自述语料由 GPT-5 生成，存在合成数据固有偏差；语言为**英文**。
- 结论限定: 该集只能作为 **英文域外部参照**，不得直接外推中文 QQ 群聊检索质量。
- 抓取范围: 仅 `benchmark/text/`（评测文件）与本 NOTICE 所列文档；32k/128k
  聊天历史与多模态数据不下载、不镜像。
""",
        encoding="utf-8",
    )
    return notice


def fetch(out_dir: Path, revision: str = PINNED_REVISION, *, check_only: bool = False) -> int:
    manifest_path = out_dir / "manifest.json"
    if check_only:
        if not manifest_path.exists():
            print("❌ 缺少 manifest.json：先运行 fetch（不带 --check）", file=sys.stderr)
            return 1
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("revision") != revision:
            print(f"❌ manifest revision {manifest.get('revision')!r} ≠ pin {revision!r}",
                  file=sys.stderr)
            return 1
        for art in manifest["artifacts"]:
            path = out_dir / art["path"]
            if not path.exists() or _sha256_file(path) != art["sha256"]:
                print(f"❌ 文件缺失或哈希不符: {art['path']}", file=sys.stderr)
                return 1
        print(f"✅ personamem 数据与 manifest 一致（revision={revision[:12]}…, "
              f"{len(manifest['artifacts'])} files）")
        return 0

    import httpx

    errors: list[str] = []
    base_used = None
    for base in _bases():
        try:
            # 探测可达性（轻量请求）
            httpx.get(f"{base}/api/datasets/bowen-upenn/PersonaMem-v2", timeout=15,
                      follow_redirects=True).raise_for_status()
            base_used = base
            break
        except Exception as exc:
            errors.append(f"{base}: {type(exc).__name__}: {exc}")
    if base_used is None:
        # 网络不可达 = 显式 skip（exit 3），消费方（CI/脚本）不得当作绿色通过
        print(json.dumps({
            "status": "skipped_network_unreachable",
            "attempts": errors,
        }, ensure_ascii=False, indent=2), file=sys.stderr)
        return 3

    artifacts = []
    try:
        for remote in FILES:
            dest = out_dir / remote
            _download(base_used, revision, remote, dest)
            artifacts.append({
                "path": remote.replace("/", os.sep) if os.sep != "/" else remote,
                "sha256": _sha256_file(dest),
                "bytes": dest.stat().st_size,
            })
    except Exception as exc:
        print(json.dumps({
            "status": "download_failed",
            "base": base_used,
            "error": f"{type(exc).__name__}: {exc}",
        }, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1

    manifest = {
        "dataset": "bowen-upenn/PersonaMem-v2",
        "revision": revision,
        "base_url": base_used,
        "license": "CC-BY-4.0",
        "artifacts": artifacts,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
    write_notice(out_dir, revision, base_used)
    print(f"✅ 下载完成（base={base_used}, revision={revision[:12]}…）："
          f"{', '.join(a['path'] for a in artifacts)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="获取 PersonaMem-v2 评测数据（pin+sha256）")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="数据目录（gitignored）")
    parser.add_argument("--revision", default=PINNED_REVISION, help="HF revision pin")
    parser.add_argument("--check", action="store_true", help="只校验现有数据与 manifest 一致")
    args = parser.parse_args(argv)
    return fetch(args.out, args.revision, check_only=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
