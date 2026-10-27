"""GET /health（API-F00-02）：数据库连通、调度器心跳、磁盘剩余；不需会话、不含业务数据。"""
import shutil

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import BACKEND_DIR, Settings
from app.core.auth import finance_head_missing, get_app_settings
from app.db import get_db
from app.dingtalk.scheduler import heartbeat

router = APIRouter(tags=["health"])


@router.get("/health")
def health(db: Session = Depends(get_db), settings: Settings = Depends(get_app_settings)):
    warnings: list[str] = []
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
        if finance_head_missing(db):
            warnings.append("finance_head_missing")
    except SQLAlchemyError:
        db_ok = False
    disk_dir = settings.DATA_DIR if settings.DATA_DIR.exists() else BACKEND_DIR
    last = heartbeat["last"]
    body = {
        "status": "ok" if db_ok else "error",
        "db": db_ok,
        "scheduler_heartbeat": last.isoformat() if last else None,
        "disk_free_mb": shutil.disk_usage(disk_dir).free // (1024 * 1024),
        "warnings": warnings,
    }
    return JSONResponse(body, status_code=200 if db_ok else 503)
