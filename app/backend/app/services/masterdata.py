"""主数据服务 CMP-F02-01（REQ-F02-01~05、REQ-F13-01；DEC-020、DEC-021）。

渠道/店铺、B 端客户、部门、预算科目（新增、改名、停用，不删除）、金蝶科目映射、汇率、SKU 对照表。
本模块只 flush 不 commit，由路由在写审计后统一提交。

供其他功能组直接调用的只读函数（不改它们的服务模块，按分工「跨组读取」）：
- fillable_stores(db)               新预算填报 / 编制任务可列出的店铺（只含启用，AC-F02-10）
- import_store_lookup(db)            实际导入校验用：店铺名称 → (店铺, 站点)（含停用店铺，AC-F02-01/10）
- store_new_channel_start(db, s)     店铺生效的新渠道起始月（店铺级优先，否则随渠道，AC-F13-01）
- is_new_channel_month(db, s, m)     某月是否处于新渠道期（起始月起 12 个月）
- b2b_customers_for_department(db, d) 负责部门的 B 端填报客户（只含启用，AC-F02-09）
- dept_expense_accounts(db)          部门费用填报的预算科目（启用且为部门费用科目，AC-F02-12）
- account_map_lookup(db)             金蝶科目编码 → 预算科目 ID（已映射到停用科目的旧映射照常归集，AC-F02-05）
- missing_budget_fx(db, year, curs)  该年度缺预算汇率的币种代码（AC-F02-07）
- budget_fx_locked(db, year)         该年度预算汇率是否已随年初原始目标锁定（DEC-020）
- actual_fx_rate(db, month, cur)     当月平均汇率（AC-F02-08）
"""
from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.calc.formulas import is_new_product
from app.calc.periods import add_months, fmt_month, month_end, parse_month
from app.calc.recalc import recalc_for_fx_change
from app.core.clock import clock
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.money import MoneyError, to_decimal
from app.models import (AuditLog, B2bUnit, BCustomer, BiActualAgg, BiActualSku, BudgetAccount, BudgetVersion,
                        Category, Channel, Department, FillingUnit, FxActual, FxBudget, ImportBatch,
                        ImportStaging, KingdeeAccountMap, KingdeeActual, PlatformUnit, Site, Sku, Spu, Store, User,
                        UserRole, UserScope)
from app.models.enums import ImportSource, ImportStatus, Role, ScopeType, UnitType, VersionType

# 结算币种可选清单（店铺 / B 端客户）；人民币不需要预算汇率
CURRENCY_NAMES = {"USD": "美元", "CAD": "加拿大元", "EUR": "欧元", "GBP": "英镑", "JPY": "日元", "AUD": "澳大利亚元"}
# B 端客户的负责部门只能是这两个（AC-F02-09）
B2B_DEPARTMENTS = ("美国业务部", "外贸部")
FX_FORMAT_MESSAGE = "请输入大于 0 的数字，最多 4 位小数"
FX_LOCKED_MESSAGE = "已随年初原始目标锁定"
FOUR_DP = Decimal("0.0001")


def _dup(message: str, field_name: str = "name") -> ValidationFailed:
    return ValidationFailed(message, code="duplicate_name", details={"field": field_name})


def _required(message: str, field_name: str) -> ValidationFailed:
    return ValidationFailed(message, code="required", details={"field": field_name})


def _clean(value: str | None) -> str:
    return (value or "").strip()


def _name_taken(db: Session, model, name: str, exclude_id: int | None = None) -> bool:
    """名称唯一校验（不区分大小写、去首尾空格）。"""
    q = select(model.id).where(func.lower(model.name) == name.lower())
    if exclude_id is not None:
        q = q.where(model.id != exclude_id)
    return db.scalar(q.limit(1)) is not None


def current_budget_year(db: Session) -> int:
    """当前编制 / 执行年度：最近的预算版本年度；尚无版本时，10 月起为次年（编制期），否则为当年。"""
    latest = db.scalar(select(func.max(BudgetVersion.year)))
    if latest:
        return latest
    today = clock.now().date()
    return today.year + 1 if today.month >= 10 else today.year


def _last_modified(db: Session, object_type: str) -> dict[str, dict]:
    """取各对象最近一次审计（时间、操作人），用于「最近修改」列。"""
    sub = (select(AuditLog.object_id, func.max(AuditLog.id).label("mid"))
           .where(AuditLog.object_type == object_type).group_by(AuditLog.object_id).subquery())
    rows = db.execute(select(AuditLog.object_id, AuditLog.occurred_at, AuditLog.actor_name)
                      .join(sub, sub.c.mid == AuditLog.id)).all()
    return {oid: {"at": at.isoformat(), "by": name} for oid, at, name in rows}


# ===========================================================================
# 渠道与店铺（API-F02-01；AC-F02-01/02/10、AC-F13-01）
# ===========================================================================
def store_new_channel_start(db: Session, store: Store, channel: Channel | None = None) -> date | None:
    if store.is_new_channel and store.new_channel_start:
        return store.new_channel_start
    channel = channel or db.get(Channel, store.channel_id)
    if channel and channel.is_new_channel and channel.new_channel_start:
        return channel.new_channel_start
    return None


def is_new_channel_month(db: Session, store: Store, month: date) -> bool:
    start = store_new_channel_start(db, store)
    return start is not None and start <= month <= add_months(start, 11)


def new_channel_info(start: date | None, level: str | None, month: date) -> dict | None:
    """新渠道期 = 起始月起 12 个月（含起始月），满 12 个月自动转为常规渠道（AC-F13-01）。"""
    if start is None:
        return None
    end = add_months(start, 11)
    if month < start:
        status = "upcoming"
    elif month <= end:
        status = "active"
    else:
        status = "expired"
    return {"start": fmt_month(start), "end": fmt_month(end), "regular_from": fmt_month(add_months(start, 12)),
            "level": level, "status": status, "is_new": status == "active"}


