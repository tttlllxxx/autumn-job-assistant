from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.entities import AppSetting, JobPosting, Notification, Recommendation


def _valid_webhook(url: str) -> bool:
    return url.startswith("https://open.feishu.cn/open-apis/bot/v2/hook/")


def _message(job: JobPosting, recommendation: Recommendation, settings: Settings) -> dict:
    matches = recommendation.evidence.get("matching_facts", [])[:3]
    gaps = recommendation.evidence.get("gaps", [])[:1]
    lines = [
        f"【{job.company}】{job.title}",
        f"地点：{job.location or '待确认'}｜总分：{recommendation.final_score:.1f}",
        "核心匹配：" + ("；".join(matches) if matches else "见控制台证据链"),
        "主要缺口：" + ("；".join(gaps) if gaps else "暂无明确缺口"),
        f"官方链接：{job.normalized_url}",
        f"控制台：{settings.public_base_url.rstrip('/')}/jobs/{job.id}",
    ]
    return {"msg_type": "text", "content": {"text": "\n".join(lines)}}


async def send_webhook(
    webhook: str,
    payload: dict,
    *,
    client: httpx.AsyncClient | None = None,
) -> None:
    owns_client = client is None
    active_client = client or httpx.AsyncClient(timeout=10)
    try:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = await active_client.post(webhook, json=payload)
                response.raise_for_status()
                body = response.json()
                if body.get("code", body.get("StatusCode", 0)) != 0:
                    raise ValueError("飞书 Webhook 返回失败状态")
                return
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                if attempt < 2:
                    await asyncio.sleep(0.25 * (2**attempt))
        assert last_error is not None
        raise last_error
    finally:
        if owns_client:
            await active_client.aclose()


async def notify_eligible(
    db: Session,
    settings: Settings,
    *,
    client: httpx.AsyncClient | None = None,
) -> dict:
    if not settings.feishu_webhook or not _valid_webhook(settings.feishu_webhook):
        return {"status": "disabled", "sent": 0, "reason": "未配置有效的飞书 Webhook"}
    candidates = db.execute(
        select(JobPosting, Recommendation)
        .join(Recommendation, Recommendation.job_id == JobPosting.id)
        .where(
            Recommendation.rerank_status == "completed",
            Recommendation.final_score >= 80,
            Recommendation.qualification_pending.is_(False),
            JobPosting.closed.is_(False),
        )
        .order_by(Recommendation.created_at.asc())
    ).all()
    sent = 0
    for job, recommendation in candidates:
        notification = db.scalar(
            select(Notification).where(
                Notification.job_id == job.id,
                Notification.recommendation_version == recommendation.version,
            )
        )
        if notification and notification.status == "sent":
            continue
        notification = notification or Notification(
            job_id=job.id,
            recommendation_version=recommendation.version,
            status="pending",
            attempts=0,
        )
        db.add(notification)
        try:
            await send_webhook(settings.feishu_webhook, _message(job, recommendation, settings), client=client)
            notification.status = "sent"
            notification.attempts = (notification.attempts or 0) + 1
            notification.error = None
            notification.sent_at = datetime.now(UTC)
            sent += 1
        except Exception as exc:
            notification.status = "failed"
            notification.attempts = (notification.attempts or 0) + 1
            notification.error = type(exc).__name__
        db.commit()
    degraded_summary_sent = False
    preference = db.get(AppSetting, "degraded_summary_enabled")
    if preference is not None and preference.value is True:
        local_candidates = db.execute(
            select(JobPosting, Recommendation)
            .join(Recommendation, Recommendation.job_id == JobPosting.id)
            .where(
                Recommendation.rerank_status == "local_only",
                Recommendation.hard_filter_passed.is_(True),
                Recommendation.qualification_pending.is_(False),
                JobPosting.closed.is_(False),
            )
            .order_by(Recommendation.final_score.desc(), Recommendation.job_id.asc())
        ).all()
        pending = [
            (job, recommendation)
            for job, recommendation in local_candidates
            if db.scalar(
                select(Notification).where(
                    Notification.job_id == job.id,
                    Notification.recommendation_version == recommendation.version,
                )
            ) is None
        ][:3]
        if pending:
            lines = ["降级推荐摘要（仅规则/本地向量，不代表完整总分）"] + [
                f"{job.company}｜{job.title}｜本地分 {recommendation.final_score:.1f}｜{job.normalized_url}"
                for job, recommendation in pending
            ]
            records = [
                Notification(
                    job_id=job.id,
                    recommendation_version=recommendation.version,
                    status="pending",
                    attempts=0,
                )
                for job, recommendation in pending
            ]
            db.add_all(records)
            try:
                await send_webhook(
                    settings.feishu_webhook,
                    {"msg_type": "text", "content": {"text": "\n".join(lines)}},
                    client=client,
                )
                for record in records:
                    record.status = "sent"
                    record.attempts = 1
                    record.sent_at = datetime.now(UTC)
                degraded_summary_sent = True
            except Exception as exc:
                for record in records:
                    record.status = "failed"
                    record.attempts = 1
                    record.error = type(exc).__name__
            db.commit()
    return {"status": "completed", "sent": sent, "degraded_summary_sent": degraded_summary_sent}
