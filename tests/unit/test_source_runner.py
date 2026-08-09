import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models.entities import JobPosting, SourceHealth
from app.sources.base import JobPayload, JobStub
from app.sources.runner import _upsert_job, run_source
from app.sources import runner


def payload(job_id: str, title: str, *, url: str, shared: bool, description: str = "虚构岗位正文") -> JobPayload:
    return JobPayload(
        external_job_id=job_id,
        title=title,
        department="虚构部门",
        location="上海",
        recruitment_type="校园招聘",
        graduation_year="2027",
        description=description,
        application_url=url,
        evidence_metadata={"shared_listing_url": shared},
    )


def test_shared_listing_keeps_distinct_external_jobs_and_same_id_updates() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    listing = "https://jobs.example.invalid/campus/positions"
    with Session(engine) as db:
        first, created_first = _upsert_job(db, "fixture", "虚构公司", payload("J1", "虚构 RAG 工程师", url=listing, shared=True))
        second, created_second = _upsert_job(db, "fixture", "虚构公司", payload("J2", "虚构 AI 安全工程师", url=listing, shared=True))
        db.commit()

        updated, created_again = _upsert_job(
            db,
            "fixture",
            "虚构公司",
            payload("J1", "虚构 RAG 平台工程师", url=listing, shared=True),
        )
        db.commit()

        assert created_first is True and created_second is True
        assert first.id != second.id
        assert created_again is False and updated.id == first.id
        assert db.scalar(select(func.count(JobPosting.id))) == 2


def test_job_specific_url_and_composite_identity_are_fallback_deduplication_keys() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        original, _ = _upsert_job(
            db,
            "fixture",
            "虚构公司",
            payload("J1", "虚构 RAG 工程师", url="https://jobs.example.invalid/jobs/1", shared=False),
        )
        db.commit()
        by_url, created_by_url = _upsert_job(
            db,
            "fixture",
            "虚构公司",
            payload("J2", "虚构 RAG 工程师", url="https://jobs.example.invalid/jobs/1", shared=False),
        )
        by_composite, created_by_composite = _upsert_job(
            db,
            "fixture",
            "虚构公司",
            payload("J3", "虚构  RAG 工程师", url="https://jobs.example.invalid/jobs/3", shared=True),
        )

        assert created_by_url is False and by_url.id == original.id
        assert created_by_composite is False and by_composite.id == original.id


class FixtureAdapter:
    parser_version = "fixture-v1"
    display_name = "虚构公司"

    def __init__(self, jobs: list[JobPayload] | None = None, *, fail: bool = False) -> None:
        self.jobs = jobs or []
        self.fail = fail

    async def discover(self, _context) -> list[JobStub]:
        if self.fail:
            raise ValueError("虚构来源故障")
        return [JobStub(item.external_job_id, item.application_url, item.title) for item in self.jobs]

    async def fetch_detail(self, stub: JobStub, _context) -> JobPayload:
        return next(item for item in self.jobs if item.external_job_id == stub.external_job_id)

    @staticmethod
    def _is_official(url: str) -> bool:
        return url.startswith("https://jobs.example.invalid/")


async def run_fixture(db: Session, monkeypatch, adapter: FixtureAdapter):
    monkeypatch.setitem(runner.REGISTRY, "fixture", adapter)
    return await run_source(db, "fixture")


@pytest.mark.asyncio
async def test_only_three_healthy_misses_close_a_job(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        kept = payload("J1", "虚构 RAG 工程师", url="https://jobs.example.invalid/jobs/1", shared=False)
        missing = payload("J2", "虚构安全工程师", url="https://jobs.example.invalid/jobs/2", shared=False)
        _upsert_job(db, "fixture", "虚构公司", kept)
        lost, _ = _upsert_job(db, "fixture", "虚构公司", missing)
        db.commit()

        for expected_missing in (1, 2, 3):
            run = await run_fixture(db, monkeypatch, FixtureAdapter([kept]))
            db.refresh(lost)
            assert run.success is True
            assert lost.missing_count == expected_missing
            assert lost.closed is (expected_missing == 3)


@pytest.mark.asyncio
async def test_failed_source_run_preserves_job_missing_count_and_records_health(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        existing, _ = _upsert_job(
            db,
            "fixture",
            "虚构公司",
            payload("J1", "虚构 RAG 工程师", url="https://jobs.example.invalid/jobs/1", shared=False),
        )
        db.commit()

        run = await run_fixture(db, monkeypatch, FixtureAdapter(fail=True))
        db.refresh(existing)
        health = db.get(SourceHealth, "fixture")

        assert run.success is False
        assert existing.missing_count == 0 and existing.closed is False
        assert health is not None
        assert health.status == "degraded" and health.consecutive_failures == 1
