from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models.entities import CandidateProfile, ResumeDocument, ResumeFact
from app.services.resumes import build_profile, reparse_document


def test_reparse_retires_old_fragments_but_preserves_user_revisions(tmp_path: Path) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    path = tmp_path / "resume.md"
    path.write_text("## 项目经历\n- 新版完整项目事实\n", encoding="utf-8")
    with Session(engine) as db:
        document = ResumeDocument(
            original_name="resume.md", stored_path=str(path), media_type="text/markdown",
            content_hash="a" * 64, parse_status="parsed", redacted_text="旧内容",
        )
        db.add(document)
        db.flush()
        old = ResumeFact(
            fact_id="fact_old", category="other", original_text="旧版碎片", redacted_text="旧版碎片",
            document_id=document.id, content_hash="b" * 64,
        )
        revision = ResumeFact(
            fact_id="fact_revision", category="project", original_text="用户修订", redacted_text="用户修订",
            document_id=document.id, content_hash="c" * 64, supersedes_fact_id="fact_previous",
        )
        db.add_all([old, revision])
        db.commit()

        reparse_document(db, document)

        assert old.active is False
        assert revision.active is True
        assert any(fact.active and fact.redacted_text == "新版完整项目事实" for fact in document.facts)


def test_reparse_latest_same_name_resume_retires_older_version_facts(tmp_path: Path) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    old_path = tmp_path / "old.md"
    new_path = tmp_path / "new.md"
    old_path.write_text("## 工作经历\n旧公司 · 旧岗位\n", encoding="utf-8")
    new_path.write_text("## 工作经历\n新公司 · 新岗位\n", encoding="utf-8")
    with Session(engine) as db:
        old_document = ResumeDocument(
            original_name="resume.md", stored_path=str(old_path), media_type="text/markdown",
            content_hash="a" * 64, parse_status="parsed", redacted_text="旧内容",
        )
        new_document = ResumeDocument(
            original_name="resume.md", stored_path=str(new_path), media_type="text/markdown",
            content_hash="b" * 64, parse_status="parsed", redacted_text="新内容",
        )
        db.add_all([old_document, new_document])
        db.flush()
        old_fact = ResumeFact(
            fact_id="fact_old_version", category="experience", original_text="旧公司 · 旧岗位",
            redacted_text="旧公司 · 旧岗位", document_id=old_document.id, content_hash="c" * 64,
        )
        db.add(old_fact)
        db.commit()

        reparse_document(db, new_document)

        assert old_fact.active is False
        assert any(fact.active and fact.redacted_text == "新公司 · 新岗位" for fact in new_document.facts)


def test_build_profile_preserves_saved_target_direction_preferences() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        profile = CandidateProfile(id=1, target_directions=["RAG 工程"], confirmed=True)
        document = ResumeDocument(
            original_name="resume.md", stored_path="/tmp/resume.md", media_type="text/markdown",
            content_hash="a" * 64, parse_status="parsed", redacted_text="算法经历",
        )
        db.add_all([profile, document])
        db.flush()
        db.add(ResumeFact(
            fact_id="fact_algorithm", category="experience", original_text="负责算法开发",
            redacted_text="负责算法开发", document_id=document.id, content_hash="b" * 64,
        ))
        db.commit()

        updated = build_profile(db)

        assert updated.target_directions == ["RAG 工程"]
        assert updated.experience_summary == "负责算法开发"
        assert updated.confirmed is False
