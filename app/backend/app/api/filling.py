"""填报（API-F04-01~08、API-F06-01/02）。

- GET    /filling-units?mine=1                     我的填报单位（状态、退回原因）
- GET    /filling-units/{id}/grid?tab=             表格（列按角色裁剪 + 行 + 合计 + 新渠道标注）
- PATCH  /filling-units/{id}/cells?tab=            批量保存单元格（每格带基准值），返回重算后的表格与失败明细
- POST   /filling-units/{id}/fill-year             填充全年（比率）
- GET    /filling-units/{id}/template              下载 .xlsx 模板
- POST   /filling-units/{id}/template-upload       上传模板（整份校验）
- POST   /filling-units/{id}/submit                提交
- PUT    /filling-units/{id}/over-limit-reasons    新渠道超出理由
- GET    /versions/{id}/pl                         收入 → 毛利 → 净利润汇总（双口径：按月、渠道、B 端客户）
- GET    /company-other-pl?version_id=             公司层其他损益（编辑经成本比例单位的「公司层其他损益」标签）
"""
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import Settings
from app.core.auth import CurrentUser, get_app_settings, get_current_user
from app.core.scope import ScopeContext, get_scope, require_roles
from app.db import get_db
from app.models.enums import Role
from app.services import filling, tasking

router = APIRouter(tags=["filling"])

MANAGEMENT = (Role.CEO, Role.FINANCE_HEAD, Role.FINANCE_BP)


class CellIn(BaseModel):
    row_key: str
    field: str
    value: Any = None
    base: Any = None


class FillYearIn(BaseModel):
    row_key: str
    value: Any = None


class ReasonsIn(BaseModel):
    reasons: dict[str, str | None]


class SubmitIn(BaseModel):
    adjust_reason: str | None = None


@router.get("/filling-units")
def my_units(mine: int = 1, ctx: ScopeContext = Depends(get_scope), db: Session = Depends(get_db)):
    return {"items": filling.my_units(db, ctx)}


@router.get("/filling-units/{unit_id}/grid")
def grid(unit_id: int, tab: str | None = None, ctx: ScopeContext = Depends(get_scope), db: Session = Depends(get_db)):
    unit = tasking.get_unit(db, unit_id)
    result = filling.build_grid(db, ctx, unit, tab)
    db.commit()  # 打开表格时按最新放量规则重判超放量标注（只改标注列）
    return result


@router.patch("/filling-units/{unit_id}/cells")
def save_cells(unit_id: int, body: list[CellIn], request: Request, tab: str | None = None,
               current: CurrentUser = Depends(get_current_user), ctx: ScopeContext = Depends(get_scope),
               db: Session = Depends(get_db)):
    result = filling.save_cells(db, ctx, current, unit_id, [c.model_dump() for c in body], request=request,
                                source="paste" if len(body) > 1 else "edit")
    db.commit()
    grid = filling.build_grid(db, ctx, tasking.get_unit(db, unit_id), tab)
    db.commit()
    return {**result, "grid": grid}


@router.post("/filling-units/{unit_id}/fill-year")
def fill_year(unit_id: int, body: FillYearIn, request: Request, tab: str | None = None,
              current: CurrentUser = Depends(get_current_user), ctx: ScopeContext = Depends(get_scope),
              db: Session = Depends(get_db)):
    result = filling.fill_year(db, ctx, current, unit_id, body.row_key, body.value, request=request)
    db.commit()
    grid = filling.build_grid(db, ctx, tasking.get_unit(db, unit_id), tab)
    db.commit()
    return {**result, "grid": grid}


@router.get("/filling-units/{unit_id}/template")
def template(unit_id: int, ctx: ScopeContext = Depends(get_scope), db: Session = Depends(get_db)):
    unit = tasking.get_unit(db, unit_id)
    content, name = filling.build_template(db, ctx, unit)
    return Response(content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})


