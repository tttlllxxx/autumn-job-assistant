from __future__ import annotations

import hashlib
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_session, require_csrf
from app.models.entities import AuthSession, JobPosting
from app.schemas.jobs import JobImport, JobOut, JobPage
from app.sources.base import normalize_url

router = APIRouter(prefix="/api/jobs", tags=["岗位"])


@router.post("/import", response_model=JobOut, dependencies=[Depends(require_csrf)])
def import_job(payload: JobImport, db: Session = Depends(get_db)) -> JobPosting:
    url = normalize_url(str(payload.url))
    existing = db.scalar(select(JobPosting).where(JobPosting.normalized_url == url))
    if existing:
        return existing
    description_hash = hashlib.sha256(payload.description.encode()).hexdigest()
    job = JobPosting(
        company=payload.company,
        source_key="manual",
        external_job_id=f"manual_{uuid.uuid4().hex}",
        title=payload.title,
        department=payload.department,
        location=payload.location,
        recruitment_type=payload.recruitment_type,
        graduation_year=payload.graduation_year,
        description=payload.description,
        normalized_url=url,
        description_hash=description_hash,
        evidence_metadata={"method": "manual_import", "untrusted_text": True},
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


@router.get("", response_model=JobPage)
def list_jobs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    company: str | None = None,
    keyword: str | None = None,
    closed: bool | None = False,
    _: AuthSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> JobPage:
    filters = []
    if company:
        filters.append(JobPosting.company == company)
    if keyword:
        escaped = keyword.replace("%", "\\%").replace("_", "\\_")
        filters.append(or_(JobPosting.title.ilike(f"%{escaped}%"), JobPosting.description.ilike(f"%{escaped}%")))
    if closed is not None:
        filters.append(JobPosting.closed.is_(closed))
    total = db.scalar(select(func.count(JobPosting.id)).where(*filters)) or 0
    items = db.scalars(
        select(JobPosting)
        .where(*filters)
        .order_by(JobPosting.first_seen_at.desc(), JobPosting.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return JobPage(items=list(items), total=total, page=page, page_size=page_size)


@router.get("/{job_id}", response_model=JobOut)
def get_job(
    job_id: int,
    _: AuthSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> JobPosting:
    job = db.get(JobPosting, job_id)
    if not job:
        raise HTTPException(404, "岗位不存在")
    return job