def _used_store_ids(db: Session) -> set[int]:
    """已被填报或导入使用的店铺（DEC-F02-03：结算币种不可改、改名需确认）。"""
    used: set[int] = set()
    used |= set(db.scalars(select(PlatformUnit.store_id).distinct()))
    used |= set(db.scalars(select(FillingUnit.scope_object_id).where(
        FillingUnit.unit_type == UnitType.PLATFORM, FillingUnit.scope_object_id.is_not(None)).distinct()))
    used |= set(db.scalars(select(KingdeeActual.store_id).where(KingdeeActual.store_id.is_not(None)).distinct()))
    used |= set(db.scalars(select(BiActualSku.store_id).distinct()))
    return used


def list_stores(db: Session, month: date) -> dict:
    channels = db.scalars(select(Channel).order_by(Channel.sort, Channel.id)).all()
    ch_by_id = {c.id: c for c in channels}
    sites = db.scalars(select(Site).order_by(Site.id)).all()
    site_by_id = {s.id: s for s in sites}
    used = _used_store_ids(db)
    order = {c.id: i for i, c in enumerate(channels)}
    stores = sorted(db.scalars(select(Store)).all(), key=lambda s: (order.get(s.channel_id, 0), s.id))
    items = []
    for s in stores:
        ch = ch_by_id[s.channel_id]
        if s.is_new_channel and s.new_channel_start:
            info = new_channel_info(s.new_channel_start, "store", month)
        elif ch.is_new_channel and ch.new_channel_start:
            info = new_channel_info(ch.new_channel_start, "channel", month)
        else:
            info = None
        site = site_by_id[s.site_id]
        items.append({
            "id": s.id, "name": s.name, "channel_id": ch.id, "channel_name": ch.name,
            "site_id": site.id, "site_code": site.code, "site_name": site.name, "currency": s.currency,
            "is_active": s.is_active, "used": s.id in used,
            "store_new_channel": bool(s.is_new_channel and s.new_channel_start),
            "store_new_channel_start": fmt_month(s.new_channel_start) if s.new_channel_start else None,
            "new_channel": info,
        })
    year = current_budget_year(db)
    store_currencies = sorted({s.currency for s in stores if s.is_active})
    return {
        "month": fmt_month(month),
        "budget_year": year,
        "channels": [{"id": c.id, "name": c.name, "is_active": c.is_active,
                      "new_channel": new_channel_info(c.new_channel_start, "channel", month)
                      if c.is_new_channel and c.new_channel_start else None} for c in channels],
        "stores": items,
        "sites": [{"id": s.id, "code": s.code, "name": s.name} for s in sites],
        "currencies": [{"code": k, "name": v} for k, v in CURRENCY_NAMES.items()],
        "fx_rated_currencies": sorted(budget_fx_rates_map(db, year)),
        "fx_missing_currencies": missing_budget_fx(db, year, store_currencies),
        "summary": {"channels": len(channels), "stores": len(stores),
                    "active": sum(1 for s in stores if s.is_active),
                    "inactive": sum(1 for s in stores if not s.is_active)},
    }


def create_channel(db: Session, name: str) -> Channel:
    name = _clean(name)
    if not name:
        raise _required("请填写渠道名称", "name")
    if _name_taken(db, Channel, name):
        raise _dup("渠道名称已存在")
    sort = (db.scalar(select(func.max(Channel.sort))) or 0) + 1
    ch = Channel(name=name, sort=sort)
    db.add(ch)
    db.flush()
    return ch


def rename_channel(db: Session, channel: Channel, name: str) -> None:
    name = _clean(name)
    if not name:
        raise _required("请填写渠道名称", "name")
    if _name_taken(db, Channel, name, channel.id):
        raise _dup("渠道名称已存在")
    channel.name = name
    db.flush()


def _validate_store_fields(db: Session, data: dict, store_id: int | None) -> tuple[str, Channel, Site, str]:
    errors = {}
    name = _clean(data.get("name"))
    channel = db.get(Channel, data.get("channel_id")) if data.get("channel_id") else None
    site = db.get(Site, data.get("site_id")) if data.get("site_id") else None
    currency = _clean(data.get("currency")).upper()
    if channel is None:
        errors["channel_id"] = "请选择所属渠道"
    if not name:
        errors["name"] = "请填写店铺名称"
    if site is None:
        errors["site_id"] = "请选择站点"
    if not currency:
        errors["currency"] = "请选择结算币种"
    elif currency not in CURRENCY_NAMES:
        errors["currency"] = "结算币种不在可选清单中"
    if errors:
        raise ValidationFailed(next(iter(errors.values())), details={"fields": errors})
    if _name_taken(db, Store, name, store_id):
        raise _dup("店铺名称已存在")
    return name, channel, site, currency


def store_snapshot(s: Store) -> dict:
    return {"name": s.name, "channel_id": s.channel_id, "site_id": s.site_id, "currency": s.currency,
            "is_active": s.is_active, "is_new_channel": s.is_new_channel,
            "new_channel_start": fmt_month(s.new_channel_start) if s.new_channel_start else None}


def create_store(db: Session, data: dict) -> Store:
    name, channel, site, currency = _validate_store_fields(db, data, None)
    store = Store(name=name, channel_id=channel.id, site_id=site.id, currency=currency,
                  is_active=bool(data.get("is_active", True)))
    db.add(store)
    db.flush()
    return store


