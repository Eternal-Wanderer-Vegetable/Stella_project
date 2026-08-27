# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""``STELLA_HOME/.stella-state.json``：跨版本的运行痕迹（纯逻辑，不 import ``config.settings``）。

**为什么需要它**：2026-08-27 之前，「这份数据上次是被哪个版本跑过的」这件事没有任何
记录。于是每个需要知道版本变化的地方都只能自己猜：GUI 去 parse ``pyproject.toml``
（``commands.rs``）拿到的是**当前程序**的版本，而不是**上次运行**的版本——两者的差值
才是「用户刚升级了」这个事实。没有这个差值：

- 升级后该做的一次性动作（提示破坏性变更、重跑 schema 迁移、清过期缓存）无从触发；
- 用户降级回旧版本（新库 + 旧代码）也没人察觉，表现为莫名其妙的报错；
- ``deploy migrate`` 从哪个版本导入过来的，事后查不到。

**文件放在 STELLA_HOME 而不是程序目录**：程序目录每次升级都被整目录替换，写在那里的
标记会跟着旧版本一起消失，也就永远读不到「上次」。

**永不抛异常**：读不出、写不进都退化为「不知道上次是什么版本」。版本标记是辅助信息，
它坏掉不该让 Bot 起不来。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

STATE_FILENAME = ".stella-state.json"
# 文件格式版本。将来加字段不必动它；只有「同名字段换含义」才 +1。
STATE_FORMAT = 1

# 版本变化的分类
FIRST_RUN = "first-run"
SAME = "same"
UPGRADE = "upgrade"
DOWNGRADE = "downgrade"
UNKNOWN = "unknown"

_VERSION_PART = re.compile(r"\d+")


@dataclass(frozen=True)
class StellaState:
    """``.stella-state.json`` 的内容。字段全部可空——旧数据目录里根本没有这个文件。"""

    last_run_version: str | None = None
    last_run_at: str | None = None
    last_schema_version: int | None = None
    first_seen_version: str | None = None
    migrated_from_version: str | None = None
    migrated_at: str | None = None
    #: 读取失败的原因（文件损坏 / 权限）。不为 None 时其余字段一律是默认值。
    error: str | None = None

    def to_payload(self) -> dict:
        """序列化为写盘用的 dict（``error`` 不落盘：它描述的是读取过程，不是状态）。"""
        return {
            "format": STATE_FORMAT,
            "last_run_version": self.last_run_version,
            "last_run_at": self.last_run_at,
            "last_schema_version": self.last_schema_version,
            "first_seen_version": self.first_seen_version,
            "migrated_from_version": self.migrated_from_version,
            "migrated_at": self.migrated_at,
        }


@dataclass(frozen=True)
class RunTransition:
    """一次「本次运行 vs 上次运行」的比较结果，供 doctor / GUI / 启动脚本使用。"""

    kind: str
    previous: str | None = None
    current: str | None = None

    @property
    def is_upgrade(self) -> bool:
        return self.kind == UPGRADE

    @property
    def is_downgrade(self) -> bool:
        return self.kind == DOWNGRADE

    def describe(self) -> str:
        """给人看的一句话。"""
        if self.kind == FIRST_RUN:
            return f"首次运行（当前 v{self.current or '?'}）"
        if self.kind == UPGRADE:
            return f"已从 v{self.previous} 升级到 v{self.current}"
        if self.kind == DOWNGRADE:
            return (
                f"当前版本 v{self.current} 低于上次运行的 v{self.previous}"
                f"——数据可能是新版本写的"
            )
        if self.kind == SAME:
            return f"版本未变（v{self.current}）"
        return f"版本变化无法判断（上次 {self.previous or '未知'}，当前 {self.current or '未知'}）"


def parse_version(text: str | None) -> tuple[int, ...] | None:
    """把 ``"3.0.0"`` / ``"v3.1.0rc1"`` 解析为可比较的数字元组；无数字则 None。

    只取数字段：预发布后缀（``rc1``、``.dev0``）在升级判定里没有意义——判定要回答的是
    「用户换了包吗」，而不是「换了哪种包」。
    """
    if not text:
        return None
    parts = _VERSION_PART.findall(str(text))
    return tuple(int(p) for p in parts) if parts else None


def compare(left: str | None, right: str | None) -> int | None:
    """版本比较：``-1`` / ``0`` / ``1``；任一侧解析不出来返回 None。"""
    a, b = parse_version(left), parse_version(right)
    if a is None or b is None:
        return None
    # 段数不同时补零（"3.0" 与 "3.0.0" 是同一个版本）
    width = max(len(a), len(b))
    a += (0,) * (width - len(a))
    b += (0,) * (width - len(b))
    return (a > b) - (a < b)