@router.post("/filling-units/{unit_id}/template-upload")
async def template_upload(unit_id: int, request: Request, file: UploadFile = File(...),
                          current: CurrentUser = Depends(get_current_user), ctx: ScopeContext = Depends(get_scope),
                          db: Session = Depends(get_db)):
    content = await file.read()
    result = filling.upload_template(db, ctx, current, unit_id, file.filename or "", content, request=request)
    db.commit()
    return result


@router.post("/filling-units/{unit_id}/submit")
def submit(unit_id: int, request: Request, body: SubmitIn | None = None,
           current: CurrentUser = Depends(get_current_user), ctx: ScopeContext = Depends(get_scope),
           settings: Settings = Depends(get_app_settings), db: Session = Depends(get_db)):
    result = filling.submit_unit(db, ctx, current, settings, unit_id, request=request,
                                 adjust_reason=body.adjust_reason if body else None)
    db.commit()
    return result


@router.put("/filling-units/{unit_id}/over-limit-reasons")
def over_limit_reasons(unit_id: int, body: ReasonsIn, request: Request,
                       current: CurrentUser = Depends(get_current_user), ctx: ScopeContext = Depends(get_scope),
                       db: Session = Depends(get_db)):
    result = filling.set_over_limit_reasons(db, ctx, current, unit_id, body.reasons, request=request)
    db.commit()
    return {"over_limit": result}


@router.get("/versions/{version_id}/pl")
def version_pl(version_id: int, _: CurrentUser = Depends(require_roles(*MANAGEMENT)), db: Session = Depends(get_db)):
    return filling.version_pl(db, version_id)


@router.get("/company-other-pl")
def company_other_pl(version_id: int, _: CurrentUser = Depends(require_roles(*MANAGEMENT)),
                     db: Session = Depends(get_db)):
    return {"items": filling.company_other_pl(db, version_id)}


# ---------------------------------------------------------------------------
# 滚动预测更新（AC-F08-05，对接 G3 versions）：同一表格编辑滚动预测稿，单位键 = G3 plan_units 的 key
# ---------------------------------------------------------------------------
@router.get("/filling-units/rolling/{version_id}/{unit_key}/grid")
def rolling_grid(version_id: int, unit_key: str, tab: str | None = None, ctx: ScopeContext = Depends(get_scope),
                 db: Session = Depends(get_db)):
    result = filling.build_grid(db, ctx, filling.rolling_unit(db, version_id, unit_key), tab)
    db.commit()
    return result


@router.patch("/filling-units/rolling/{version_id}/{unit_key}/cells")
def rolling_cells(version_id: int, unit_key: str, body: list[CellIn], request: Request, tab: str | None = None,
                  current: CurrentUser = Depends(get_current_user), ctx: ScopeContext = Depends(get_scope),
                  db: Session = Depends(get_db)):
    unit = filling.rolling_unit(db, version_id, unit_key)
    result = filling.save_cells(db, ctx, current, unit, [c.model_dump() for c in body], request=request,
                                source="paste" if len(body) > 1 else "edit")
    db.commit()
    grid = filling.build_grid(db, ctx, filling.rolling_unit(db, version_id, unit_key), tab)
    db.commit()
    return {**result, "grid": grid}


@router.post("/filling-units/rolling/{version_id}/{unit_key}/fill-year")
def rolling_fill_year(version_id: int, unit_key: str, body: FillYearIn, request: Request, tab: str | None = None,
                      current: CurrentUser = Depends(get_current_user), ctx: ScopeContext = Depends(get_scope),
                      db: Session = Depends(get_db)):
    unit = filling.rolling_unit(db, version_id, unit_key)
    result = filling.fill_year(db, ctx, current, unit, body.row_key, body.value, request=request)
    db.commit()
    grid = filling.build_grid(db, ctx, filling.rolling_unit(db, version_id, unit_key), tab)
    db.commit()
    return {**result, "grid": grid}


@router.post("/filling-units/rolling/{version_id}/{unit_key}/submit")
def rolling_submit(version_id: int, unit_key: str, current: CurrentUser = Depends(get_current_user),
                   ctx: ScopeContext = Depends(get_scope), db: Session = Depends(get_db)):
    result = filling.submit_rolling(db, ctx, current, version_id, unit_key)
    db.commit()
    return result
