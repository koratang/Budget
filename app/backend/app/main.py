"""应用入口：创建应用、挂载全部路由、托管 static/ 与 SPA 回退（DEC-004 单体）。

启动：.venv/bin/uvicorn app.main:app --port 8000
配置不合法（如 APP_ENV=prod 且 DEV_IDENTITY_SWITCH=true）时 create_app 抛 ConfigError，进程拒绝启动（DEC-013）。
"""
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

from app.api import (alerts, approvals, auth, bizfin, dept_expense, exports, filling, health, imports, masterdata,
                     me, reports, roles, rules, tasks, versions, workbench)
from app.config import Settings, get_settings
from app.core.auth import bootstrap_finance_head, purge_dev_sessions
from app.core.errors import NotFound, install_error_handlers
from app.db import session_factory
from app.dingtalk.gateway import DingTalkClient
from app.dingtalk.scheduler import create_scheduler

STATIC_DIR = Path(__file__).resolve().parent / "static"

FEATURE_ROUTERS = [masterdata, roles, tasks, filling, dept_expense, approvals, versions, imports, reports, alerts,
                   rules, exports, workbench, bizfin]

_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _request_logger(settings: Settings) -> logging.Logger:
    """请求日志（技术方案 §7.3）：单行 JSON 写入 DATA_DIR/logs/，按天滚动、保留 90 天；不含请求体与金额。"""
    log_dir = Path(settings.DATA_DIR) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    path = str(log_dir / "requests.log")
    logger = logging.getLogger(f"budget.request.{path}")
    if not logger.handlers:
        handler = TimedRotatingFileHandler(path, when="midnight", backupCount=90, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


def create_app(settings: Settings | None = None, dingtalk: DingTalkClient | None = None) -> FastAPI:
    settings = settings or get_settings()
    client = dingtalk or DingTalkClient(settings)
    session_maker = session_factory(settings.DATABASE_URL)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        with session_maker() as db:
            if settings.APP_ENV == "prod":
                purge_dev_sessions(db)
            bootstrap_finance_head(db, settings)
            db.commit()
        scheduler = create_scheduler(session_maker, client) if settings.SCHEDULER_ENABLED else None
        if scheduler:
            scheduler.start()
        try:
            yield
        finally:
            if scheduler:
                scheduler.shutdown(wait=False)
            client.close()

    app = FastAPI(title="预算管理平台", lifespan=lifespan, docs_url="/api/docs" if settings.APP_ENV != "prod" else None,
                  openapi_url="/api/openapi.json" if settings.APP_ENV != "prod" else None, redoc_url=None)
    app.state.settings = settings
    app.state.dingtalk = client
    app.state.session_maker = session_maker
    install_error_handlers(app)
    request_log = _request_logger(settings)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = uuid.uuid4().hex
        started = time.perf_counter()
        # 写操作防跨站：带 Origin 时必须与本站一致（技术方案 §7.2）
        origin = request.headers.get("origin")
        if (request.method in _WRITE_METHODS and origin and request.url.path.startswith("/api/")
                and urlsplit(origin).netloc != request.headers.get("host")):
            return JSONResponse({"code": "forbidden", "message": "无权限"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        if request.url.path.startswith("/api/"):
            request_log.info(json.dumps({
                "request_id": request.state.request_id, "method": request.method, "path": request.url.path,
                "user_id": getattr(request.state, "user_id", None), "status": response.status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 1)}, ensure_ascii=False))
        return response

    app.include_router(health.router, prefix="/api")
    app.include_router(auth.router, prefix="/api")
    if settings.dev_identity_enabled:
        app.include_router(auth.dev_router, prefix="/api")
    app.include_router(me.router, prefix="/api")
    for module in FEATURE_ROUTERS:
        app.include_router(module.router, prefix="/api")

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
    def api_not_found(rest: str):
        raise NotFound("接口不存在")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        candidate = (STATIC_DIR / full_path).resolve()
        if full_path and candidate.is_file() and candidate.is_relative_to(STATIC_DIR):
            return FileResponse(candidate)
        return FileResponse(STATIC_DIR / "index.html")

    return app


app = create_app()