def update_store(db: Session, store: Store, data: dict) -> None:
    name, channel, site, currency = _validate_store_fields(db, data, store.id)
    used = store.id in _used_store_ids(db)
    if used and currency != store.currency:
        raise ValidationFailed("该店铺已被填报或导入使用，结算币种不可修改", code="currency_locked",
                               details={"field": "currency"})
    if used and (channel.id != store.channel_id or site.id != store.site_id):
        raise ValidationFailed("该店铺已被填报或导入使用，所属渠道与站点不可修改", code="store_used",
                               details={"field": "channel_id"})
    store.name, store.channel_id, store.site_id, store.currency = name, channel.id, site.id, currency
    store.is_active = bool(data.get("is_active", store.is_active))
    db.flush()


def _parse_start(is_new: bool, start: str | None) -> date | None:
    if not is_new:
        return None
    if not start:
        raise _required("请选择起始月", "start")
    try:
        return parse_month(start)
    except ValueError as e:
        raise ValidationFailed("起始月格式应为 YYYY-MM", details={"field": "start"}) from e


def set_store_new_channel(db: Session, store: Store, is_new: bool, start: str | None) -> None:
    ch = db.get(Channel, store.channel_id)
    if ch.is_new_channel and ch.new_channel_start and is_new:
        raise Conflict(f"该店铺已随渠道 {ch.name} 标记为新渠道", code="channel_marked")
    store.new_channel_start = _parse_start(is_new, start)
    store.is_new_channel = store.new_channel_start is not None
    db.flush()


def set_channel_new_channel(db: Session, channel: Channel, is_new: bool, start: str | None) -> None:
    channel.new_channel_start = _parse_start(is_new, start)
    channel.is_new_channel = channel.new_channel_start is not None
    db.flush()


def fillable_stores(db: Session) -> list[Store]:
    """新预算填报 / 编制任务生成平台渠道单位时列出的店铺：只含启用店铺（AC-F02-01、AC-F02-10）。"""
    return list(db.scalars(select(Store).where(Store.is_active.is_(True)).order_by(Store.channel_id, Store.id)))


def import_store_lookup(db: Session) -> dict[str, tuple[int, int]]:
    """实际导入校验主数据：店铺名称 → (店铺 ID, 站点 ID)；停用店铺照常接受（AC-F02-10）。"""
    return {name: (sid, site) for sid, name, site in db.execute(select(Store.id, Store.name, Store.site_id))}


# ===========================================================================
# B 端客户与部门（API-F02-03；AC-F02-09）
# ===========================================================================
def _scope_holders(db: Session, role: str, scope_type: str) -> dict[int, list[dict]]:
    rows = db.execute(
        select(UserScope.object_id, User.name, User.is_active)
        .join(User, User.id == UserScope.user_id)
        .join(UserRole, (UserRole.user_id == User.id) & (UserRole.role_code == role))
        .where(UserScope.scope_type == scope_type).order_by(User.id)).all()
    out: dict[int, list[dict]] = {}
    for oid, name, active in rows:
        out.setdefault(oid, []).append({"name": name, "is_active": active})
    return out


def list_customers(db: Session) -> dict:
    depts = {d.id: d for d in db.scalars(select(Department))}
    owners = _scope_holders(db, Role.B2B, ScopeType.CUSTOMER)
    customers = db.scalars(select(BCustomer).order_by(BCustomer.id)).all()
    year = current_budget_year(db)
    b2b_depts = [d for d in depts.values() if d.name in B2B_DEPARTMENTS]
    b2b_depts.sort(key=lambda d: B2B_DEPARTMENTS.index(d.name))
    return {
        "items": [{"id": c.id, "name": c.name, "department_id": c.department_id,
                   "department_name": depts[c.department_id].name, "currency": c.currency,
                   "is_active": c.is_active, "owners": owners.get(c.id, [])} for c in customers],
        "by_department": {d.name: sum(1 for c in customers if c.department_id == d.id) for d in b2b_depts},
        "department_options": [{"id": d.id, "name": d.name} for d in b2b_depts],
        "currencies": [{"code": k, "name": v} for k, v in CURRENCY_NAMES.items()],
        "budget_year": year,
        "fx_rated_currencies": sorted(budget_fx_rates_map(db, year)),
    }


def _validate_customer(db: Session, data: dict, customer_id: int | None) -> tuple[str, Department, str]:
    name = _clean(data.get("name"))
    dept = db.get(Department, data.get("department_id")) if data.get("department_id") else None
    currency = _clean(data.get("currency")).upper()
    if not name:
        raise _required("请填写客户名称", "name")
    if dept is None:
        raise _required("请选择负责部门", "department_id")
    if dept.name not in B2B_DEPARTMENTS:
        raise ValidationFailed("负责部门只能是美国业务部或外贸部", details={"field": "department_id"})
    if not currency:
        raise _required("请选择结算币种", "currency")
    if currency not in CURRENCY_NAMES:
        raise ValidationFailed("结算币种不在可选清单中", details={"field": "currency"})
    if _name_taken(db, BCustomer, name, customer_id):
        raise _dup("客户名称不能重复")
    return name, dept, currency


def customer_snapshot(c: BCustomer) -> dict:
    return {"name": c.name, "department_id": c.department_id, "currency": c.currency, "is_active": c.is_active}


def create_customer(db: Session, data: dict) -> BCustomer:
    name, dept, currency = _validate_customer(db, data, None)
    c = BCustomer(name=name, department_id=dept.id, currency=currency, is_active=True)
    db.add(c)
    db.flush()
    return c


def update_customer(db: Session, c: BCustomer, data: dict) -> None:
    name, dept, currency = _validate_customer(db, data, c.id)
    if currency != c.currency and db.scalar(select(exists().where(B2bUnit.customer_id == c.id))):
        raise ValidationFailed("该客户已有预算数据，结算币种不可修改", code="currency_locked",
                               details={"field": "currency"})
    c.name, c.department_id, c.currency = name, dept.id, currency
    c.is_active = bool(data.get("is_active", c.is_active))
    db.flush()


