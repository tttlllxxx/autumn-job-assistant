from types import SimpleNamespace

import pytest

from app.services import daily


class FakeSession:
    def __init__(self, profile) -> None:
        self.profile = profile

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def get(self, _model, _key):
        return self.profile


@pytest.mark.asyncio
async def test_daily_pipeline_collects_then_recommends_and_notifies(monkeypatch, tmp_path) -> None:
    calls: list[str] = []

    async def collect(**kwargs) -> None:
        assert kwargs == {"allow_browser": True}
        calls.append("collect")

    async def recommend(_db, _settings) -> None:
        calls.append("recommend")

    async def notify(_db, _settings) -> None:
        calls.append("notify")

    monkeypatch.setattr(daily, "run_all_sources", collect)
    monkeypatch.setattr(daily, "recompute_recommendations", recommend)
    monkeypatch.setattr(daily, "notify_eligible", notify)
    monkeypatch.setattr(daily, "SessionLocal", lambda: FakeSession(SimpleNamespace(confirmed=True)))
    monkeypatch.setattr(
        daily,
        "get_settings",
        lambda: SimpleNamespace(data_dir=tmp_path, model_cache_dir=tmp_path / "models"),
    )

    await daily.run_daily_pipeline()

    assert calls == ["collect", "recommend", "notify"]


@pytest.mark.asyncio
async def test_daily_pipeline_skips_ranking_until_profile_confirmed(monkeypatch) -> None:
    calls: list[str] = []

    async def collect(**_kwargs) -> None:
        calls.append("collect")

    async def must_not_run(*_args) -> None:
        raise AssertionError("未确认画像时不应运行")

    monkeypatch.setattr(daily, "run_all_sources", collect)
    monkeypatch.setattr(daily, "recompute_recommendations", must_not_run)
    monkeypatch.setattr(daily, "notify_eligible", must_not_run)
    monkeypatch.setattr(daily, "SessionLocal", lambda: FakeSession(None))

    await daily.run_daily_pipeline()

    assert calls == ["collect"]
