# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""安装状态账本、三态进程探活与跨进程安装锁（轻量、零重依赖）。

这个模块是 WP04 的状态契约落点。硬约束：

* **只依赖标准库**——它会被 NSIS 离线装载（嵌入式 Python 还没有 pip）、
  deploy CLI 与 GUI 侧共同加载；import 本模块绝不允许拉起 config.settings
  之类的全应用配置（deploy.process 就因为 import 即加载全应用配置而不
  适合直接照搬）。
* **三态探活**：进程存在性只有 alive / gone / unknown 三种结论。Windows 上
  ``os.kill(pid, 0)`` 会 TerminateProcess（这不是探测，是击杀）；而
  「OpenProcess 失败即不存在」也是错的——权限不足同样让 OpenProcess 失败。
  只有 ERROR_INVALID_PARAMETER（pid 不存在）才允许判 gone；其余一律
  unknown，**绝不据 unknown 删锁或动手**。
* **进程身份**：裸 PID 会被操作系统复用。锁记录里保存「进程创建身份」
  （Windows = 创建时间 FILETIME；POSIX = /proc starttime），恢复陈旧锁时
  身份对不上 = 原 owner 已死、PID 被复用，而不是「还活着」。
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any

LEDGER_FILENAME = "install-ledger.json"
LOCK_FILENAME = "install.lock"
LEDGER_SCHEMA_VERSION = 1

# 总体状态（对应安装契约 InstallOutcome 的超集，账本侧多一个 running 中间态）
LEDGER_RUNNING = "running"
LEDGER_READY = "ready"
LEDGER_FAILED = "failed"
LEDGER_INTERRUPTED = "interrupted"

# 组件状态：pending → verified → staged → activated → healthy；failed 单独落
COMPONENT_PENDING = "pending"
COMPONENT_VERIFIED = "verified"
COMPONENT_STAGED = "staged"
COMPONENT_ACTIVATED = "activated"
COMPONENT_HEALTHY = "healthy"
COMPONENT_FAILED = "failed"

ALIVE = "alive"
GONE = "gone"
UNKNOWN = "unknown"


def ledger_path(data_root: Path) -> Path:
    return Path(data_root) / ".stella" / LEDGER_FILENAME


def lock_path(data_root: Path) -> Path:
    return Path(data_root) / ".stella" / LOCK_FILENAME


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        Path(temporary).replace(path)
    finally:
        Path(temporary).unlink(missing_ok=True)


# ============================================================
# 三态进程探活与进程身份
# ============================================================


def probe_pid(pid: int) -> str:
    """无副作用探测：alive / gone / unknown 三态。

    * POSIX：``os.kill(pid, 0)`` 是安全的（信号 0 只做存在性检查）；
      PermissionError 表示进程存在但无权发信号 → alive。
    * Windows：OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION) +
      GetExitCodeProcess。OpenProcess 失败且 LastError 为
      ERROR_INVALID_PARAMETER（pid 不存在）→ gone；**其它失败（典型是
      权限不足）→ unknown**，绝不推断为死亡。
    """
    if pid <= 0:
        return GONE
    if os.name == "nt":
        return _windows_probe(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return GONE
    except PermissionError:
        # 存在但无权发信号：进程在（POSIX 语义，与我们无关的他人进程）
        return ALIVE
    except OSError:
        return UNKNOWN
    return _posix_alive_not_zombie(pid)


def _posix_alive_not_zombie(pid: int) -> str:
    """僵尸进程仍在进程表里；读 /proc 区分（非 Linux 读不到 → alive）。"""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return ALIVE
    try:
        return GONE if stat[stat.rindex(")") + 2] == "Z" else ALIVE
    except (ValueError, IndexError):
        return ALIVE


def _windows_probe(pid: int) -> str:
    import ctypes
    import ctypes.wintypes

    process_query_limited_information = 0x1000
    still_active = 259
    error_invalid_parameter = 87
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = ctypes.wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [
        ctypes.wintypes.DWORD,
        ctypes.wintypes.BOOL,
        ctypes.wintypes.DWORD,
    ]
    kernel32.GetExitCodeProcess.argtypes = [
        ctypes.wintypes.HANDLE,
        ctypes.POINTER(ctypes.wintypes.DWORD),
    ]
    kernel32.GetExitCodeProcess.restype = ctypes.wintypes.BOOL
    kernel32.CloseHandle.argtypes = [ctypes.wintypes.HANDLE]
    kernel32.CloseHandle.restype = ctypes.wintypes.BOOL

    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        if ctypes.get_last_error() == error_invalid_parameter:
            return GONE
        return UNKNOWN
    try:
        code = ctypes.wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return UNKNOWN
        return ALIVE if code.value == still_active else GONE
    finally:
        kernel32.CloseHandle(handle)


def process_identity(pid: int) -> str | None:
    """当前 PID 对应进程的创建身份；取不到返回 None（调用方不得凭 None 抢锁）。

    Windows 用 GetProcessTimes 的创建时间（FILETIME），POSIX 用
    /proc/<pid>/stat 的 starttime（字段 22）。两者都在进程存活期间稳定，
    进程死亡后被新进程复用 PID 时必然变化。
    """
    if pid <= 0:
        return None
    if os.name == "nt":
        return _windows_identity(pid)
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        fields = stat[stat.rindex(")") + 2:].split()
        # stat 布局：pid (comm) state ppid ...；starttime 是去掉 comm 后的第 20 个字段
        return f"posix-starttime-{fields[19]}"
    except (OSError, ValueError, IndexError):
        return None


def _windows_identity(pid: int) -> str | None:
    import ctypes
    import ctypes.wintypes

    process_query_limited_information = 0x1000
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = ctypes.wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [
        ctypes.wintypes.DWORD,
        ctypes.wintypes.BOOL,
        ctypes.wintypes.DWORD,
    ]

    class _FileTime(ctypes.Structure):
        _fields_ = [("low", ctypes.wintypes.DWORD), ("high", ctypes.wintypes.DWORD)]

    kernel32.GetProcessTimes.restype = ctypes.wintypes.BOOL
    kernel32.GetProcessTimes.argtypes = [
        ctypes.wintypes.HANDLE,
        ctypes.POINTER(_FileTime),
        ctypes.POINTER(_FileTime),
        ctypes.POINTER(_FileTime),
        ctypes.POINTER(_FileTime),
    ]
    kernel32.CloseHandle.argtypes = [ctypes.wintypes.HANDLE]

    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return None
    try:
        creation = _FileTime()
        exit_time = _FileTime()
        kernel_time = _FileTime()
        user_time = _FileTime()
        if not kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel_time),
            ctypes.byref(user_time),
        ):
            return None
        value = (creation.high << 32) | creation.low
        return f"win-creation-{value}"
    finally:
        kernel32.CloseHandle(handle)