def b2b_customers_for_department(db: Session, department_id: int) -> list[BCustomer]:
    """该负责部门 B 端填报中列出的客户：只含启用客户（AC-F02-09）。"""
    return list(db.scalars(select(BCustomer).where(BCustomer.department_id == department_id,
                                                   BCustomer.is_active.is_(True)).order_by(BCustomer.id)))


def list_departments(db: Session) -> dict:
    heads = _scope_holders(db, Role.DEPT_HEAD, ScopeType.DEPARTMENT)
    staff = _scope_holders(db, Role.DEPT_BUDGET, ScopeType.DEPARTMENT)
    depts = db.scalars(select(Department).order_by(Department.sort, Department.id)).all()
    return {"items": [{"id": d.id, "name": d.name, "is_active": d.is_active, "heads": heads.get(d.id, []),
                       "budget_staff": staff.get(d.id, [])} for d in depts]}


def create_department(db: Session, name: str) -> Department:
    name = _clean(name)
    if not name:
        raise _required("请填写部门名称", "name")
    if _name_taken(db, Department, name):
        raise _dup("部门名称已存在")
    d = Department(name=name, sort=(db.scalar(select(func.max(Department.sort))) or 0) + 1)
    db.add(d)
    db.flush()
    return d


def update_department(db: Session, d: Department, name: str, is_active: bool) -> None:
    name = _clean(name)
    if not name:
        raise _required("请填写部门名称", "name")
    if _name_taken(db, Department, name, d.id):
        raise _dup("部门名称已存在")
    d.name, d.is_active = name, is_active
    db.flush()


# ===========================================================================
# 预算科目与金蝶科目映射（API-F02-04 / API-F02-06；AC-F02-05、AC-F02-12）
# ===========================================================================
def list_budget_accounts(db: Session, usage: str | None = None) -> list[dict]:
    """usage=None 全部；mapping 映射下拉（启用科目）；dept_expense 部门费用填报（启用的部门费用科目）。"""
    q = select(BudgetAccount).order_by(BudgetAccount.sort, BudgetAccount.id)
    if usage in ("mapping", "dept_expense"):
        q = q.where(BudgetAccount.is_active.is_(True))
    if usage == "dept_expense":
        q = q.where(BudgetAccount.is_dept_expense.is_(True))
    counts = dict(db.execute(select(KingdeeAccountMap.account_id, func.count())
                             .where(KingdeeAccountMap.account_id.is_not(None))
                             .group_by(KingdeeAccountMap.account_id)).all())
    modified = _last_modified(db, "budget_account")
    return [{"id": a.id, "name": a.name, "is_dept_expense": a.is_dept_expense, "is_active": a.is_active,
             "status": "启用" if a.is_active else "停用", "mapped_count": counts.get(a.id, 0),
             "last_modified": modified.get(str(a.id))} for a in db.scalars(q)]


def dept_expense_accounts(db: Session) -> list[BudgetAccount]:
    """部门费用填报的预算科目：启用且为部门费用科目（停用科目不进入之后生成的填报行，AC-F02-12）。"""
    return list(db.scalars(select(BudgetAccount).where(BudgetAccount.is_active.is_(True),
                                                       BudgetAccount.is_dept_expense.is_(True))
                           .order_by(BudgetAccount.sort, BudgetAccount.id)))


def account_snapshot(a: BudgetAccount) -> dict:
    return {"name": a.name, "is_dept_expense": a.is_dept_expense, "is_active": a.is_active}


def create_budget_account(db: Session, name: str, is_dept_expense: bool = True) -> BudgetAccount:
    name = _clean(name)
    if not name:
        raise _required("请填写预算科目名称", "name")
    if _name_taken(db, BudgetAccount, name):
        raise _dup("预算科目名称已存在")
    a = BudgetAccount(name=name, is_dept_expense=is_dept_expense,
                      sort=(db.scalar(select(func.max(BudgetAccount.sort))) or 0) + 1)
    db.add(a)
    db.flush()
    return a


def update_budget_account(db: Session, a: BudgetAccount, name: str | None, status: str | None) -> None:
    if name is not None:
        name = _clean(name)
        if not name:
            raise _required("请填写预算科目名称", "name")
        if _name_taken(db, BudgetAccount, name, a.id):
            raise _dup("预算科目名称已存在")
        a.name = name
    if status is not None:
        if status not in ("启用", "停用"):
            raise ValidationFailed("状态只能是启用或停用", details={"field": "status"})
        a.is_active = status == "启用"
    db.flush()


def account_map_lookup(db: Session) -> dict[str, int]:
    """金蝶导入归集：金蝶科目编码 → 预算科目 ID（未映射的编码不在其中）。修改映射只影响之后的导入。"""
    return dict(db.execute(select(KingdeeAccountMap.kingdee_code, KingdeeAccountMap.account_id)
                           .where(KingdeeAccountMap.account_id.is_not(None))).all())


_UNMAPPED_ERROR_TYPES = {"account_unmapped", "kingdee_account_unmapped", "unmapped_account"}


