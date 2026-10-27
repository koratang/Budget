"""Excel 导出（API-F14-01）：GET /export?view=&filters=<JSON>。

范围过滤复用各页面接口的同一服务函数（NFR-003、AC-F14-01）；越权返回 403「无权限」。
"""
import json
from urllib.parse import quote

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.errors import ValidationFailed
from app.core.scope import ScopeContext, get_scope
from app.db import get_db
from app.services import exporter

router = APIRouter(prefix="/export", tags=["exports"])

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("")
def export(view: str, filters: str = "{}", ctx: ScopeContext = Depends(get_scope), db: Session = Depends(get_db)):
    try:
        parsed = json.loads(filters or "{}")
    except json.JSONDecodeError as e:
        raise ValidationFailed("筛选条件不合法") from e
    if not isinstance(parsed, dict):
        raise ValidationFailed("筛选条件不合法")
    name, content = exporter.export(db, ctx, view, parsed)
    ascii_name = "export.xlsx"
    return Response(content, media_type=XLSX, headers={
        "Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"})
