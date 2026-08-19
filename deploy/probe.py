# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""doctor 的采集层：只做有副作用的探测，不判断好坏。

每个采集函数独立、**绝不抛异常**（失败写 ``None`` 或错误字符串），
``collect()`` 汇总为 ``Snapshot``。判断逻辑见 checks.py（纯函数），
本层不 import checks，保证分层单向。
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import socket
import sqlite3
import sys
from urllib.parse import urlparse

import httpx
from dotenv import dotenv_values

try:
    import tomllib
except ImportError:  # pragma: no cover - Python 3.10 需要 tomli 兜底
    import tomli as tomllib

from config import (
    ALLOWED_GROUPS,
    CONSOLIDATION_LM_STUDIO_MODEL,
    DB_CLEANUP_ON_START,
    DB_PATH,
    LM_STUDIO_BASE_URL,
    LM_STUDIO_MODEL,
    MEMORY_EMBEDDING_ENABLED,
    MEMORY_EMBEDDING_MODEL,
    MEMORY_EXTRACT_LM_STUDIO_MODEL,
    PROJECT_ROOT,
    SYSTEM_PROMPT_PATH,
)
from memory.schema import SCHEMA_VERSION

from .models import Snapshot

# 已废弃的 .env 键：精确匹配
_DEPRECATED_KEYS = frozenset(
    {
        "NAPCAT_SHELL_PATH",
        "NAPCAT_AUTO_START",
        "NAPCAT_QQ_ACCOUNT",
        "NAPCAT_QQ_PASSWORD",
        "NAPCAT_QQ_PASSWORD_MD5",
        "NAPCAT_LAUNCH_LOG_PATH",
        "NAPCAT_SHOW_WINDOW",
        "RECENT_MESSAGE_LIMIT",
        "MEMORY_CANDIDATE_CONFIRM_MIN_CONFIDENCE",
        "MEMORY_CANDIDATE_CONFIRM_MIN_IMPORTANCE",
        "PROACTIVE_MIN_PROB",
        "PROACTIVE_MAX_PROB",
        "PROACTIVE_HIGH_FREQ_INTERVAL",
        "PROACTIVE_LOW_FREQ_INTERVAL",
    }
)
# 已废弃的 .env 键：前缀匹配
_DEPRECATED_PREFIXES = ("NAPCAT_WATCHDOG_",)


def _probe_python() -> tuple[tuple[int, int, int], list[str]]:
    """版本号 + 缺失依赖包列表。"""
    version = (sys.version_info.major, sys.version_info.minor, sys.version_info.micro)
    required = ["nonebot", "httpx", "dotenv", "nonebot_plugin_apscheduler"]
    if version[:2] == (3, 10):
        required.append("tomli")
    missing = [pkg for pkg in required if importlib.util.find_spec(pkg) is None]
    return version, missing


def _probe_env_file() -> tuple[bool, list[str]]:
    """.env 是否存在 + 废弃键列表（读文本、忽略注释行）。"""
    env_path = PROJECT_ROOT / ".env"
    try:
        exists = env_path.exists()
        deprecated: list[str] = []
        if exists:
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key = line.split("=", 1)[0].strip()
                if key in _DEPRECATED_KEYS or any(
                    key.startswith(p) for p in _DEPRECATED_PREFIXES
                ):
                    deprecated.append(key)
        return exists, sorted(set(deprecated))
    except Exception:
        return False, []


def _extract_ws_url(values: dict) -> str | None:
    """从 dotenv_values 结果里取出第一个正向 WS URL（JSON 数组或裸 URL）。"""
    for key in ("ONEBOT_WS_URLS", "ONEBOT_V11_WS_URLS"):
        raw = (values.get(key) or "").strip()
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list) and parsed:
                return str(parsed[0])
        except (ValueError, TypeError):
            pass
        return raw
    return None


def _tcp_reachable(url: str, timeout: float = 3.0) -> bool | None:
    """从 ws:// / wss:// URL 解出 host:port 并尝试 TCP 连接。

    只做 TCP 层探测，不做 WebSocket 握手——项目无 websockets 依赖，
    而「端口能连上」已足以区分「NapCat 没开 WS 服务端」与「地址配错了」。
    """
    try:
        parts = urlparse(url)
        host = parts.hostname
        port = parts.port or (443 if parts.scheme == "wss" else 80)
        if not host:
            return None
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, ValueError):
        return False
    except Exception:
        return None


