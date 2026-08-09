from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.security import get_current_session, require_csrf
from app.models.entities import AuthSession, JobPosting, Recommendation, UserFeedback
from app.schemas.jobs import JobOut
from app.schemas.recommendations import FeedbackRequest, RecommendationOut, RecommendationPage
from app.services.feishu import notify_eligible
from app.services.evaluation import evaluate_user_feedback
from app.services.recommendations import recompute_recommendations
from app.services.task_runs import TaskAlreadyRunningError, begin_task, fail_task, finish_task

router = APIRouter(prefix="/api", tags=["推荐"])


@router.get("/recommendations", response_model=RecommendationPage)
def list_recommendations(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    status: str | None = Query(default=None, pattern="^(recommended|pending|filtered|all)$"),
    job_id: int | None = Query(default=None, ge=1),
    include_filtered: bool = False,
    include_pending: bool = False,
    _: AuthSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> RecommendationPage:
    version = db.scalar(select(func.max(Recommendation.version)))
    if version is None:
        return RecommendationPage(
            items=[], total=0, page=page, page_size=page_size,
            counts={"all": 0, "recommended": 0, "pending": 0, "filtered": 0},
            updated_at=None,
        )
    version_filter = Recommendation.version == version
    updated_at = db.scalar(select(func.max(Recommendation.created_at)).where(version_filter))
    counts = {
        "all": int(db.scalar(select(func.count(Recommendation.id)).where(version_filter)) or 0),
        "recommended": int(db.scalar(select(func.count(Recommendation.id)).where(
            version_filter,
            Recommendation.hard_filter_passed.is_(True),
            Recommendation.qualification_pending.is_(False),
        )) or 0),
        "pending": int(db.scalar(select(func.count(Recommendation.id)).where(
            version_filter,
            Recommendation.hard_filter_passed.is_(True),
            Recommendation.qualification_pending.is_(True),
        )) or 0),
        "filtered": int(db.scalar(select(func.count(Recommendation.id)).where(
            version_filter,
            Recommendation.hard_filter_passed.is_(False),
        )) or 0),
    }
    filters = [Recommendation.version == version]
    if job_id is not None:
        filters.append(Recommendation.job_id == job_id)
    elif status == "recommended":
        filters.extend((Recommendation.hard_filter_passed.is_(True), Recommendation.qualification_pending.is_(False)))
    elif status == "pending":
        filters.extend((Recommendation.hard_filter_passed.is_(True), Recommendation.qualification_pending.is_(True)))
    elif status == "filtered":
        filters.append(Recommendation.hard_filter_passed.is_(False))
    elif status != "all":
        if not include_filtered:
            filters.append(Recommendation.hard_filter_passed.is_(True))
        if not include_pending:
            filters.append(Recommendation.qualification_pending.is_(False))
    total = db.scalar(select(func.count(Recommendation.id)).where(*filters)) or 0
    rows = db.execute(
        select(Recommendation, JobPosting)
        .join(JobPosting, JobPosting.id == Recommendation.job_id)
        .where(*filters)
        .order_by(Recommendation.final_score.desc(), Recommendation.job_id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    items = [
        {
            **RecommendationOut.model_validate(recommendation).model_dump(),
            "job": JobOut.model_validate(job).model_dump(),
        }
        for recommendation, job in rows
    ]
    return RecommendationPage(
        items=items, total=total, page=page, page_size=page_size, counts=counts, updated_at=updated_at
    )


@router.post("/recommendations/recompute", dependencies=[Depends(require_csrf)])
async def recompute(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    try:
        task = begin_task(db, "recommendation_recompute", message="正在更新岗位推荐")
    except TaskAlreadyRunningError as exc:
        raise HTTPException(409, str(exc)) from exc
    try:
        result = await recompute_recommendations(db, settings)
        result["notifications"] = await notify_eligible(db, settings)
        finish_task(db, task.id, result)
        return result
    except ValueError as exc:
        fail_task(db, task.id, exc)
        raise HTTPException(409, str(exc)) from exc
    except Exception as exc:
        fail_task(db, task.id, exc)
        raise


@router.post("/jobs/{job_id}/feedback", dependencies=[Depends(require_csrf)])
def feedback(job_id: int, payload: FeedbackRequest, db: Session = Depends(get_db)) -> dict:
    job = db.get(JobPosting, job_id)
    if not job:
        raise HTTPException(404, "岗位不存在")
    if payload.action == "confirm_qualification":
        job.qualification_confirmed = True
        version = db.scalar(select(func.max(Recommendation.version)))
        recommendation = db.scalar(select(Recommendation).where(
            Recommendation.job_id == job_id,
            Recommendation.version == version,
        )) if version is not None else None
        if recommendation is not None:
            recommendation.qualification_pending = False
            evidence = dict(recommendation.evidence or {})
            pipeline = dict(evidence.get("pipeline") or {})
            if pipeline.get("llm") == "skipped":
                pipeline.update(llm="pending", llm_detail="资格已人工确认，等待更新推荐")
            evidence["pipeline"] = pipeline
            recommendation.evidence = evidence
        db.commit()
        return {
            "job_id": job_id,
            "qualification_confirmed": True,
            "recommendation_updated": recommendation is not None,
        }
    if payload.action == "reset_weights":
        for item in db.scalars(select(UserFeedback)).all():
            item.weight_delta = 0
        db.commit()
        return {"reset": True}
    if payload.action in {"suitable", "unsuitable"}:
        db.add(UserFeedback(job_id=job_id, action=payload.action, reason=payload.reason, weight_delta=0))
        db.commit()
        return {
            "job_id": job_id,
            "suitability": payload.action,
            "evaluation": evaluate_user_feedback(db),
        }
    existing_delta = float(
        db.scalar(select(func.sum(UserFeedback.weight_delta)).where(UserFeedback.job_id == job_id)) or 0
    )
    requested = 1.0 if payload.action == "favorite" else -1.0
    new_total = max(-5.0, min(5.0, existing_delta + requested))
    applied = new_total - existing_delta
    db.add(UserFeedback(job_id=job_id, action=payload.action, reason=payload.reason, weight_delta=applied))
    db.commit()
    return {"job_id": job_id, "action": payload.action, "applied_weight": applied, "total_weight": new_total}


@router.get("/feedback/weights")
def feedback_weights(
    job_id: int | None = Query(default=None, ge=1),
    _: AuthSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> dict:
    query = select(UserFeedback)
    if job_id is not None:
        query = query.where(UserFeedback.job_id == job_id)
    items = db.scalars(query.order_by(UserFeedback.created_at.desc(), UserFeedback.id.desc())).all()
    suitability = next((item.action for item in items if item.action in {"suitable", "unsuitable"}), None)
    return {
        "total_weight": sum(item.weight_delta for item in items),
        "limit": 5,
        "suitability": suitability,
        "items": [
            {
                "job_id": item.job_id,
                "action": item.action,
                "reason": item.reason,
                "weight_delta": item.weight_delta,
                "created_at": item.created_at,
            }
            for item in items
        ],
    }


@router.get("/evaluation")
def evaluation(
    _: AuthSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> dict:
    return evaluate_user_feedback(db)
