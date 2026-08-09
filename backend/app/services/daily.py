from __future__ import annotations

import logging

from app.core.config import Settings, get_settings
from app.core.database import SessionLocal
from app.models.entities import CandidateProfile
from app.services.feishu import notify_eligible
from app.services.recommendations import recompute_recommendations
from app.sources.runner import run_all_sources

logger = logging.getLogger(__name__)


async def run_daily_pipeline() -> None:
    settings: Settings = get_settings()
    await run_all_sources(allow_browser=True)
    with SessionLocal() as db:
        profile = db.get(CandidateProfile, 1)
        if not profile or not profile.confirmed:
            logger.info("每日采集完成；画像尚未确认，跳过推荐与通知")
            return
        try:
            await recompute_recommendations(db, settings)
            await notify_eligible(db, settings)
        except Exception as exc:
            logger.exception("每日推荐流程失败 (%s)", type(exc).__name__)

