# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""``.env`` 合并器：用新版模板的骨架 + 用户的旧值，生成新的 ``.env``。

升级时不能直接拷旧 ``.env``（会丢掉新版本的键与注释），也不能直接用新模板
（会丢掉用户所有配置）。正确做法是**以新模板为骨架逐行替换成用户值**：

- 模板里的注释是给用户的说明书（尤其 OneBot 连接那段跨两个软件的配置），必须留住；
- 用户手工调过的阈值（PROACTIVE_* / MEMORY_* 等）必须沿用——2026-08-27 之前
  ``deploy init --force`` 的提示是「请从 .env.bak 里对照恢复」，那等于让用户
  拿两个 27KB 的文件人工比对；
- 已废弃的键要**主动移除并说明原因**，否则用户的配置里永远留着不生效的行；
- 被新键取代的键（``env_keys.SUPERSEDED``）要**换算成新键的值**再移除——只删不换
  等于把用户原来的选择改回默认值，而那种改动在报告里看不出来。

逐行替换的思路来自 ``init_wizard.render_env``（它只管向导那 5 个键），这里把
「要替换的键」泛化成「旧文件里出现过的所有键」。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import env_keys

# 匹配 `KEY=`、`# KEY=`、`#KEY=`（模板里大量键是注释掉的默认值）
_KEY_LINE = re.compile(r"^\s*#?\s*([A-Z][A-Z0-9_]*)\s*=")
# 匹配一行真正生效的赋值（不含注释）
_ASSIGN = re.compile(r"^\s*([A-Z][A-Z0-9_]*)\s*=(.*)$")


@dataclass
class EnvMergeReport:
    """合并结果的结构化摘要，供 CLI 打印与 GUI 渲染。"""

    kept: list[str] = field(default_factory=list)
    appended: list[str] = field(default_factory=list)
    removed: list[tuple[str, str]] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    # (旧键, 新键, 换算后的值)。值已按敏感键规则脱敏，可直接打印。
    migrated: list[tuple[str, str, str]] = field(default_factory=list)

    def to_markdown(self, max_list: int = 12) -> str:
        def _fmt(keys: list[str]) -> str:
            head = "、".join(keys[:max_list])
            more = f" 等 {len(keys)} 项" if len(keys) > max_list else ""
            return f"{head}{more}" if keys else "（无）"

        lines = [
            "### 配置文件（.env）",
            "",
            f"- 沿用旧值：{len(self.kept)} 项",
            f"- 新版新增、走默认值：{len(self.missing)} 项",
            f"- 已废弃、已移除：{len(self.removed)} 项",
            f"- 已被新键取代、值已换算：{len(self.migrated)} 项",
            f"- 无法识别、保留在文件末尾：{len(self.unknown)} 项",
        ]
        if self.appended:
            lines.append(f"- 模板里没有但代码仍在读、已追加：{_fmt(self.appended)}")
        if self.removed:
            lines += ["", "**已移除的废弃配置**："]
            lines += [f"- `{key}`：{reason}" for key, reason in self.removed]
        if self.migrated:
            lines += ["", "**已换算到新键**："]
            lines += [
                f"- `{old}` → `{new}={value}`" for old, new, value in self.migrated
            ]
        if self.unknown:
            lines += ["", f"**无法识别（原样保留在末尾）**：{_fmt(self.unknown)}"]
        if self.missing:
            lines += ["", f"**走默认值**：{_fmt(self.missing)}"]
        sensitive = [k for k in self.kept if env_keys.is_sensitive(k)]
        if sensitive:
            lines += ["", f"敏感项已沿用（值不打印）：{ '、'.join(sensitive) }"]
        return "\n".join(lines)


def parse_env(text: str) -> dict[str, str]:
    """解析 ``.env`` 文本为「键 → 右侧原文」。

    刻意保留右侧**原文**（含引号与行尾注释）：写回去时逐字节还原用户的值，
    不做任何规范化——引号脱不脱、有没有空格，都不是升级该管的事。
    """
    values: dict[str, str] = {}
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        match = _ASSIGN.match(line)
        if match:
            values[match.group(1)] = match.group(2).strip()
    return values


def template_keys(template: str) -> set[str]:
    """模板里出现过的键（含被注释掉的默认值行）。"""
    keys: set[str] = set()
    for line in template.splitlines():
        match = _KEY_LINE.match(line)
        if match:
            keys.add(match.group(1))
    return keys


