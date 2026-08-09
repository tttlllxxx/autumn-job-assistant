from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from urllib.parse import urlparse


# Provider price pages publish USD prices. Keep the conversion visible and
# editable in one place; these values are estimates, not billing statements.
USD_TO_RMB_REFERENCE_RATE = Decimal("7.20")


@dataclass(frozen=True)
class PricingSuggestion:
    provider: str
    model: str
    input_price_rmb_per_million: float
    output_price_rmb_per_million: float
    pricing_basis: str
    source_url: str
    verified_on: str
    usd_to_rmb_rate: float

    def as_response(self) -> dict:
        return {"matched": True, **asdict(self)}


@dataclass(frozen=True)
class _USDPrice:
    input_per_million: Decimal
    output_per_million: Decimal
    basis: str


_DEEPSEEK_PRICES = {
    "deepseek-v4-flash": _USDPrice(Decimal("0.14"), Decimal("0.28"), "官方标准价；输入按缓存未命中价保守估算"),
    "deepseek-v4-pro": _USDPrice(Decimal("0.435"), Decimal("0.87"), "官方标准价；输入按缓存未命中价保守估算"),
}

_OPENAI_PRICES = {
    "gpt-5-mini": _USDPrice(Decimal("0.25"), Decimal("2.00"), "官方标准文本 token 价；输入按非缓存价估算"),
}


def _rmb(usd_price: Decimal) -> float:
    return float(usd_price * USD_TO_RMB_REFERENCE_RATE)


def _catalog_model(model: str, catalog: dict[str, _USDPrice]) -> str | None:
    normalized = model.strip().lower()
    if normalized in catalog:
        return normalized
    for alias in catalog:
        if normalized.startswith(f"{alias}-"):
            return alias
    return None


def suggest_llm_pricing(base_url: str, model: str) -> PricingSuggestion | None:
    """Return an auditable price estimate for known official API hosts only."""
    host = (urlparse(base_url.strip()).hostname or "").lower()
    if host == "api.deepseek.com":
        catalog_model = _catalog_model(model, _DEEPSEEK_PRICES)
        if catalog_model is None:
            return None
        price = _DEEPSEEK_PRICES[catalog_model]
        return PricingSuggestion(
            provider="DeepSeek",
            model=catalog_model,
            input_price_rmb_per_million=_rmb(price.input_per_million),
            output_price_rmb_per_million=_rmb(price.output_per_million),
            pricing_basis=price.basis,
            source_url="https://api-docs.deepseek.com/quick_start/pricing",
            verified_on="2026-08-09",
            usd_to_rmb_rate=float(USD_TO_RMB_REFERENCE_RATE),
        )
    if host == "api.openai.com":
        catalog_model = _catalog_model(model, _OPENAI_PRICES)
        if catalog_model is None:
            return None
        price = _OPENAI_PRICES[catalog_model]
        return PricingSuggestion(
            provider="OpenAI",
            model=catalog_model,
            input_price_rmb_per_million=_rmb(price.input_per_million),
            output_price_rmb_per_million=_rmb(price.output_per_million),
            pricing_basis=price.basis,
            source_url=f"https://developers.openai.com/api/docs/models/{catalog_model}",
            verified_on="2026-08-09",
            usd_to_rmb_rate=float(USD_TO_RMB_REFERENCE_RATE),
        )
    return None
