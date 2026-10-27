"""版本、季度调整与滚动预测（API-F08-01~06）。

每个业务路由声明认证与权限依赖；对比结果按数据范围过滤（NFR-003）。审批动作由 /approvals（G2）分发到
services.adjustments，本模块只负责发起、提交、进度、滚动预测与快照、版本列表与对比。
"""
from decimal import Decimal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.calc.periods import fmt_month, quarter_of
from app.core.auth import CurrentUser, get_current_user
from app.core.clock import clock
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.money import dec_str, fmt_cny
from app.core.scope import ScopeContext, get_scope, require_roles
from app.db import get_db
from app.models import BCustomer, BudgetVersion, Category, Channel, Department, Site, Store, TargetAdjustment
from app.models.enums import AdjustmentStatus, Role, VersionType
from app.services import adjustments
from app.services import versions as svc

router = APIRouter(prefix="/versions", tags=["versions"])

LIST_TYPES = (VersionType.ORIGINAL_TARGET, VersionType.ADJUSTED_TARGET, VersionType.SNAPSHOT)


def _link(request: Request, path: str) -> str:
    return f"{request.app.state.settings.APP_BASE_URL.rstrip('/')}{path}"


def _actor(current: CurrentUser) -> svc.Actor:
    return svc.Actor(user=current.user, roles=current.roles, auth_source=current.auth_source)


def _signed(value: Decimal) -> str:
    if value == 0:
        return "—"
    return ("+" if value > 0 else "−") + fmt_cny(abs(value))


def _version_rows(db: Session, year: int) -> list[dict]:
    rows = db.scalars(select(BudgetVersion).where(BudgetVersion.year == year, BudgetVersion.type.in_(LIST_TYPES))).all()
    targets = sorted([v for v in rows if v.type in svc.TARGET_TYPES], key=lambda v: v.version_no)
    snaps = sorted([v for v in rows if v.type == VersionType.SNAPSHOT], key=lambda v: v.quarter or 0)
    out = []
    for i, v in enumerate(targets):
        approver = db.get(svc.User, v.approved_by) if v.approved_by else None
        if v.type == VersionType.ORIGINAL_TARGET:
            status = "已锁定" if len(targets) > 1 else "已锁定 · 当前目标"
        elif i == len(targets) - 1:
            status = "当前目标"
        else:
            status = f"已被 V{targets[i + 1].version_no} 替代"
        out.append({"id": v.id, "label": svc.version_label(v), "type": v.type,
                    "type_label": VersionType.LABELS[v.type],
                    "quarter_label": f"{v.year} Q{v.quarter}" if v.quarter else "—", "status_label": status,
                    "current": i == len(targets) - 1,
                    "approver": f"{approver.name}（CEO 审批）" if approver else "—",
                    "time": svc.fmt_dt(v.approved_at), "reason": v.adjust_reason or (
                        f"{v.year} 年度全公司预算经 CEO 审批通过" if v.type == VersionType.ORIGINAL_TARGET else "")})
    for v in snaps:
        publisher = db.get(svc.User, v.approved_by) if v.approved_by else None
        out.append({"id": v.id, "label": svc.version_label(v), "type": v.type, "type_label": "滚动预测快照",
                    "quarter_label": f"{v.year} Q{v.quarter}", "status_label": "不可修改", "current": False,
                    "approver": f"{publisher.name}（发布）" if publisher else "—",
                    "time": svc.fmt_dt(v.approved_at), "published_on": v.published_on.isoformat()
                    if v.published_on else None, "reason": v.adjust_reason or ""})
    return out


def _rolling_card(db: Session, v: BudgetVersion | None) -> dict | None:
    if v is None:
        return None
    creator = db.get(svc.User, v.created_by) if v.created_by else None
    units = svc.rolling_units(db, v) if v.type == VersionType.ROLLING_DRAFT else []
    return {"id": v.id, "quarter": v.quarter, "type": v.type,
            "status_label": "填报中" if v.type == VersionType.ROLLING_DRAFT else "已发布快照",
            "initiated_by_name": creator.name if creator else ("—" if v.source_version_id else None),
            "initiated_at": svc.fmt_dt(v.created_at), "published_on": v.published_on.isoformat()
            if v.published_on else None,
            "open_months_text": f"{v.quarter * 3 - 2}–12 月（本季度及以后）" if v.quarter else "",
            "progress": {"total": len(units), "submitted": sum(u["submitted"] for u in units)},
            "unsubmitted": [u for u in units if not u["submitted"]], "units": units,
            "basis": v.adjust_reason}


