import bcrypt
import jwt
import uuid
import base64
import hashlib
from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet

from config import settings

# 直接用 bcrypt 库（而非 passlib），规避 passlib 与 bcrypt>=4.1 的兼容 bug
# （passlib 在加载 bcrypt 后端探测时会用超长 secret 触发
# "password cannot be longer than 72 bytes"）。bcrypt 本身只取前 72 字节。


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8")[:72], bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8")[:72], hashed.encode("utf-8"))
    except Exception:
        return False


def _encode(payload: dict, ttl: timedelta, typ: str) -> str:
    """公共编码：写入 iat/exp/typ，typ 用于区分 access / refresh。"""
    now = datetime.now(timezone.utc)
    payload.update({
        "iat": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
        "typ": typ,                                   # "access" / "refresh" 类型标记
        "jti": uuid.uuid4().hex,                      # 唯一标识，用于注销时吊销（黑名单）
    })
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: str, username: str) -> str:
    return _encode(
        {"sub": user_id, "username": username},       # 用户唯一 ID（记忆/会话隔离的关键）
        timedelta(minutes=settings.access_token_expire_minutes),
        "access",
    )


def create_refresh_token(user_id: str, username: str) -> str:
    return _encode(
        {"sub": user_id, "username": username},
        timedelta(hours=settings.refresh_token_expire_hours),
        "refresh",
    )


def decode_token(token: str, expected_typ: str):
    """通用解码：校验签名、过期、typ 类型；失败返回 None。"""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except Exception:
        return None
    if payload.get("typ") != expected_typ:
        return None
    return payload


def decode_access_token(token: str):
    return decode_token(token, "access")


def decode_refresh_token(token: str):
    return decode_token(token, "refresh")


# ==================== Fernet 对称加密（用于按用户存储邮箱授权码等敏感凭证）====================
# 密钥派生自 JWT_SECRET（SHA256 → 32 字节 → URL-safe base64），部署后不变；
# 同一 JWT_SECRET 可解出相同 Fernet 密钥，无需额外存储。
_FERNET: Fernet | None = None


def _get_fernet() -> Fernet:
    global _FERNET
    if _FERNET is None:
        key_bytes = hashlib.sha256(settings.jwt_secret.encode()).digest()
        _FERNET = Fernet(base64.urlsafe_b64encode(key_bytes))
    return _FERNET


def encrypt_credential(plain: str) -> str:
    """Fernet 加密敏感凭证，返回 base64 字符串可安全存入数据库。"""
    return _get_fernet().encrypt(plain.encode()).decode()


def decrypt_credential(enc: str) -> str:
    """Fernet 解密数据库中的加密凭证。"""
    return _get_fernet().decrypt(enc.encode()).decode()
