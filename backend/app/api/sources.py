from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_session, require_csrf
from app.models.entities import AuthSession, SourceHealth, SourceRun
from app.schemas.jobs import SourceRunRequest
from app.sources.registry import REGISTRY
from app.sources.runner import run_source

router = APIRouter(prefix="/api/sources", tags=["招聘来源"])


@router.get("")
def list_sources(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    status: str | None = None,
    _: AuthSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> list[dict]:
    health = {item.source_key: item for item in db.scalars(select(SourceHealth)).all()}
    items = [
        {
            "source_key": key,
            "display_name": adapter.display_name,
            "official_entry": adapter.start_url,
            "parser_version": adapter.parser_version,
            "status": health[key].status if key in health else "unknown",
            "last_success_at": health[key].last_success_at if key in health else None,
            "consecutive_failures": health[key].consecutive_failures if key in health else 0,
            "last_error": health[key].last_error if key in health else None,
            "stable_for_acceptance": health[key].stable_for_acceptance if key in health else False,
        }
        for key, adapter in REGISTRY.items()
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
    source_keys = payload.source_keys or list(REGISTRY)
    invalid = sorted(set(source_keys) - set(REGISTRY))
    if invalid:
        raise HTTPException(422, f"未知来源：{', '.join(invalid)}")
    results = []
    for key in source_keys:
        run = await run_source(
            db,
            key,
            allow_browser=payload.allow_browser,
            max_jobs=payload.max_jobs_per_source,
        )
        results.append({"source_key": key, "run_id": run.id, "success": run.success, "error": run.error_message})
    return {"results": results}
