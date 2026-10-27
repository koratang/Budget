"""主数据（API-F02-01~06）：渠道/店铺、SKU 对照表、B 端客户与部门、科目映射、汇率、预算科目。

权限（技术方案 §4.5 功能级）：财务BP 读写；CEO 与财务负责人只读；新渠道标记仅财务负责人（AC-F13-01）；
其他角色 403「无权限」。每次写入与审计同事务提交（NFR-004）。
"""
from datetime import date

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.calc.periods import fmt_month, parse_month
from app.core.audit import write_audit
from app.core.auth import CurrentUser
from app.core.clock import clock
from app.core.errors import NotFound, ValidationFailed
from app.core.scope import require_roles
from app.db import get_db
from app.models import BCustomer, BudgetAccount, Channel, Department, Store
from app.models.enums import Role
from app.services import masterdata as svc

router = APIRouter(prefix="/master", tags=["masterdata"])

readers = require_roles(Role.FINANCE_BP, Role.FINANCE_HEAD, Role.CEO)
bp_only = require_roles(Role.FINANCE_BP)
head_only = require_roles(Role.FINANCE_HEAD)


def _month_param(value: str | None) -> date:
    if not value:
        return clock.now().date().replace(day=1)
    try:
        return parse_month(value)
    except ValueError as e:
        raise ValidationFailed("月份格式应为 YYYY-MM", details={"field": "month"}) from e


def _get(db: Session, model, obj_id: int, label: str):
    obj = db.get(model, obj_id)
    if obj is None:
        raise NotFound(f"{label}不存在")
    return obj


def _perms(current: CurrentUser) -> dict:
    return {"can_edit": current.has_role(Role.FINANCE_BP), "can_mark_new_channel": current.has_role(Role.FINANCE_HEAD)}


# ---------------------------------------------------------------------------
# 渠道与店铺（API-F02-01）
# ---------------------------------------------------------------------------
@router.get("/stores")
def list_stores(month: str | None = None, current: CurrentUser = Depends(readers), db: Session = Depends(get_db)):
    return {**svc.list_stores(db, _month_param(month)), **_perms(current)}


@router.get("/channels")
def list_channels(month: str | None = None, current: CurrentUser = Depends(readers), db: Session = Depends(get_db)):
    return svc.list_stores(db, _month_param(month))["channels"]


class ChannelIn(BaseModel):
    name: str = ""


@router.post("/channels", status_code=201)
def create_channel(body: ChannelIn, request: Request, current: CurrentUser = Depends(bp_only),
                   db: Session = Depends(get_db)):
    ch = svc.create_channel(db, body.name)
    write_audit(db, action="create", object_type="channel", object_id=ch.id, after={"name": ch.name},
                actor=current, request=request)
    db.commit()
    return {"id": ch.id, "name": ch.name}


@router.put("/channels/{channel_id}")
def rename_channel(channel_id: int, body: ChannelIn, request: Request, current: CurrentUser = Depends(bp_only),
                   db: Session = Depends(get_db)):
    ch = _get(db, Channel, channel_id, "渠道")
    before = {"name": ch.name}
    svc.rename_channel(db, ch, body.name)
    write_audit(db, action="update", object_type="channel", object_id=ch.id, before=before, after={"name": ch.name},
                actor=current, request=request)
    db.commit()
    return {"id": ch.id, "name": ch.name}


class NewChannelIn(BaseModel):
    is_new: bool
    start: str | None = None


@router.put("/channels/{channel_id}/new-channel")
def mark_channel(channel_id: int, body: NewChannelIn, request: Request, current: CurrentUser = Depends(head_only),
                 db: Session = Depends(get_db)):
    ch = _get(db, Channel, channel_id, "渠道")
    before = {"is_new_channel": ch.is_new_channel,
              "new_channel_start": fmt_month(ch.new_channel_start) if ch.new_channel_start else None}
    svc.set_channel_new_channel(db, ch, body.is_new, body.start)
    after = {"is_new_channel": ch.is_new_channel,
             "new_channel_start": fmt_month(ch.new_channel_start) if ch.new_channel_start else None}
    write_audit(db, action="mark_new_channel", object_type="channel", object_id=ch.id, before=before, after=after,
                actor=current, request=request)
    db.commit()
    return {"id": ch.id, **after}