@router.get("")
def list_versions(year: int | None = None, current: CurrentUser = Depends(get_current_user),
                  ctx: ScopeContext = Depends(get_scope), db: Session = Depends(get_db)):
    today = clock.today()
    if year is None:
        # 当年尚无版本（如编制期在上年第四季度）时默认显示最近有版本的年度
        has_current = db.scalar(select(BudgetVersion.id).where(BudgetVersion.year == today.year).limit(1))
        latest = db.scalar(select(func.max(BudgetVersion.year)))
        year = today.year if has_current or latest is None else latest
    quarter = quarter_of(today) if today.year == year else None
    through = svc.actual_through(db, year)
    is_fin = current.has_role(Role.FINANCE_HEAD)
    adj = db.scalar(select(TargetAdjustment).where(TargetAdjustment.year == year,
                                                   TargetAdjustment.status.in_((AdjustmentStatus.IN_PROGRESS,
                                                                                AdjustmentStatus.PENDING_CEO))))
    if adj is None and quarter:
        adj = db.scalar(select(TargetAdjustment).where(TargetAdjustment.year == year,
                                                       TargetAdjustment.quarter == quarter))
    rolling = svc.rolling_version(db, year, quarter) if quarter else None
    adj_block = adjustments.block_reason(db, year, quarter) if quarter else ("not_current", "只能在当年发起")
    roll_block = None
    if not quarter:
        roll_block = "只能在当年发起"
    elif rolling is not None:
        roll_block = f"{year} Q{quarter} 滚动更新已发起。"
    elif svc.current_target(db, year) is None:
        roll_block = f"{year} 年度还没有年初原始目标"
    q1_visible = bool(quarter == 1 and rolling is None and svc.original_target(db, year))
    years = sorted(set(db.scalars(select(BudgetVersion.year).distinct())) | {today.year})
    data = {
        "year": year, "years": years, "today": today.isoformat(), "quarter": quarter,
        "actual_through": fmt_month(through) if through else None,
        "is_finance_head": is_fin, "versions": _version_rows(db, year),
        "adjustment": adjustments.adjustment_view(db, adj) if adj and is_fin else None,
        "adjustable_months": [fmt_month(m) for m in adjustments.adjustable_months(db, year)],
        "rolling": _rolling_card(db, rolling) if is_fin else None,
        "actions": {
            "adjust": {"enabled": is_fin and adj_block is None, "reason": adj_block[1] if adj_block else None},
            "rolling": {"enabled": is_fin and roll_block is None, "reason": roll_block},
            "publish_original": {"visible": is_fin and q1_visible},
        },
        "my_adjustment_units": adjustments.my_units(db, current),
        "my_rolling": None,
    }
    if rolling is not None and rolling.type == VersionType.ROLLING_DRAFT:
        mine = [u for u in svc.rolling_units(db, rolling) if u["filler_id"] == current.user.id]
        if mine:
            data["my_rolling"] = {"id": rolling.id, "quarter": rolling.quarter, "units": mine,
                                  "open_months_text": f"{rolling.quarter * 3 - 2}–12 月",
                                  "actual_through": data["actual_through"]}
    return data


class CompareDims:
    LABELS = {"channel": "渠道 × 店铺 × 站点", "category": "品类 × 新品/老品", "customer": "B端客户"}