def _latest_unmapped_from_import(db: Session) -> tuple[dict | None, dict[str, dict]]:
    """最近一次金蝶导入校验中出现的未映射科目（错误代码见 import_batch.errors）。"""
    batch = db.scalar(select(ImportBatch).where(ImportBatch.source.in_((ImportSource.KINGDEE,
                                                                        ImportSource.KINGDEE_HISTORY)),
                                                ImportBatch.parent_batch_id.is_(None))
                      .order_by(ImportBatch.uploaded_at.desc(), ImportBatch.id.desc()).limit(1))
    if batch is None:
        return None, {}
    found: dict[str, dict] = {}
    for err in batch.errors or []:
        if not isinstance(err, dict) or err.get("type") not in _UNMAPPED_ERROR_TYPES:
            continue
        code = str(err.get("code") or err.get("value") or "").strip()
        if not code:
            continue
        item = found.setdefault(code, {"kingdee_code": code, "kingdee_name": err.get("name"), "rows": 0})
        item["rows"] += int(err.get("rows") or 1)
    source = {"at": (batch.validated_at or batch.uploaded_at).isoformat(), "file_name": batch.file_name,
              "status": batch.status}
    return source, found


def list_account_mapping(db: Session) -> dict:
    accounts = {a.id: a for a in db.scalars(select(BudgetAccount))}
    users = dict(db.execute(select(User.id, User.name)).all())
    maps = db.scalars(select(KingdeeAccountMap).order_by(KingdeeAccountMap.kingdee_code)).all()
    source, from_import = _latest_unmapped_from_import(db)
    mapped_codes = {m.kingdee_code for m in maps if m.account_id is not None}
    unmapped: dict[str, dict] = {}
    for m in maps:
        if m.account_id is None:
            unmapped[m.kingdee_code] = {"kingdee_code": m.kingdee_code, "kingdee_name": m.kingdee_name, "rows": 0}
    for code, item in from_import.items():
        if code in mapped_codes:
            continue
        cur = unmapped.setdefault(code, {"kingdee_code": code, "kingdee_name": item["kingdee_name"], "rows": 0})
        cur["rows"] = item["rows"]
        cur["kingdee_name"] = cur["kingdee_name"] or item["kingdee_name"]
    items = []
    for m in maps:
        if m.account_id is None:
            continue
        a = accounts[m.account_id]
        items.append({"kingdee_code": m.kingdee_code, "kingdee_name": m.kingdee_name, "account_id": a.id,
                      "account_name": a.name, "account_active": a.is_active,
                      "updated_at": m.updated_at.isoformat() if m.updated_at else None,
                      "updated_by": users.get(m.updated_by)})
    return {
        "items": items,
        "unmapped": {"items": sorted(unmapped.values(), key=lambda x: x["kingdee_code"]),
                     "source": source if from_import else None},
        "account_options": [{"id": a["id"], "name": a["name"]} for a in list_budget_accounts(db, "mapping")],
        "summary": {"mapped": len(items), "accounts": len({i["account_id"] for i in items})},
    }


def save_account_mapping(db: Session, user_id: int, code: str, name: str | None, account_id: int | None,
                         create_only: bool) -> tuple[KingdeeAccountMap, dict | None]:
    code = _clean(code)
    if not code:
        raise _required("请填写金蝶科目编码", "kingdee_code")
    if not account_id:
        raise _required("请选择预算科目", "account_id")
    account = db.get(BudgetAccount, account_id)
    if account is None:
        raise ValidationFailed("预算科目不存在", details={"field": "account_id"})
    if not account.is_active:
        raise ValidationFailed("所选预算科目已停用，请选择启用的预算科目", details={"field": "account_id"})
    row = db.scalar(select(KingdeeAccountMap).where(KingdeeAccountMap.kingdee_code == code))
    before = None
    if row is not None:
        if create_only and row.account_id is not None:
            raise ValidationFailed("该金蝶科目编码已有映射，请在列表中修改", code="duplicate_code",
                                   details={"field": "kingdee_code"})
        before = {"kingdee_name": row.kingdee_name, "account_id": row.account_id}
    else:
        row = KingdeeAccountMap(kingdee_code=code)
        db.add(row)
    if name is not None and _clean(name):
        row.kingdee_name = _clean(name)
    row.account_id = account.id
    row.updated_by = user_id
    row.updated_at = clock.now()
    db.flush()
    return row, before


# ===========================================================================
# 汇率（API-F02-05；AC-F02-06/07/08/11；DEC-020）
# ===========================================================================
def budget_fx_rates_map(db: Session, year: int) -> dict[str, Decimal]:
    return dict(db.execute(select(FxBudget.currency, FxBudget.rate).where(FxBudget.year == year)).all())


def original_target_version(db: Session, year: int) -> BudgetVersion | None:
    return db.scalar(select(BudgetVersion).where(BudgetVersion.year == year,
                                                 BudgetVersion.type == VersionType.ORIGINAL_TARGET)
                     .order_by(BudgetVersion.id).limit(1))


def budget_fx_locked(db: Session, year: int) -> bool:
    """存在该年度「年初原始目标」版本即视为汇率已锁定（DEC-020，不另存状态）。"""
    return original_target_version(db, year) is not None


def missing_budget_fx(db: Session, year: int, currencies) -> list[str]:
    """该年度缺预算汇率的币种代码（人民币除外），按代码排序（AC-F02-07 提交时提示）。"""
    rated = set(budget_fx_rates_map(db, year))
    return sorted({c for c in currencies if c and c != "CNY"} - rated)


def actual_fx_rate(db: Session, month: date, currency: str) -> Decimal | None:
    return db.scalar(select(FxActual.rate).where(FxActual.month == month, FxActual.currency == currency))


def parse_fx_rate(value) -> Decimal:
    try:
        rate = to_decimal(value)
    except MoneyError as e:
        raise ValidationFailed(FX_FORMAT_MESSAGE, code="fx_format") from e
    if isinstance(value, str) and not value.strip():
        raise ValidationFailed(FX_FORMAT_MESSAGE, code="fx_format")
    if rate <= 0 or rate != rate.quantize(FOUR_DP):
        raise ValidationFailed(FX_FORMAT_MESSAGE, code="fx_format")
    return rate.quantize(FOUR_DP)


