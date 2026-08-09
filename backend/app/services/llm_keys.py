from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.entities import AppSetting

KEYRING_SETTING = "llm_api_keys"
ACTIVE_KEY_SETTING = "llm_active_key_id"
LEGACY_KEY_ID = "legacy"
ENVIRONMENT_KEY_ID = "environment"


def _legacy_key(db: Session) -> str | None:
    item = db.get(AppSetting, "llm_api_key")
    return str(item.value) if item is not None and item.value else None


def _keyring(db: Session, *, include_legacy: bool = True) -> list[dict[str, str]]:
    item = db.get(AppSetting, KEYRING_SETTING)
    records = [dict(record) for record in (item.value or [])] if item is not None and isinstance(item.value, list) else []
    legacy = _legacy_key(db)
    if include_legacy and legacy and not any(record.get("id") == LEGACY_KEY_ID for record in records):
        records.insert(0, {
            "id": LEGACY_KEY_ID,
            "label": "默认 Key",
            "api_key": legacy,
            "created_at": item.updated_at.isoformat() if item is not None else "",
        })
    return records


def _save_keyring(db: Session, records: list[dict[str, str]]) -> None:
    item = db.get(AppSetting, KEYRING_SETTING) or AppSetting(key=KEYRING_SETTING)
    item.value = records
    item.secret = True
    db.add(item)


def _set_active(db: Session, key_id: str | None) -> None:
    item = db.get(AppSetting, ACTIVE_KEY_SETTING) or AppSetting(key=ACTIVE_KEY_SETTING)
    item.value = key_id
    item.secret = False
    db.add(item)


def _active_id(db: Session, environment_key: str | None) -> str | None:
    item = db.get(AppSetting, ACTIVE_KEY_SETTING)
    requested = str(item.value) if item is not None and item.value else None
    local_ids = {record["id"] for record in _keyring(db) if record.get("id")}
    if requested in local_ids:
        return requested
    if requested == ENVIRONMENT_KEY_ID and environment_key:
        return requested
    if local_ids:
        return next(record["id"] for record in _keyring(db) if record.get("id"))
    return ENVIRONMENT_KEY_ID if environment_key else None


def resolve_llm_api_key(db: Session, environment_key: str | None) -> str | None:
    active_id = _active_id(db, environment_key)
    if active_id == ENVIRONMENT_KEY_ID:
        return environment_key
    return next((record["api_key"] for record in _keyring(db) if record.get("id") == active_id), None)


def _masked(value: str) -> str:
    if len(value) <= 6:
        return f"••••{value[-2:]}"
    return f"{value[:3]}••••{value[-4:]}"


def llm_key_options(db: Session, environment_key: str | None) -> tuple[list[dict], str | None]:
    active_id = _active_id(db, environment_key)
    options = [
        {
            "id": record["id"],
            "label": record.get("label") or "API Key",
            "masked": _masked(record["api_key"]),
            "source": "local",
            "active": record["id"] == active_id,
            "created_at": record.get("created_at") or None,
        }
        for record in _keyring(db)
    ]
    if environment_key:
        options.append({
            "id": ENVIRONMENT_KEY_ID,
            "label": "环境变量 Key",
            "masked": _masked(environment_key),
            "source": "environment",
            "active": active_id == ENVIRONMENT_KEY_ID,
            "created_at": None,
        })
    return options, active_id


def add_llm_api_key(db: Session, label: str, api_key: str, environment_key: str | None = None) -> str:
    previous_active_id = _active_id(db, environment_key)
    records = _keyring(db)
    existing = next((record for record in records if record.get("api_key") == api_key), None)
    if existing is not None:
        existing["label"] = label
        key_id = existing["id"]
    else:
        key_id = uuid4().hex
        records.append({
            "id": key_id,
            "label": label,
            "api_key": api_key,
            "created_at": datetime.now(UTC).isoformat(),
        })
    _save_keyring(db, records)
    _set_active(db, previous_active_id or key_id)
    db.commit()
    return key_id


def activate_llm_api_key(db: Session, key_id: str, environment_key: str | None) -> None:
    local_ids = {record["id"] for record in _keyring(db)}
    if key_id not in local_ids and not (key_id == ENVIRONMENT_KEY_ID and environment_key):
        raise ValueError("API Key 不存在")
    _set_active(db, key_id)
    db.commit()


def delete_llm_api_key(db: Session, key_id: str, environment_key: str | None) -> None:
    if key_id == ENVIRONMENT_KEY_ID:
        raise ValueError("环境变量 Key 需在 .env 中删除")
    records = _keyring(db)
    if not any(record["id"] == key_id for record in records):
        raise ValueError("API Key 不存在")
    records = [record for record in records if record["id"] != key_id]
    _save_keyring(db, records)
    if key_id == LEGACY_KEY_ID:
        legacy = db.get(AppSetting, "llm_api_key")
        if legacy is not None:
            legacy.value = None
            legacy.secret = True
            db.add(legacy)
    current = _active_id(db, environment_key)
    if current == key_id:
        _set_active(db, records[0]["id"] if records else ENVIRONMENT_KEY_ID if environment_key else None)
    db.commit()
