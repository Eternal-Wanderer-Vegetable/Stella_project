# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""管理员凭据与 JWT 的底层实现（方案 §9.2）。

存储：``STELLA_HOME/webui/auth.json``——单管理员模型，文件不存在即
「未初始化」，首次访问走 setup 向导。不进 .env：密码与密钥是敏感面，
混进环境变量会被 ``deploy config-schema`` 提取到 GUI 高级配置页，那是
泄密通道不是配置面。

密码哈希：hashlib.scrypt（标准库，零新依赖）。参数固化进序列化串，
将来调参不破坏旧记录。

JWT：pyjwt HS256，载荷 ``{sub, iat, exp}``。单管理员模型刻意不放权限
范围（scope 体系是后置项，见方案 §19）；jwt_secret 与凭据同文件存储，
「注销所有登录态」= 轮换 secret。

**本模块所有配置读取都在调用时进行**（``import config.settings`` 后取
属性，而不是 from-import 绑定值）：测试要靠 monkeypatch STELLA_HOME 把
凭据隔离进临时目录，import 期绑定会让隔离失效。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt

import config.settings as settings
from webui.responses import ApiError

# scrypt 参数（RFC 7914 推荐量级；n/r/p 与 dklen 全部写进序列化串）
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_DKLEN = 32

COOKIE_NAME = "stella_webui_jwt"


def auth_file() -> Path:
    """凭据文件路径。STELLA_HOME 在调用时读取（见模块 docstring）。"""
    return Path(settings.STELLA_HOME) / "webui" / "auth.json"


def setup_required() -> bool:
    return not auth_file().exists()


def load_record() -> dict | None:
    """读凭据记录；不存在或损坏返回 None（损坏按未初始化处理——宁要重新
    setup 的麻烦，不要一个永远登录不进去的死锁态）。"""
    path = auth_file()
    if not path.exists():
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    for key in ("username", "password", "jwt_secret"):
        if not isinstance(record.get(key), str) or not record[key]:
            return None
    return record


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P,
        dklen=_DKLEN,
    )
    return (
        f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}"
        f"${salt.hex()}${digest.hex()}"
    )


def _verify_password(password: str, serialized: str) -> bool:
    try:
        scheme, n, r, p, salt_hex, hash_hex = serialized.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    try:
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(bytes.fromhex(hash_hex)),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest, bytes.fromhex(hash_hex))


def _write_record(record: dict) -> None:
    path = auth_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    tmp.replace(path)


def setup_admin(username: str, password: str) -> dict:
    """创建管理员凭据；已初始化时 403（setup 端点只此一条路）。"""
    if load_record() is not None:
        raise ApiError("管理员已初始化，请直接登录", status_code=403)
    record = {
        "username": username,
        "password": _hash_password(password),
        "jwt_secret": secrets.token_hex(32),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_record(record)
    return record


def verify_credentials(username: str, password: str) -> bool:
    """恒定时间比较用户名与密码；未初始化一律失败（不存在用户枚举）。"""
    record = load_record()
    if record is None:
        return False
    user_ok = hmac.compare_digest(
        record["username"].encode("utf-8"), username.encode("utf-8")
    )
    pass_ok = _verify_password(password, record["password"])
    return user_ok and pass_ok


def update_credentials(
    record: dict,
    *,
    new_username: str | None = None,
    new_password: str | None = None,
) -> dict:
    """更新用户名/密码。改密码时轮换 jwt_secret——所有已签发 token 立即失效，
    这是「注销所有登录态」的唯一真实现（JWT 无状态，没有黑名单可拉）。"""
    if new_username:
        record["username"] = new_username
    if new_password:
        record["password"] = _hash_password(new_password)
        record["jwt_secret"] = secrets.token_hex(32)
    _write_record(record)
    return record


def token_ttl_hours() -> int:
    return int(settings.WEBUI_TOKEN_TTL_HOURS)


def create_token(record: dict, *, ttl_hours: int | None = None) -> tuple[str, str]:
    """签发 JWT。返回 ``(token, expires_at_iso)``。"""
    hours = ttl_hours if ttl_hours is not None else token_ttl_hours()
    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=hours)
    payload = {"sub": record["username"], "iat": int(now.timestamp()),
               "exp": int(expires.timestamp())}
    token = jwt.encode(payload, record["jwt_secret"], algorithm="HS256")
    return token, expires.isoformat()


def decode_token(token: str) -> str:
    """校验并返回用户名。任何失败统一 401（理由写进 message 供前端提示，
    但不区分「过期」与「伪造」的响应码——对攻击者二者等价）。"""
    record = load_record()
    secret = record["jwt_secret"] if record else _ephemeral_secret()
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError as exc:
        raise ApiError("登录已过期，请重新登录", status_code=401) from exc
    except jwt.InvalidTokenError as exc:
        raise ApiError("登录凭证无效", status_code=401) from exc
    username = payload.get("sub")
    if not isinstance(username, str) or not username:
        raise ApiError("登录凭证无效", status_code=401)
    return username


# 凭据未初始化时的兜底 secret：此时不存在合法 token，随便一个进程内随机值
# 都能让 decode 稳定地失败（而不是抛 KeyError）。进程重启即换，无持久意义。
_EPHEMERAL_SECRET: str | None = None


def _ephemeral_secret() -> str:
    global _EPHEMERAL_SECRET
    if _EPHEMERAL_SECRET is None:
        _EPHEMERAL_SECRET = secrets.token_hex(32)
    return _EPHEMERAL_SECRET


def desktop_session_secret() -> str | None:
    """桌面壳注入的免登录 secret（方案 §4 D5 / §9.3）。

    壳启动 Bot 子进程时经环境变量注入（≥32 字符随机值），只在调用时读
    os.environ——它不是 settings 常量（不该进 .env，也不该被 config-schema
    提取到配置页），是进程级的临时信任通道。
    """
    secret = os.environ.get("STELLA_DESKTOP_SESSION_SECRET", "").strip()
    if len(secret) < 32:
        return None
    return secret
