# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""NoneBot adapter catalog, selection, and connection settings for the platform page."""

from __future__ import annotations

import json
import os
import re
from importlib.metadata import PackageNotFoundError, version
from io import StringIO
from pathlib import Path

from dotenv.parser import parse_stream

from core.transport.adapter_loader import (
    DEFAULT_ADAPTER_MODULES,
    parse_adapter_modules,
)
from core.transport.adapter_policy import unavailable_adapter_reasons
from deploy import env_keys
from deploy.env_schema import build_schema
from webui.responses import ApiError
from webui.services import envfile

_CATALOG_DATA = json.loads(
    Path(__file__).with_name("nonebot_adapter_catalog.json").read_text(encoding="utf-8")
)
_ADAPTER_CATALOG = tuple(_CATALOG_DATA["adapters"])
_ADAPTER_PACKAGES = {item["package"] for item in _ADAPTER_CATALOG}
_ADAPTER_ENV_KEYS_KEY = "STELLA_ADAPTER_ENV_KEYS"
_ADAPTER_ENV_MODULES_KEY = "STELLA_ADAPTER_ENV_MODULES"
_PLATFORM_MANAGED_ENV_KEYS = frozenset(
    {
        _ADAPTER_ENV_KEYS_KEY,
        _ADAPTER_ENV_MODULES_KEY,
        "STELLA_ADAPTER_MODULES",
        "DRIVER",
        "HOST",
        "PORT",
        "ONEBOT_WS_URLS",
        "ONEBOT_ACCESS_TOKEN",
        "QQ_BOTS",
        "TELEGRAM_BOTS",
        "TELEGRAM_PROXY",
        "TELEGRAM_WEBHOOK_URL",
        "DISCORD_BOTS",
        "DISCORD_PROXY",
    }
)
_NONEBOT_CORE_ENV_KEYS = frozenset(
    {
        "ENVIRONMENT",
        "DRIVER",
        "HOST",
        "PORT",
        "LOG_LEVEL",
        "API_TIMEOUT",
        "SUPERUSERS",
        "NICKNAME",
        "COMMAND_START",
        "COMMAND_SEP",
        "SESSION_EXPIRE_TIMEOUT",
    }
)
_SETTINGS_ENV_KEYS = frozenset(
    field["key"]
    for field in build_schema(Path(__file__).resolve().parents[2] / "config" / "settings.py")[
        "fields"
    ]
)
_PROTECTED_ADAPTER_ENV_KEYS = (
    _SETTINGS_ENV_KEYS
    | _PLATFORM_MANAGED_ENV_KEYS
    | _NONEBOT_CORE_ENV_KEYS
    | frozenset(env_keys.DEPRECATED)
    | frozenset(env_keys.SUPERSEDED)
)
_QQ_INTENT_DEFAULTS = {
    "guilds": True,
    "guild_members": True,
    "guild_messages": False,
    "guild_message_reactions": True,
    "direct_message": False,
    "open_forum_event": False,
    "audio_live_member": False,
    "group_members": False,
    "c2c_group_at_messages": False,
    "interaction": False,
    "message_audit": True,
    "forum_event": False,
    "audio_action": False,
    "at_messages": True,
}
_DISCORD_INTENTS = {"guild_messages", "direct_messages", "message_content"}
_DISCORD_INTENT_DEFAULTS = {
    "guild_messages": True,
    "direct_messages": True,
    "message_content": False,
}
_ENV_KEY = re.compile(r"^[A-Z][A-Z0-9_]*$")


def _dotenv_values() -> dict[str, str]:
    """Read .env values with python-dotenv's multiline and quoting rules."""
    path = envfile.env_file()
    if not path.exists():
        return {}
    try:
        with path.open(encoding="utf-8") as stream:
            return {
                binding.key: binding.value
                for binding in parse_stream(stream)
                if binding.key and binding.value is not None
            }
    except OSError:
        return {}


def _load_json_list(raw: dict[str, str], key: str) -> list[dict]:
    value = raw.get(key, "").strip()
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        raise ApiError(f"{key} 不是有效的 JSON 数组；请先修复现有配置") from None
    if not isinstance(parsed, list) or any(not isinstance(item, dict) for item in parsed):
        raise ApiError(f"{key} 必须是 JSON 对象数组")
    return parsed


