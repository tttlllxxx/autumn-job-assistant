from app.services.llm_pricing import suggest_llm_pricing


def test_deepseek_v4_flash_uses_cache_miss_price_as_conservative_estimate() -> None:
    suggestion = suggest_llm_pricing("https://api.deepseek.com/v1", "deepseek-v4-flash")

    assert suggestion is not None
    assert suggestion.provider == "DeepSeek"
    assert suggestion.input_price_rmb_per_million == 1.008
    assert suggestion.output_price_rmb_per_million == 2.016
    assert "缓存未命中" in suggestion.pricing_basis


def test_pricing_catalog_does_not_guess_for_proxy_or_unknown_model() -> None:
    assert suggest_llm_pricing("https://proxy.example.invalid/v1", "deepseek-v4-flash") is None
    assert suggest_llm_pricing("https://api.deepseek.com", "unknown-model") is None


def test_openai_snapshot_uses_canonical_model_price() -> None:
    suggestion = suggest_llm_pricing("https://api.openai.com/v1", "gpt-5-mini-2025-08-07")

    assert suggestion is not None
    assert suggestion.model == "gpt-5-mini"
    assert suggestion.input_price_rmb_per_million == 1.8
    assert suggestion.output_price_rmb_per_million == 14.4