def merge_env(
    old_env: str,
    template: str,
    *,
    schema_keys: set[str] | None = None,
    prefer_template: set[str] | None = None,
) -> tuple[str, EnvMergeReport]:
    """把旧 ``.env`` 的值合进新模板，返回 ``(新 .env 文本, 报告)``。

    ``schema_keys`` 是 ``config/settings.py`` 实际读取的键（由
    ``env_schema.build_schema`` 提供）。它用来区分两种「模板里没有」的键：
    代码仍在读的（追加到末尾，继续生效）与谁都不认识的（也保留，但标为无法识别，
    因为删掉别人手工加的东西比留着更糟）。

    ``prefer_template`` 里的键以模板为准、忽略旧值。``deploy init --force`` 用它：
    用户刚在向导里回答过的那几项，理应盖掉旧文件里的老答案。

    被新键取代的旧键（``env_keys.SUPERSEDED``）按「换算 + 移除」处理，优先级是
    **向导答案 > 用户显式写的新键 > 旧键换算值**。重复合并是幂等的：第二遍时
    旧键已经不在文件里，什么都不会发生。
    """
    report = EnvMergeReport()
    known = schema_keys or set()
    prefer = prefer_template or set()
    old_values = parse_env(old_env)

    pending: dict[str, str] = {}
    superseded: list[tuple[str, str, str]] = []
    for key, value in old_values.items():
        reason = env_keys.deprecation_reason(key)
        if reason:
            report.removed.append((key, reason))
            continue
        if key in prefer:
            continue
        migrated = env_keys.migrate_value(key, value)
        if migrated is not None:
            # 旧键已被新键取代：换算成新键的值，旧键那行随之消失。先攒着不入
            # pending——用户可能**同时**显式写了新键，谁优先要等这一轮扫完才知道。
            superseded.append((key, *migrated))
            continue
        target = env_keys.RENAMED.get(key, key)
        if target != key:
            report.removed.append((key, f"已改名为 {target}，值已自动沿用"))
        pending[target] = value

    # 换算值只在新键既没被用户显式设置、也不是本次向导答案时才生效。
    # 判断放在主循环之后：旧键在新键之前还是之后出现取决于用户的文件顺序，
    # 靠 dict 的插入顺序碰运气会一半的情况出错。
    for old, target, new_value in superseded:
        if target in prefer:
            report.removed.append((old, f"已被 {target} 取代（新值来自本次向导）"))
        elif target in pending:
            report.removed.append((old, f"已被 {target} 取代，而 {target} 已显式设置"))
        else:
            pending[target] = new_value
            shown = "（值不打印）" if env_keys.is_sensitive(target) else new_value
            report.migrated.append((old, target, shown))

    replaced: set[str] = set()
    output: list[str] = []
    for line in template.splitlines():
        match = _KEY_LINE.match(line)
        if match:
            key = match.group(1)
            # 只替换第一次出现：模板里同名键出现两次时，后者可能是注释里的示例
            if key in pending and key not in replaced:
                output.append(f"{key}={pending[key]}")
                replaced.add(key)
                report.kept.append(key)
                continue
        output.append(line)

    leftovers = [key for key in pending if key not in replaced]
    recognized = [key for key in leftovers if key in known]
    unrecognized = [key for key in leftovers if key not in known]
    if recognized:
        output += [
            "",
            "# ── 以下配置模板里没有，但代码仍在读取（由 deploy 升级时保留） ──",
        ]
        for key in recognized:
            output.append(f"{key}={pending[key]}")
            report.kept.append(key)
            report.appended.append(key)
    if unrecognized:
        output += [
            "",
            "# ── 以下配置无法识别：可能是手工添加、或来自更早的版本 ──",
            "# 保留原样以防误删；确认无用后可自行删除。",
        ]
        for key in unrecognized:
            output.append(f"{key}={pending[key]}")
            report.unknown.append(key)

    present = set(pending)
    report.missing = sorted((template_keys(template) | known) - present)
    return "\n".join(output) + "\n", report


def merge_env_files(
    old_path: Path,
    template_path: Path,
    *,
    schema_keys: set[str] | None = None,
    prefer_template: set[str] | None = None,
) -> tuple[str, EnvMergeReport]:
    """文件版 :func:`merge_env`。旧文件不存在时等价于「直接用模板」。"""
    old_text = old_path.read_text(encoding="utf-8") if old_path.is_file() else ""
    template_text = template_path.read_text(encoding="utf-8")
    return merge_env(
        old_text,
        template_text,
        schema_keys=schema_keys,
        prefer_template=prefer_template,
    )


def settings_keys(settings_path: Path) -> set[str]:
    """``config/settings.py`` 实际读取的键集合（解析失败时返回空集合）。"""
    try:
        from . import env_schema

        data = env_schema.build_schema(settings_path)
    except Exception:
        return set()
    return {field["key"] for field in data.get("fields", [])}

