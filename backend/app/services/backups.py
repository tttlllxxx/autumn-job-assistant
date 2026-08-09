from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import uuid
import zipfile
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import __version__
from app.core.config import Settings
from app.models.entities import (
    AppSetting,
    Application,
    CandidateProfile,
    CostLedger,
    JobPosting,
    Recommendation,
    RecommendationEvidence,
    ResumeDocument,
    ResumeFact,
    ResumeVersion,
    SourceHealth,
    SourceRun,
    UserFeedback,
    utcnow,
)
from app.services.applications_csv import export_csv

BACKUP_FORMAT_VERSION = 1
EXPORT_MODELS = (
    CandidateProfile,
    ResumeDocument,
    ResumeFact,
    JobPosting,
    SourceRun,
    SourceHealth,
    Recommendation,
    RecommendationEvidence,
    Application,
    ResumeVersion,
    UserFeedback,
    CostLedger,
)
RESTORE_ORDER = EXPORT_MODELS
DELETE_ORDER = tuple(reversed(EXPORT_MODELS))


def _json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _row(item: Any) -> dict[str, Any]:
    return {column.name: _json_value(getattr(item, column.name)) for column in item.__table__.columns}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def create_backup(db: Session, settings: Settings) -> tuple[str, Path, dict]:
    backup_id = f"backup-{utcnow().strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    output_path = settings.data_dir / "backups" / f"{backup_id}.zip"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    files: dict[str, bytes] = {}
    counts: dict[str, int] = {}
    for model in EXPORT_MODELS:
        items = db.scalars(select(model)).all()
        name = model.__tablename__
        counts[name] = len(items)
        rows = [_row(item) for item in items]
        if model is ResumeDocument:
            for item, row in zip(items, rows, strict=True):
                path = Path(item.stored_path)
                archive = f"resumes/originals/{item.id}{path.suffix.lower()}"
                row["stored_path"] = archive if path.is_file() else None
                if path.is_file():
                    files[archive] = path.read_bytes()
        elif model is ResumeVersion:
            for item, row in zip(items, rows, strict=True):
                if item.pdf_path:
                    path = Path(item.pdf_path)
                    archive = f"resumes/generated/{item.id}.pdf"
                    row["pdf_path"] = archive if path.is_file() else None
                    if path.is_file():
                        files[archive] = path.read_bytes()
        files[f"data/{name}.json"] = json.dumps(rows, ensure_ascii=False, sort_keys=True).encode("utf-8")
    applications = db.scalars(select(Application).order_by(Application.id)).all()
    files["applications.csv"] = export_csv(list(applications)).encode("utf-8")
    safe_settings = {
        item.key: item.value
        for item in db.scalars(select(AppSetting).where(AppSetting.secret.is_(False))).all()
        if not any(token in item.key.lower() for token in ("password", "secret", "api_key", "webhook", "token"))
    }
    files["config/settings.json"] = json.dumps(safe_settings, ensure_ascii=False, sort_keys=True).encode("utf-8")
    manifest = {
        "format_version": BACKUP_FORMAT_VERSION,
        "app_version": __version__,
        "created_at": utcnow().isoformat(),
        "record_counts": counts,
        "files": sorted([*files, "manifest.json", "checksums.sha256"]),
    }
    files["manifest.json"] = json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
    checksum_lines = [f"{_sha256(content)}  {name}" for name, content in sorted(files.items())]
    files["checksums.sha256"] = ("\n".join(checksum_lines) + "\n").encode()
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(files.items()):
            archive.writestr(name, content)
    return backup_id, output_path, manifest


def _validate_member(info: zipfile.ZipInfo, settings: Settings) -> None:
    path = PurePosixPath(info.filename)
    if path.is_absolute() or ".." in path.parts or "\\" in info.filename:
        raise ValueError("备份包含不安全路径")
    if info.file_size > settings.max_backup_bytes:
        raise ValueError("备份中的单个文件超过大小限制")
    mode = info.external_attr >> 16
    if mode and (mode & 0o170000) == 0o120000:
        raise ValueError("备份不允许包含符号链接")


def validate_backup(path: Path, settings: Settings) -> tuple[dict, dict[str, bytes]]:
    if path.stat().st_size > settings.max_backup_bytes:
        raise ValueError("备份文件超过大小限制")
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if len(infos) > 10_000:
            raise ValueError("备份文件数量超过限制")
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            raise ValueError("备份包含重复路径")
        total = 0
        for info in infos:
            _validate_member(info, settings)
            total += info.file_size
            if total > settings.max_backup_bytes:
                raise ValueError("备份解压后总大小超过限制")
        required = {"manifest.json", "checksums.sha256", "applications.csv", "config/settings.json"}
        if not required.issubset(names):
            raise ValueError("备份缺少必需文件")
        files = {name: archive.read(name) for name in names if not name.endswith("/")}
    try:
        manifest = json.loads(files["manifest.json"])
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("manifest.json 无效") from exc
    if manifest.get("format_version") != BACKUP_FORMAT_VERSION:
        raise ValueError("不支持的备份格式版本")
    if sorted(manifest.get("files", [])) != sorted(files):
        raise ValueError("备份文件清单不一致")
    expected: dict[str, str] = {}
    for line in files["checksums.sha256"].decode().splitlines():
        checksum, name = line.split("  ", 1)
        expected[name] = checksum
    for name, content in files.items():
        if name == "checksums.sha256":
            continue
        if expected.get(name) != _sha256(content):
            raise ValueError(f"文件校验和不匹配：{name}")
    return manifest, files


