from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api import applications, auth, backups, health, jobs, recommendations, resumes, settings, sources, tailor, tasks
from app.core.config import get_settings
from app.core.database import Base, SessionLocal, engine
from app.core.security import configure_logging, initialize_admin
from app.services.daily import run_daily_pipeline
from app.services.task_runs import interrupt_running_tasks

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    configure_logging()
    settings.ensure_directories()
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        initialize_admin(db, settings)
        interrupt_running_tasks(db)
    scheduler = AsyncIOScheduler(timezone=settings.schedule_timezone)
    scheduler.add_job(
        run_daily_pipeline,
        CronTrigger(hour=settings.schedule_hour, minute=0, timezone=settings.schedule_timezone),
        id="daily-job-pipeline",
        coalesce=True,
        max_instances=1,
        replace_existing=True,
    )
    scheduler.start()
    logger.info("秋招助手 %s 已启动", __version__)
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="秋招助手", version=__version__, lifespan=lifespan)
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(resumes.router)
app.include_router(sources.router)
app.include_router(jobs.router)
app.include_router(recommendations.router)
app.include_router(settings.router)
app.include_router(tailor.router)
app.include_router(applications.router)
app.include_router(backups.router)
app.include_router(tasks.router)


@app.exception_handler(HTTPException)
async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
    recovery = None
    if exc.status_code == 401:
        recovery = "请刷新页面以恢复本地会话"
    elif exc.status_code == 403:
        recovery = "请刷新页面后重试"
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": f"HTTP_{exc.status_code}", "message": str(exc.detail), "recovery": recovery},
    )


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "code": "VALIDATION_ERROR",
            "message": "提交的数据格式不正确",
            "recovery": "请检查高亮字段后重试",
            "details": [
                {"type": item["type"], "loc": item["loc"], "msg": item["msg"]}
                for item in exc.errors()
            ],
        },
    )


@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("未处理异常：%s %s (%s)", request.method, request.url.path, type(exc).__name__)
    return JSONResponse(
        status_code=500,
        content={
            "code": "INTERNAL_ERROR",
            "message": "服务暂时无法完成请求",
            "recovery": "请稍后重试；若持续失败，请查看已脱敏的服务日志",
        },
    )


frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if frontend_dist.exists():
    assets_dir = frontend_dist / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="frontend-assets")

    @app.get("/{frontend_path:path}", include_in_schema=False)
    async def frontend_app(frontend_path: str) -> FileResponse:
        return FileResponse(frontend_dist / "index.html", headers={"Cache-Control": "no-store"})