@router.get("/compare")
def compare(a: int, b: int, dims: str = "channel", ctx: ScopeContext = Depends(get_scope),
            db: Session = Depends(get_db)):
    if dims not in CompareDims.LABELS:
        raise ValidationFailed("维度只能是 channel / category / customer")
    if a == b:
        raise ValidationFailed("请选择两个不同的版本", code="same_version")
    va, vb = svc.get_version(db, a), svc.get_version(db, b)
    for v in (va, vb):
        if v.type not in LIST_TYPES:
            raise NotFound("版本不存在")
    ta, tb = svc.version_dimension_totals(db, va, dims, ctx), svc.version_dimension_totals(db, vb, dims, ctx)
    zero = Decimal(0)
    rows = []
    for key in set(ta) | set(tb):
        ra, ga = ta.get(key, (zero, zero))
        rb, gb = tb.get(key, (zero, zero))
        rows.append({"key": "|".join(str(k) for k in key), **_dims_view(db, dims, key),
                     **_money("revenue", ra, rb), **_money("gross", ga, gb), "net_display": "—"})
    rows.sort(key=lambda r: r["sort"])
    total_ra = sum((Decimal(r["revenue_a"]) for r in rows), zero)
    total_rb = sum((Decimal(r["revenue_b"]) for r in rows), zero)
    total_ga = sum((Decimal(r["gross_a"]) for r in rows), zero)
    total_gb = sum((Decimal(r["gross_b"]) for r in rows), zero)
    company = None
    kpis = {**_money("revenue", total_ra, total_rb), **_money("gross", total_ga, total_gb)}
    if ctx.all_company:
        ca, cb = svc.company_totals(db, va), svc.company_totals(db, vb)
        company = _money("net", ca.net, cb.net)
        kpis = {**_money("revenue", ca.revenue, cb.revenue), **_money("gross", ca.gross, cb.gross), **company}
    scope_text = "全公司" if ctx.all_company else _scope_text(db, ctx)
    return {"a": {"id": va.id, "label": svc.version_label(va), "type_label": VersionType.LABELS[va.type]},
            "b": {"id": vb.id, "label": svc.version_label(vb), "type_label": VersionType.LABELS[vb.type]},
            "dims": dims, "dims_label": CompareDims.LABELS[dims], "scope_text": scope_text,
            "all_company": ctx.all_company, "kpis": kpis, "rows": rows,
            "total": {**_money("revenue", total_ra, total_rb), **_money("gross", total_ga, total_gb),
                      "net_display": "—"},
            "company": company}


def _money(prefix: str, a: Decimal, b: Decimal) -> dict:
    return {f"{prefix}_a": dec_str(a), f"{prefix}_b": dec_str(b), f"{prefix}_diff": dec_str(b - a),
            f"{prefix}_a_display": fmt_cny(a), f"{prefix}_b_display": fmt_cny(b),
            f"{prefix}_diff_display": _signed(b - a)}


def _dims_view(db: Session, dims: str, key: tuple) -> dict:
    if dims == "channel":
        store = db.get(Store, key[0])
        channel, site = db.get(Channel, store.channel_id), db.get(Site, store.site_id)
        return {"store": store.name, "site": site.name, "channel": channel.name,
                "sort": (channel.sort, store.id, 0)}
    if dims == "category":
        cat = db.get(Category, key[0])
        return {"category": cat.name, "is_new": key[1], "is_new_label": "新品" if key[1] else "老品",
                "sort": (cat.sort, 0 if key[1] else 1, 0)}
    cust = db.get(BCustomer, key[0])
    dept = db.get(Department, cust.department_id)
    return {"customer": cust.name, "department": dept.name, "currency": cust.currency, "sort": (dept.sort, cust.id, 0)}


def _scope_text(db: Session, ctx: ScopeContext) -> str:
    parts = []
    if ctx.store_ids:
        parts.append("店铺 " + "、".join(db.scalars(select(Store.name).where(Store.id.in_(ctx.store_ids))
                                                     .order_by(Store.id))))
    if ctx.customer_ids:
        parts.append("B端客户 " + "、".join(db.scalars(select(BCustomer.name)
                                                        .where(BCustomer.id.in_(ctx.customer_ids)))))
    if ctx.department_ids:
        parts.append("部门 " + "、".join(db.scalars(select(Department.name)
                                                     .where(Department.id.in_(ctx.department_ids)))))
    return "；".join(parts) or "无数据范围"


@router.get("/{version_id}/summary")
def version_summary(version_id: int, store_id: int | None = None, ctx: ScopeContext = Depends(get_scope),
                    db: Session = Depends(get_db)):
    """版本月度汇总：公司月度收入 / 毛利 / 净利润与来源；带 store_id 时为该店铺月度收入与毛利。"""
    v = svc.get_version(db, version_id)
    if store_id is not None:
        store = db.get(Store, store_id)
        if store is None:
            raise NotFound("店铺不存在")
        ctx.ensure_store(store.id, store.channel_id)
        data = {m: val for (m, s), val in svc.version_store_monthly(db, v).items() if s == store_id}
        months = [{"month": fmt_month(m), "revenue": dec_str(r), "revenue_display": fmt_cny(r),
                   "gross": dec_str(g), "source": src} for m, (r, g, src) in sorted(data.items())]
        return {"id": v.id, "label": svc.version_label(v), "store": store.name, "months": months}
    if not ctx.all_company:
        from app.core.errors import Forbidden
        raise Forbidden()
    rows = svc.version_company_monthly(db, v)
    return {"id": v.id, "label": svc.version_label(v), "locked": v.locked,
            "published_on": v.published_on.isoformat() if v.published_on else None,
            "quarter_label": f"{v.year} Q{v.quarter}" if v.quarter else None,
            "months": [{"month": fmt_month(m), "revenue": dec_str(line.revenue), "gross": dec_str(line.gross),
                        "net": dec_str(line.net), "source": src} for m, (line, src) in sorted(rows.items())]}