def _env_bool(value: str | None, default: bool = False) -> bool:
    if value is None or not value.strip():
        return default
    return value.strip().strip("\"'").lower() in {"true", "1", "yes", "on"}


def _bool_input(payload: dict, key: str, default: bool = False) -> bool:
    value = payload.get(key, default)
    if not isinstance(value, bool):
        raise ApiError(f"{key} 必须为布尔值")
    return value


def _str_input(payload: dict, key: str, *, max_length: int = 4096) -> str:
    value = payload.get(key, "")
    if not isinstance(value, str):
        raise ApiError(f"{key} 必须为字符串")
    value = value.strip()
    if len(value) > max_length:
        raise ApiError(f"{key} 超过允许长度")
    return value


def _adapter_env_key(value: object) -> str:
    if not isinstance(value, str):
        raise ApiError("适配器环境变量名称必须是字符串")
    key = value.strip()
    if not _ENV_KEY.fullmatch(key):
        raise ApiError(f"非法适配器环境变量名称: {key or '空值'}")
    if key in _PROTECTED_ADAPTER_ENV_KEYS or key.startswith("STELLA_"):
        raise ApiError(f"{key} 属于 Stella 或平台页专用配置，不能作为通用适配器字段修改")
    return key


def _adapter_env_manifest(raw: dict[str, str]) -> list[str]:
    value = raw.get(_ADAPTER_ENV_KEYS_KEY, "").strip()
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        raise ApiError(f"{_ADAPTER_ENV_KEYS_KEY} 不是有效的 JSON 数组；请先修复现有配置") from None
    if not isinstance(parsed, list):
        raise ApiError(f"{_ADAPTER_ENV_KEYS_KEY} 必须是 JSON 字符串数组")
    keys = [_adapter_env_key(item) for item in parsed]
    if len(set(keys)) != len(keys):
        raise ApiError(f"{_ADAPTER_ENV_KEYS_KEY} 中存在重复配置键")
    return keys


def _adapter_env_modules(raw: dict[str, str]) -> dict[str, str]:
    value = raw.get(_ADAPTER_ENV_MODULES_KEY, "").strip()
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        raise ApiError(f"{_ADAPTER_ENV_MODULES_KEY} 不是有效的 JSON 对象；请先修复现有配置") from None
    if not isinstance(parsed, dict):
        raise ApiError(f"{_ADAPTER_ENV_MODULES_KEY} 必须是环境变量与适配器模块的映射对象")
    bindings: dict[str, str] = {}
    for raw_key, raw_module in parsed.items():
        key = _adapter_env_key(raw_key)
        if not isinstance(raw_module, str):
            raise ApiError(f"{_ADAPTER_ENV_MODULES_KEY} 中的模块路径必须是字符串")
        module = raw_module.strip()
        if module:
            try:
                parsed_modules = parse_adapter_modules(module)
            except ValueError:
                raise ApiError(f"{_ADAPTER_ENV_MODULES_KEY} 中包含无效模块路径: {module}") from None
            if len(parsed_modules) != 1 or parsed_modules[0] != module:
                raise ApiError(f"{_ADAPTER_ENV_MODULES_KEY} 每个键只能绑定一个模块路径")
            bindings[key] = module
    return bindings


def _adapter_env_is_sensitive(key: str) -> bool:
    upper = key.upper()
    compact = "".join(character for character in upper if character.isalnum())
    if any(marker in compact for marker in ("TOKENSTOREPATH", "TOKENEXPIRES", "TOKENEXPIRY")):
        return False
    return env_keys.is_sensitive(upper) or any(
        marker in compact
        for marker in (
            "TOKEN",
            "PASSWORD",
            "PASSWD",
            "SECRET",
            "APIKEY",
            "ACCESSKEY",
            "PRIVATEKEY",
            "CLIENTKEY",
            "APPKEY",
            "VERIFYKEY",
            "ENCRYPTKEY",
            "RECOVERYKEY",
            "RECOVERYCODE",
            "CREDENTIAL",
            "COOKIE",
            "PROXY",
            "TICKET",
            "SIGNATURE",
            "WEBHOOKURL",
            "AUTHORIZATION",
        )
    )