def _port_in_use(host: str, port: int) -> bool | None:
    """探测端口是否已被占用。无法判断时返回 None。

    注意：Bot 自己在运行时端口必然被占用，这属正常。检查层的 fix_hint
    要说明这一点，doctor 无法区分「被自己占」和「被别人占」。
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind((host, port))
            return False
        except OSError:
            return True
        finally:
            sock.close()
    except Exception:
        return None


def _probe_onebot() -> dict:
    """判定连接模式与可达性（反向 WS 端口 / 正向 WS 地址）。"""
    result = {
        "mode": "unknown",
        "host": "",
        "port": 0,
        "port_in_use": None,
        "forward_reachable": None,
    }
    try:
        env_path = PROJECT_ROOT / ".env"
        if not env_path.exists():
            return result
        values = dotenv_values(env_path)
    except Exception:
        return result

    ws_url = _extract_ws_url(values)
    if ws_url:
        result["mode"] = "forward"
        result["forward_reachable"] = _tcp_reachable(ws_url)
        return result

    try:
        host = (values.get("HOST") or "127.0.0.1").strip() or "127.0.0.1"
        port = int((values.get("PORT") or "8080").strip() or "8080")
    except (TypeError, ValueError):
        host, port = "127.0.0.1", 8080
    result["mode"] = "reverse"
    result["host"] = host
    result["port"] = port
    result["port_in_use"] = _port_in_use(host, port)
    return result


def fetch_loaded_models(base_url: str = "") -> tuple[list[str], str]:
    """查询 LM Studio 已加载模型 ID 列表。

    返回 ``(模型列表, 错误信息)``，错误信息为空表示成功。
    ``base_url`` 为空时用配置的 ``LM_STUDIO_BASE_URL``。
    doctor 与 init 向导共用，避免重复实现 HTTP 请求。
    """
    try:
        url = (base_url or LM_STUDIO_BASE_URL).rstrip("/")
        resp = httpx.get(f"{url}/v1/models", timeout=5.0, trust_env=False)
        resp.raise_for_status()
        data = resp.json()
        models = [m.get("id") for m in (data.get("data") or []) if m.get("id")]
        return models, ""
    except Exception as e:
        return [], str(e)[:300]


def _probe_lm_studio() -> dict:
    """探测 LM Studio /v1/models：可达性 + 已加载模型 ID 列表。"""
    result = {"lm_reachable": None, "lm_error": "", "lm_models": []}
    models, err = fetch_loaded_models()
    if err:
        result["lm_reachable"] = False
        result["lm_error"] = err
    else:
        result["lm_reachable"] = True
        result["lm_models"] = models
    return result


def _probe_database() -> dict:
    """数据库存在性 / 可写性 / schema 版本 / 遗留列 / source_kind 分布。"""
    result = {
        "db_exists": DB_PATH.exists(),
        "db_path": str(DB_PATH),
        "db_writable": None,
        "schema_version": None,
        "code_schema_version": SCHEMA_VERSION,
        "legacy_group_id_tables": [],
        "source_kind_counts": {},
    }
    if not result["db_exists"]:
        try:
            result["db_writable"] = os.access(DB_PATH.parent, os.W_OK)
        except Exception:
            result["db_writable"] = None
        return result
    try:
        conn = sqlite3.connect(DB_PATH)
        try:
            cursor = conn.cursor()
            # 只读操作，确认能打开
            cursor.execute("PRAGMA user_version")
            cursor.fetchone()
            try:
                row = conn.execute(
                    "SELECT version FROM schema_meta WHERE k='version'"
                ).fetchone()
                result["schema_version"] = int(row[0]) if row and row[0] else 0
            except sqlite3.OperationalError:
                result["schema_version"] = 0
            for table in ("memories", "memory_candidates", "user_profiles", "atomic_facts"):
                try:
                    cursor.execute(f"PRAGMA table_info({table})")
                    cols = [r[1] for r in cursor.fetchall()]
                    if "group_id" in cols:
                        result["legacy_group_id_tables"].append(table)
                except sqlite3.OperationalError:
                    continue
            try:
                cursor.execute(
                    "SELECT source_kind, COUNT(*) FROM group_messages GROUP BY source_kind"
                )
                result["source_kind_counts"] = {
                    str(k): int(c) for k, c in cursor.fetchall()
                }
            except sqlite3.OperationalError:
                pass
        finally:
            conn.close()
        result["db_writable"] = os.access(DB_PATH.parent, os.W_OK)
    except Exception:
        result["db_writable"] = False
    return result


def _probe_spaces() -> dict:
    """群号冲突 + 账本与显式 toml 不一致（不复用 config.spaces._load）。"""
    result = {"space_conflicts": [], "space_assignment_mismatch": []}
    explicit: dict[int, str] = {}
    spaces_dir = PROJECT_ROOT / "config" / "spaces"
    try:
        if spaces_dir.is_dir():
            for path in sorted(spaces_dir.glob("*.toml")):
                space = path.stem
                try:
                    with path.open("rb") as f:
                        data = tomllib.load(f)
                except Exception:
                    continue
                qq_groups = data.get("qq_groups")
                if not isinstance(qq_groups, list):
                    continue
                for g in qq_groups:
                    if not isinstance(g, int):
                        continue
                    if g in explicit:
                        result["space_conflicts"].append(
                            {"group_id": g, "spaces": [explicit[g], space]}
                        )
                    else:
                        explicit[g] = space
    except Exception:
        pass

    ledger_file = DB_PATH.parent / ".space_assignments.json"
    try:
        if ledger_file.exists():
            ledger = json.loads(ledger_file.read_text(encoding="utf-8"))
            if isinstance(ledger, dict):
                for k, v in ledger.items():
                    try:
                        g = int(k)
                    except (TypeError, ValueError):
                        continue
                    ledger_name = str(v)
                    explicit_name = explicit.get(g)
                    # 账本是自动命名的 space_N、而显式 toml 给了别的名字 → 历史记忆仍挂旧名
                    if (
                        explicit_name is not None
                        and ledger_name != explicit_name
                        and re.match(r"^space_\d+$", ledger_name)
                    ):
                        result["space_assignment_mismatch"].append(
                            {
                                "group_id": g,
                                "ledger": ledger_name,
                                "explicit": explicit_name,
                            }
                        )
    except Exception:
        pass
    return result


def _probe_misc() -> dict:
    """人格文件 + 磁盘剩余空间。"""
    result = {"persona_exists": False, "persona_size": 0, "disk_free_mb": None}
    try:
        p = SYSTEM_PROMPT_PATH
        result["persona_exists"] = p.exists()
        result["persona_size"] = p.stat().st_size if p.exists() else 0
    except Exception:
        pass
    try:
        usage = shutil.disk_usage(DB_PATH.parent)
        result["disk_free_mb"] = usage.free / (1024 * 1024)
    except Exception:
        result["disk_free_mb"] = None
    return result


def _probe_status_api() -> bool:
    """状态接口是否可达。

    复用 process 里的实现：它已处理 HOST=0.0.0.0 → 127.0.0.1 的映射与
    .env 读取，重复一份必然漂移。延迟 import：probe 与 process 目前互不
    依赖，但将来 process 若反向 import probe，模块级 import 会形成环。
    """
    try:
        from .process import _fetch_live_status

        # 超时略短于 process 的 1.0s：doctor 是交互命令，多一项探测不该拖慢
        return _fetch_live_status(timeout=0.8) is not None
    except Exception:
        return False


def collect() -> Snapshot:
    """采集全部环境事实并组装 Snapshot。

    每个探针本身不抛异常；collect 再兜一层——doctor 自身崩溃是最糟的体验，
    任何意外都应降级为「该项无法确定」。
    """
    try:
        python_version, missing = _probe_python()
    except Exception:
        python_version, missing = (0, 0, 0), []
    try:
        env_exists, deprecated_keys = _probe_env_file()
    except Exception:
        env_exists, deprecated_keys = False, []
    try:
        onebot = _probe_onebot()
    except Exception:
        onebot = {}
    try:
        lm = _probe_lm_studio()
    except Exception:
        lm = {}
    try:
        db = _probe_database()
    except Exception:
        db = {}
    try:
        spaces = _probe_spaces()
    except Exception:
        spaces = {}
    try:
        misc = _probe_misc()
    except Exception:
        misc = {}
    try:
        status_api_reachable = _probe_status_api()
    except Exception:
        status_api_reachable = False
    return Snapshot(
        python_version=python_version,
        missing_packages=missing,
        env_exists=env_exists,
        deprecated_env_keys=deprecated_keys,
        allowed_groups=list(ALLOWED_GROUPS),
        db_cleanup_on_start=DB_CLEANUP_ON_START,
        onebot_mode=onebot.get("mode", "unknown"),
        onebot_host=onebot.get("host", "127.0.0.1"),
        onebot_port=onebot.get("port", 8080),
        onebot_port_in_use=onebot.get("port_in_use"),
        onebot_forward_reachable=onebot.get("forward_reachable"),
        status_api_reachable=status_api_reachable,
        lm_reachable=lm.get("lm_reachable"),
        lm_error=lm.get("lm_error", ""),
        lm_models=lm.get("lm_models", []),
        lm_model_chat=LM_STUDIO_MODEL,
        lm_model_consolidation=CONSOLIDATION_LM_STUDIO_MODEL,
        lm_model_extract=MEMORY_EXTRACT_LM_STUDIO_MODEL,
        lm_model_embedding=MEMORY_EMBEDDING_MODEL,
        embedding_enabled=MEMORY_EMBEDDING_ENABLED,
        db_exists=db.get("db_exists", False),
        db_path=db.get("db_path", ""),
        db_writable=db.get("db_writable"),
        schema_version=db.get("schema_version"),
        code_schema_version=db.get("code_schema_version", SCHEMA_VERSION),
        legacy_group_id_tables=db.get("legacy_group_id_tables", []),
        source_kind_counts=db.get("source_kind_counts", {}),
        space_conflicts=spaces.get("space_conflicts", []),
        space_assignment_mismatch=spaces.get("space_assignment_mismatch", []),
        persona_exists=misc.get("persona_exists", False),
        persona_size=misc.get("persona_size", 0),
        disk_free_mb=misc.get("disk_free_mb"),
    )
