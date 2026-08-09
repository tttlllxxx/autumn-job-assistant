from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.security import get_current_session, require_csrf
from app.models.entities import AuthSession, JobPosting, Recommendation, ResumeVersion
from app.schemas.jobs import JobOut
from app.schemas.tailor import ResumeVersionOut, TailorAdviceOut, TailorAdviceSummaryOut, TailorRequest
from app.services.tailor import create_tailored_resume, save_tailor_advice, stored_tailor_advice

router = APIRouter(prefix="/api", tags=["定制简历"])


def _out(version: ResumeVersion) -> ResumeVersionOut:
    return ResumeVersionOut.model_validate(version).model_copy(update={"has_pdf": bool(version.pdf_path)})


@router.get("/jobs/{job_id}/tailor-advice", response_model=TailorAdviceOut)
def tailor_advice(
    job_id: int,
    _: AuthSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> dict:
    job = db.get(JobPosting, job_id)
    if not job or job.closed:
        raise HTTPException(404, "岗位不存在或已关闭")
    advice = stored_tailor_advice(db, job_id)
    if advice is None:
        raise HTTPException(404, "请先在岗位推荐页生成修改建议")
    return {**advice, "job": JobOut.model_validate(job).model_dump()}


@router.post(
    "/jobs/{job_id}/tailor-advice",
    response_model=TailorAdviceOut,
    dependencies=[Depends(require_csrf)],
)
async def generate_tailor_advice(
    job_id: int,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    job = db.get(JobPosting, job_id)
    if not job or job.closed:
        raise HTTPException(404, "岗位不存在或已关闭")
    try:
        advice = await save_tailor_advice(db, job, settings)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {**advice, "job": JobOut.model_validate(job).model_dump()}


@router.get("/tailor-advice", response_model=list[TailorAdviceSummaryOut])
def list_tailor_advice(
    _: AuthSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> list[dict]:
    rows = db.execute(
        select(Recommendation, JobPosting)
        .join(JobPosting, JobPosting.id == Recommendation.job_id)
        .order_by(Recommendation.created_at.desc(), Recommendation.id.desc())
    ).all()
    seen: set[int] = set()
    items = []
    for recommendation, job in rows:
        if job.id in seen:
            continue
        stored = (recommendation.evidence or {}).get("tailor_advice")
        if not isinstance(stored, dict):
            continue
        seen.add(job.id)
        items.append({
            "job": JobOut.model_validate(job).model_dump(),
            "recommendation_version": stored["recommendation_version"],
            "updated_at": stored["updated_at"],
            "suggestion_count": len(stored.get("suggestions", [])),
        })
    return items


@router.post("/jobs/{job_id}/tailor", response_model=ResumeVersionOut, dependencies=[Depends(require_csrf)])
async def tailor(
    job_id: int,
    payload: TailorRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ResumeVersionOut:
    if not payload.confirmed:
        raise HTTPException(409, "必须由用户明确确认目标岗位后才能生成")
    job = db.get(JobPosting, job_id)
    if not job or job.closed:
        raise HTTPException(404, "岗位不存在或已关闭")
    try:
        version = await create_tailored_resume(db, settings, job, payload.sentences)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return _out(version)


@router.get("/resume-versions", response_model=list[ResumeVersionOut])
def list_versions(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    status: str | None = None,
    job_id: int | None = Query(default=None, ge=1),
    _: AuthSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> list[ResumeVersionOut]:
    filters = []
    if status:
        filters.append(ResumeVersion.status == status)
    if job_id is not None:
        filters.append(ResumeVersion.job_id == job_id)
    items = db.scalars(
        select(ResumeVersion)
        .where(*filters)
        .order_by(ResumeVersion.created_at.desc(), ResumeVersion.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return [_out(item) for item in items]


@router.get("/resume-versions/{version_id}/download")
def download_version(
    version_id: int,
    _: AuthSession = Depends(get_current_session),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    version = db.get(ResumeVersion, version_id)
    if not version or version.status != "completed" or not version.pdf_path:
        raise HTTPException(404, "该版本没有可下载的 PDF")
    path = Path(version.pdf_path).resolve()
    generated_dir = (settings.data_dir / "generated").resolve()
    if generated_dir not in path.parents or not path.is_file():
        raise HTTPException(404, "PDF 文件不存在")
    return FileResponse(path, media_type="application/pdf", filename=f"tailored-resume-{version.id}.pdf")
