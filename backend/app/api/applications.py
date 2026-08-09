from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_session, require_csrf
from app.models.entities import Application, AuthSession
from app.schemas.applications import ApplicationInput, ApplicationOut, ApplicationPage, ApplicationPatch
from app.services.applications_csv import STAGE_RESULT_VALUES, STAGE_VALUES, STATUS_VALUES, export_csv, parse_csv

router = APIRouter(prefix="/api/applications", tags=["投递管理"])


def _validate_enums(status: str, stage: str, result: str) -> None:
    if status and status not in STATUS_VALUES:
        raise HTTPException(422, "状态不在允许的枚举中")
    if stage and stage not in STAGE_VALUES:
        raise HTTPException(422, "当前阶段不在允许的枚举中")
    if result and result not in STAGE_RESULT_VALUES:
        raise HTTPException(422, "阶段结果不在允许的枚举中")


@router.get("", response_model=ApplicationPage)
def list_applications(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    status: str | None = None,
    _: AuthSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> ApplicationPage:
    filters = [Application.status == status] if status else []
    total = db.scalar(select(func.count(Application.id)).where(*filters)) or 0
    items = db.scalars(
        select(Application)
        .where(*filters)
        .order_by(Application.progress_updated_at.desc().nullslast(), Application.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return ApplicationPage(items=list(items), total=total, page=page, page_size=page_size)


@router.post("", response_model=ApplicationOut, dependencies=[Depends(require_csrf)])
def create_application(payload: ApplicationInput, db: Session = Depends(get_db)) -> Application:
    _validate_enums(payload.status, payload.current_stage, payload.stage_result)
    item = Application(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.patch("/{application_id}", response_model=ApplicationOut, dependencies=[Depends(require_csrf)])
def update_application(application_id: int, payload: ApplicationPatch, db: Session = Depends(get_db)) -> Application:
    item = db.get(Application, application_id)
    if not item:
        raise HTTPException(404, "投递记录不存在")
    changes = payload.model_dump(exclude_unset=True)
    status = changes.get("status", item.status)
    stage = changes.get("current_stage", item.current_stage)
    result = changes.get("stage_result", item.stage_result)
    _validate_enums(status, stage, result)
    for key, value in changes.items():
        setattr(item, key, value)
    if changes:
        item.raw_values = {}
    db.commit()
    db.refresh(item)
    return item


@router.post("/import-csv", dependencies=[Depends(require_csrf)])
async def import_applications_csv(
    file: UploadFile = File(...),
    commit: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> dict:
    content = await file.read(10 * 1024 * 1024 + 1)
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(413, "CSV 不能超过 10 MB")
    try:
        rows, errors = parse_csv(content)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if errors:
        return {"valid": False, "rows": len(rows) + len(errors), "errors": errors, "committed": 0}
    if commit:
        db.add_all(Application(**row) for row in rows)
        db.commit()
    return {"valid": True, "rows": len(rows), "errors": [], "committed": len(rows) if commit else 0}


@router.get("/export-csv")
def export_applications_csv(
    _: AuthSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> Response:
    applications = db.scalars(select(Application).order_by(Application.id)).all()
    content = export_csv(list(applications)).encode("utf-8")
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="applications.csv"'},
    )