def self_identity() -> dict[str, Any]:
    """当前进程的 owner 记录（pid + 创建身份）。"""
    pid = os.getpid()
    return {"pid": pid, "identity": process_identity(pid)}


def classify_owner(owner: dict[str, Any]) -> str:
    """锁记录里的 owner 归类：``alive`` / ``stale`` / ``unknown``。

    * 探活 gone → stale（owner 已死，可恢复锁）。
    * 进程活着但创建身份与记录不一致 → stale（PID 被复用，原 owner 死）。
    * 探活 unknown、记录缺失或身份取不到 → unknown（**绝不**据此删锁）。
    * 活着且身份一致 → alive（别人正在装，互斥等待）。
    """
    try:
        pid = int(owner.get("pid") or 0)
    except (TypeError, ValueError):
        return UNKNOWN
    if pid <= 0:
        return UNKNOWN
    recorded = str(owner.get("identity") or "")
    state = probe_pid(pid)
    if state == GONE:
        return "stale"
    if state == UNKNOWN:
        return UNKNOWN
    if not recorded:
        return UNKNOWN
    return "alive" if process_identity(pid) == recorded else "stale"


# ============================================================
# 跨进程安装锁（O_EXCL 原子创建 + owner 身份 + 三态陈旧恢复）
# ============================================================


class InstallLockError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class InstallLock:
    """数据根级的跨进程互斥锁。

    O_EXCL 原子创建是真实的 OS 互斥（不存在「检查后创建」窗口）。锁文件
    记录 owner 的 pid + 创建身份；恢复陈旧锁必须同时满足：探活为 gone，
    或进程活着但创建身份与记录不一致（PID 复用）。探活 unknown 或身份
    取不到时**绝不**删锁——那正是旧实现的 os.kill 误杀与误抢锁的根源。

    当前安装链路只锁数据根一把（install root 锁随版本化激活在 WP10 引入，
    届时统一「先 install root 后 data root」的获取顺序）。
    """

    def __init__(self, data_root: Path):
        self.data_root = Path(data_root)
        self.path = lock_path(self.data_root)
        self._held = False

    def acquire(self, *, recover_stale: bool = True) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError as exc:
                if not recover_stale or not self._try_recover_stale():
                    raise InstallLockError(
                        "install_in_progress",
                        "已有安装/修复操作正在进行中（另一进程持有安装锁）",
                    ) from exc
                continue
            except OSError as exc:
                raise InstallLockError("lock_unavailable", str(exc)) from exc
            try:
                os.write(fd, (json.dumps(self_identity()) + "\n").encode("utf-8"))
                os.fsync(fd)
            finally:
                os.close(fd)
            self._held = True
            return

    def release(self) -> None:
        if not self._held:
            return
        with contextlib.suppress(FileNotFoundError):
            self.path.unlink()
        self._held = False

    def _try_recover_stale(self) -> bool:
        try:
            owner = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            # 读不出 owner 的锁：归属不明，保守起见不删（等运维/用户处置）
            return False
        if not isinstance(owner, dict):
            return False
        if classify_owner(owner) != "stale":
            return False
        # 陈旧性成立：删锁并重试 acquire。仍有极小竞态（此刻恰有新 owner
        # 创建了锁），由 O_EXCL 语义兜底——unlink 只可能删到同一把陈旧锁
        # 或失败，不会让两个进程同时持锁。
        try:
            self.path.unlink()
        except FileNotFoundError:
            return True
        except OSError:
            return False
        return True

    def __enter__(self) -> InstallLock:  # noqa: PYI034
        self.acquire()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()


