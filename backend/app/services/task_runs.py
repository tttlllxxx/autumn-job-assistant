from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import TaskRun, utcnow


class TaskAlreadyRunningError(ValueError):
    pass


def begin_task(
    db: Session,
    task_type: str,
    *,
    scope_key: str | None = None,
    total: int = 0,
    message: str = "",
) -> TaskRun:
    existing = db.scalar(
        select(TaskRun).where(
            TaskRun.task_type == task_type,
            TaskRun.scope_key == scope_key,
            TaskRun.status == "running",
        )
    )
    if existing is not None:
        raise TaskAlreadyRunningError("同类任务仍在运行，请等待完成")
    task = TaskRun(
        task_type=task_type,
        scope_key=scope_key,
        status="running",
        total=total,
        message=message,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def update_task(db: Session, task_id: int, *, current: int, message: str = "") -> None:
    task = db.get(TaskRun, task_id)
    if task is None:
        return
    task.current = current
    task.message = message
    db.commit()


def finish_task(db: Session, task_id: int, result: dict) -> None:
    task = db.get(TaskRun, task_id)
    if task is None:
        return
    task.status = "completed"
    task.current = task.total or task.current
    task.result = result
    task.finished_at = utcnow()
    db.commit()


def fail_task(db: Session, task_id: int, exc: Exception) -> None:
    db.rollback()
    task = db.get(TaskRun, task_id)
    if task is None:
        return
    task.status = "failed"
    task.error_message = str(exc)[:500]
    task.finished_at = utcnow()
    db.commit()


def interrupt_running_tasks(db: Session) -> None:
    tasks = db.scalars(select(TaskRun).where(TaskRun.status == "running")).all()
    for task in tasks:
        task.status = "interrupted"
        task.error_message = "服务重启，任务未能完成"
        task.finished_at = utcnow()
    if tasks:
        db.commit()
