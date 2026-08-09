import httpx
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.database import Base
from app.models.entities import AppSetting, JobPosting, Notification, Recommendation
from app.services.feishu import notify_eligible


@pytest.mark.asyncio
async def test_notification_threshold_and_idempotency(tmp_path) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        job = JobPosting(
            company="虚构公司",
            source_key="manual",
            external_job_id="J1",
            title="AI 后端开发",
            description="使用 Python 开发 RAG 服务",
            normalized_url="https://example.invalid/jobs/1",
            description_hash="a" * 64,
            location="北京",
        )
        db.add(job)
        db.flush()
        db.add(
            Recommendation(
                job_id=job.id,
                version=1,
                hard_filter_passed=True,
                qualification_pending=False,
                rule_score=30,
                vector_score=25,
                llm_score=30,
                final_score=85,
                rerank_status="completed",
                evidence={"matching_facts": ["匹配 Python"], "gaps": ["工程规模待确认"]},
            )
        )
        db.commit()
        calls = 0

        def handler(_request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(200, json={"code": 0})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        settings = Settings(
            data_dir=tmp_path,
            model_cache_dir=tmp_path / "models",
            feishu_webhook="https://open.feishu.cn/open-apis/bot/v2/hook/fictional-token",
        )
        first = await notify_eligible(db, settings, client=client)
        second = await notify_eligible(db, settings, client=client)
        await client.aclose()

        assert first["sent"] == 1
        assert second["sent"] == 0
        assert calls == 1
        assert db.scalar(select(func.count(Notification.id))) == 1


@pytest.mark.asyncio
async def test_local_only_result_is_never_notified(tmp_path) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        job = JobPosting(
            company="虚构公司",
            source_key="manual",
            external_job_id="J2",
            title="AI 后端开发",
            description="使用 Python 开发 RAG 服务",
            normalized_url="https://example.invalid/jobs/2",
            description_hash="b" * 64,
        )
        db.add(job)
        db.flush()
        db.add(
            Recommendation(
                job_id=job.id,
                version=1,
                hard_filter_passed=True,
                qualification_pending=False,
                rule_score=30,
                vector_score=30,
                final_score=99,
                rerank_status="local_only",
            )
        )
        db.commit()
        settings = Settings(
            data_dir=tmp_path,
            model_cache_dir=tmp_path / "models",
            feishu_webhook="https://open.feishu.cn/open-apis/bot/v2/hook/fictional-token",
        )
        result = await notify_eligible(db, settings)
        assert result["sent"] == 0
        assert result["degraded_summary_sent"] is False


@pytest.mark.asyncio
async def test_explicit_preference_sends_one_idempotent_degraded_summary(tmp_path) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        job = JobPosting(
            company="虚构公司",
            source_key="manual",
            external_job_id="J3",
            title="RAG 工程师",
            description="使用 Python 开发 RAG 服务",
            normalized_url="https://example.invalid/jobs/3",
            description_hash="c" * 64,
        )
        db.add(job)
        db.flush()
        db.add_all(
            [
                Recommendation(
                    job_id=job.id,
                    version=1,
                    hard_filter_passed=True,
                    qualification_pending=False,
                    rule_score=25,
                    vector_score=25,
                    final_score=50,
                    rerank_status="local_only",
                ),
                AppSetting(key="degraded_summary_enabled", value=True, secret=False),
            ]
        )
        db.commit()
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            assert "不代表完整总分" in request.read().decode()
            return httpx.Response(200, json={"code": 0})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        settings = Settings(
            data_dir=tmp_path,
            model_cache_dir=tmp_path / "models",
            feishu_webhook="https://open.feishu.cn/open-apis/bot/v2/hook/fictional-token",
        )
        first = await notify_eligible(db, settings, client=client)
        second = await notify_eligible(db, settings, client=client)
        await client.aclose()

        assert first["degraded_summary_sent"] is True
        assert second["degraded_summary_sent"] is False
        assert calls == 1