def _currency_usage(db: Session) -> dict[str, dict[str, int]]:
    usage: dict[str, dict[str, int]] = {}
    for cur, n in db.execute(select(Store.currency, func.count()).where(Store.is_active.is_(True))
                             .group_by(Store.currency)):
        usage.setdefault(cur, {"stores": 0, "customers": 0})["stores"] = n
    for cur, n in db.execute(select(BCustomer.currency, func.count()).where(BCustomer.is_active.is_(True))
                             .group_by(BCustomer.currency)):
        usage.setdefault(cur, {"stores": 0, "customers": 0})["customers"] = n
    usage.pop("CNY", None)
    return usage


def list_budget_fx(db: Session, year: int) -> dict:
    usage = _currency_usage(db)
    rows = {r.currency: r for r in db.scalars(select(FxBudget).where(FxBudget.year == year))}
    users = dict(db.execute(select(User.id, User.name)).all())
    version = original_target_version(db, year)
    lock_date = None
    if version is not None:
        lock_at = version.approved_at or version.created_at
        lock_date = lock_at.date().isoformat() if lock_at else None
    codes = sorted(set(usage) | set(rows), key=lambda c: (list(CURRENCY_NAMES).index(c)
                                                          if c in CURRENCY_NAMES else 99, c))
    items = []
    for code in codes:
        r = rows.get(code)
        u = usage.get(code, {"stores": 0, "customers": 0})
        items.append({"currency": code, "name": CURRENCY_NAMES.get(code, code),
                      "rate": format(r.rate.quantize(FOUR_DP), "f") if r else None,
                      "stores": u["stores"], "customers": u["customers"],
                      "editable": r is None or version is None,
                      "updated_at": r.updated_at.isoformat() if r and r.updated_at else None,
                      "updated_by": users.get(r.updated_by) if r else None})
    years = sorted(set(db.scalars(select(FxBudget.year).distinct())) | {current_budget_year(db), year}
                   | set(db.scalars(select(BudgetVersion.year).distinct())), reverse=True)
    return {"year": year, "years": years, "locked": version is not None, "locked_on": lock_date,
            "lock_message": FX_LOCKED_MESSAGE if version is not None else None,
            "items": items, "missing": [i["currency"] for i in items if i["rate"] is None and
                                        (i["stores"] or i["customers"])],
            "used_count": len(usage)}


def save_budget_fx(db: Session, user_id: int, year: int, currency: str, value) -> tuple[FxBudget, Decimal | None, int]:
    currency = _clean(currency).upper()
    if not currency or currency == "CNY" or len(currency) != 3:
        raise ValidationFailed("币种代码不合法", details={"field": "currency"})
    rate = parse_fx_rate(value)
    row = db.scalar(select(FxBudget).where(FxBudget.year == year, FxBudget.currency == currency))
    if row is not None and budget_fx_locked(db, year):
        raise Conflict(FX_LOCKED_MESSAGE, code="fx_locked")
    before = row.rate if row is not None else None
    if row is None:
        row = FxBudget(year=year, currency=currency, rate=rate, updated_by=user_id, updated_at=clock.now())
        db.add(row)
    else:
        row.rate, row.updated_by, row.updated_at = rate, user_id, clock.now()
    db.flush()
    recalculated = 0
    if before is None or before != rate:
        # 锁定前修改：同一事务内重算该年度全部未锁定版本中该币种的单元（DEC-020、AC-F02-06）
        recalculated = recalc_for_fx_change(db, year, currency)
    return row, before, recalculated


def list_actual_fx(db: Session, year: int) -> dict:
    months = [date(year, m, 1) for m in range(1, 13)]
    rates = {(r.month, r.currency): r.rate for r in db.scalars(
        select(FxActual).where(FxActual.month >= months[0], FxActual.month <= months[-1]))}
    bi = {(m, c) for m, c in db.execute(
        select(BiActualSku.month, BiActualSku.currency).where(BiActualSku.month >= months[0],
                                                              BiActualSku.month <= months[-1]).distinct())}
    currencies = sorted(set(_currency_usage(db)) | {c for _, c in rates} | {c for _, c in bi},
                        key=lambda c: (list(CURRENCY_NAMES).index(c) if c in CURRENCY_NAMES else 99, c))
    currencies = [c for c in currencies if c != "CNY"]
    rows = []
    missing = []
    for m in months:
        has_bi = any(mm == m for mm, _ in bi)
        rows.append({"month": fmt_month(m), "bi_imported": has_bi,
                     "rates": {c: (format(rates[(m, c)].quantize(FOUR_DP), "f") if (m, c) in rates else None)
                               for c in currencies}})
        for c in currencies:
            if (m, c) in bi and (m, c) not in rates:
                missing.append(f"{fmt_month(m)} {c}")
    return {"year": year, "currencies": currencies, "rows": rows, "missing": missing}


def save_actual_fx(db: Session, user_id: int, month_str: str, currency: str, value) -> tuple[FxActual, Decimal | None]:
    try:
        month = parse_month(month_str)
    except ValueError as e:
        raise ValidationFailed("月份格式应为 YYYY-MM", details={"field": "month"}) from e
    currency = _clean(currency).upper()
    if not currency or currency == "CNY" or len(currency) != 3:
        raise ValidationFailed("币种代码不合法", details={"field": "currency"})
    rate = parse_fx_rate(value)
    row = db.scalar(select(FxActual).where(FxActual.month == month, FxActual.currency == currency))
    before = row.rate if row is not None else None
    if row is None:
        row = FxActual(month=month, currency=currency, rate=rate, updated_by=user_id, updated_at=clock.now())
        db.add(row)
    else:
        row.rate, row.updated_by, row.updated_at = rate, user_id, clock.now()
    db.flush()
    # 当月平均汇率保存即重算该月 BI 归集的人民币收入（用于核对与汇率差，AC-F02-08、AC-F09-07）
    for agg in db.scalars(select(BiActualAgg).where(BiActualAgg.month == month, BiActualAgg.currency == currency)):
        agg.revenue_cny = agg.revenue_local * rate
    db.flush()
    return row, before


