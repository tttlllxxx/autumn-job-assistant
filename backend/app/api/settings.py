from datetime import UTC, datetime
from typing import Literal
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.security import get_current_session, require_csrf
from app.models.entities import AppSetting, AuthSession, CostLedger
from app.services.feishu import send_webhook
from app.services.llm import configured_provider, llm_available, resolved_llm_settings, selected_provider

router = APIRouter(prefix="/api/settings", tags=["设置"])


class PreferenceUpdate(BaseModel):
    degraded_summary_enabled: bool | None = None
    llm_provider: Literal["auto", "api", "codex", "disabled"] | None = None


class LLMConfigUpdate(BaseModel):
    llm_base_url: str | None = Field(default=None, max_length=2000)
    llm_api_key: str | None = Field(default=None, max_length=10000)
    llm_model: str | None = Field(default=None, max_length=255)
    llm_input_price_rmb_per_million: float | None = Field(default=None, ge=0)
    llm_output_price_rmb_per_million: float | None = Field(default=None, ge=0)
    llm_monthly_budget_rmb: float | None = Field(default=None, ge=0)

    @field_validator("llm_base_url", "llm_api_key", "llm_model", mode="before")
    @classmethod
    def strip_text(cls, value):
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        return stripped or None

    @field_validator("llm_base_url")
    @classmethod
    def validate_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("API Base URL 必须是有效的 HTTP(S) 地址")
        return value.rstrip("/")

    @field_validator("llm_monthly_budget_rmb")
    @classmethod
    def validate_budget(cls, value: float | None) -> float:
        if value is None:
            raise ValueError("每月预算不能为空")
        return value


def _llm_config_response(settings: Settings, db: Session) -> dict:
    resolved = resolved_llm_settings(settings, db)
    key_item = db.get(AppSetting, "llm_api_key")
    return {
        "llm_base_url": resolved.llm_base_url,
        "llm_model": resolved.llm_model,
        "llm_input_price_rmb_per_million": resolved.llm_input_price_rmb_per_million,
        "llm_output_price_rmb_per_million": resolved.llm_output_price_rmb_per_million,
        "llm_monthly_budget_rmb": resolved.llm_monthly_budget_rmb,
        "api_key_configured": bool(resolved.llm_api_key),
        "api_key_source": "local" if key_item is not None and key_item.value else "environment" if resolved.llm_api_key else None,
    }


@router.post("/feishu/test", dependencies=[Depends(require_csrf)])
async def test_feishu(settings: Settings = Depends(get_settings)) -> dict:
    if not settings.feishu_webhook:
        raise HTTPException(409, "尚未配置飞书 Webhook")
    if not settings.feishu_webhook.startswith("https://open.feishu.cn/open-apis/bot/v2/hook/"):
        raise HTTPException(422, "飞书 Webhook 地址格式不正确")
    try:
        await send_webhook(
            settings.feishu_webhook,
            {"msg_type": "text", "content": {"text": "秋招助手 Webhook 测试成功（不包含任何简历信息）"}},
        )
    except Exception as exc:
        raise HTTPException(502, "飞书 Webhook 测试失败，请检查机器人配置") from exc
    return {"success": True}


@router.get("/budget")
def budget(
    _: AuthSession = Depends(get_current_session),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    settings = resolved_llm_settings(settings, db)
    month = datetime.now(UTC).strftime("%Y-%m")
    used = float(db.scalar(select(func.sum(CostLedger.estimated_cost_rmb)).where(CostLedger.request_month == month)) or 0)
    enabled, reason = llm_available(settings, db)
    provider = selected_provider(settings, db)
    return {
        "month": month,
        "budget_rmb": settings.llm_monthly_budget_rmb,
        "used_rmb": used,
        "remaining_rmb": max(0, settings.llm_monthly_budget_rmb - used),
        "llm_enabled": enabled,
        "degraded_reason": reason or None,
        "pricing_configured": settings.llm_input_price_rmb_per_million is not None
        and settings.llm_output_price_rmb_per_million is not None,
        "llm_provider": provider,
        "cost_note": "Codex 使用当前登录额度，无法在本应用中估算人民币成本" if provider == "codex" else None,
    }


@router.get("/llm")
def llm_config(
    _: AuthSession = Depends(get_current_session),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    return _llm_config_response(settings, db)


@router.patch("/llm", dependencies=[Depends(require_csrf)])
def update_llm_config(
    payload: LLMConfigUpdate,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    changes = payload.model_dump(exclude_unset=True)
    for key, value in changes.items():
        item = db.get(AppSetting, key) or AppSetting(key=key)
        item.value = value
        item.secret = key == "llm_api_key"
        db.add(item)
    db.commit()
    return _llm_config_response(settings, db)


@router.get("/preferences")
def preferences(
    _: AuthSession = Depends(get_current_session),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    item = db.get(AppSetting, "degraded_summary_enabled")
    enabled, reason = llm_available(settings, db)
    return {
        "degraded_summary_enabled": bool(item and item.value is True),
        "llm_provider": configured_provider(settings, db),
        "effective_llm_provider": selected_provider(settings, db),
        "llm_available": enabled,
        "llm_reason": reason or None,
    }


@router.patch("/preferences", dependencies=[Depends(require_csrf)])
def update_preferences(payload: PreferenceUpdate, db: Session = Depends(get_db)) -> dict:
    changes = payload.model_dump(exclude_none=True)
    for key, value in changes.items():
        item = db.get(AppSetting, key) or AppSetting(key=key, secret=False)
        item.value = value
        item.secret = False
        db.add(item)
    db.commit()
    return preferences(db=db, settings=get_settings(), _=None)
