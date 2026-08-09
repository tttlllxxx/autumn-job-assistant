import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.applications import create_application, delete_application, update_application
from app.core.database import Base
from app.models.entities import JobPosting
from app.schemas.applications import ApplicationInput, ApplicationPatch


def test_application_created_from_job_uses_canonical_job_fields() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        job = JobPosting(
            company="虚构科技",
            source_key="fixture",
            external_job_id="job-1",
            title="RAG 工程师",
            department="AI 平台",
            location="上海",
            recruitment_type="校园招聘",
            description="负责 Python RAG 平台开发",
            normalized_url="https://jobs.example.invalid/1",
            description_hash="a" * 64,
        )
        db.add(job)
        db.commit()

        application = create_application(
            ApplicationInput(job_id=job.id, company="不会采用", position="不会采用", channel="官网"),
            db,
        )

        assert application.job_id == job.id
        assert application.company == "虚构科技"
        assert application.position == "RAG 工程师"
        assert application.department == "AI 平台"
        assert application.url == "https://jobs.example.invalid/1"
        assert application.next_action == ""
        assert application.progress_updated_at is not None

        first_progress_update = application.progress_updated_at
        updated = update_application(
            application.id,
            ApplicationPatch(next_action="完成在线测评"),
            db,
        )
        assert updated.next_action == "完成在线测评"
        assert updated.progress_updated_at is not None
        assert updated.progress_updated_at >= first_progress_update

        cleared = update_application(
            application.id,
            ApplicationPatch(next_action=None),
            db,
        )
        assert cleared.next_action == ""

        with pytest.raises(HTTPException, match="已在投递看板"):
            create_application(ApplicationInput(job_id=job.id), db)

        assert delete_application(application.id, db) == {"removed": application.id}
        with pytest.raises(HTTPException, match="投递记录不存在"):
            delete_application(application.id, db)
