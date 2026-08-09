from __future__ import annotations

import hashlib
import logging
import re
import secrets
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.models.entities import AdminCredential, AuthSession, LoginAttempt

SESSION_COOKIE = "aja_session"
CSRF_HEADER = "X-CSRF-Token"
_hasher = PasswordHasher()


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def initialize_admin(db: Session, settings: Settings) -> None:
    if db.get(AdminCredential, 1) is not None:
        return
    if settings.app_env == "production" and settings.admin_password == "change-me":
        raise RuntimeError("生产环境必须配置非默认 ADMIN_PASSWORD")
    db.add(AdminCredential(id=1, password_hash=_hasher.hash(settings.admin_password)))
    db.commit()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def too_many_attempts(db: Session, ip: str, username: str, settings: Settings) -> bool:
    cutoff = datetime.now(UTC) - timedelta(seconds=settings.login_window_seconds)
    count = db.scalar(
        select(func.count(LoginAttempt.id)).where(
            LoginAttempt.ip_hash == digest(ip),
            LoginAttempt.username == username,
            LoginAttempt.success.is_(False),
            LoginAttempt.attempted_at >= cutoff,
        )
    )
    return bool(count and count >= settings.login_attempts)


def record_attempt(db: Session, ip: str, username: str, success: bool) -> None:
    db.add(LoginAttempt(ip_hash=digest(ip), username=username, success=success))
    db.commit()


def create_session(db: Session, settings: Settings) -> tuple[str, str, AuthSession]:
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    session = AuthSession(
        token_hash=digest(token),
        csrf_hash=digest(csrf),
        expires_at=datetime.now(UTC) + timedelta(hours=settings.session_hours),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return token, csrf, session


def set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_hours * 3600,
        httponly=True,
        secure=settings.secure_cookie,
        samesite="strict",
        path="/",
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        SESSION_COOKIE,
        httponly=True,
        secure=settings.secure_cookie,
        samesite="strict",
        path="/",
    )


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def get_current_session(
    request: Request,
    db: Session = Depends(get_db),
) -> AuthSession:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="本地会话尚未初始化，请刷新页面")
    session = db.scalar(select(AuthSession).where(AuthSession.token_hash == digest(token)))
    if session is None or _as_utc(session.expires_at) <= datetime.now(UTC):
        if session is not None:
            db.delete(session)
            db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="本地会话已过期，请刷新页面")
    return session


def require_csrf(
    request: Request,
    session: AuthSession = Depends(get_current_session),
) -> AuthSession:
    csrf = request.headers.get(CSRF_HEADER)
    if not csrf or not secrets.compare_digest(session.csrf_hash, digest(csrf)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF 校验失败，请刷新页面后重试")
    return session


def purge_expired_sessions(db: Session) -> None:
    db.execute(delete(AuthSession).where(AuthSession.expires_at <= datetime.now(UTC)))
    db.commit()


class SensitiveDataFilter(logging.Filter):
    _patterns = (
        re.compile(r"(?i)(password|api[_-]?key|cookie|authorization|webhook)(\s*[:=]\s*)\S+"),
        re.compile(r"\b1[3-9]\d{9}\b"),
        re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"),
        re.compile(r"https://open\.feishu\.cn/open-apis/bot/v2/hook/[\w-]+"),
    )

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        for pattern in self._patterns:
            message = pattern.sub("[REDACTED]", message)
        record.msg = message
        record.args = ()
        return True


def configure_logging() -> None:
    root = logging.getLogger()
    if not any(isinstance(item, SensitiveDataFilter) for item in root.filters):
        root.addFilter(SensitiveDataFilter())
    for handler in root.handlers:
        if not any(isinstance(item, SensitiveDataFilter) for item in handler.filters):
            handler.addFilter(SensitiveDataFilter())