def _adapter_json_field_is_sensitive(key: str) -> bool:
    """Recognize nested credential fields without hiding timestamps or token-store paths."""
    expanded = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key)
    parts = set(re.findall(r"[A-Za-z0-9]+", expanded.lower()))
    if "token" in parts and parts.intersection({"expire", "expires", "expiry", "expiration"}):
        return bool(parts.intersection({"secret", "password", "passwd", "credential", "cookie"}))
    if parts.intersection(
        {
            "token",
            "secret",
            "password",
            "passwd",
            "passphrase",
            "credential",
            "cookie",
            "proxy",
            "ticket",
            "signature",
            "authorization",
        }
    ):
        return not ("token" in parts and bool(parts.intersection({"store", "path"})))
    has_credential_key = bool(
        {"api", "access", "private", "client", "app", "verify", "encrypt", "recovery"}.intersection(parts)
        and "key" in parts
    )
    has_webhook_secret = bool({"webhook", "callback"}.intersection(parts) and "secret" in parts)
    return has_credential_key or has_webhook_secret


def _redact_adapter_json(value: object, path: str = "") -> tuple[object, list[str]]:
    """Hide nested credentials in JSON-valued adapter settings before returning them."""
    secret_paths: list[str] = []
    if isinstance(value, dict):
        redacted: dict = {}
        for key, item in value.items():
            child_path = f"{path}/{str(key).replace('~', '~0').replace('/', '~1')}"
            if isinstance(key, str) and _adapter_json_field_is_sensitive(key):
                if item not in (None, ""):
                    secret_paths.append(child_path)
                redacted[key] = ""
            else:
                redacted[key], nested_paths = _redact_adapter_json(item, child_path)
                secret_paths.extend(nested_paths)
        return redacted, secret_paths
    if isinstance(value, list):
        redacted_list: list = []
        for index, item in enumerate(value):
            redacted_item, nested_paths = _redact_adapter_json(item, f"{path}/{index}")
            redacted_list.append(redacted_item)
            secret_paths.extend(nested_paths)
        return redacted_list, secret_paths
    return value, secret_paths


def _adapter_json_identity(value: object) -> tuple[str, str] | None:
    if not isinstance(value, dict):
        return None
    for key in (
        "app_id",
        "client_id",
        "account_id",
        "account",
        "id",
        "bot_id",
        "user_id",
        "self_id",
        "name",
    ):
        item = value.get(key)
        if item not in (None, ""):
            return key, str(item)
    return None


def _preserve_adapter_json_secrets(old: object, new: object) -> object:
    """Restore blank nested secret fields from the stored JSON config by bot identity."""
    if isinstance(old, dict) and isinstance(new, dict):
        merged = dict(new)
        for key, old_value in old.items():
            if key not in merged:
                if isinstance(key, str) and _adapter_json_field_is_sensitive(key) and old_value not in (None, ""):
                    merged[key] = old_value
                continue
            new_value = merged[key]
            if isinstance(key, str) and _adapter_json_field_is_sensitive(key) and new_value in (None, ""):
                if old_value not in (None, ""):
                    merged[key] = old_value
            else:
                merged[key] = _preserve_adapter_json_secrets(old_value, new_value)
        return merged
    if isinstance(old, list) and isinstance(new, list):
        old_by_identity = {
            identity: item
            for item in old
            if (identity := _adapter_json_identity(item)) is not None
        }
        merged_list: list = []
        for index, item in enumerate(new):
            identity = _adapter_json_identity(item)
            if identity is not None:
                previous = old_by_identity.get(identity)
            elif index < len(old) and _adapter_json_identity(old[index]) is None:
                previous = old[index]
            else:
                previous = None
            merged_list.append(
                _preserve_adapter_json_secrets(previous, item)
                if previous is not None
                else item
            )
        return merged_list
    return new


def _adapter_env_status(raw: dict[str, str]) -> tuple[list[dict], list[str]]:
    entries: list[dict] = []
    process_overrides: list[str] = []
    modules = _adapter_env_modules(raw)
    for key in _adapter_env_manifest(raw):
        file_value = raw.get(key, "")
        process_value = os.environ.get(key)
        process_override = process_value is not None and process_value != file_value
        effective_value = process_value if process_override else file_value
        sensitive = _adapter_env_is_sensitive(key)
        display_value = "" if sensitive else effective_value or ""
        sensitive_paths: list[str] = []
        if display_value:
            try:
                parsed_value = json.loads(display_value)
            except (TypeError, ValueError):
                pass
            else:
                if isinstance(parsed_value, (dict, list)):
                    redacted, sensitive_paths = _redact_adapter_json(parsed_value)
                    display_value = json.dumps(
                        redacted, ensure_ascii=False, separators=(",", ":")
                    )
        entries.append(
            {
                "key": key,
                "module": modules.get(key, ""),
                "value": display_value,
                "has_value": bool(effective_value),
                "sensitive": sensitive,
                "sensitive_paths": sensitive_paths,
                "process_override": process_override,
            }
        )
        if process_override:
            process_overrides.append(key)
    return entries, process_overrides