def _convert_row(model, row: dict[str, Any]) -> dict[str, Any]:
    allowed = {column.name: column for column in model.__table__.columns}
    if set(row) - set(allowed):
        raise ValueError(f"{model.__tablename__} 包含未知字段")
    converted = dict(row)
    for name, column in allowed.items():
        value = converted.get(name)
        if value is None:
            continue
        try:
            python_type = column.type.python_type
        except NotImplementedError:
            continue
        if python_type is datetime and isinstance(value, str):
            converted[name] = datetime.fromisoformat(value)
        elif python_type is date and isinstance(value, str):
            converted[name] = date.fromisoformat(value)
    return converted


def restore_backup(db: Session, settings: Settings, path: Path) -> dict[str, int]:
    manifest, files = validate_backup(path, settings)
    try:
        safe_settings = json.loads(files["config/settings.json"])
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("备份设置无效") from exc
    if not isinstance(safe_settings, dict) or any(
        any(token in str(key).lower() for token in ("password", "secret", "api_key", "webhook", "token"))
        for key in safe_settings
    ):
        raise ValueError("备份设置包含禁止的秘密字段")
    parsed: dict[Any, list[dict[str, Any]]] = {}
    for model in RESTORE_ORDER:
        name = f"data/{model.__tablename__}.json"
        try:
            rows = json.loads(files[name])
        except (KeyError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError(f"备份数据无效：{name}") from exc
        if not isinstance(rows, list):
            raise ValueError(f"备份数据不是数组：{name}")
        parsed[model] = [_convert_row(model, row) for row in rows]
    with tempfile.TemporaryDirectory(prefix="aja-restore-") as temp:
        temp_root = Path(temp)
        staged: dict[str, Path] = {}
        for name, content in files.items():
            if name.startswith("resumes/"):
                target = temp_root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
                staged[name] = target
        for row in parsed[ResumeDocument]:
            archive = row.get("stored_path")
            row["stored_path"] = str(settings.data_dir / "uploads" / f"restored-{row['id']}{Path(archive).suffix}") if archive else ""
        for row in parsed[ResumeVersion]:
            archive = row.get("pdf_path")
            row["pdf_path"] = str(settings.data_dir / "generated" / f"restored-{row['id']}.pdf") if archive else None
        prepared_files: list[tuple[Path, Path]] = []
        for row in parsed[ResumeDocument]:
            destination = Path(row["stored_path"])
            original = next((name for name in staged if name.startswith(f"resumes/originals/{row['id']}")), None)
            if original:
                destination.parent.mkdir(parents=True, exist_ok=True)
                prepared = destination.with_name(f".{destination.name}.restore-{uuid.uuid4().hex}.tmp")
                shutil.copy2(staged[original], prepared)
                prepared_files.append((prepared, destination))
        for row in parsed[ResumeVersion]:
            if row.get("pdf_path"):
                destination = Path(row["pdf_path"])
                destination.parent.mkdir(parents=True, exist_ok=True)
                prepared = destination.with_name(f".{destination.name}.restore-{uuid.uuid4().hex}.tmp")
                shutil.copy2(staged[f"resumes/generated/{row['id']}.pdf"], prepared)
                prepared_files.append((prepared, destination))
        installed_files: list[tuple[Path, Path | None]] = []
        try:
            for model in DELETE_ORDER:
                db.execute(delete(model))
            db.flush()
            db.expunge_all()
            for model in RESTORE_ORDER:
                db.add_all(model(**row) for row in parsed[model])
                db.flush()
            db.execute(delete(AppSetting).where(AppSetting.secret.is_(False)))
            for key, value in safe_settings.items():
                setting = db.get(AppSetting, str(key)) or AppSetting(key=str(key), secret=False)
                setting.value = value
                setting.secret = False
                db.add(setting)
            db.flush()
            for prepared, destination in prepared_files:
                rollback = None
                if destination.exists():
                    rollback = destination.with_name(f".{destination.name}.rollback-{uuid.uuid4().hex}.tmp")
                    destination.replace(rollback)
                installed_files.append((destination, rollback))
                prepared.replace(destination)
            db.commit()
        except Exception:
            db.rollback()
            for destination, rollback in reversed(installed_files):
                destination.unlink(missing_ok=True)
                if rollback is not None:
                    rollback.replace(destination)
            for prepared, _ in prepared_files:
                prepared.unlink(missing_ok=True)
            raise
        else:
            for _, rollback in installed_files:
                if rollback is not None:
                    rollback.unlink(missing_ok=True)
    return {**{model.__tablename__: len(rows) for model, rows in parsed.items()}, "settings": len(safe_settings)}
