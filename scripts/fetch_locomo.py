# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""获取 LoCoMo 公开测试集（MBENCH-002 M1）：revision pin + sha256 清单 + 显式失败。

数据集：snap-research/locomo ``data/locomo10.json``（CC BY-NC 4.0，约 2.8MB，
10 段多会话长对话 + 约 1986 条 QA 标注）。只取 QA 评测所需的对话数据；
MSC persona 与事件摘要任务数据不下载。

可靠性契约（与 fetch_personamem.py 一致）：
- revision 固定 pin，逐文件 sha256 入 manifest——内容漂移即失败；
- 主源不可达时回落 jsDelivr CDN（网络环境差异），回落事实入 manifest；
- 下载失败必须显式报告非零退出，绝不静默绿（exit 3 = 网络不可达）。

用法：
    python scripts/fetch_locomo.py                 # 下载到 memory/benchmark/_public/locomo/
    python scripts/fetch_locomo.py --check         # 校验现有文件与 manifest 一致
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = PROJECT_ROOT / "memory" / "benchmark" / "_public" / "locomo"

# revision pin：snap-research/locomo main HEAD（2024-08-13，数据集发布后未再变更）
PINNED_REVISION = "3eb6f2c585f5e1699204e3c3bdf7adc5c28cb376"
PRIMARY_BASE = "https://raw.githubusercontent.com/snap-research/locomo/{revision}"
FALLBACK_BASE = "https://cdn.jsdelivr.net/gh/snap-research/locomo@{revision}"
FILES = ("data/locomo10.json",)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _download(base_template: str, revision: str, remote: str, dest: Path) -> None:
    import httpx

    url = f"{base_template.format(revision=revision)}/{remote}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with httpx.stream("GET", url, timeout=120, follow_redirects=True) as r:
        r.raise_for_status()
        with dest.open("wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)


def write_notice(out_dir: Path, revision: str, base_used: str) -> Path:
    """CC BY-NC 4.0 attribution 与用途限定声明。"""
    notice = out_dir / "NOTICE.md"
    notice.write_text(
        f"""# LoCoMo 数据来源声明（NOTICE）

- 数据集: snap-research/locomo（GitHub），文件 `data/locomo10.json`
- Revision (pinned): `{revision}`
- 获取端点: `{base_used}`
- 许可证: **CC BY-NC 4.0**（Attribution-NonCommercial）—— 仅限非商业研究用途；
  本目录内容（含再加工的适配场景）不入库（.gitignore），分发需附带本声明。
- 语言: 英文。结论限定: 该集作为 **英文域外部参照**，不得直接外推中文 QQ 群聊质量。
- 抓取范围: 仅 `data/locomo10.json`（对话+QA 标注）；MSC persona 与事件摘要
  任务数据不下载。QA 评测使用其 5 类标注（single-hop/multi-hop/temporal/
  open-domain/adversarial）。
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
        print(f"✅ locomo 数据与 manifest 一致（revision={revision[:12]}…, "
              f"{len(manifest['artifacts'])} files）")
        return 0

    bases = (PRIMARY_BASE, FALLBACK_BASE)
    artifacts = []
    base_used = None
    errors: list[str] = []
    for base_template in bases:
        try:
            for remote in FILES:
                dest = out_dir / remote
                _download(base_template, revision, remote, dest)
                artifacts.append({
                    "path": remote,
                    "sha256": _sha256_file(dest),
                    "bytes": dest.stat().st_size,
                })
            base_used = base_template.format(revision=revision[:12])
            break
        except Exception as exc:
            errors.append(f"{base_template}: {type(exc).__name__}: {exc}")
            artifacts.clear()
    if base_used is None:
        # 网络不可达 = 显式 skip（exit 3），消费方不得当作绿色通过
        print(json.dumps({
            "status": "skipped_network_unreachable",
            "attempts": errors,
        }, ensure_ascii=False, indent=2), file=sys.stderr)
        return 3

    manifest = {
        "dataset": "snap-research/locomo",
        "revision": revision,
        "base_url": base_used,
        "license": "CC-BY-NC-4.0",
        "artifacts": artifacts,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
    write_notice(out_dir, revision, base_used)
    print(f"✅ 下载完成（base={base_used}, revision={revision[:12]}…）："
          f"{', '.join(a['path'] for a in artifacts)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="获取 LoCoMo 评测数据（pin+sha256）")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="数据目录（gitignored）")
    parser.add_argument("--revision", default=PINNED_REVISION, help="GitHub revision pin")
    parser.add_argument("--check", action="store_true", help="只校验现有数据与 manifest 一致")
    args = parser.parse_args(argv)
    return fetch(args.out, args.revision, check_only=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
