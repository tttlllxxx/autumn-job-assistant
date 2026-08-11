from __future__ import annotations

import hashlib
import re
from collections import Counter
from datetime import UTC, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.target_policy import TARGET_POLICY, TargetPolicy
from app.models.entities import CandidateProfile, JobPosting, SourceHealth, SourceRun
from app.sources.base import CrawlContext, JobPayload, normalize_url
from app.sources.registry import REGISTRY, get_registry

USER_AGENT = "AutumnJobAssistant/0.1 (single-user personal job search)"


def _payload_rejection_reason(payload: JobPayload, policy: TargetPolicy = TARGET_POLICY) -> str | None:
    return policy.source_rejection_reason(payload.title, payload.description, payload.recruitment_type)


def _upsert_job(db: Session, source_key: str, company: str, payload: JobPayload) -> tuple[JobPosting, bool]:
    url = normalize_url(payload.application_url)
    job = db.scalar(
        select(JobPosting).where(
            (JobPosting.source_key == source_key) & (JobPosting.external_job_id == payload.external_job_id)
        )
    )
    description_hash = hashlib.sha256(payload.description.encode()).hexdigest()
    if job is None and not payload.evidence_metadata.get("shared_listing_url", False):
        job = db.scalar(select(JobPosting).where(JobPosting.normalized_url == url))
    if job is None:
        candidates = db.scalars(
            select(JobPosting).where(
                JobPosting.company == company,
                JobPosting.location == payload.location,
                JobPosting.description_hash == description_hash,
            )
        ).all()
        normalized_title = re.sub(r"\s+", "", payload.title).casefold()
        job = next(
            (item for item in candidates if re.sub(r"\s+", "", item.title).casefold() == normalized_title),
            None,
        )
    created = job is None
    if job is None:
        job = JobPosting(
            company=company,
            source_key=source_key,
            external_job_id=payload.external_job_id,
            title=payload.title,
            description=payload.description,
            normalized_url=url,
            description_hash=description_hash,
        )
        db.add(job)
    job.title = payload.title
    job.department = payload.department
    job.location = payload.location
    job.recruitment_type = payload.recruitment_type
    job.graduation_year = payload.graduation_year
    job.description = payload.description
    job.description_hash = description_hash
    job.evidence_metadata = payload.evidence_metadata
    job.published_at = payload.published_at
    job.last_seen_at = datetime.now(UTC)
    job.missing_count = 0
    job.closed = False
    return job, created


async def run_source(db: Session, source_key: str, *, allow_browser: bool = False, max_jobs: int = 500) -> SourceRun:
    adapter = get_registry(db)[source_key]
    run = SourceRun(source_key=source_key, adapter_version=adapter.parser_version)
    db.add(run)
    db.commit()
    seen_ids: set[str] = set()
    rejection_reasons: Counter[str] = Counter()
    policy_rejected_count = 0
    profile = db.get(CandidateProfile, 1)
    policy = (
        TargetPolicy(
            graduation_year=profile.target_graduation_year or TARGET_POLICY.graduation_year,
            allow_internship=TargetPolicy.targets_include_internship(profile.target_recruitment_types),
        )
        if profile
        else TARGET_POLICY
    )
    context: CrawlContext | None = None
    try:
        async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
            context = CrawlContext(client=client, allow_browser=allow_browser, max_jobs=max_jobs)
            stubs = await adapter.discover(context)
            run.discovered_count = len(stubs)
            for stub in stubs:
                try:
                    payload = await adapter.fetch_detail(stub, context)
                    if not payload.title or not payload.description:
                        rejection_reasons["字段不完整"] += 1
                        continue
                    if not adapter._is_official(payload.application_url):
                        rejection_reasons["非官方申请链接"] += 1
                        continue
                    rejection_reason = _payload_rejection_reason(payload, policy)
                    if rejection_reason is not None:
                        rejection_reasons[rejection_reason] += 1
                        policy_rejected_count += 1
                        continue
                    if payload.external_job_id in seen_ids:
                        rejection_reasons["重复岗位"] += 1
                        continue
                    _, created = _upsert_job(db, source_key, adapter.display_name, payload)
                    seen_ids.add(payload.external_job_id)
                    run.new_count += int(created)
                    run.updated_count += int(not created)
                except (httpx.HTTPError, ValueError):
                    rejection_reasons["详情解析失败"] += 1
                    continue
            if not seen_ids and not policy_rejected_count:
                raise ValueError("未采集到字段完整的有效岗位")
        active_jobs = db.scalars(
            select(JobPosting).where(JobPosting.source_key == source_key, JobPosting.closed.is_(False))
        ).all()
        for job in active_jobs:
            if job.external_job_id not in seen_ids:
                job.missing_count += 1
                if job.missing_count >= 3:
                    job.closed = True
        run.success = True
        health = db.get(SourceHealth, source_key) or SourceHealth(source_key=source_key)
        health.status = "healthy"
        health.last_success_at = datetime.now(UTC)
        health.consecutive_failures = 0
        health.last_error = None
        db.add(health)
        db.flush()
    except Exception as exc:
        db.rollback()
        run = db.get(SourceRun, run.id)
        assert run is not None
        run.success = False
        run.error_type = type(exc).__name__
        run.error_message = str(exc)[:500]
        health = db.get(SourceHealth, source_key) or SourceHealth(source_key=source_key)
        health.status = "degraded"
        health.consecutive_failures = (health.consecutive_failures or 0) + 1
        health.last_error = f"{type(exc).__name__}: {str(exc)[:300]}"
        db.add(health)
    run.finished_at = datetime.now(UTC)
    run.accepted_count = len(seen_ids)
    run.rejected_count = sum(rejection_reasons.values())
    run.rejection_reasons = dict(rejection_reasons)
    if context is not None:
        run.request_count = context.request_count
        run.encountered_auth = context.encountered_auth
    db.commit()
    db.refresh(run)
    return run


async def run_all_sources(*, allow_browser: bool = False, max_jobs: int = 500) -> None:
    from app.core.database import SessionLocal

    with SessionLocal() as db:
        source_keys = list(get_registry(db))
    for source_key in source_keys:
        with SessionLocal() as db:
            await run_source(db, source_key, allow_browser=allow_browser, max_jobs=max_jobs)
