from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.database import Base
from app.models.entities import CandidateProfile, CostLedger, JobPosting, Recommendation, ResumeDocument, ResumeFact
from app.schemas.tailor import TailorAdviceLLMResponse, TailorAdviceRewrite, TailoredSentence
from app.services import tailor as tailor_service
from app.services.llm import StructuredResult
from app.services.tailor import build_tailor_advice, create_tailored_resume, save_tailor_advice, stored_tailor_advice, validate_sentences


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


def test_tailor_advice_is_built_for_one_clicked_job_from_its_latest_evidence() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        document = ResumeDocument(
            original_name="fictional.md", stored_path="/tmp/fictional.md", media_type="text/markdown",
            content_hash="f" * 64, parse_status="parsed", redacted_text="",
        )
        job = JobPosting(
            company="虚构公司", source_key="manual", external_job_id="ADVICE-1", title="RAG 工程师",
            description="熟悉 Python 并具备 RAG 项目经验", normalized_url="https://example.invalid/jobs/advice",
            description_hash="1" * 64,
        )
        db.add_all([document, job]); db.flush()
        fact = ResumeFact(
            fact_id="fact_advice", category="project", original_text="使用 Python 构建 RAG 课程项目",
            redacted_text="使用 Python 构建 RAG 课程项目", document_id=document.id, content_hash="2" * 64,
            active=True, confirmed=True,
        )
        db.add(fact); db.flush()
        db.add(Recommendation(
            job_id=job.id, version=2, hard_filter_passed=True, hard_filter_details={}, qualification_pending=False,
            rule_score=20, vector_score=20, final_score=70, rerank_status="completed",
            evidence={
                "fact_ids": ["fact_advice"], "matching_facts": ["RAG 项目经验与岗位匹配"],
                "jd_quotes": ["熟悉 Python 并具备 RAG 项目经验"], "gaps": ["缺少生产部署经验"],
                "rule": {"skill_hits": ["Python", "RAG"]},
            },
        ))
        db.commit()
        advice = build_tailor_advice(db, job)

    assert advice["recommendation_version"] == 2
    assert advice["suggestions"][0]["section"] == "项目经历"
    assert "Python、RAG" in advice["suggestions"][0]["action"]
    assert advice["suggestions"][0]["current_text"] == "使用 Python 构建 RAG 课程项目"
    assert advice["suggestions"][0]["suggested_text"] == "使用 Python 构建 RAG 课程项目"
    assert advice["gaps"] == ["缺少生产部署经验"]


def test_long_confirmed_experience_can_be_validated_without_truncation() -> None:
    facts = fact_map()
    long_text = "负责模型评测与流程治理。" * 45
    facts["fact_safe"].redacted_text = long_text
    result = validate_sentences(
        [TailoredSentence(text=long_text, fact_ids=["fact_safe"])],
        facts,
    )

    assert len(long_text) > 500
    assert result["valid"] is True


@pytest.mark.asyncio
async def test_tailor_advice_only_appears_after_explicit_generation() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        document = ResumeDocument(
            original_name="fictional.md", stored_path="/tmp/fictional.md", media_type="text/markdown",
            content_hash="3" * 64, parse_status="parsed", redacted_text="",
        )
        job = JobPosting(
            company="虚构公司", source_key="manual", external_job_id="ADVICE-2", title="Python 工程师",
            description="熟悉 Python", normalized_url="https://example.invalid/jobs/advice-2", description_hash="4" * 64,
        )
        db.add_all([document, job]); db.flush()
        db.add(ResumeFact(
            fact_id="fact_saved_advice", category="project", original_text="使用 Python 完成课程项目",
            redacted_text="使用 Python 完成课程项目", document_id=document.id, content_hash="5" * 64,
            active=True, confirmed=True,
        ))
        db.add(Recommendation(
            job_id=job.id, version=1, hard_filter_passed=True, hard_filter_details={}, qualification_pending=False,
            rule_score=20, vector_score=20, final_score=70, rerank_status="completed",
            evidence={"fact_ids": ["fact_saved_advice"], "rule": {"skill_hits": ["Python"]}},
        ))
        db.commit()

        assert stored_tailor_advice(db, job.id) is None
        generated = await save_tailor_advice(db, job)
        stored = stored_tailor_advice(db, job.id)

        assert stored is not None
        assert stored["suggestions"] == generated["suggestions"]


@pytest.mark.asyncio
async def test_tailor_advice_uses_specific_llm_action_rewrite_and_rationale(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        document = ResumeDocument(
            original_name="fictional.md", stored_path="/tmp/fictional.md", media_type="text/markdown",
            content_hash="6" * 64, parse_status="parsed", redacted_text="",
        )
        job = JobPosting(
            company="虚构公司", source_key="manual", external_job_id="ADVICE-3", title="RAG 工程师",
            description="熟悉 Python，具备 RAG 项目经验", normalized_url="https://example.invalid/jobs/advice-3",
            description_hash="7" * 64,
        )
        db.add_all([document, job]); db.flush()
        db.add(ResumeFact(
            fact_id="fact_llm_advice", category="project", original_text="使用 Python 构建 RAG 课程项目",
            redacted_text="使用 Python 构建 RAG 课程项目", document_id=document.id, content_hash="8" * 64,
            active=True, confirmed=True,
        ))
        db.add(Recommendation(
            job_id=job.id, version=1, hard_filter_passed=True, hard_filter_details={}, qualification_pending=False,
            rule_score=20, vector_score=20, final_score=70, rerank_status="completed",
            evidence={
                "fact_ids": ["fact_llm_advice"], "matching_facts": ["已有 RAG 项目经验"],
                "jd_quotes": ["具备 RAG 项目经验"], "rule": {"skill_hits": ["Python", "RAG"]},
            },
        ))
        db.commit()

        async def fake_call(*args, **_kwargs):
            messages = args[2]
            assert "不得机械添加关键词前缀" in messages[0]["content"]
            assert "target_requirement" in messages[1]["content"]
            return StructuredResult(
                value=TailorAdviceLLMResponse(rewrites=[TailorAdviceRewrite(
                    fact_id="fact_llm_advice",
                    action="把技术栈和项目动作放到句首，直接对应 JD 的 RAG 项目要求。",
                    revised_text="基于 Python 构建 RAG 课程项目。",
                    rationale="原事实同时包含 Python 与 RAG，可直接支撑 JD 的项目经验要求。",
                )]),
                provider="codex",
                model_name="fictional-model",
            )

        monkeypatch.setattr(tailor_service, "llm_available", lambda *_args: (True, ""))
        monkeypatch.setattr(tailor_service, "call_structured", fake_call)
        generated = await save_tailor_advice(db, job, Settings())

    suggestion = generated["suggestions"][0]
    assert suggestion["action"].startswith("把技术栈和项目动作放到句首")
    assert suggestion["suggested_text"] == "基于 Python 构建 RAG 课程项目。"
    assert suggestion["rationale"].startswith("原事实同时包含 Python 与 RAG")
    assert "fact_id" not in suggestion


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
