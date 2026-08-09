from __future__ import annotations

import logging
import hashlib
import json

from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.core.database import SessionLocal
from app.models.entities import AppSetting, CandidateProfile, JobPosting, UserFeedback
from app.services.feishu import notify_eligible
from app.services.recommendations import recompute_recommendations
from app.sources.runner import run_all_sources
from app.services.task_runs import (
    TaskAlreadyRunningError,
    begin_task,
    fail_task,
    finish_task,
    update_task,
)

logger = logging.getLogger(__name__)


def _recommendation_fingerprint(db) -> str:
    profile = db.get(CandidateProfile, 1)
    jobs = db.execute(
        select(
            JobPosting.id,
            JobPosting.title,
            JobPosting.location,
            JobPosting.description_hash,
            JobPosting.closed,
            JobPosting.qualification_confirmed,
        ).order_by(JobPosting.id)
    ).all()
    feedback_id = db.scalar(select(UserFeedback.id).order_by(UserFeedback.id.desc()).limit(1))
    value = {
        "profile_version": profile.version if profile else None,
        "jobs": [tuple(row) for row in jobs],
        "feedback_id": feedback_id,
    }
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _stored_fingerprint(db) -> str | None:
    setting = db.get(AppSetting, "daily_recommendation_fingerprint")
    return str(setting.value) if setting else None


def _save_fingerprint(db, value: str) -> None:
    setting = db.get(AppSetting, "daily_recommendation_fingerprint") or AppSetting(
        key="daily_recommendation_fingerprint",
        secret=False,
    )
    setting.value = value
    setting.secret = False
    db.add(setting)
    db.commit()


def _progress(task_id: int, current: int, message: str) -> None:
    with SessionLocal() as db:
        update_task(db, task_id, current=current, message=message)


async def run_daily_pipeline() -> None:
    settings: Settings = get_settings()
    with SessionLocal() as db:
        try:
            task = begin_task(db, "daily_pipeline", total=3, message="正在采集招聘来源")
        except TaskAlreadyRunningError:
            logger.info("每日任务仍在运行，跳过本次重复调度")
            return
    try:
        await run_all_sources(allow_browser=True)
        _progress(task.id, 1, "来源采集完成")
    except Exception as exc:
        with SessionLocal() as db:
            fail_task(db, task.id, exc)
        raise
    with SessionLocal() as db:
        profile = db.get(CandidateProfile, 1)
        if not profile or not profile.confirmed:
            logger.info("每日采集完成；画像尚未确认，跳过推荐与通知")
            finish_task(db, task.id, {"collected": True, "recommendations": "skipped_unconfirmed"})
            return
        fingerprint = _recommendation_fingerprint(db)
        if fingerprint == _stored_fingerprint(db):
            logger.info("岗位、画像与反馈均无变化，跳过重复推荐计算")
            finish_task(db, task.id, {"collected": True, "recommendations": "skipped_unchanged"})
            return
        try:
            result = await recompute_recommendations(db, settings)
            update_task(db, task.id, current=2, message="推荐计算完成")
            notifications = await notify_eligible(db, settings)
            _save_fingerprint(db, fingerprint)
            finish_task(db, task.id, {
                "collected": True,
                "recommendation_version": result["version"],
                "notifications": notifications,
            })
        except Exception as exc:
            fail_task(db, task.id, exc)
            logger.exception("每日推荐流程失败 (%s)", type(exc).__name__)
