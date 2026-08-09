from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_session
from app.models.entities import AuthSession, TaskRun

router = APIRouter(prefix="/api/tasks", tags=["后台任务"])


@router.get("")
def list_tasks(
    task_type: str | None = None,
    scope_key: str | None = None,
    active_only: bool = Query(default=True),
    limit: int = Query(default=20, ge=1, le=100),
    _: AuthSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> list[dict]:
    filters = []
    if task_type:
        filters.append(TaskRun.task_type == task_type)
    if scope_key is not None:
        filters.append(TaskRun.scope_key == scope_key)
    if active_only:
        filters.append(TaskRun.status == "running")
    tasks = db.scalars(
        select(TaskRun).where(*filters).order_by(TaskRun.id.desc()).limit(limit)
    ).all()
    return [
        {column.name: getattr(task, column.name) for column in TaskRun.__table__.columns}
        for task in tasks
    ]
