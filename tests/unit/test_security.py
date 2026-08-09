import logging

from fastapi import Response
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.database import Base
from app.core.security import (
    SensitiveDataFilter,
    create_session,
    digest,
    initialize_admin,
    record_attempt,
    set_session_cookie,
    too_many_attempts,
    verify_password,
)
from app.models.entities import AdminCredential, AuthSession


def test_admin_password_is_argon2_hashed_and_environment_does_not_overwrite_it(tmp_path) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        first = Settings(data_dir=tmp_path, model_cache_dir=tmp_path / "models", admin_password="fictional-first")
        initialize_admin(db, first)
        stored = db.get(AdminCredential, 1).password_hash

        second = Settings(data_dir=tmp_path, model_cache_dir=tmp_path / "models", admin_password="fictional-second")
        initialize_admin(db, second)

        assert stored.startswith("$argon2")
        assert db.get(AdminCredential, 1).password_hash == stored
        assert verify_password("fictional-first", stored) is True
        assert verify_password("fictional-second", stored) is False


def test_session_and_csrf_secrets_are_only_stored_as_hashes(tmp_path) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    settings = Settings(data_dir=tmp_path, model_cache_dir=tmp_path / "models")
    with Session(engine) as db:
        token, csrf, session = create_session(db, settings)
        persisted = db.scalar(select(AuthSession).where(AuthSession.id == session.id))

        assert persisted.token_hash == digest(token) and persisted.token_hash != token
        assert persisted.csrf_hash == digest(csrf) and persisted.csrf_hash != csrf


def test_login_rate_limit_is_scoped_to_ip_and_username(tmp_path) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    settings = Settings(
        data_dir=tmp_path,
        model_cache_dir=tmp_path / "models",
        login_attempts=2,
        login_window_seconds=300,
    )
    with Session(engine) as db:
        record_attempt(db, "192.0.2.1", "admin", False)
        assert too_many_attempts(db, "192.0.2.1", "admin", settings) is False
        record_attempt(db, "192.0.2.1", "admin", False)

        assert too_many_attempts(db, "192.0.2.1", "admin", settings) is True
        assert too_many_attempts(db, "192.0.2.2", "admin", settings) is False
        assert too_many_attempts(db, "192.0.2.1", "different", settings) is False


def test_session_cookie_is_http_only_strict_and_secure_in_production(tmp_path) -> None:
    response = Response()
    settings = Settings(data_dir=tmp_path, model_cache_dir=tmp_path / "models", app_env="production")
    set_session_cookie(response, "fictional-token", settings)
    header = response.headers["set-cookie"].lower()

    assert "httponly" in header
    assert "samesite=strict" in header
    assert "secure" in header


def test_sensitive_log_filter_redacts_all_required_secret_classes() -> None:
    record = logging.LogRecord(
        "test",
        logging.INFO,
        __file__,
        1,
        "password=fictional-pass cookie=session-value api_key=fictional-key "
        "https://open.feishu.cn/open-apis/bot/v2/hook/fictional-hook "
        "13900000000 fictional@example.com",
        (),
        None,
    )

    assert SensitiveDataFilter().filter(record) is True
    message = record.getMessage()
    for secret in (
        "fictional-pass",
        "session-value",
        "fictional-key",
        "fictional-hook",
        "13900000000",
        "fictional@example.com",
    ):
        assert secret not in message
