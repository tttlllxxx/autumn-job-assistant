from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.security import get_current_session, require_csrf
from app.models.entities import AuthSession, CandidateProfile, ResumeDocument, ResumeFact
from app.schemas.resumes import FactAction, FactOut, ProfileOut, ProfileUpdate, ResumeOut
from app.services.resumes import build_profile, create_resume, reparse_document, revise_fact
from app.services.task_runs import TaskAlreadyRunningError, begin_task, fail_task, finish_task

router = APIRouter(prefix="/api", tags=["简历与画像"])


@router.post("/resumes", response_model=ResumeOut, dependencies=[Depends(require_csrf)])
async def upload_resume(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ResumeDocument:
    if not file.filename:
        raise HTTPException(422, "文件名不能为空")
    content = await file.read(settings.max_upload_bytes + 1)
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(413, f"简历不能超过 {settings.max_upload_bytes // 1024 // 1024} MB")
    try:
        task = begin_task(db, "resume_parse", message="正在解析简历")
    except TaskAlreadyRunningError as exc:
        raise HTTPException(409, str(exc)) from exc
    try:
        document = create_resume(
            db,
            filename=file.filename,
            content=content,
            upload_dir=settings.data_dir / "uploads",
        )
    except ValueError as exc:
        fail_task(db, task.id, exc)
        raise HTTPException(422, str(exc)) from exc
    if document.parse_status != "failed":
        build_profile(db)
    result = db.scalar(
        select(ResumeDocument)
        .options(selectinload(ResumeDocument.facts))
        .where(ResumeDocument.id == document.id)
    )
    assert result is not None
    if result.parse_status == "failed":
        fail_task(db, task.id, ValueError(result.parse_error or "简历解析失败"))
    else:
        finish_task(db, task.id, {"document_id": result.id, "parse_status": result.parse_status})
    return result


@router.get("/resumes", response_model=list[ResumeOut])
def list_resumes(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    parse_status: str | None = None,
    _: AuthSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> list[ResumeDocument]:
    filters = [ResumeDocument.parse_status == parse_status] if parse_status else []
    return list(
        db.scalars(
            select(ResumeDocument)
            .options(selectinload(ResumeDocument.facts))
            .where(*filters)
            .order_by(ResumeDocument.created_at.desc(), ResumeDocument.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).unique()
    )


@router.post("/resumes/{document_id}/reparse", response_model=ResumeOut, dependencies=[Depends(require_csrf)])
def reparse_resume(document_id: int, db: Session = Depends(get_db)) -> ResumeDocument:
    document = db.get(ResumeDocument, document_id)
    if not document:
        raise HTTPException(404, "简历不存在")
    try:
        reparse_document(db, document)
        build_profile(db)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return db.scalar(
        select(ResumeDocument)
        .options(selectinload(ResumeDocument.facts))
        .where(ResumeDocument.id == document_id)
    )


@router.get("/profile", response_model=ProfileOut)
def get_profile(
    _: AuthSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> CandidateProfile:
    profile = db.get(CandidateProfile, 1)
    if not profile:
        raise HTTPException(404, "尚未导入可解析的简历")
    return profile


@router.patch("/profile", response_model=ProfileOut, dependencies=[Depends(require_csrf)])
def update_profile(payload: ProfileUpdate, db: Session = Depends(get_db)) -> CandidateProfile:
    profile = db.get(CandidateProfile, 1)
    if not profile:
        raise HTTPException(404, "尚未导入可解析的简历")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(profile, key, value)
    profile.confirmed = False
    profile.version += 1
    db.commit()
    db.refresh(profile)
    return profile


@router.post("/profile/confirm", response_model=ProfileOut, dependencies=[Depends(require_csrf)])
def confirm_profile(db: Session = Depends(get_db)) -> CandidateProfile:
    profile = db.get(CandidateProfile, 1)
    if not profile:
        raise HTTPException(404, "尚未导入可解析的简历")
    facts = db.scalars(select(ResumeFact).where(ResumeFact.active.is_(True))).all()
    if not facts:
        raise HTTPException(409, "没有可确认的简历事实")
    for fact in facts:
        fact.confirmed = True
    profile.confirmed = True
    profile.version += 1
    db.commit()
    db.refresh(profile)
    return profile


@router.post("/facts/{fact_id}", response_model=FactOut, dependencies=[Depends(require_csrf)])
def change_fact(fact_id: str, payload: FactAction, db: Session = Depends(get_db)) -> ResumeFact:
    fact = db.scalar(
        select(ResumeFact).options(selectinload(ResumeFact.document)).where(ResumeFact.fact_id == fact_id)
    )
    if not fact or not fact.active:
        raise HTTPException(404, "事实不存在或已停用")
    if payload.action == "confirm":
        fact.confirmed = True
    elif payload.action == "disable":
        fact.active = False
    else:
        if payload.text is None:
            raise HTTPException(422, "修改事实时必须提供 text")
        try:
            replacement = revise_fact(db, fact, payload.text)
            build_profile(db)
            return replacement
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    db.commit()
    build_profile(db)
    db.refresh(fact)
    return fact
