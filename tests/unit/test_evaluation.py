from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models.entities import JobPosting, Recommendation, UserFeedback
from app.services.evaluation import evaluate_user_feedback


def test_latest_inline_suitability_feedback_drives_precision_at_10() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        jobs = []
        for number in range(1, 51):
            job = JobPosting(
                company="虚构公司",
                source_key="manual",
                external_job_id=f"J{number}",
                title=f"虚构岗位 {number}",
                description="虚构岗位正文",
                normalized_url=f"https://example.invalid/jobs/{number}",
                description_hash=f"{number:064d}"[-64:],
            )
            db.add(job)
            jobs.append(job)
        db.flush()
        for rank, job in enumerate(jobs):
            db.add(
                Recommendation(
                    job_id=job.id,
                    version=1,
                    hard_filter_passed=True,
                    qualification_pending=False,
                    rule_score=30,
                    vector_score=30,
                    final_score=100 - rank,
                    rerank_status="completed",
                )
            )
            db.add(
                UserFeedback(
                    job_id=job.id,
                    action="suitable" if rank < 7 else "unsuitable",
                    weight_delta=0,
                )
            )
        db.add(UserFeedback(job_id=jobs[0].id, action="suitable", weight_delta=0))
        db.commit()

        result = evaluate_user_feedback(db)

        assert result["status"] == "passed"
        assert result["labels"] == 50
        assert result["precision_at_10"] == 0.7
        assert result["unlabeled_top10_job_ids"] == []


def test_evaluation_waits_for_inline_feedback_without_inventing_precision() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        assert evaluate_user_feedback(db)["status"] == "waiting_for_recommendations"
        assert evaluate_user_feedback(db)["precision_at_10"] is None
