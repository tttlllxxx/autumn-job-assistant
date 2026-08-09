from pathlib import Path
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.security import get_current_session, require_csrf
from app.models.entities import AuthSession
from app.services.backups import create_backup, restore_backup

router = APIRouter(prefix="/api", tags=["备份恢复"])


@router.post("/backups", dependencies=[Depends(require_csrf)])
def create(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> dict:
    backup_id, path, manifest = create_backup(db, settings)
    return {"backup_id": backup_id, "filename": path.name, "manifest": manifest}


@router.get("/backups/{backup_id}/download")
def download(
    backup_id: str,
    _: AuthSession = Depends(get_current_session),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    if not backup_id.startswith("backup-") or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for char in backup_id):
        raise HTTPException(404, "备份不存在")
    path = (settings.data_dir / "backups" / f"{backup_id}.zip").resolve()
    backup_dir = (settings.data_dir / "backups").resolve()
    if backup_dir not in path.parents or not path.is_file():
        raise HTTPException(404, "备份不存在")
    return FileResponse(path, media_type="application/zip", filename=path.name)


@router.post("/restore", dependencies=[Depends(require_csrf)])
async def restore(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    content = await file.read(settings.max_backup_bytes + 1)
    if len(content) > settings.max_backup_bytes:
        raise HTTPException(413, "备份文件超过大小限制")
    temp_path = settings.data_dir / "backups" / f"restore-upload-{uuid.uuid4().hex}.zip"
    temp_path.write_bytes(content)
    try:
        counts = restore_backup(db, settings, temp_path)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        temp_path.unlink(missing_ok=True)
    return {"success": True, "restored_counts": counts}