# ---------------------------------------------------------------------------
# 目标调整
# ---------------------------------------------------------------------------
@router.post("/adjustments")
def start_adjustment(request: Request, current: CurrentUser = Depends(require_roles(Role.FINANCE_HEAD)),
                     db: Session = Depends(get_db)):
    adj = adjustments.start_adjustment(db, current, today=clock.today())
    view = adjustments.adjustment_view(db, adj)
    db.commit()
    return view


@router.get("/adjustments/{adjustment_id}", dependencies=[Depends(get_scope)])
def adjustment_progress(adjustment_id: int, current: CurrentUser = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    adj = db.get(TargetAdjustment, adjustment_id)
    if adj is None:
        raise NotFound("目标调整不存在")
    view = adjustments.adjustment_view(db, adj)
    if not current.has_role(Role.FINANCE_HEAD, Role.CEO):
        mine = [u for u in view["units"] if u["filler_id"] == current.user.id]
        if not mine:
            from app.core.errors import Forbidden
            raise Forbidden()
        view["units"] = mine
    return view


class SubmitIn(BaseModel):
    adjust_reason: str | None = None


@router.post("/adjustments/units/{unit_id}/submit", dependencies=[Depends(get_scope)])
def submit_adjustment_unit(unit_id: int, body: SubmitIn, current: CurrentUser = Depends(get_current_user),
                           db: Session = Depends(get_db)):
    unit = adjustments.submit_unit(db, current, unit_id, body.adjust_reason)
    view = adjustments.unit_view(db, unit)
    db.commit()
    return view


# ---------------------------------------------------------------------------
# 滚动预测与快照
# ---------------------------------------------------------------------------
@router.post("/rolling")
def start_rolling(request: Request, current: CurrentUser = Depends(require_roles(Role.FINANCE_HEAD)),
                  db: Session = Depends(get_db)):
    v = svc.start_rolling(db, _actor(current), today=clock.today(), link=_link(request, "/versions"))
    card = _rolling_card(db, v)
    db.commit()
    return card


@router.post("/rolling/publish-original")
def publish_original(current: CurrentUser = Depends(require_roles(Role.FINANCE_HEAD)),
                     db: Session = Depends(get_db)):
    v = svc.publish_original(db, _actor(current), today=clock.today())
    db.commit()
    return {"id": v.id, "label": svc.version_label(v), "published_on": v.published_on.isoformat()}


@router.get("/rolling/{version_id}", dependencies=[Depends(get_scope)])
def rolling_detail(version_id: int, current: CurrentUser = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    v = svc.get_version(db, version_id)
    if v.type not in (VersionType.ROLLING_DRAFT, VersionType.SNAPSHOT) or v.quarter is None:
        raise NotFound("滚动预测不存在")
    card = _rolling_card(db, v)
    if not current.has_role(Role.FINANCE_HEAD, Role.CEO, Role.FINANCE_BP):
        card["units"] = [u for u in card["units"] if u["filler_id"] == current.user.id]
        card["unsubmitted"] = []
    return card


@router.post("/rolling/{version_id}/units/{unit_key}/submit", dependencies=[Depends(get_scope)])
def submit_rolling_unit(version_id: int, unit_key: str, current: CurrentUser = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    result = svc.submit_rolling_unit(db, _actor(current), version_id, unit_key)
    db.commit()
    return result


class PublishIn(BaseModel):
    confirm_unsubmitted: bool = False


@router.post("/rolling/{version_id}/publish")
def publish_rolling(version_id: int, body: PublishIn,
                    current: CurrentUser = Depends(require_roles(Role.FINANCE_HEAD)), db: Session = Depends(get_db)):
    try:
        result = svc.publish_rolling(db, _actor(current), version_id, confirm_unsubmitted=body.confirm_unsubmitted,
                                     today=clock.today())
    except Conflict:
        db.rollback()
        raise
    v = svc.get_version(db, result["id"])
    db.commit()
    return {"id": v.id, "label": svc.version_label(v), "published_on": v.published_on.isoformat(),
            "quarter_label": f"{v.year} Q{v.quarter}", "basis": v.adjust_reason}

