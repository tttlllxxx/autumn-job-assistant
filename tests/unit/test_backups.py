import zipfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.database import Base
from app.models.entities import AdminCredential, AppSetting, CandidateProfile, ResumeDocument, ResumeFact
from app.services.backups import create_backup, restore_backup, validate_backup


def seed(db: Session, data_dir: Path) -> None:
    original = data_dir / "uploads" / "fictional.md"
    original.parent.mkdir(parents=True, exist_ok=True)
    original.write_text("虚构候选人简历", encoding="utf-8")
    profile = CandidateProfile(id=1, target_directions=["RAG 工程"], skills=["Python"], confirmed=True)
    document = ResumeDocument(
        original_name="fictional.md",
        stored_path=str(original),
        media_type="text/markdown",
        content_hash="a" * 64,
        parse_status="parsed",
        redacted_text="使用 Python 构建课程项目",
    )
    db.add_all(
        [
            profile,
            document,
            AdminCredential(id=1, password_hash="SECRET_PASSWORD_HASH"),
            AppSetting(key="theme", value="light", secret=False),
            AppSetting(key="feishu_webhook", value="SECRET_WEBHOOK", secret=True),
        ]
    )
    db.flush()
    db.add(
        ResumeFact(
            fact_id="fact_backup",
            category="project",
            original_text="使用 Python 构建课程项目",
            redacted_text="使用 Python 构建课程项目",
            document_id=document.id,
            content_hash="b" * 64,
            confirmed=True,
        )
    )
    db.commit()


def test_backup_excludes_secrets_and_restores_profile_files_and_settings(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, model_cache_dir=tmp_path / "models")
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        seed(db, tmp_path)
        _backup_id, path, manifest = create_backup(db, settings)
        raw = path.read_bytes()
        assert b"SECRET_PASSWORD_HASH" not in raw
        assert b"SECRET_WEBHOOK" not in raw
        assert manifest["format_version"] == 1

        profile = db.get(CandidateProfile, 1)
        profile.skills = ["被修改"]
        db.add(AppSetting(key="backup_later_setting", value="must disappear", secret=False))
        db.commit()
        counts = restore_backup(db, settings, path)
        db.expire_all()

        restored = db.get(CandidateProfile, 1)
        assert restored.skills == ["Python"]
        assert db.scalar(select(ResumeFact).where(ResumeFact.fact_id == "fact_backup")) is not None
        assert Path(db.scalar(select(ResumeDocument)).stored_path).read_text(encoding="utf-8") == "虚构候选人简历"
        assert db.get(AppSetting, "theme").value == "light"
        assert db.get(AppSetting, "feishu_webhook").value == "SECRET_WEBHOOK"
        assert db.get(AppSetting, "backup_later_setting") is None
        assert counts["candidate_profiles"] == 1


def test_zip_slip_is_rejected_before_extraction(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, model_cache_dir=tmp_path / "models")
    path = tmp_path / "malicious.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("../escape.txt", "bad")
    with pytest.raises(ValueError, match="不安全路径"):
        validate_backup(path, settings)
    assert not (tmp_path.parent / "escape.txt").exists()


def test_checksum_tampering_is_rejected_without_database_change(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, model_cache_dir=tmp_path / "models")
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        seed(db, tmp_path)
        _, original, _ = create_backup(db, settings)
        tampered = tmp_path / "tampered.zip"
        with zipfile.ZipFile(original) as source, zipfile.ZipFile(tampered, "w") as target:
            for info in source.infolist():
                content = source.read(info.filename)
                if info.filename == "config/settings.json":
                    content = b'{"theme":"tampered"}'
                target.writestr(info, content)
        with pytest.raises(ValueError, match="校验和"):
            restore_backup(db, settings, tampered)
        assert db.get(CandidateProfile, 1).skills == ["Python"]
