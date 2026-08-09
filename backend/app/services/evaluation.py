from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.entities import Recommendation, UserFeedback

SUITABILITY_ACTIONS = {"suitable": True, "unsuitable": False}


def evaluate_user_feedback(db: Session, *, required_labels: int = 50) -> dict:
    feedback = db.scalars(
        select(UserFeedback)
        .where(UserFeedback.action.in_(SUITABILITY_ACTIONS))
        .order_by(UserFeedback.id)
    ).all()
    labels = {item.job_id: SUITABILITY_ACTIONS[item.action] for item in feedback}
    version = db.scalar(select(func.max(Recommendation.version)))
    if version is None:
        return {
            "status": "waiting_for_recommendations",
            "labels": len(labels),
            "required_labels": required_labels,
            "precision_at_10": None,
            "unlabeled_top10_job_ids": [],
        }
    ranked = db.scalars(
        select(Recommendation)
        .where(
            Recommendation.version == version,
            Recommendation.hard_filter_passed.is_(True),
            Recommendation.qualification_pending.is_(False),
        )
        .order_by(Recommendation.final_score.desc(), Recommendation.job_id.asc())
    ).all()
    top10 = list(ranked[:10])
    unlabeled = [item.job_id for item in top10 if item.job_id not in labels]
    ready = len(labels) >= required_labels and len(top10) == 10 and not unlabeled
    precision = (
        sum(labels[item.job_id] for item in top10) / 10
        if ready
        else None
    )
    return {
        "status": "passed" if ready and precision >= 0.70 else "failed" if ready else "collecting_feedback",
        "version": version,
        "labels": len(labels),
        "required_labels": required_labels,
        "ranked_candidates": len(ranked),
        "top10_job_ids": [item.job_id for item in top10],
        "unlabeled_top10_job_ids": unlabeled,
        "precision_at_10": precision,
    }