def classify(previous: str | None, current: str | None) -> str:
    """把「上次运行版本 → 当前版本」归为 first-run / same / upgrade / downgrade / unknown。"""
    if not previous:
        return FIRST_RUN
    result = compare(current, previous)
    if result is None:
        return UNKNOWN
    return SAME if result == 0 else (UPGRADE if result > 0 else DOWNGRADE)


def program_version(root: Path) -> str | None:
    """从 ``root/pyproject.toml`` 读版本号（发布包里就是靠这一行标版本的）。

    刻意不用 ``importlib.metadata``：Stella 不是 pip 安装的包，发布包就是一个解压出来的
    目录，``pyproject.toml`` 的那一行是唯一可靠的版本来源。
    """
    path = root / "pyproject.toml"
    try:
        if not path.is_file():
            return None
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith(("version = ", "version=")):
                return stripped.split("=", 1)[1].strip().strip("\"'") or None
    except OSError:
        return None
    return None


def state_path(home: Path) -> Path:
    return home / STATE_FILENAME


def load(home: Path) -> StellaState:
    """读状态文件。不存在 → 全空的 :class:`StellaState`；损坏 → ``error`` 说明原因。"""
    path = state_path(home)
    try:
        if not path.is_file():
            return StellaState()
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return StellaState(error=f"{path} 读取失败: {type(e).__name__}: {e}")
    if not isinstance(data, dict):
        return StellaState(error=f"{path} 内容不是 JSON 对象")

    def _text(key: str) -> str | None:
        value = data.get(key)
        return str(value) if isinstance(value, (str, int, float)) and str(value) else None

    schema_version = data.get("last_schema_version")
    return StellaState(
        last_run_version=_text("last_run_version"),
        last_run_at=_text("last_run_at"),
        last_schema_version=int(schema_version) if isinstance(schema_version, int) else None,
        first_seen_version=_text("first_seen_version"),
        migrated_from_version=_text("migrated_from_version"),
        migrated_at=_text("migrated_at"),
    )


def save(home: Path, state: StellaState) -> str | None:
    """原子写入状态文件。成功返回 None，失败返回错误描述（**不抛异常**）。

    先写 ``.tmp`` 再 ``replace``：进程在写一半时被杀掉（用户直接关窗口是常态）不能留下
    一个半截的 JSON——那会让下次启动读到「损坏」，进而误判成首次运行。
    """
    path = state_path(home)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(
            json.dumps(state.to_payload(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp.replace(path)
    except OSError as e:
        return f"{path} 写入失败: {type(e).__name__}: {e}"
    return None


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def record_run(
    home: Path,
    program_root: Path,
    *,
    schema_version: int | None = None,
) -> RunTransition:
    """记下「这份数据被当前版本跑过」，并返回与上次运行的比较结果。

    调用方：Bot 启动（``bot.py``）与 ``deploy start``。写失败不影响返回值——调用方拿到的
    比较结果仍然正确，只是下次启动会重新把它当成同一次变化。
    """
    current = program_version(program_root)
    previous = load(home)
    transition = RunTransition(
        kind=classify(previous.last_run_version, current),
        previous=previous.last_run_version,
        current=current,
    )
    save(
        home,
        replace(
            previous,
            error=None,
            last_run_version=current,
            last_run_at=_now(),
            last_schema_version=schema_version
            if schema_version is not None
            else previous.last_schema_version,
            # 第一次见到这份数据的版本只写一次，之后永不改写（用于「这库最早是哪版建的」）
            first_seen_version=previous.first_seen_version or current,
        ),
    )
    return transition


def record_migration(
    home: Path,
    program_root: Path,
    source_version: str | None,
    *,
    schema_version: int | None = None,
) -> str | None:
    """``deploy migrate`` 成功后记下「数据是从哪个版本导入过来的」。

    同时把 ``last_run_version`` 置为当前版本：导入完成后这份数据已经是新版布局，
    紧接着的第一次启动不该再被判成「刚升级」而重复提示。
    """
    current = program_version(program_root)
    previous = load(home)
    return save(
        home,
        replace(
            previous,
            error=None,
            last_run_version=current,
            last_run_at=_now(),
            last_schema_version=schema_version
            if schema_version is not None
            else previous.last_schema_version,
            first_seen_version=previous.first_seen_version or source_version or current,
            migrated_from_version=source_version,
            migrated_at=_now(),
        ),
    )
