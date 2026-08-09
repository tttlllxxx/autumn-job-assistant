from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, inspect, select, text
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_session
from app.models.entities import Application, AuthSession, JobPosting, Recommendation, SourceHealth, TaskRun

router = APIRouter(tags=["健康检查"])


@router.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
def ready(db: Session = Depends(get_db)) -> dict[str, str]:
    try:
        db.execute(text("SELECT 1"))
        inspector = inspect(db.get_bind())
        required_tables = {"candidate_profiles", "job_postings", "source_runs", "task_runs", "applications"}
        if not required_tables.issubset(inspector.get_table_names()):
            raise RuntimeError("数据库迁移未完成")
        source_columns = {column["name"] for column in inspector.get_columns("source_runs")}
        profile_columns = {column["name"] for column in inspector.get_columns("candidate_profiles")}
        if not {"accepted_count", "rejected_count"}.issubset(source_columns) or not {
            "target_graduation_year", "target_recruitment_types"
        }.issubset(profile_columns):
            raise RuntimeError("数据库结构不是当前版本")
    except Exception as exc:
        raise HTTPException(status_code=503, detail="数据库尚未就绪") from exc
    return {"status": "ready"}


@router.get("/api/system/status")
def system_status(
    _: AuthSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> dict:
    recommendation_version = db.scalar(select(func.max(Recommendation.version)))
    recommendation_updated_at = db.scalar(select(func.max(Recommendation.created_at)))
    source_status = {
        status: count
        for status, count in db.execute(
            select(SourceHealth.status, func.count(SourceHealth.source_key)).group_by(SourceHealth.status)
        ).all()
    }
    task_status = {
        status: count
        for status, count in db.execute(
            select(TaskRun.status, func.count(TaskRun.id)).group_by(TaskRun.status)
        ).all()
    }
    recent_tasks = db.scalars(select(TaskRun).order_by(TaskRun.id.desc()).limit(5)).all()
    return {
        "active_jobs": int(db.scalar(select(func.count(JobPosting.id)).where(JobPosting.closed.is_(False))) or 0),
        "applications": int(db.scalar(select(func.count(Application.id))) or 0),
        "recommendation_version": recommendation_version,
        "recommendation_updated_at": recommendation_updated_at,
        "source_status": source_status,
        "task_status": task_status,
        "recent_tasks": [
            {
                "id": task.id,
                "task_type": task.task_type,
                "status": task.status,
                "message": task.message,
                "started_at": task.started_at,
                "finished_at": task.finished_at,
                "error_message": task.error_message,
            }
            for task in recent_tasks
        ],
    }
