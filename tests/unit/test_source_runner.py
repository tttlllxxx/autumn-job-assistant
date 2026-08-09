import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models.entities import JobPosting, SourceHealth
from app.sources.base import JobPayload, JobStub
from app.sources.runner import _payload_rejection_reason, _upsert_job, run_source
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


@pytest.mark.parametrize(
    ("title", "description"),
    [
        ("隐私协议", "https://example.invalid/privacy"),
        ("美团赛事", "这是一段活动介绍，不是具体岗位的职责和任职要求"),
        ("Eagle Program", "这是一段招聘项目介绍，不是具体岗位的职责和任职要求"),
        ("携程集团2026年春季校园招聘全球启动", "这是一段旧批次介绍，不是 2027 届岗位"),
        ("大住宿全球培训生AGT", '<p><a href="/campaign"><img src="poster.jpg"></a></p>'),
    ],
)
def test_non_job_payloads_are_rejected(title: str, description: str) -> None:
    item = payload("BAD", title, url="https://jobs.example.invalid/jobs/BAD", shared=False, description=description)

    assert _payload_rejection_reason(item) is not None


def test_concrete_job_payload_is_not_rejected() -> None:
    item = payload(
        "GOOD", "RAG 后端开发工程师", url="https://jobs.example.invalid/jobs/GOOD", shared=False,
        description="负责检索增强服务开发；要求熟悉 Python、数据库和分布式系统。",
    )

    assert _payload_rejection_reason(item) is None


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
async def test_run_source_uses_database_aware_registry(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    selected = FixtureAdapter([
        payload("J1", "虚构 RAG 工程师", url="https://jobs.example.invalid/jobs/1", shared=False)
    ])
    monkeypatch.setitem(runner.REGISTRY, "fixture", FixtureAdapter(fail=True))
    monkeypatch.setattr(runner, "get_registry", lambda _db: {"fixture": selected})

    with Session(engine) as db:
        run = await run_source(db, "fixture")

    assert run.success is True


@pytest.mark.asyncio
async def test_source_run_records_accepted_and_rejected_funnel(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    valid = payload("J1", "虚构 RAG 工程师", url="https://jobs.example.invalid/jobs/1", shared=False)
    rejected = payload("J2", "隐私协议", url="https://jobs.example.invalid/privacy", shared=False)
    with Session(engine) as db:
        run = await run_fixture(db, monkeypatch, FixtureAdapter([valid, rejected]))

    assert run.discovered_count == 2
    assert run.accepted_count == 1
    assert run.rejected_count == 1
    assert run.rejection_reasons == {"页面导航或隐私条款，不是岗位": 1}


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
