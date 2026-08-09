from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.database import Base
from app.models.entities import CandidateProfile, CostLedger, JobPosting, ResumeDocument, ResumeFact
from app.schemas.tailor import TailoredSentence
from app.services import tailor as tailor_service
from app.services.tailor import create_tailored_resume, validate_sentences


def fact_map() -> dict[str, ResumeFact]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    document = ResumeDocument(
        original_name="fictional.md",
        stored_path="/tmp/fictional.md",
        media_type="text/markdown",
        content_hash="a" * 64,
        parse_status="parsed",
        redacted_text="",
    )
    session.add(document)
    session.flush()
    fact = ResumeFact(
        fact_id="fact_safe",
        category="project",
        original_text="使用 Python 和 RAG 构建课程项目，准确率提升 12%",
        redacted_text="使用 Python 和 RAG 构建课程项目，准确率提升 12%",
        document_id=document.id,
        content_hash="b" * 64,
        confirmed=True,
    )
    session.add(fact)
    session.commit()
    return {fact.fact_id: fact}


def test_valid_sentence_keeps_fact_trace() -> None:
    result = validate_sentences(
        [TailoredSentence(text="使用 Python 和 RAG 构建课程项目，准确率提升 12%", fact_ids=["fact_safe"])],
        fact_map(),
    )
    assert result["valid"] is True
    assert result["sentences"][0]["fact_ids"] == ["fact_safe"]


def test_rejects_invented_number_and_experience_upgrade() -> None:
    facts = fact_map()
    invented_number = validate_sentences(
        [TailoredSentence(text="使用 Python 构建 RAG 项目，准确率提升 95%", fact_ids=["fact_safe"])], facts
    )
    upgraded = validate_sentences(
        [TailoredSentence(text="精通 Python 并主导生产环境 RAG 项目", fact_ids=["fact_safe"])], facts
    )
    assert invented_number["valid"] is False
    assert "95%" in invented_number["errors"][0]["values"]
    assert upgraded["valid"] is False
    assert {"精通", "主导", "生产环境"}.issubset(set(upgraded["errors"][0]["values"]))


def test_rejects_missing_or_inactive_fact_id() -> None:
    result = validate_sentences(
        [TailoredSentence(text="使用 Python", fact_ids=["fact_missing"])], fact_map()
    )
    assert result["valid"] is False
    assert result["errors"][0]["code"] == "INVALID_FACT_ID"


@pytest.mark.asyncio
async def test_tailor_llm_cost_is_recorded_even_when_validation_rejects_output(tmp_path: Path, monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        document = ResumeDocument(
            original_name="fictional.md",
            stored_path="/tmp/fictional.md",
            media_type="text/markdown",
            content_hash="c" * 64,
            parse_status="parsed",
            redacted_text="使用 Python 构建课程项目",
        )
        profile = CandidateProfile(id=1, confirmed=True)
        job = JobPosting(
            company="虚构公司",
            source_key="manual",
            external_job_id="J-COST",
            title="RAG 工程师",
            description="使用 Python 开发 RAG 平台",
            normalized_url="https://example.invalid/jobs/cost",
            description_hash="d" * 64,
        )
        db.add_all([document, profile, job])
        db.flush()
        db.add(
            ResumeFact(
                fact_id="fact_cost",
                category="project",
                original_text="使用 Python 构建课程项目",
                redacted_text="使用 Python 构建课程项目",
                document_id=document.id,
                content_hash="e" * 64,
                active=True,
                confirmed=True,
            )
        )
        db.commit()

        async def fake_request(*_args, **_kwargs):
            return [TailoredSentence(text="使用 Python 构建项目，准确率 99%", fact_ids=["fact_cost"])], 100, 50, 0.2, "fictional-model", "api"

        monkeypatch.setattr(tailor_service, "request_tailored_sentences", fake_request)
        settings = Settings(
            data_dir=tmp_path,
            model_cache_dir=tmp_path / "models",
            llm_provider="api",
            llm_base_url="https://llm.example.invalid/v1",
            llm_api_key="fictional-key",
            llm_model="fictional-model",
            llm_input_price_rmb_per_million=1,
            llm_output_price_rmb_per_million=1,
        )
        version = await create_tailored_resume(db, settings, job, None)
        ledger = db.scalar(select(CostLedger))

        assert version.status == "validation_failed"
        assert ledger is not None
        assert ledger.purpose == "resume_tailor" and ledger.estimated_cost_rmb == 0.2
