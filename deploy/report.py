# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""doctor 的渲染层：把检查结论变成 JSON 或终端文本。

--json 输出面向桌面安装器（Tauri），结构稳定且自描述，GUI 只做渲染。
"""

from __future__ import annotations

import json
import sys

from .models import CheckResult


def to_json(results: list[CheckResult]) -> str:
    """序列化为结构化 JSON。id 供 GUI 做图标/本地化映射。"""
    return json.dumps(
        {
            "version": 1,
            "summary": _summarize(results),
            "items": [
                {
                    "id": r.id,
                    "level": r.level,
                    "title": r.title,
                    "detail": r.detail,
                    "fix_hint": r.fix_hint,
                }
                for r in results
            ],
        },
        ensure_ascii=False,
        indent=2,
    )


def _summarize(results: list[CheckResult]) -> dict:
    counts = {"ok": 0, "warn": 0, "error": 0}
    for r in results:
        counts[r.level] = counts.get(r.level, 0) + 1
    counts["blocking"] = has_blocking(results)
    return counts


def has_blocking(results: list[CheckResult]) -> bool:
    """是否存在 error 级结论（阻塞启动）。"""
    return any(r.level == "error" for r in results)


def to_terminal(results: list[CheckResult]) -> str:
    """人类可读文本。颜色用 ANSI，检测不到终端时自动降级。"""
    use_color = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()
    lines: list[str] = []
    levels = {"error": "错误", "warn": "警告", "ok": "通过"}
    styles = {
        "error": ("31", "1"),
        "warn": ("33", "1"),
        "ok": ("32", ""),
    }
    for r in results:
        code, bold = styles[r.level]
        if use_color:
            label = f"\x1b[{code};{bold}m[{levels[r.level]}]\x1b[0m"
        else:
            label = f"[{levels[r.level]}]"
        lines.append(f"{label} {r.title}")
        if r.detail:
            lines.append(f"    {r.detail}")
        if r.fix_hint:
            lines.append(f"    解决：{r.fix_hint}")
    lines.append("")
    if has_blocking(results):
        lines.append("发现阻塞性问题，请先解决后再启动。")
    else:
        lines.append("未发现阻塞性问题。")
    return "\n".join(lines)