class StoreIn(BaseModel):
    channel_id: int | None = None
    name: str = ""
    site_id: int | None = None
    currency: str = ""
    is_active: bool = True


@router.post("/stores", status_code=201)
def create_store(body: StoreIn, request: Request, current: CurrentUser = Depends(bp_only),
                 db: Session = Depends(get_db)):
    store = svc.create_store(db, body.model_dump())
    write_audit(db, action="create", object_type="store", object_id=store.id, after=svc.store_snapshot(store),
                actor=current, request=request)
    db.commit()
    return {"id": store.id, **svc.store_snapshot(store)}


@router.put("/stores/{store_id}")
def update_store(store_id: int, body: StoreIn, request: Request, current: CurrentUser = Depends(bp_only),
                 db: Session = Depends(get_db)):
    store = _get(db, Store, store_id, "店铺")
    before = svc.store_snapshot(store)
    svc.update_store(db, store, body.model_dump())
    write_audit(db, action="update", object_type="store", object_id=store.id, before=before,
                after=svc.store_snapshot(store), actor=current, request=request)
    db.commit()
    return {"id": store.id, **svc.store_snapshot(store)}


@router.put("/stores/{store_id}/new-channel")
def mark_store(store_id: int, body: NewChannelIn, request: Request, current: CurrentUser = Depends(head_only),
               db: Session = Depends(get_db)):
    store = _get(db, Store, store_id, "店铺")
    before = svc.store_snapshot(store)
    svc.set_store_new_channel(db, store, body.is_new, body.start)
    write_audit(db, action="mark_new_channel", object_type="store", object_id=store.id, before=before,
                after=svc.store_snapshot(store), actor=current, request=request)
    db.commit()
    return {"id": store.id, **svc.store_snapshot(store)}


# ---------------------------------------------------------------------------
# SKU 对照表（API-F02-02）
# ---------------------------------------------------------------------------
@router.get("/sku-mapping")
def sku_mapping(month: str | None = None, q: str | None = None, category: str | None = None,
                kind: str | None = Query(None, pattern="^(new|old)$"), page: int = Query(1, ge=1),
                current: CurrentUser = Depends(readers), db: Session = Depends(get_db)):
    return {**svc.list_sku_mapping(db, _month_param(month), q, category, kind, page, 50), **_perms(current)}


@router.post("/sku-mapping/upload")
async def sku_upload(request: Request, file: UploadFile = File(...), current: CurrentUser = Depends(bp_only),
                     db: Session = Depends(get_db)):
    content = await file.read()
    result = svc.upload_sku_mapping(db, current.user.id, file.filename or "SKU对照表.xlsx", content)
    write_audit(db, action="sku_upload_validate", object_type="import_batch", object_id=result["id"],
                after={"status": result["status"], "issues": len(result["issues"]), "file_name": result["file_name"]},
                actor=current, request=request)
    db.commit()
    return result


@router.get("/sku-mapping/upload/{batch_id}")
def sku_upload_status(batch_id: int, current: CurrentUser = Depends(bp_only), db: Session = Depends(get_db)):
    return svc.batch_payload(db, svc.get_sku_batch(db, batch_id))


@router.post("/sku-mapping/upload/{batch_id}/confirm")
def sku_upload_confirm(batch_id: int, request: Request, current: CurrentUser = Depends(bp_only),
                       db: Session = Depends(get_db)):
    batch = svc.get_sku_batch(db, batch_id)
    result = svc.confirm_sku_mapping(db, current.user.id, batch)
    write_audit(db, action="sku_upload_confirm", object_type="import_batch", object_id=batch.id,
                after={"added": result["added"], "updated": result["updated"], "file_name": batch.file_name},
                actor=current, request=request)
    db.commit()
    return result


