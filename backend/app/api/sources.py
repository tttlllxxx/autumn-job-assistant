import ipaddress
import uuid
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_session, require_csrf
from app.models.entities import AuthSession, CandidateProfile, JobPosting, SourceHealth, SourceRun
from app.schemas.jobs import CustomSourceCreate, SourceRunRequest, SourceUpdate
from app.sources.registry import (
    custom_source_configs,
    get_registry,
    save_custom_source_configs,
    save_source_entry_overrides,
    source_entry_overrides,
)
from app.sources.runner import run_source
from app.services.task_runs import TaskAlreadyRunningError, begin_task, fail_task, finish_task, update_task

router = APIRouter(prefix="/api/sources", tags=["招聘来源"])


@router.get("")
def list_sources(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    status: str | None = None,
    _: AuthSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> list[dict]:
    registry = get_registry(db)
    profile = db.get(CandidateProfile, 1)
    target_year = profile.target_graduation_year if profile else "2027"
    health = {item.source_key: item for item in db.scalars(select(SourceHealth)).all()}
    latest_run_ids = select(
        SourceRun.source_key,
        func.max(SourceRun.id).label("run_id"),
    ).group_by(SourceRun.source_key).subquery()
    latest_runs = {
        item.source_key: item
        for item in db.scalars(
            select(SourceRun).join(latest_run_ids, SourceRun.id == latest_run_ids.c.run_id)
        ).all()
    }
    job_counts: dict[str, int] = {}
    year_unverified_counts: dict[str, int] = {}
    for source_key, graduation_year, count in db.execute(
        select(JobPosting.source_key, JobPosting.graduation_year, func.count(JobPosting.id))
        .where(JobPosting.closed.is_(False))
        .group_by(JobPosting.source_key, JobPosting.graduation_year)
    ).all():
        job_counts[source_key] = job_counts.get(source_key, 0) + count
        if not graduation_year or target_year not in graduation_year:
            year_unverified_counts[source_key] = year_unverified_counts.get(source_key, 0) + count
    items = [
        {
            "source_key": key,
            "display_name": adapter.display_name,
            "official_entry": adapter.start_url,
            "parser_version": adapter.parser_version,
            "collection_method": adapter.collection_method,
            "status": health[key].status if key in health else "unknown",
            "last_success_at": health[key].last_success_at if key in health else None,
            "last_run_at": latest_runs[key].finished_at if key in latest_runs else None,
            "active_job_count": job_counts.get(key, 0),
            "year_unverified_count": year_unverified_counts.get(key, 0),
            "target_graduation_year": target_year,
            "last_discovered_count": latest_runs[key].discovered_count if key in latest_runs else 0,
            "last_accepted_count": latest_runs[key].accepted_count if key in latest_runs else 0,
            "last_rejected_count": latest_runs[key].rejected_count if key in latest_runs else 0,
            "last_rejection_reasons": latest_runs[key].rejection_reasons if key in latest_runs else {},
            "consecutive_failures": health[key].consecutive_failures if key in health else 0,
            "last_error": health[key].last_error if key in health else None,
            "stable_for_acceptance": health[key].stable_for_acceptance if key in health else False,
            "custom": key.startswith("custom_"),
        }
        for key, adapter in registry.items()
        if status is None or (health[key].status if key in health else "unknown") == status
    ]
    return items[(page - 1) * page_size : page * page_size]


@router.get("/runs")
def list_runs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    source_key: str | None = None,
    _: AuthSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> dict:
    filters = [SourceRun.source_key == source_key] if source_key else []
    total = db.scalar(select(func.count(SourceRun.id)).where(*filters)) or 0
    items = db.scalars(
        select(SourceRun)
        .where(*filters)
        .order_by(SourceRun.started_at.desc(), SourceRun.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "items": [
            {column.name: getattr(item, column.name) for column in SourceRun.__table__.columns}
            for item in items
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("/run", dependencies=[Depends(require_csrf)])
async def trigger_run(payload: SourceRunRequest, db: Session = Depends(get_db)) -> dict:
    registry = get_registry(db)
    source_keys = payload.source_keys or list(registry)
    invalid = sorted(set(source_keys) - set(registry))
    if invalid:
        raise HTTPException(422, f"未知来源：{', '.join(invalid)}")
    try:
        task = begin_task(db, "source_run", total=len(source_keys), message="正在采集招聘来源")
    except TaskAlreadyRunningError as exc:
        raise HTTPException(409, str(exc)) from exc
    results = []
    try:
        for index, key in enumerate(source_keys, start=1):
            run = await run_source(
                db,
                key,
                allow_browser=payload.allow_browser,
                max_jobs=payload.max_jobs_per_source,
            )
            results.append({
                "source_key": key,
                "run_id": run.id,
                "success": run.success,
                "discovered": run.discovered_count,
                "accepted": run.accepted_count,
                "rejected": run.rejected_count,
                "rejection_reasons": run.rejection_reasons,
                "error": run.error_message,
            })
            update_task(db, task.id, current=index, message=f"已完成 {key}")
        result = {"results": results}
        finish_task(db, task.id, result)
        return result
    except Exception as exc:
        fail_task(db, task.id, exc)
        raise


def _validate_public_entry(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if parsed.scheme != "https" or not host:
        raise HTTPException(422, "请填写 HTTPS 官方招聘入口")
    if host == "localhost" or host.endswith(".local"):
        raise HTTPException(422, "官方招聘入口不能指向本地地址")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise HTTPException(422, "官方招聘入口不能指向内网地址")
    return url


@router.post("/custom", dependencies=[Depends(require_csrf)])
async def add_custom_source(
    payload: CustomSourceCreate,
    db: Session = Depends(get_db),
) -> dict:
    entry = _validate_public_entry(str(payload.official_entry))
    configs = custom_source_configs(db)
    normalized_name = payload.company.strip()
    if not normalized_name:
        raise HTTPException(422, "公司名称不能只包含空格")
    if any(item.get("display_name") == normalized_name or item.get("official_entry") == entry for item in configs):
        raise HTTPException(409, "该公司或官方入口已添加")
    source_key = f"custom_{uuid.uuid4().hex[:12]}"
    try:
        task = begin_task(db, "custom_source_parse", scope_key=source_key, total=1, message="正在解析公司岗位")
    except TaskAlreadyRunningError as exc:
        raise HTTPException(409, str(exc)) from exc
    try:
        configs.append({"source_key": source_key, "display_name": normalized_name, "official_entry": entry})
        save_custom_source_configs(db, configs)
        run = await run_source(db, source_key, allow_browser=True, max_jobs=500)
        result = {
            "source_key": source_key,
            "success": run.success,
            "discovered": run.discovered_count,
            "accepted": getattr(run, "accepted_count", run.new_count + run.updated_count),
            "rejected": getattr(run, "rejected_count", 0),
            "new": run.new_count,
            "updated": run.updated_count,
            "error": run.error_message,
            "finished_at": run.finished_at,
        }
        finish_task(db, task.id, {key: value for key, value in result.items() if key != "finished_at"})
        return result
    except Exception as exc:
        fail_task(db, task.id, exc)
        raise


@router.patch("/{source_key}", dependencies=[Depends(require_csrf)])
async def update_source_entry(source_key: str, payload: SourceUpdate, db: Session = Depends(get_db)) -> dict:
    registry = get_registry(db)
    if source_key not in registry:
        raise HTTPException(404, "数据来源不存在")
    entry = _validate_public_entry(str(payload.official_entry))
    if any(key != source_key and adapter.start_url == entry for key, adapter in registry.items()):
        raise HTTPException(409, "该官方入口已被其他来源使用")
    try:
        task = begin_task(db, "source_entry_update", scope_key=source_key, total=1, message="正在更新并解析官方入口")
    except TaskAlreadyRunningError as exc:
        raise HTTPException(409, str(exc)) from exc
    try:
        if source_key.startswith("custom_"):
            configs = custom_source_configs(db)
            for item in configs:
                if item.get("source_key") == source_key:
                    item["official_entry"] = entry
                    break
            else:
                raise HTTPException(404, "自定义来源不存在")
            save_custom_source_configs(db, configs)
        else:
            overrides = source_entry_overrides(db)
            overrides[source_key] = entry
            save_source_entry_overrides(db, overrides)
        run = await run_source(db, source_key, allow_browser=True, max_jobs=500)
        result = {
            "source_key": source_key,
            "official_entry": entry,
            "success": run.success,
            "discovered": run.discovered_count,
            "accepted": getattr(run, "accepted_count", run.new_count + run.updated_count),
            "rejected": getattr(run, "rejected_count", 0),
            "new": run.new_count,
            "updated": run.updated_count,
            "error": run.error_message,
            "finished_at": run.finished_at,
        }
        finish_task(db, task.id, {key: value for key, value in result.items() if key != "finished_at"})
        return result
    except Exception as exc:
        fail_task(db, task.id, exc)
        raise


@router.delete("/custom/{source_key}", dependencies=[Depends(require_csrf)])
def remove_custom_source(source_key: str, db: Session = Depends(get_db)) -> dict:
    configs = custom_source_configs(db)
    kept = [item for item in configs if item.get("source_key") != source_key]
    if len(kept) == len(configs):
        raise HTTPException(404, "自定义来源不存在")
    save_custom_source_configs(db, kept)
    return {"removed": source_key}