# ===========================================================================
# SKU 对照表（API-F02-02；AC-F02-03/04；DEC-021）
# ===========================================================================
SKU_COLUMNS = {"sku": "SKU", "spu": "SPU 编码", "category": "品类", "listed_on": "首次上架日期"}


@dataclass
class SkuRow:
    row: int
    sku: str
    spu: str
    category: str
    listed_on: date | None
    raw_date: str = ""


@dataclass
class SkuCheck:
    issues: list[dict] = field(default_factory=list)
    rows: list[SkuRow] = field(default_factory=list)


def _norm_header(v) -> str:
    return "".join(str(v or "").split()).upper()


def _cell_text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def _parse_date(v) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = _cell_text(v)
    parts = s.split("-")
    if len(parts) != 3 or len(parts[0]) != 4 or len(parts[1]) != 2 or len(parts[2]) != 2:
        return None
    try:
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        return None


def read_sku_sheet(content: bytes) -> list[list]:
    from python_calamine import CalamineWorkbook

    try:
        wb = CalamineWorkbook.from_filelike(io.BytesIO(content))
        return wb.get_sheet_by_index(0).to_python(skip_empty_area=False)
    except Exception as e:  # calamine 对非 Excel 文件抛多种异常
        raise ValidationFailed("无法读取文件，请上传 .xlsx 文件", code="bad_file") from e


def check_sku_rows(db: Session, table: list[list]) -> SkuCheck:
    """逐行校验并收集全部问题（不在第一个错误处停止）；行号为 Excel 行号（表头为第 1 行）。"""
    if not table:
        raise ValidationFailed("文件为空", code="bad_file")
    header = [_norm_header(h) for h in table[0]]
    idx: dict[str, int] = {}
    for key, label in SKU_COLUMNS.items():
        want = _norm_header(label)
        for i, h in enumerate(header):
            if h == want or h.startswith(want):
                idx[key] = i
                break
    missing_cols = [SKU_COLUMNS[k] for k in SKU_COLUMNS if k not in idx]
    if missing_cols:
        raise ValidationFailed(f"表头缺少列：{'、'.join(missing_cols)}", code="bad_header")
    categories = set(db.scalars(select(Category.name)))
    check = SkuCheck()
    seen_sku: dict[str, int] = {}
    spu_cat: dict[str, tuple[str, int]] = {}
    for offset, raw in enumerate(table[1:], start=2):
        cells = list(raw) + [None] * (len(header) - len(raw))
        if all(_cell_text(c) == "" for c in cells):
            continue
        sku = _cell_text(cells[idx["sku"]])
        spu = _cell_text(cells[idx["spu"]])
        cat = _cell_text(cells[idx["category"]])
        raw_date = cells[idx["listed_on"]]
        date_text = _cell_text(raw_date)
        missing = [label for key, label in (("sku", "SKU"), ("spu", "SPU 编码"), ("category", "品类"),
                                            ("listed_on", "首次上架日期"))
                   if not {"sku": sku, "spu": spu, "category": cat, "listed_on": date_text}[key]]
        problems = []
        if missing:
            joined = "、".join(missing)
            problems.append(("missing_field", f"缺少 {joined}" if joined[0].isascii() else f"缺少{joined}"))
        listed_on = _parse_date(raw_date) if date_text else None
        if date_text and listed_on is None:
            problems.append(("date_format", f"日期格式错误：{date_text}，应为 YYYY-MM-DD"))
        if sku:
            if sku in seen_sku:
                problems.append(("duplicate_sku", f"SKU 重复：与第 {seen_sku[sku]} 行相同"))
            else:
                seen_sku[sku] = offset
        if cat and cat not in categories:
            problems.append(("category_not_found", f"品类不在清单：{cat}"))
        elif cat and spu:
            first = spu_cat.get(spu)
            if first is None:
                spu_cat[spu] = (cat, offset)
            elif first[0] != cat:
                problems.append(("spu_category_conflict",
                                 f"同一 SPU 品类不一致：{spu} 在第 {first[1]} 行为「{first[0]}」，本行为「{cat}」"))
        for code, message in problems:
            check.issues.append({"row": offset, "sku": sku or None, "code": code, "message": message})
        if not problems:
            check.rows.append(SkuRow(offset, sku, spu, cat, listed_on, date_text))
    return check


def batch_payload(db: Session, batch: ImportBatch) -> dict:
    status = {ImportStatus.VALIDATION_FAILED: "failed", ImportStatus.PENDING_CONFIRM: "passed",
              ImportStatus.EFFECTIVE: "imported"}.get(batch.status, batch.status)
    summary = {}
    issues = []
    for e in batch.errors or []:
        if e.get("summary"):
            summary = e["summary"]
        else:
            issues.append({"row": e["row"], "sku": e.get("sku"), "type": e["message"], "name": e.get("sku"),
                           "message": e["message"], "code": e["code"]})
    return {"id": batch.id, "status": status, "file_name": batch.file_name, "row_count": batch.row_count,
            "issues": issues, "added": summary.get("added", 0), "updated": summary.get("updated", 0)}