# ---------------------------------------------------------------------------
# B 端客户与部门（API-F02-03）
# ---------------------------------------------------------------------------
@router.get("/b-customers")
def list_customers(current: CurrentUser = Depends(readers), db: Session = Depends(get_db)):
    return {**svc.list_customers(db), **_perms(current)}


class CustomerIn(BaseModel):
    name: str = ""
    department_id: int | None = None
    currency: str = ""
    is_active: bool = True


@router.post("/b-customers", status_code=201)
def create_customer(body: CustomerIn, request: Request, current: CurrentUser = Depends(bp_only),
                    db: Session = Depends(get_db)):
    c = svc.create_customer(db, body.model_dump())
    write_audit(db, action="create", object_type="b_customer", object_id=c.id, after=svc.customer_snapshot(c),
                actor=current, request=request)
    db.commit()
    return {"id": c.id, **svc.customer_snapshot(c)}


@router.put("/b-customers/{customer_id}")
def update_customer(customer_id: int, body: CustomerIn, request: Request, current: CurrentUser = Depends(bp_only),
                    db: Session = Depends(get_db)):
    c = _get(db, BCustomer, customer_id, "客户")
    before = svc.customer_snapshot(c)
    svc.update_customer(db, c, body.model_dump())
    write_audit(db, action="update", object_type="b_customer", object_id=c.id, before=before,
                after=svc.customer_snapshot(c), actor=current, request=request)
    db.commit()
    return {"id": c.id, **svc.customer_snapshot(c)}


@router.get("/departments")
def list_departments(current: CurrentUser = Depends(readers), db: Session = Depends(get_db)):
    return {**svc.list_departments(db), **_perms(current)}


class DepartmentIn(BaseModel):
    name: str = ""
    is_active: bool = True


@router.post("/departments", status_code=201)
def create_department(body: DepartmentIn, request: Request, current: CurrentUser = Depends(bp_only),
                      db: Session = Depends(get_db)):
    d = svc.create_department(db, body.name)
    write_audit(db, action="create", object_type="department", object_id=d.id, after={"name": d.name},
                actor=current, request=request)
    db.commit()
    return {"id": d.id, "name": d.name, "is_active": d.is_active}


@router.put("/departments/{department_id}")
def update_department(department_id: int, body: DepartmentIn, request: Request,
                      current: CurrentUser = Depends(bp_only), db: Session = Depends(get_db)):
    d = _get(db, Department, department_id, "部门")
    before = {"name": d.name, "is_active": d.is_active}
    svc.update_department(db, d, body.name, body.is_active)
    write_audit(db, action="update", object_type="department", object_id=d.id, before=before,
                after={"name": d.name, "is_active": d.is_active}, actor=current, request=request)
    db.commit()
    return {"id": d.id, "name": d.name, "is_active": d.is_active}


# ---------------------------------------------------------------------------
# 科目映射（API-F02-04）与预算科目（API-F02-06）
# ---------------------------------------------------------------------------
@router.get("/account-mapping")
def account_mapping(current: CurrentUser = Depends(readers), db: Session = Depends(get_db)):
    return {**svc.list_account_mapping(db), **_perms(current)}


class MappingIn(BaseModel):
    kingdee_code: str = ""
    kingdee_name: str | None = None
    account_id: int | None = None


def _save_mapping(body: MappingIn, request: Request, current: CurrentUser, db: Session, create_only: bool) -> dict:
    row, before = svc.save_account_mapping(db, current.user.id, body.kingdee_code, body.kingdee_name,
                                           body.account_id, create_only)
    write_audit(db, action="save_mapping", object_type="kingdee_account_map", object_id=row.kingdee_code,
                before=before, after={"kingdee_name": row.kingdee_name, "account_id": row.account_id},
                actor=current, request=request)
    db.commit()
    return {"kingdee_code": row.kingdee_code, "kingdee_name": row.kingdee_name, "account_id": row.account_id}


@router.post("/account-mapping", status_code=201)
def create_mapping(body: MappingIn, request: Request, current: CurrentUser = Depends(bp_only),
                   db: Session = Depends(get_db)):
    return _save_mapping(body, request, current, db, create_only=True)


