# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""``STELLA_HOME``：用户数据根目录的定位（纯逻辑，不 import ``config.settings``）。

**为什么要有它**：用户数据与程序此前在同一个目录，而发布包是整目录 zip。于是
「解压新版到新目录」这个动作本身就把用户和他的数据分开了，升级必须手工搬 10 项文件
（漏一项就是静默故障）。把用户数据挪出安装目录之后，升级 = 换掉程序目录，数据不动。

定位顺序（**不读 .env**——``STELLA_HOME`` 只能来自真环境变量或指针文件，否则会形成
「要读 .env 才知道 .env 在哪」的死循环）：

1. 环境变量 ``STELLA_HOME``；
2. 机器级指针文件（``%LOCALAPPDATA%\\Stella\\home.txt`` / ``~/.config/stella/home.txt``）
   —— 它在**程序目录之外**，所以任何一份新解压的程序都能立刻接上老数据。这是「升级
   只需一步」的实现基础；
3. 安装目录本身像是用过的旧布局（有 ``.env`` 或 ``memory/agent_memory.db``）→ 就地使用，
   3.0.0 及更早的安装原地继续工作，零改动；
4. ``<安装目录>/StellaData`` 已存在 → 用它（**便携模式**）。想把程序连数据整个拷进 U 盘、
   或希望仓库/发布包/运行期的布局完全一致时，建一个这样的子目录即可。开发仓库走的就是
   这条；
5. 都没有 → ``<安装目录>/../StellaData``（便携、用户看得见、可整体拷走）。

**为什么默认是「同级」而不是「内部」**（第 5 条 vs 第 4 条）：程序目录是升级时被整体
替换、也会被用户当作「旧版本」删掉的那个目录。数据放进去，就等于把「删掉旧版本文件夹」
变成一个不可逆的数据丢失操作——而那是个再自然不过的清理动作。所以默认在外，
只有用户**显式**建了 ``StellaData`` 子目录才认为他要的是自包含布局。

**永不抛异常**：任何一步出错都退回安装目录，也就是退回 2026-08-27 之前的行为。
定位失败不该让 Bot 起不来。

数据目录内部的相对布局与旧安装**完全一致**（``memory/``、``config/spaces/``、
``system_prompts/``、``data/``、``logs/``）。刻意不换成更好听的名字：这样「旧布局」
只是「STELLA_HOME 恰好等于安装目录」的一个特例，全项目不需要任何双布局分支，
``deploy migrate`` 的路径清单也两种布局通用。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# 数据目录的默认名（放在安装目录的同级）
DEFAULT_DIR_NAME = "StellaData"
# 指针文件名（内容 = 数据目录的绝对路径，一行）
POINTER_NAME = "home.txt"
ENV_VAR = "STELLA_HOME"
# 「这个目录被用过」的判据：有配置或有记忆库
LEGACY_MARKERS = (".env", "memory/agent_memory.db", "deploy.answers.toml")


@dataclass(frozen=True)
class HomeResolution:
    """定位结果。``source`` 是给人看的来源说明（doctor / GUI 会显示它）。"""

    path: Path
    source: str


def pointer_path() -> Path:
    """机器级指针文件的位置。

    Windows 用 ``%LOCALAPPDATA%\\Stella``，其余平台用 XDG 的
    ``~/.config/stella``——它必须在程序目录之外，否则换一份程序就失效了。
    """
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "Stella" / POINTER_NAME
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "stella" / POINTER_NAME


def read_pointer() -> Path | None:
    """读指针文件；不存在、读不出、内容不是个存在的目录都返回 None。"""
    path = pointer_path()
    try:
        if not path.is_file():
            return None
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text:
        return None
    candidate = Path(text)
    return candidate if candidate.is_dir() else None


def write_pointer(home: Path) -> str | None:
    """把数据目录写进指针文件。成功返回 None，失败返回错误描述。"""
    path = pointer_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(home.resolve()) + "\n", encoding="utf-8")
    except OSError as e:
        return f"指针文件 {path} 写入失败: {e}"
    return None


def looks_used(directory: Path) -> bool:
    """目录里有没有「用过的痕迹」（旧布局判据）。"""
    return any((directory / marker).exists() for marker in LEGACY_MARKERS)


def resolve(install_root: Path, *, create: bool = False) -> HomeResolution:
    """定位数据目录。``create=True`` 时才创建目录并写指针文件。

    默认 **不创建**：``import config`` 不该有建目录、写文件这种副作用。真正需要落盘的
    时机（``deploy init`` / ``deploy migrate`` / GUI 首次配置）会显式传 ``create=True``。
    """
    try:
        return _resolve(install_root, create=create)
    except Exception:
        # 定位失败一律退回安装目录 = 退回旧行为，绝不让 Bot 起不来
        return HomeResolution(path=install_root, source="定位失败，回退到安装目录")


def _resolve(install_root: Path, *, create: bool) -> HomeResolution:
    from_env = os.environ.get(ENV_VAR, "").strip()
    if from_env:
        home = Path(from_env).expanduser()
        if create:
            _ensure(home)
        return HomeResolution(path=home, source=f"环境变量 {ENV_VAR}")

    pointed = read_pointer()
    if pointed is not None:
        return HomeResolution(path=pointed, source=f"指针文件 {pointer_path()}")

    if looks_used(install_root):
        return HomeResolution(path=install_root, source="旧布局：数据在安装目录内")

    # 便携模式：用户显式在安装目录里建了 StellaData，就用它。放在默认值之前判断，
    # 但排在「旧布局」之后——旧安装的数据在安装目录根上，不该被一个恰好同名的空目录抢走。
    inside = install_root / DEFAULT_DIR_NAME
    if inside.is_dir():
        return HomeResolution(path=inside.resolve(), source="便携模式：安装目录内的 StellaData")

    home = (install_root.parent / DEFAULT_DIR_NAME).resolve()
    if create:
        _ensure(home)
        write_pointer(home)
    return HomeResolution(path=home, source=f"新建数据目录 {home}")


def _ensure(home: Path) -> None:
    home.mkdir(parents=True, exist_ok=True)