def upload_sku_mapping(db: Session, user_id: int, file_name: str, content: bytes) -> dict:
    if not file_name.lower().endswith(".xlsx"):
        raise ValidationFailed("请上传 .xlsx 文件", code="bad_file")
    table = read_sku_sheet(content)
    check = check_sku_rows(db, table)
    now = clock.now()
    batch = ImportBatch(source=ImportSource.SKU, file_name=file_name, file_size=len(content),
                        sha256=hashlib.sha256(content).hexdigest(), uploaded_by=user_id, uploaded_at=now,
                        validated_at=now, row_count=len(check.rows) + len({i["row"] for i in check.issues}))
    if check.issues:
        batch.status = ImportStatus.VALIDATION_FAILED
        batch.errors = check.issues
        db.add(batch)
        db.flush()
        return batch_payload(db, batch)
    existing = set(db.scalars(select(Sku.code).where(Sku.code.in_([r.sku for r in check.rows]))))
    added = sum(1 for r in check.rows if r.sku not in existing)
    batch.status = ImportStatus.PENDING_CONFIRM
    batch.errors = [{"summary": {"added": added, "updated": len(check.rows) - added}}]
    db.add(batch)
    db.flush()
    db.add_all([ImportStaging(batch_id=batch.id, row_no=r.row,
                              data={"sku": r.sku, "spu": r.spu, "category": r.category,
                                    "listed_on": r.listed_on.isoformat()}) for r in check.rows])
    db.flush()
    return batch_payload(db, batch)


def get_sku_batch(db: Session, batch_id: int) -> ImportBatch:
    batch = db.get(ImportBatch, batch_id)
    if batch is None or batch.source != ImportSource.SKU:
        raise NotFound("上传记录不存在")
    return batch


def confirm_sku_mapping(db: Session, user_id: int, batch: ImportBatch) -> dict:
    """按 SKU 增改、不删除；SPU 首次上架日期在同一事务内重新派生为其下 SKU 最早日期（DEC-021）。"""
    if batch.status != ImportStatus.PENDING_CONFIRM:
        raise Conflict("该文件未通过校验或已写入", code="batch_not_pending")
    staged = db.scalars(select(ImportStaging).where(ImportStaging.batch_id == batch.id)
                        .order_by(ImportStaging.row_no)).all()
    cats = dict(db.execute(select(Category.name, Category.id)).all())
    spus = {s.code: s for s in db.scalars(select(Spu).where(Spu.code.in_({r.data["spu"] for r in staged})))}
    skus = {s.code: s for s in db.scalars(select(Sku).where(Sku.code.in_([r.data["sku"] for r in staged])))}
    touched_spu: set[int] = set()
    for r in staged:
        d = r.data
        listed = date.fromisoformat(d["listed_on"])
        spu = spus.get(d["spu"])
        if spu is None:
            spu = Spu(code=d["spu"], category_id=cats[d["category"]], first_listed_on=listed)
            db.add(spu)
            db.flush()
            spus[spu.code] = spu
        else:
            spu.category_id = cats[d["category"]]
        sku = skus.get(d["sku"])
        if sku is None:
            sku = Sku(code=d["sku"], spu_id=spu.id, listed_on=listed)
            db.add(sku)
            skus[sku.code] = sku
        else:
            if sku.spu_id != spu.id:
                touched_spu.add(sku.spu_id)
            sku.spu_id, sku.listed_on, sku.updated_at = spu.id, listed, clock.now()
        touched_spu.add(spu.id)
    db.flush()
    for spu_id in touched_spu:
        first = db.scalar(select(func.min(Sku.listed_on)).where(Sku.spu_id == spu_id))
        if first is not None:
            db.get(Spu, spu_id).first_listed_on = first
    batch.status = ImportStatus.EFFECTIVE
    batch.confirmed_at, batch.confirmed_by = clock.now(), user_id
    db.execute(ImportStaging.__table__.delete().where(ImportStaging.batch_id == batch.id))
    db.flush()
    return batch_payload(db, batch)


def list_sku_mapping(db: Session, month: date, q: str | None, category: str | None, kind: str | None,
                     page: int, page_size: int) -> dict:
    base = (select(Sku.code, Spu.code, Category.name, Sku.listed_on, Spu.first_listed_on)
            .join(Spu, Spu.id == Sku.spu_id).join(Category, Category.id == Spu.category_id))
    rows = []
    for sku, spu, cat, listed, first in db.execute(base.order_by(Spu.code, Sku.code)):
        new_until = add_months(first, 12)
        rows.append({"sku": sku, "spu": spu, "category": cat, "sku_listed_on": listed.isoformat(),
                     "spu_first_listed_on": first.isoformat(), "new_until": new_until.isoformat(),
                     "is_new": is_new_product(month, first)})
    new_spus = {r["spu"] for r in rows if r["is_new"]}
    filtered = [r for r in rows
                if (not q or q.lower() in r["sku"].lower() or q.lower() in r["spu"].lower())
                and (not category or r["category"] == category)
                and (not kind or (kind == "new") == r["is_new"])]
    last = db.scalar(select(ImportBatch).where(ImportBatch.source == ImportSource.SKU,
                                               ImportBatch.status == ImportStatus.EFFECTIVE)
                     .order_by(ImportBatch.confirmed_at.desc(), ImportBatch.id.desc()).limit(1))
    start = (page - 1) * page_size
    return {
        "month": fmt_month(month), "month_end": month_end(month).isoformat(),
        "summary": {"sku_count": len(rows), "spu_count": len({r["spu"] for r in rows}),
                    "category_count": len({r["category"] for r in rows}),
                    "last_upload": {"at": (last.confirmed_at or last.uploaded_at).isoformat(),
                                    "by": db.get(User, last.uploaded_by).name, "file_name": last.file_name}
                    if last else None},
        "categories": list(db.scalars(select(Category.name).order_by(Category.sort, Category.id))),
        "new_spu_count": len(new_spus),
        "total": len(filtered), "page": page, "page_size": page_size,
        "items": filtered[start:start + page_size],
    }


def sku_count(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(Sku)) or 0

