from pathlib import Path
from typing import Literal

import pytest
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.database import Base
from app.models.entities import AppSetting
from app.services import llm
from app.services.llm import (
    _call_api,
    _strict_json_schema,
    codex_command_args,
    configured_provider,
    llm_available,
    resolved_llm_settings,
    selected_provider,
)


class FixtureOutput(BaseModel):
    status: Literal["ok"]


def test_api_configuration_wins_in_auto_mode_and_preference_can_override(tmp_path: Path) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    settings = Settings(
        data_dir=tmp_path,
        model_cache_dir=tmp_path / "models",
        llm_provider="auto",
        llm_base_url="https://llm.example.invalid/v1",
        llm_api_key="fictional-key",
        llm_model="fictional-model",
    )
    with Session(engine) as db:
        assert selected_provider(settings, db) == "api"
        db.add(AppSetting(key="llm_provider", value="codex", secret=False))
        db.commit()
        assert configured_provider(settings, db) == "codex"
        assert selected_provider(settings, db) == "codex"


def test_local_api_configuration_overrides_environment_and_enables_api(tmp_path: Path) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    settings = Settings(data_dir=tmp_path, model_cache_dir=tmp_path / "models", llm_provider="auto")
    values = {
        "llm_base_url": "https://local-config.example.invalid/v1",
        "llm_api_key": "fictional-local-key",
        "llm_model": "local-config-model",
        "llm_input_price_rmb_per_million": 1.5,
        "llm_output_price_rmb_per_million": 6,
        "llm_monthly_budget_rmb": 80,
    }
    with Session(engine) as db:
        for key, value in values.items():
            db.add(AppSetting(key=key, value=value, secret=key == "llm_api_key"))
        db.commit()
        resolved = resolved_llm_settings(settings, db)
        assert resolved.llm_api_key == "fictional-local-key"
        assert resolved.llm_monthly_budget_rmb == 80
        assert selected_provider(settings, db) == "api"
        assert llm_available(settings, db) == (True, "")


def test_codex_command_is_ephemeral_schema_constrained_and_has_no_tools(tmp_path: Path) -> None:
    args = codex_command_args(
        Settings(data_dir=tmp_path, model_cache_dir=tmp_path / "models"),
        tmp_path,
        tmp_path / "schema.json",
        tmp_path / "output.json",
    )
    joined = " ".join(args)
    assert "--ephemeral" in args
    assert "--sandbox read-only" in joined
    assert "--output-schema" in args
    assert "features.shell_tool=false" in args
    assert "features.apps=false" in args
    assert "web_search=\"disabled\"" in args
    assert "dangerously-bypass" not in joined


def test_codex_schema_disallows_extra_properties_recursively() -> None:
    schema = _strict_json_schema(
        {"type": "object", "properties": {"nested": {"type": "object", "properties": {"value": {"type": "string"}}}}}
    )
    assert schema["additionalProperties"] is False
    assert schema["properties"]["nested"]["additionalProperties"] is False


@pytest.mark.asyncio
async def test_api_provider_validates_json_and_calculates_configured_cost(monkeypatch, tmp_path: Path) -> None:
    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "choices": [{"message": {"content": '{"status":"ok"}'}}],
                "usage": {"prompt_tokens": 1_000_000, "completion_tokens": 500_000},
            }

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args) -> None:
            return None

        async def post(self, url, *, headers, json):
            assert url == "https://llm.example.invalid/v1/chat/completions"
            assert headers["Authorization"] == "Bearer fictional-key"
            assert json["response_format"] == {"type": "json_object"}
            return Response()

    monkeypatch.setattr(llm.httpx, "AsyncClient", lambda **_kwargs: Client())
    result = await _call_api(
        Settings(
            data_dir=tmp_path,
            model_cache_dir=tmp_path / "models",
            llm_provider="api",
            llm_base_url="https://llm.example.invalid/v1",
            llm_api_key="fictional-key",
            llm_model="fictional-model",
            llm_input_price_rmb_per_million=2,
            llm_output_price_rmb_per_million=4,
        ),
        [{"role": "user", "content": "虚构输入"}],
        FixtureOutput,
    )
    assert result.value.status == "ok"
    assert result.provider == "api" and result.model_name == "fictional-model"
    assert result.estimated_cost_rmb == 4


@pytest.mark.asyncio
async def test_deepseek_v4_uses_fast_non_thinking_mode(monkeypatch, tmp_path: Path) -> None:
    captured: dict = {}

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"choices": [{"message": {"content": '{"status":"ok"}'}}], "usage": {}}

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args) -> None:
            return None

        async def post(self, _url, *, headers, json):
            captured.update(json)
            return Response()

    monkeypatch.setattr(llm.httpx, "AsyncClient", lambda **_kwargs: Client())
    await _call_api(
        Settings(
            data_dir=tmp_path, model_cache_dir=tmp_path / "models", llm_provider="api",
            llm_base_url="https://api.deepseek.com", llm_api_key="fictional-key",
            llm_model="deepseek-v4-flash", llm_input_price_rmb_per_million=1,
            llm_output_price_rmb_per_million=2,
        ),
        [{"role": "user", "content": "虚构输入"}], FixtureOutput,
    )

    assert captured["thinking"] == {"type": "disabled"}
    assert captured["max_tokens"] == 4096