@router.put("/account-mapping")
def update_mapping(body: MappingIn, request: Request, current: CurrentUser = Depends(bp_only),
                   db: Session = Depends(get_db)):
    return _save_mapping(body, request, current, db, create_only=False)


@router.get("/budget-accounts")
def budget_accounts(usage: str | None = Query(None, pattern="^(mapping|dept_expense)$"),
                    current: CurrentUser = Depends(readers), db: Session = Depends(get_db)):
    return {"items": svc.list_budget_accounts(db, usage), **_perms(current)}


class AccountIn(BaseModel):
    name: str | None = None
    status: str | None = None
    is_dept_expense: bool = True


@router.post("/budget-accounts", status_code=201)
def create_account(body: AccountIn, request: Request, current: CurrentUser = Depends(bp_only),
                   db: Session = Depends(get_db)):
    a = svc.create_budget_account(db, body.name or "", body.is_dept_expense)
    write_audit(db, action="create", object_type="budget_account", object_id=a.id, after=svc.account_snapshot(a),
                actor=current, request=request)
    db.commit()
    return {"id": a.id, **svc.account_snapshot(a)}


@router.put("/budget-accounts/{account_id}")
def update_account(account_id: int, body: AccountIn, request: Request, current: CurrentUser = Depends(bp_only),
                   db: Session = Depends(get_db)):
    a = _get(db, BudgetAccount, account_id, "预算科目")
    before = svc.account_snapshot(a)
    svc.update_budget_account(db, a, body.name, body.status)
    write_audit(db, action="update", object_type="budget_account", object_id=a.id, before=before,
                after=svc.account_snapshot(a), actor=current, request=request)
    db.commit()
    return {"id": a.id, **svc.account_snapshot(a)}


# ---------------------------------------------------------------------------
# 汇率（API-F02-05）
# ---------------------------------------------------------------------------
@router.get("/fx/budget")
def budget_fx(year: int | None = None, current: CurrentUser = Depends(readers), db: Session = Depends(get_db)):
    return {**svc.list_budget_fx(db, year or svc.current_budget_year(db)), **_perms(current)}


class BudgetFxIn(BaseModel):
    year: int
    currency: str
    rate: str | int


@router.put("/fx/budget")
def save_budget_fx(body: BudgetFxIn, request: Request, current: CurrentUser = Depends(bp_only),
                   db: Session = Depends(get_db)):
    row, before, recalculated = svc.save_budget_fx(db, current.user.id, body.year, body.currency, body.rate)
    write_audit(db, action="save_fx_budget", object_type="fx_budget", object_id=f"{row.year}-{row.currency}",
                before={"rate": before} if before is not None else None, after={"rate": row.rate},
                actor=current, request=request)
    db.commit()
    return {"year": row.year, "currency": row.currency, "rate": format(row.rate.quantize(svc.FOUR_DP), "f"),
            "recalculated_units": recalculated}


@router.get("/fx/actual")
def actual_fx(year: int | None = None, current: CurrentUser = Depends(readers), db: Session = Depends(get_db)):
    return {**svc.list_actual_fx(db, year or svc.current_budget_year(db)), **_perms(current)}


class ActualFxIn(BaseModel):
    month: str
    currency: str
    rate: str | int


@router.put("/fx/actual")
def save_actual_fx(body: ActualFxIn, request: Request, current: CurrentUser = Depends(bp_only),
                   db: Session = Depends(get_db)):
    row, before = svc.save_actual_fx(db, current.user.id, body.month, body.currency, body.rate)
    write_audit(db, action="save_fx_actual", object_type="fx_actual",
                object_id=f"{fmt_month(row.month)}-{row.currency}",
                before={"rate": before} if before is not None else None, after={"rate": row.rate},
                actor=current, request=request)
    db.commit()
    return {"month": fmt_month(row.month), "currency": row.currency,
            "rate": format(row.rate.quantize(svc.FOUR_DP), "f")}
