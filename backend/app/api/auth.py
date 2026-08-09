from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.security import (
    clear_session_cookie,
    create_session,
    digest,
    get_current_session,
    record_attempt,
    require_csrf,
    set_session_cookie,
    too_many_attempts,
    verify_password,
)
from app.models.entities import AdminCredential, AuthSession
from app.schemas.auth import AuthResponse, LoginRequest

router = APIRouter(prefix="/api/auth", tags=["认证"])


@router.post("/local-session", response_model=AuthResponse)
def local_session(
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AuthResponse:
    """Create the private local session used by the passwordless web app."""
    token, csrf, _ = create_session(db, settings)
    set_session_cookie(response, token, settings)
    return AuthResponse(authenticated=True, csrf_token=csrf)


@router.post("/login", response_model=AuthResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AuthResponse:
    client_ip = request.client.host if request.client else "unknown"
    if too_many_attempts(db, client_ip, payload.username, settings):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="登录尝试过多，请稍后重试")
    credential = db.get(AdminCredential, 1)
    valid = bool(
        payload.username == "admin"
        and credential
        and verify_password(payload.password, credential.password_hash)
    )
    record_attempt(db, client_ip, payload.username, valid)
    if not valid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    token, csrf, _ = create_session(db, settings)
    set_session_cookie(response, token, settings)
    return AuthResponse(authenticated=True, csrf_token=csrf)


@router.post("/logout", response_model=AuthResponse)
def logout(
    request: Request,
    response: Response,
    _: AuthSession = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AuthResponse:
    token = request.cookies.get("aja_session")
    if token:
        db.execute(delete(AuthSession).where(AuthSession.token_hash == digest(token)))
        db.commit()
    clear_session_cookie(response, settings)
    return AuthResponse(authenticated=False)


@router.get("/me", response_model=AuthResponse)
def me(_: AuthSession = Depends(get_current_session)) -> AuthResponse:
    return AuthResponse(authenticated=True)
