import re
from pydantic import BaseModel, Field, field_validator

# 账号 = 邮箱 或 手机号（二选一，作为唯一登录 ID）
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_RE = re.compile(r"^\+?\d{6,20}$")


def is_email(val: str) -> bool:
    return bool(_EMAIL_RE.match(val or ""))


def is_phone(val: str) -> bool:
    return bool(_PHONE_RE.match(val or ""))


def normalize_account(raw: str) -> str:
    """注册/登录统一规整：去空格；邮箱转小写（手机号保持不变），保证同一邮箱只注册一次。"""
    s = (raw or "").strip()
    if is_email(s):
        return s.lower()
    return s


class RegisterRequest(BaseModel):
    username: str                                     # 邮箱或手机号（二选一，作为唯一登录 ID）
    password: str = Field(min_length=6, max_length=64)
    nickname: str | None = None                       # 昵称可重复、可空

    @field_validator("username")
    @classmethod
    def _validate_account(cls, v):
        v = v.strip()
        if not (is_email(v) or is_phone(v)):
            raise ValueError("请输入有效的邮箱或手机号")
        return v


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user_id: str
    username: str


class RefreshRequest(BaseModel):
    refresh_token: str                               # 用 refresh 换发新 access


class LogoutRequest(BaseModel):
    refresh_token: str | None = None                 # 注销：吊销该 refresh（及当前 access）


class ChatRequest(BaseModel):
    message: str = Field(max_length=8000)            # 上限防撑爆上下文/计费（约 4k token）
    conversation_id: str | None = None              # 不传则自动新建会话
    client_msg_id: str | None = None                # 前端生成的稳定消息 ID，用于版本/编辑跟踪
    mode: str = "send"                              # send / regenerate


class ChatResponse(BaseModel):
    conversation_id: str
    reply: str
    tool_calls: list[dict] = []
