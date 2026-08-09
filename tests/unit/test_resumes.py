from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models.entities import ResumeDocument, ResumeFact
from app.services.resumes import reparse_document


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