def _adapter_env_updates(payload: dict, raw: dict[str, str]) -> dict[str, str | None]:
    rows = payload.get("adapter_env")
    if not isinstance(rows, list) or len(rows) > 128:
        raise ApiError("adapter_env 必须是最多包含 128 项的配置数组")
    updates: dict[str, str | None] = {}
    keys: list[str] = []
    modules = _adapter_env_modules(raw)
    new_modules: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ApiError("adapter_env 每一项必须是配置对象")
        key = _adapter_env_key(row.get("key"))
        if key in keys:
            raise ApiError(f"适配器环境变量 {key} 重复")
        value = _str_input(row, "value", max_length=8192)
        if "\n" in value or "\r" in value or "\0" in value:
            raise ApiError(f"{key} 不能包含换行符或 NUL 字符")
        if not value and _adapter_env_is_sensitive(key):
            value = raw.get(key, "")
        elif value and key in raw:
            try:
                old_json = json.loads(raw[key])
                new_json = json.loads(value)
            except (TypeError, ValueError):
                pass
            else:
                if isinstance(old_json, (dict, list)) and isinstance(new_json, type(old_json)):
                    value = json.dumps(
                        _preserve_adapter_json_secrets(old_json, new_json),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
        updates[key] = _quote_env(value)
        keys.append(key)
        module = row.get("module", modules.get(key, ""))
        if not isinstance(module, str):
            raise ApiError(f"{key} 的适配器模块必须为字符串")
        module = module.strip()
        if module:
            try:
                parsed_modules = parse_adapter_modules(module)
            except ValueError:
                raise ApiError(f"{key} 包含无效适配器模块路径: {module}") from None
            if len(parsed_modules) != 1 or parsed_modules[0] != module:
                raise ApiError(f"{key} 只能绑定一个适配器模块")
            new_modules[key] = module

    old_keys = _adapter_env_manifest(raw)
    for key in old_keys:
        if key not in keys:
            updates[key] = None
    updates[_ADAPTER_ENV_KEYS_KEY] = _json_env(keys)
    updates[_ADAPTER_ENV_MODULES_KEY] = _json_env(new_modules)
    return updates


def _status(raw: dict[str, str]) -> dict:
    qq_bots = _load_json_list(raw, "QQ_BOTS")
    telegram_bots = _load_json_list(raw, "TELEGRAM_BOTS")
    discord_bots = _load_json_list(raw, "DISCORD_BOTS")
    qq = qq_bots[0] if qq_bots else {}
    telegram = telegram_bots[0] if telegram_bots else {}
    discord = discord_bots[0] if discord_bots else {}
    qq_intent = qq.get("intent") if isinstance(qq.get("intent"), dict) else {}
    discord_intent = discord.get("intent") if isinstance(discord.get("intent"), dict) else {}
    qq_intent = {**_QQ_INTENT_DEFAULTS, **qq_intent}
    discord_intent = {**_DISCORD_INTENT_DEFAULTS, **discord_intent}
    return {
        "onebot": {
            "host": raw.get("HOST", "0.0.0.0"),
            "port": raw.get("PORT", "8080"),
            "ws_urls": _parse_onebot_urls(raw.get("ONEBOT_WS_URLS", "")),
            "has_token": bool(raw.get("ONEBOT_ACCESS_TOKEN", "")),
        },
        "qq": {
            "app_id": str(qq.get("id", "")),
            "has_secret": bool(qq.get("secret", "")),
            "use_websocket": bool(qq.get("use_websocket", True)),
            "intent": {key: bool(qq_intent.get(key, default)) for key, default in _QQ_INTENT_DEFAULTS.items()},
            "additional_bots": max(0, len(qq_bots) - 1),
        },
        "telegram": {
            "has_token": bool(telegram.get("token", "")),
            "is_webhook": bool(telegram.get("is_webhook", False)),
            "api_server": str(telegram.get("api_server", "https://api.telegram.org/")),
            "has_proxy": bool(raw.get("TELEGRAM_PROXY", "")),
            "webhook_url": raw.get("TELEGRAM_WEBHOOK_URL", ""),
            "additional_bots": max(0, len(telegram_bots) - 1),
        },
        "discord": {
            "has_token": bool(discord.get("token", "")),
            "intent": {key: bool(discord_intent.get(key, default)) for key, default in _DISCORD_INTENT_DEFAULTS.items()},
            "has_proxy": bool(raw.get("DISCORD_PROXY", "")),
            "register_all_commands": bool(discord.get("application_commands")),
            "additional_bots": max(0, len(discord_bots) - 1),
        },
    }


def _parse_onebot_urls(value: str) -> list[str]:
    if not value.strip():
        return []
    try:
        parsed = json.loads(value)
    except ValueError:
        return []
    return parsed if isinstance(parsed, list) and all(isinstance(url, str) for url in parsed) else []


def _quote_env(value: str) -> str:
    """Quote a value so dotenv preserves JSON strings, spaces, #, and $ literally."""
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _write_adapter_values(updates: dict[str, str | None]) -> dict:
    """Atomically update adapter env keys without truncating legacy multiline values."""
    path: Path = envfile.env_file()
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    replacements = dict(updates)
    output: list[str] = []
    written: list[str] = []
    removed: list[str] = []
    for key in replacements:
        if not _ENV_KEY.fullmatch(key):
            raise ApiError(f"非法配置键名: {key}")
    for binding in parse_stream(StringIO(text)):
        key = binding.key
        if key in replacements:
            replacement = replacements[key]
            if replacement is None:
                if key not in removed:
                    removed.append(key)
                continue
            output.append(f"{key}={replacement}\n")
            if key not in written:
                written.append(key)
        else:
            output.append(binding.original.string)
    for key, value in replacements.items():
        if key not in written and value is not None:
            if output and not output[-1].endswith("\n"):
                output.append("\n")
            output.append(f"{key}={value}\n")
            written.append(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("".join(output), encoding="utf-8")
    tmp.replace(path)
    return {"written": written, "removed": removed}


def _json_env(value: object) -> str:
    return _quote_env(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def _first_bot(raw: dict[str, str], key: str) -> tuple[list[dict], dict]:
    bots = _load_json_list(raw, key)
    return bots, bots[0] if bots else {}


def _validated_intents(payload: dict, key: str, allowed: set[str]) -> dict[str, bool]:
    value = payload.get(key, {})
    if not isinstance(value, dict):
        raise ApiError(f"{key} 必须是对象")
    if set(value) - allowed:
        raise ApiError(f"{key} 包含不支持的权限项")
    if any(not isinstance(item, bool) for item in value.values()):
        raise ApiError(f"{key} 的权限值必须为布尔值")
    return value


def _module_updates(
    payload: dict, raw: dict[str, str]
) -> tuple[list[str], dict[str, str | None]]:
    raw_modules = payload.get("modules")
    if not isinstance(raw_modules, list) or any(not isinstance(module, str) for module in raw_modules):
        raise ApiError("modules 必须是适配器模块路径字符串列表")
    try:
        modules = parse_adapter_modules(",".join(module.strip() for module in raw_modules))
    except ValueError as exc:
        raise ApiError(str(exc)) from None
    updates: dict[str, str | None] = {
        "STELLA_ADAPTER_MODULES": ",".join(modules) if modules else "none"
    }
    if "driver" in payload:
        driver = _str_input(payload, "driver", max_length=512)
        if driver:
            updates["DRIVER"] = driver
    connections = payload.get("connections", {})
    if not isinstance(connections, dict):
        raise ApiError("connections 必须是对象")

    if "onebot" in connections:
        if "nonebot.adapters.onebot.v11" not in modules:
            raise ApiError("保存 OneBot 配置前，请先启用 OneBot V11 适配器")
        onebot_payload = connections["onebot"]
        if not isinstance(onebot_payload, dict):
            raise ApiError("onebot 配置必须是对象")
        updates.update(_onebot_updates(onebot_payload))

    if "qq" in connections:
        if "nonebot.adapters.qq" not in modules:
            raise ApiError("保存 QQ 官方配置前，请先启用 QQ 官方适配器")
        config = connections["qq"]
        if not isinstance(config, dict):
            raise ApiError("qq 配置必须是对象")
        bots, current = _first_bot(raw, "QQ_BOTS")
        app_id = _str_input(config, "app_id", max_length=128)
        secret = _str_input(config, "app_secret", max_length=512) or (
            str(current.get("secret", "")) if current.get("id") == app_id else ""
        )
        if not app_id or not secret:
            raise ApiError("QQ 官方机器人需要填写 App ID 和 App Secret")
        intents = {**_QQ_INTENT_DEFAULTS, **(current.get("intent", {}) if isinstance(current.get("intent"), dict) else {})}
        intents.update(_validated_intents(config, "intent", set(_QQ_INTENT_DEFAULTS)))
        bot = {**current, "id": app_id, "secret": secret, "intent": intents}
        if "use_websocket" in config:
            bot["use_websocket"] = _bool_input(config, "use_websocket", True)
        updates["QQ_BOTS"] = _json_env([bot, *bots[1:]])

    if "telegram" in connections:
        if "nonebot.adapters.telegram" not in modules:
            raise ApiError("保存 Telegram 配置前，请先启用 Telegram 适配器")
        config = connections["telegram"]
        if not isinstance(config, dict):
            raise ApiError("telegram 配置必须是对象")
        bots, current = _first_bot(raw, "TELEGRAM_BOTS")
        token = _str_input(config, "token", max_length=512) or str(current.get("token", ""))
        if not token:
            raise ApiError("Telegram 机器人需要填写 Bot Token")
        bot = {
            **current,
            "token": token,
            "api_server": _str_input(config, "api_server", max_length=2048) or str(current.get("api_server", "https://api.telegram.org/")),
            "is_webhook": _bool_input(config, "is_webhook", bool(current.get("is_webhook", False))),
        }
        updates["TELEGRAM_BOTS"] = _json_env([bot, *bots[1:]])
        if "webhook_url" in config:
            webhook = _str_input(config, "webhook_url", max_length=2048)
            if webhook and not webhook.startswith("https://"):
                raise ApiError("Telegram Webhook URL 必须以 https:// 开头")
            if webhook:
                updates["TELEGRAM_WEBHOOK_URL"] = webhook
        if "proxy" in config:
            proxy = _str_input(config, "proxy", max_length=2048)
            if proxy:
                updates["TELEGRAM_PROXY"] = proxy

    if "discord" in connections:
        if "nonebot.adapters.discord" not in modules:
            raise ApiError("保存 Discord 配置前，请先启用 Discord 适配器")
        config = connections["discord"]
        if not isinstance(config, dict):
            raise ApiError("discord 配置必须是对象")
        bots, current = _first_bot(raw, "DISCORD_BOTS")
        token = _str_input(config, "token", max_length=512) or str(current.get("token", ""))
        if not token:
            raise ApiError("Discord 机器人需要填写 Bot Token")
        existing_intent = current.get("intent") if isinstance(current.get("intent"), dict) else {}
        intents = {**existing_intent, **_validated_intents(config, "intent", _DISCORD_INTENTS)}
        bot = {**current, "token": token, "intent": intents}
        if _bool_input(config, "register_all_commands", bool(current.get("application_commands"))):
            bot["application_commands"] = {"*": ["*"]}
        else:
            bot.pop("application_commands", None)
        updates["DISCORD_BOTS"] = _json_env([bot, *bots[1:]])
        if "proxy" in config:
            proxy = _str_input(config, "proxy", max_length=2048)
            if proxy:
                updates["DISCORD_PROXY"] = proxy

    if "adapter_env" in payload:
        updates.update(_adapter_env_updates(payload, raw))

    return list(modules), updates


def _onebot_updates(payload: dict) -> dict[str, str]:
    updates: dict[str, str] = {}
    if "ws_urls" in payload:
        urls = payload["ws_urls"]
        if not isinstance(urls, list) or any(not isinstance(url, str) for url in urls):
            raise ApiError("ws_urls 必须是字符串列表")
        urls = [url.strip() for url in urls if url.strip()]
        for url in urls:
            if not url.startswith(("ws://", "wss://")):
                raise ApiError("正向 WS 地址必须以 ws:// 或 wss:// 开头")
        updates["ONEBOT_WS_URLS"] = json.dumps(urls, ensure_ascii=False)
    token = _str_input(payload, "access_token", max_length=512)
    if token:
        updates["ONEBOT_ACCESS_TOKEN"] = token
    if "host" in payload:
        host = _str_input(payload, "host", max_length=255)
        if host:
            updates["HOST"] = host
    if "port" in payload:
        try:
            port = int(payload["port"])
        except (TypeError, ValueError):
            raise ApiError("PORT 需要整数") from None
        if not (1 <= port <= 65535):
            raise ApiError("PORT 超出范围")
        updates["PORT"] = str(port)
    return updates


def onebot() -> dict:
    # HOST/PORT/ONEBOT_* 不在 settings._env 体系（NoneBot 直读环境变量），
    # 所以这里读 .env 原文而不是 settings 属性——那几个属性根本不存在。
    raw = _dotenv_values()
    return {
        "host": raw.get("HOST", "0.0.0.0"),
        "port": raw.get("PORT", "8080"),
        "ws_urls": _parse_onebot_urls(raw.get("ONEBOT_WS_URLS", "")),
        "has_token": bool(raw.get("ONEBOT_ACCESS_TOKEN", "")),
    }


def adapters() -> dict:
    """Read configured and running adapter module paths without reading secrets."""
    from config.settings import STELLA_ADAPTER_MODULES

    raw = _dotenv_values()
    configured = raw.get("STELLA_ADAPTER_MODULES")
    configured_modules = parse_adapter_modules(
        configured if "STELLA_ADAPTER_MODULES" in raw else None
    )
    try:
        effective_modules = parse_adapter_modules(STELLA_ADAPTER_MODULES)
    except ValueError:
        # An invalid process setting prevents Bot startup; keep the status endpoint
        # resilient so operators can still see and correct the saved .env value.
        effective_modules = ()
    installed_packages: dict[str, str | None] = {}
    for package in _ADAPTER_PACKAGES:
        try:
            installed_packages[package] = version(package)
        except PackageNotFoundError:
            installed_packages[package] = None
    adapter_env, adapter_env_process_overrides = _adapter_env_status(raw)
    unavailable = unavailable_adapter_reasons()
    catalog = [
        {
            **item,
            "available": item["module"] not in unavailable,
            **(
                {"unavailable_reason": unavailable[item["module"]]}
                if item["module"] in unavailable
                else {}
            ),
        }
        for item in _ADAPTER_CATALOG
    ]
    return {
        "modules": list(configured_modules or DEFAULT_ADAPTER_MODULES)
        if configured is None and "STELLA_ADAPTER_MODULES" not in raw
        else list(configured_modules),
        "effective_modules": list(effective_modules),
        "process_override": "STELLA_ADAPTER_MODULES" in os.environ,
        "driver": raw.get("DRIVER", ""),
        "driver_process_override": "DRIVER" in os.environ,
        "installed_packages": installed_packages,
        "catalog": catalog,
        "catalog_updated_at": _CATALOG_DATA.get("updated_at", ""),
        "catalog_source_url": _CATALOG_DATA.get("source_url", ""),
        "adapter_env": adapter_env,
        "adapter_env_process_overrides": adapter_env_process_overrides,
        "connections": _status(raw),
    }


def update_adapters(payload: dict) -> dict:
    """Persist enabled adapters and their secrets without importing adapter packages."""
    raw = _dotenv_values()
    modules, updates = _module_updates(payload, raw)
    current_modules = parse_adapter_modules(
        raw.get("STELLA_ADAPTER_MODULES")
        if "STELLA_ADAPTER_MODULES" in raw
        else None
    )
    unavailable_modules = set(unavailable_adapter_reasons())
    newly_blocked = (set(modules) & unavailable_modules) - set(current_modules)
    if newly_blocked:
        raise ApiError(
            "适配器已被屏蔽或当前 Python 版本不支持："
            f"{', '.join(sorted(newly_blocked))}"
        )
    report = _write_adapter_values(updates)
    return {**report, "modules": list(modules), "restart_required": True}


def update(payload: dict) -> dict:
    updates = _onebot_updates(payload)
    report = envfile.write_values(updates)
    return {**report, "restart_required": True}
