from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models.entities import AppSetting
from app.services.llm_keys import (
    ENVIRONMENT_KEY_ID,
    activate_llm_api_key,
    add_llm_api_key,
    delete_llm_api_key,
    llm_key_options,
    resolve_llm_api_key,
)


def test_legacy_key_is_masked_and_can_coexist_with_new_switchable_key() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(AppSetting(key="llm_api_key", value="sk-legacy-1234", secret=True))
        db.commit()

        new_id = add_llm_api_key(db, "DeepSeek 备用", "sk-new-key-5678")
        options, active_id = llm_key_options(db, "sk-env-key-9999")

        assert active_id == "legacy"
        assert {item["label"] for item in options} == {"默认 Key", "DeepSeek 备用", "环境变量 Key"}
        assert all("legacy" not in item["masked"] and "new-key" not in item["masked"] for item in options)
        assert resolve_llm_api_key(db, "sk-env-key-9999") == "sk-legacy-1234"

        activate_llm_api_key(db, ENVIRONMENT_KEY_ID, "sk-env-key-9999")
        assert resolve_llm_api_key(db, "sk-env-key-9999") == "sk-env-key-9999"


def test_deleting_active_key_falls_back_without_exposing_secret() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        first = add_llm_api_key(db, "主 Key", "sk-primary-1111")
        second = add_llm_api_key(db, "备用 Key", "sk-backup-2222")
        delete_llm_api_key(db, second, None)

        assert resolve_llm_api_key(db, None) == "sk-primary-1111"
        options, active_id = llm_key_options(db, None)
        assert active_id == first
        assert options == [{
            "id": first, "label": "主 Key", "masked": "sk-••••2222".replace("2222", "1111"),
            "source": "local", "active": True, "created_at": options[0]["created_at"],
        }]


def test_saving_local_key_does_not_replace_selected_environment_key() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        add_llm_api_key(db, "本地 Key", "sk-local-1111", "sk-environment-9999")

        options, active_id = llm_key_options(db, "sk-environment-9999")
        assert active_id == ENVIRONMENT_KEY_ID
        assert resolve_llm_api_key(db, "sk-environment-9999") == "sk-environment-9999"
        assert next(item for item in options if item["label"] == "本地 Key")["active"] is False
