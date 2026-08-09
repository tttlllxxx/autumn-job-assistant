from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.services.task_runs import begin_task, finish_task, interrupt_running_tasks


def test_task_state_persists_completion_and_interrupts_stale_runs() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        completed = begin_task(db, "recommendation_recompute", total=1)
        finish_task(db, completed.id, {"version": 2})
        db.refresh(completed)
        assert completed.status == "completed"
        assert completed.result == {"version": 2}

        stale = begin_task(db, "source_run", total=12)
        interrupt_running_tasks(db)
        db.refresh(stale)
        assert stale.status == "interrupted"
        assert stale.finished_at is not None