# ============================================================
# 安装账本
# ============================================================


def read_ledger(data_root: Path) -> dict[str, Any] | None:
    path = ledger_path(data_root)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def write_ledger(data_root: Path, payload: dict[str, Any]) -> None:
    _atomic_json(ledger_path(data_root), payload)


def new_ledger(
    data_root: Path,
    *,
    profile: str,
    catalog_sha256: str | None = None,
    components: list[str],
) -> dict[str, Any]:
    """开一份新账本（running）；owner 记录当前进程身份供陈旧判定。"""
    payload: dict[str, Any] = {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "operation_id": uuid.uuid4().hex,
        "profile": profile,
        "catalog_sha256": catalog_sha256 or "",
        "owner": self_identity(),
        "state": LEDGER_RUNNING,
        "current_step": "",
        "reboot_required": False,
        "components": {
            component_id: {"state": COMPONENT_PENDING, "attempts": 0}
            for component_id in components
        },
    }
    write_ledger(data_root, payload)
    return payload


def update_ledger(data_root: Path, **changes: Any) -> dict[str, Any] | None:
    payload = read_ledger(data_root)
    if payload is None:
        return None
    payload.update(changes)
    write_ledger(data_root, payload)
    return payload


def set_component(
    data_root: Path,
    component_id: str,
    *,
    state: str,
    error_code: str | None = None,
    error_message: str | None = None,
    expected_digest: str | None = None,
    reboot_required: bool | None = None,
) -> None:
    payload = read_ledger(data_root)
    if payload is None:
        return
    components = payload.setdefault("components", {})
    record = components.setdefault(component_id, {"state": state, "attempts": 0})
    record["state"] = state
    record["attempts"] = int(record.get("attempts", 0)) + 1
    if expected_digest is not None:
        record["expected_digest"] = expected_digest
    if error_code is not None:
        record["error_code"] = error_code
    if error_message is not None:
        record["error_message"] = str(error_message)[:500]
    if reboot_required is not None:
        record["reboot_required"] = reboot_required
        payload["reboot_required"] = True
    write_ledger(data_root, payload)


def classify_previous_ledger(
    data_root: Path, owner_present: bool
) -> str | None:
    """把上一份账本归类为兼容语义：running（活 owner）/ interrupted / 其它原值。

    旧 owner 已消失的 running 一律转 interrupted（崩溃恢复的依据）；
    owner 还活着时保持 running（并发进程在装，由锁负责互斥）。
    """
    payload = read_ledger(data_root)
    if payload is None:
        return None
    state = str(payload.get("state") or "")
    if state != LEDGER_RUNNING:
        return state
    if owner_present:
        return LEDGER_RUNNING
    update_ledger(data_root, state=LEDGER_INTERRUPTED)
    return LEDGER_INTERRUPTED


__all__ = [
    "ALIVE",
    "COMPONENT_ACTIVATED",
    "COMPONENT_FAILED",
    "COMPONENT_HEALTHY",
    "COMPONENT_PENDING",
    "COMPONENT_STAGED",
    "COMPONENT_VERIFIED",
    "GONE",
    "LEDGER_FAILED",
    "LEDGER_FILENAME",
    "LEDGER_INTERRUPTED",
    "LEDGER_READY",
    "LEDGER_RUNNING",
    "LEDGER_SCHEMA_VERSION",
    "LOCK_FILENAME",
    "UNKNOWN",
    "InstallLock",
    "InstallLockError",
    "classify_owner",
    "classify_previous_ledger",
    "ledger_path",
    "lock_path",
    "new_ledger",
    "probe_pid",
    "process_identity",
    "read_ledger",
    "self_identity",
    "set_component",
    "update_ledger",
    "write_ledger",
]
