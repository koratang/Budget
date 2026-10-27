"""预算版本、季度滚动预测与版本对比（CMP-F08-01；AC-F08-05~09，DEC-016）。

- 目标版本：年初原始目标 V1（version_no = 1）与调整后目标 Vn（version_no 递增），「当前目标」取版本号最大者。
- 已导入金蝶实际的月份：存在「已生效」的金蝶（含历史）逻辑批次的期间。
- 滚动预测：发起时复制来源版本全部数据行为「滚动预测稿」，只开放本季度及以后月份；填报人的提交记录写审计日志
  （action = rolling_unit_submitted），发布时未提交单位的数据恢复为来源版本数值后再计算。
- 季度快照：已导入实际的月份取金蝶实际，其余取版本数据；发布后版本锁定，并写入冻结的月度汇总 snapshot_month。
  快照的店铺级实际取「发布时刻已生效」的金蝶批次，之后的覆盖导入不改变快照。
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session, aliased

from app.calc.periods import fmt_month, quarter_of, year_months
from app.calc.recalc import recalc_b2b_units, recalc_platform_units
from app.core.audit import write_audit
from app.core.clock import clock
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.dingtalk.outbox import build_notice, enqueue_notice
from app.models import (AuditLog, B2bUnit, BCustomer, BudgetAccount, BudgetVersion, CompanyOtherPl, Department,
                        DeptExpense, ImportBatch, KingdeeActual, PlatformUnit, Reserve, SnapshotMonth, Store, User,
                        UserRole, UserScope)
from app.models.enums import ImportSource, ImportStatus, Role, ScopeType, UnitType, VersionType

ZERO = Decimal(0)
TARGET_TYPES = (VersionType.ORIGINAL_TARGET, VersionType.ADJUSTED_TARGET)
KINGDEE_SOURCES = (ImportSource.KINGDEE, ImportSource.KINGDEE_HISTORY)
LOCKED_MESSAGE = "版本已锁定，不能修改"

# 预算版本数据表（复制版本时按此清单 INSERT … SELECT，DEC-016）
_COPY_TABLES = {
    "platform_unit": ("month, channel_id, store_id, site_id, category_id, is_new, spu_count, avg_sales, avg_price, "
                      "discount_rate, refund_rate, ad_rate, commission_rate, sales_qty, revenue_local, revenue_cny, "
                      "refund, purchase_cost, commission, promotion, first_leg, last_mile, tariff, storage, "
                      "inventory_claim, other_opex, gross_profit, gross_margin, over_limit, over_limit_reason, "
                      "updated_by, updated_at"),
    "channel_category_ratio": ("month, channel_id, site_id, category_id, purchase_cost_rate, first_leg_rate, "
                               "last_mile_rate, storage_rate, tariff_rate, updated_by, updated_at"),
    "channel_site_ratio": "month, channel_id, site_id, inventory_claim_rate, other_opex_rate, updated_by, updated_at",
    "b2b_unit": ("month, customer_id, sales_local, refund_rate, promotion_rate, other_opex_rate, commission_rate, "
                 "inventory_claim_rate, purchase_cost_rate, first_leg_rate, last_mile_rate, storage_rate, tariff_rate, "
                 "revenue_cny, refund, purchase_cost, commission, promotion, first_leg, last_mile, tariff, storage, "
                 "inventory_claim, other_opex, gross_profit, gross_margin, updated_by, updated_at"),
    "dept_expense": "month, department_id, account_id, amount, updated_by, updated_at",
    "company_other_pl": "month, item, amount, updated_by, updated_at",
    "reserve": "department_id, account_id, name, amount, plan_month, created_by, created_at",
}

# 金蝶实际的损益口径：收入类为正向，其余为支出方向（发生额为正表示支出）
INCOME_ITEMS = frozenset({"revenue", "inventory_claim"})
CHANNEL_ITEMS = frozenset({"revenue", "refund", "purchase_cost", "commission", "promotion", "first_leg", "last_mile",
                           "tariff", "storage", "inventory_claim", "other_opex"})


# ---------------------------------------------------------------------------
# 当前用户（审批接口的 user 参数可能是 CurrentUser，也可能是 User）
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Actor:
    user: User
    roles: frozenset[str]
    auth_source: str | None = None

    @property
    def id(self) -> int:
        return self.user.id

    def has_role(self, *roles: str) -> bool:
        return bool(self.roles & set(roles))


def as_actor(db: Session, user) -> Actor:
    if isinstance(user, Actor):
        return user
    if hasattr(user, "user") and hasattr(user, "roles"):
        return Actor(user=user.user, roles=frozenset(user.roles), auth_source=getattr(user, "auth_source", None))
    roles = frozenset(db.scalars(select(UserRole.role_code).where(UserRole.user_id == user.id)))
    return Actor(user=user, roles=roles)


def audit(db: Session, actor: Actor | None, **kw):
    """write_audit 需要 CurrentUser 形态（.user / .auth_source），Actor 满足该形态。"""
    return write_audit(db, actor=actor, **kw)  # type: ignore[arg-type]


def users_with_role(db: Session, role: str) -> list[User]:
    return list(db.scalars(select(User).join(UserRole, UserRole.user_id == User.id)
                           .where(UserRole.role_code == role, User.is_active.is_(True)).order_by(User.id)))


def notify(db: Session, *, biz_type: str, biz_id: int | None, users: list[User | None], title: str, name: str,
           object_name: str = "", period: str = "", link: str) -> None:
    receivers = [u.dingtalk_userid for u in users if u is not None and u.is_active]
    enqueue_notice(db, biz_type=biz_type, biz_id=biz_id, receivers=receivers,
                   content=build_notice(title=title, name=name, object_name=object_name, period=period, link=link))


def fmt_dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    from app.core.clock import TZ
    return value.astimezone(TZ).strftime("%Y-%m-%d %H:%M")


# ---------------------------------------------------------------------------
# 版本查询
# ---------------------------------------------------------------------------
def target_versions(db: Session, year: int) -> list[BudgetVersion]:
    rows = db.scalars(select(BudgetVersion).where(BudgetVersion.year == year,
                                                  BudgetVersion.type.in_(TARGET_TYPES))).all()
    return sorted(rows, key=lambda v: v.version_no)


def current_target(db: Session, year: int) -> BudgetVersion | None:
    rows = target_versions(db, year)
    return rows[-1] if rows else None


def original_target(db: Session, year: int) -> BudgetVersion | None:
    return db.scalar(select(BudgetVersion).where(BudgetVersion.year == year,
                                                 BudgetVersion.type == VersionType.ORIGINAL_TARGET))


def version_label(v: BudgetVersion) -> str:
    if v.type in TARGET_TYPES:
        return f"V{v.version_no}"
    if v.type == VersionType.SNAPSHOT:
        return f"Q{v.quarter} 快照"
    if v.type == VersionType.ROLLING_DRAFT:
        return f"Q{v.quarter} 滚动预测稿"
    if v.type == VersionType.ADJUSTMENT_DRAFT:
        return f"Q{v.quarter} 调整稿" if v.quarter else "调整稿"
    return VersionType.LABELS.get(v.type, v.type)


def get_version(db: Session, version_id: int) -> BudgetVersion:
    v = db.get(BudgetVersion, version_id)
    if v is None:
        raise NotFound("版本不存在")
    return v


def ensure_version_editable(db: Session, version_id: int) -> BudgetVersion:
    """服务层第一道防线：锁定版本（原始目标、调整后目标、快照）的任何修改返回 409（DEC-016）。"""
    v = get_version(db, version_id)
    if v.locked:
        raise Conflict(LOCKED_MESSAGE, code="version_locked")
    return v


def open_months(db: Session, version_id: int) -> set[date] | None:
    """版本中允许编辑的月份（供填报表格判定）：None 表示不限制；空集表示全部锁定。
    调整稿：尚未导入金蝶实际的月份（AC-F08-02）；滚动预测稿：本季度及以后月份（AC-F08-05）。"""
    v = get_version(db, version_id)
    if v.locked:
        return set()
    if v.type == VersionType.ADJUSTMENT_DRAFT:
        done = actual_months(db, v.year)
        return {m for m in year_months(v.year) if m not in done}
    if v.type == VersionType.ROLLING_DRAFT and v.quarter:
        return {m for m in year_months(v.year) if quarter_of(m) >= v.quarter}
    return None


# ---------------------------------------------------------------------------
# 已导入金蝶实际的月份与金蝶实际汇总
# ---------------------------------------------------------------------------
def actual_months(db: Session, year: int | None = None) -> set[date]:
    q = select(ImportBatch.period).where(ImportBatch.source.in_(KINGDEE_SOURCES),
                                         ImportBatch.status == ImportStatus.EFFECTIVE,
                                         ImportBatch.period.is_not(None)).distinct()
    months = set(db.scalars(q))
    return {m for m in months if year is None or m.year == year}


def actual_through(db: Session, year: int) -> date | None:
    months = actual_months(db, year)
    return max(months) if months else None


def kingdee_batches_effective_at(db: Session, months: list[date], at: datetime | None) -> list[int]:
    """各月在时刻 at 生效的金蝶逻辑批次（at 为空取当前生效批次）。"""
    if not months:
        return []
    if at is None:
        return list(db.scalars(select(ImportBatch.id).where(
            ImportBatch.source.in_(KINGDEE_SOURCES), ImportBatch.status == ImportStatus.EFFECTIVE,
            ImportBatch.period.in_(months))))
    repl = aliased(ImportBatch)
    q = (select(ImportBatch.id)
         .outerjoin(repl, repl.id == ImportBatch.replaced_by_batch_id)
         .where(ImportBatch.source.in_(KINGDEE_SOURCES), ImportBatch.period.in_(months),
                ImportBatch.status.in_((ImportStatus.EFFECTIVE, ImportStatus.REPLACED)),
                ImportBatch.confirmed_at <= at,
                or_(ImportBatch.replaced_by_batch_id.is_(None), repl.confirmed_at > at)))
    return list(db.scalars(q))


@dataclass
class PlLine:
    revenue: Decimal = ZERO
    gross: Decimal = ZERO
    dept: Decimal = ZERO
    other: Decimal = ZERO   # 公司层其他损益（收益为正）

    @property
    def net(self) -> Decimal:
        return self.gross - self.dept + self.other


def _signed(pl_item: str | None, amount: Decimal) -> Decimal:
    return amount if pl_item in INCOME_ITEMS else -amount


def kingdee_rows(db: Session, batch_ids: list[int]):
    """金蝶实际行（月、店铺、站点、客户、部门、未归属、损益口径、是否部门费用、金额）。"""
    if not batch_ids:
        return []
    return db.execute(
        select(KingdeeActual.month, KingdeeActual.store_id, KingdeeActual.site_id, KingdeeActual.customer_id,
               KingdeeActual.department_id, KingdeeActual.unassigned, BudgetAccount.pl_item,
               BudgetAccount.is_dept_expense, func.sum(KingdeeActual.amount))
        .join(BudgetAccount, BudgetAccount.id == KingdeeActual.account_id)
        .where(KingdeeActual.batch_id.in_(batch_ids))
        .group_by(KingdeeActual.month, KingdeeActual.store_id, KingdeeActual.site_id, KingdeeActual.customer_id,
                  KingdeeActual.department_id, KingdeeActual.unassigned, BudgetAccount.pl_item,
                  BudgetAccount.is_dept_expense)).all()


def actual_monthly(db: Session, months: list[date], at: datetime | None = None) -> dict[date, PlLine]:
    """金蝶实际的公司月度损益：收入、毛利（渠道口径，含 B 端与未归属渠道）、部门费用、公司层其他损益。"""
    out: dict[date, PlLine] = {m: PlLine() for m in months}
    for month, _s, _site, _c, _d, _u, item, is_dept, amount in kingdee_rows(
            db, kingdee_batches_effective_at(db, months, at)):
        line = out.setdefault(month, PlLine())
        if is_dept:
            line.dept += amount
        elif item in CHANNEL_ITEMS:
            line.gross += _signed(item, amount)
            if item == "revenue":
                line.revenue += amount
        else:
            line.other += _signed(item, amount)
    return out


def actual_store_monthly(db: Session, months: list[date], at: datetime | None = None
                         ) -> dict[tuple[date, int], tuple[Decimal, Decimal]]:
    """金蝶实际按（月, 店铺）的人民币收入与毛利。"""
    out: dict[tuple[date, int], list[Decimal]] = defaultdict(lambda: [ZERO, ZERO])
    for month, store_id, _site, _c, _d, _u, item, is_dept, amount in kingdee_rows(
            db, kingdee_batches_effective_at(db, months, at)):
        if store_id is None or is_dept or item not in CHANNEL_ITEMS:
            continue
        acc = out[(month, store_id)]
        if item == "revenue":
            acc[0] += amount
        acc[1] += _signed(item, amount)
    return {k: (v[0], v[1]) for k, v in out.items()}


def actual_customer_monthly(db: Session, months: list[date], at: datetime | None = None
                            ) -> dict[tuple[date, int], tuple[Decimal, Decimal]]:
    out: dict[tuple[date, int], list[Decimal]] = defaultdict(lambda: [ZERO, ZERO])
    for month, store_id, _site, customer_id, _d, _u, item, is_dept, amount in kingdee_rows(
            db, kingdee_batches_effective_at(db, months, at)):
        if customer_id is None or store_id is not None or is_dept or item not in CHANNEL_ITEMS:
            continue
        acc = out[(month, customer_id)]
        if item == "revenue":
            acc[0] += amount
        acc[1] += _signed(item, amount)
    return {k: (v[0], v[1]) for k, v in out.items()}


# ---------------------------------------------------------------------------
# 版本数据汇总
# ---------------------------------------------------------------------------
def data_version_id(db: Session, v: BudgetVersion) -> int:
    """持有单元数据的版本：Q1 以原始目标发布的快照没有单元行，取其来源版本。"""
    has_rows = db.scalar(select(func.count()).select_from(PlatformUnit).where(PlatformUnit.version_id == v.id)) or \
        db.scalar(select(func.count()).select_from(DeptExpense).where(DeptExpense.version_id == v.id))
    if not has_rows and v.source_version_id:
        return v.source_version_id
    return v.id


def forecast_monthly(db: Session, version_id: int) -> dict[date, PlLine]:
    """版本数据的公司月度损益：Σ平台毛利 + ΣB 端毛利 − Σ部门费用（含专项）+ 公司层其他损益。"""
    out: dict[date, PlLine] = defaultdict(PlLine)
    for month, rev, gross in db.execute(
            select(PlatformUnit.month, func.coalesce(func.sum(PlatformUnit.revenue_cny), 0),
                   func.coalesce(func.sum(PlatformUnit.gross_profit), 0))
            .where(PlatformUnit.version_id == version_id).group_by(PlatformUnit.month)):
        out[month].revenue += rev
        out[month].gross += gross
    for month, rev, gross in db.execute(
            select(B2bUnit.month, func.coalesce(func.sum(B2bUnit.revenue_cny), 0),
                   func.coalesce(func.sum(B2bUnit.gross_profit), 0))
            .where(B2bUnit.version_id == version_id).group_by(B2bUnit.month)):
        out[month].revenue += rev
        out[month].gross += gross
    for month, amount in db.execute(select(DeptExpense.month, func.sum(DeptExpense.amount))
                                    .where(DeptExpense.version_id == version_id).group_by(DeptExpense.month)):
        out[month].dept += amount
    for month, amount in db.execute(select(Reserve.plan_month, func.sum(Reserve.amount))
                                    .where(Reserve.version_id == version_id).group_by(Reserve.plan_month)):
        out[month].dept += amount
    for month, amount in db.execute(select(CompanyOtherPl.month, func.sum(CompanyOtherPl.amount))
                                    .where(CompanyOtherPl.version_id == version_id).group_by(CompanyOtherPl.month)):
        out[month].other += amount
    return dict(out)


def forecast_store_monthly(db: Session, version_id: int) -> dict[tuple[date, int], tuple[Decimal, Decimal]]:
    rows = db.execute(select(PlatformUnit.month, PlatformUnit.store_id,
                             func.coalesce(func.sum(PlatformUnit.revenue_cny), 0),
                             func.coalesce(func.sum(PlatformUnit.gross_profit), 0))
                      .where(PlatformUnit.version_id == version_id)
                      .group_by(PlatformUnit.month, PlatformUnit.store_id))
    return {(m, s): (r, g) for m, s, r, g in rows}


def snapshot_actual_months(db: Session, v: BudgetVersion) -> set[date]:
    return set(db.scalars(select(SnapshotMonth.month).where(SnapshotMonth.version_id == v.id,
                                                            SnapshotMonth.source == "actual")))


def version_store_monthly(db: Session, v: BudgetVersion) -> dict[tuple[date, int], tuple[Decimal, Decimal, str]]:
    """版本按（月, 店铺）的人民币收入、毛利与来源（forecast / actual）。快照的已导入月份取发布时刻的金蝶实际。"""
    out = {k: (r, g, "forecast") for k, (r, g) in forecast_store_monthly(db, data_version_id(db, v)).items()}
    if v.type == VersionType.SNAPSHOT:
        months = sorted(snapshot_actual_months(db, v))
        if months:
            out = {k: val for k, val in out.items() if k[0] not in months}
            for k, (r, g) in actual_store_monthly(db, months, v.approved_at).items():
                out[k] = (r, g, "actual")
    return out


def version_company_monthly(db: Session, v: BudgetVersion) -> dict[date, tuple[PlLine, str]]:
    """版本公司月度损益与来源；快照直接读冻结汇总。"""
    if v.type == VersionType.SNAPSHOT:
        rows = db.scalars(select(SnapshotMonth).where(SnapshotMonth.version_id == v.id)).all()
        if rows:
            return {r.month: (PlLine(revenue=r.revenue_cny, gross=r.gross_profit,
                                     other=r.net_profit - r.gross_profit), r.source) for r in rows}
    data = forecast_monthly(db, data_version_id(db, v))
    return {m: (data.get(m, PlLine()), "forecast") for m in year_months(v.year)}


# ---------------------------------------------------------------------------
# 复制版本（DEC-016）
# ---------------------------------------------------------------------------
def copy_version_rows(db: Session, source_id: int, target_id: int) -> None:
    for table, cols in _COPY_TABLES.items():
        db.execute(text(f"INSERT INTO {table} (version_id, {cols}) SELECT :t, {cols} FROM {table} "
                        f"WHERE version_id = :s"), {"t": target_id, "s": source_id})
    db.flush()


# ---------------------------------------------------------------------------
# 滚动预测（AC-F08-05~07、AC-F08-09）
# ---------------------------------------------------------------------------
ROLLING_ROLES = (Role.OPERATIONS, Role.B2B, Role.LOGISTICS, Role.FINANCE_BP)


def rolling_version(db: Session, year: int, quarter: int) -> BudgetVersion | None:
    return db.scalar(select(BudgetVersion).where(
        BudgetVersion.year == year, BudgetVersion.quarter == quarter,
        BudgetVersion.type.in_((VersionType.ROLLING_DRAFT, VersionType.SNAPSHOT))))


@dataclass
class PlannedUnit:
    """按 4.8.1 规则推导的填报单位（目标调整生成 FillingUnit；滚动预测只用于提交跟踪）。"""
    unit_type: str
    scope_object_id: int | None
    name: str
    filler: User | None
    reviewer: User | None
    extra: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.unit_type}:{self.scope_object_id or 0}"


def _dept_head(db: Session, user: User | None) -> User | None:
    if user is None or user.department_id is None:
        return None
    dept = db.get(Department, user.department_id)
    return db.get(User, dept.head_user_id) if dept and dept.head_user_id else None


def plan_units(db: Session) -> list[PlannedUnit]:
    """按技术方案 4.8.1 的填报单位生成规则推导全部单位（启用店铺、B 端负责部门、成本比例、物流比例、部门费用）。"""
    scopes: dict[int, dict[str, set[int]]] = defaultdict(lambda: defaultdict(set))
    for uid, st, oid in db.execute(select(UserScope.user_id, UserScope.scope_type, UserScope.object_id)):
        scopes[uid][st].add(oid)

    def role_users(role: str) -> list[User]:
        return users_with_role(db, role)

    units: list[PlannedUnit] = []
    operations = role_users(Role.OPERATIONS)
    for store in db.scalars(select(Store).where(Store.is_active.is_(True)).order_by(Store.id)):
        filler = next((u for u in operations if store.id in scopes[u.id][ScopeType.STORE]
                       or store.channel_id in scopes[u.id][ScopeType.CHANNEL]), None)
        units.append(PlannedUnit(UnitType.PLATFORM, store.id, store.name, filler, _dept_head(db, filler)))
    b2b_users = role_users(Role.B2B)
    dept_ids = list(db.scalars(select(BCustomer.department_id).where(BCustomer.is_active.is_(True))
                               .distinct()))
    for dept in db.scalars(select(Department).where(Department.id.in_(dept_ids)).order_by(Department.sort,
                                                                                          Department.id)):
        cust_ids = set(db.scalars(select(BCustomer.id).where(BCustomer.department_id == dept.id,
                                                             BCustomer.is_active.is_(True))))
        filler = next((u for u in b2b_users if scopes[u.id][ScopeType.CUSTOMER] & cust_ids), None)
        reviewer = db.get(User, dept.head_user_id) if dept.head_user_id else None
        units.append(PlannedUnit(UnitType.B2B, dept.id, f"B端 · {dept.name}", filler, reviewer))
    bp = next(iter(role_users(Role.FINANCE_BP)), None)
    units.append(PlannedUnit(UnitType.COST_RATIO, None, "成本比例", bp, _dept_head(db, bp)))
    logistics = next(iter(role_users(Role.LOGISTICS)), None)
    units.append(PlannedUnit(UnitType.LOGISTICS_RATIO, None, "物流比例", logistics, _dept_head(db, logistics)))
    for u in role_users(Role.DEPT_BUDGET):
        for dept_id in sorted(scopes[u.id][ScopeType.DEPARTMENT]):
            if any(p.unit_type == UnitType.DEPT_EXPENSE and p.scope_object_id == dept_id for p in units):
                continue
            dept = db.get(Department, dept_id)
            if dept is None or not dept.is_active:
                continue
            reviewer = db.get(User, dept.head_user_id) if dept.head_user_id else None
            units.append(PlannedUnit(UnitType.DEPT_EXPENSE, dept.id, f"部门费用 · {dept.name}", u, reviewer))
    return units


def ensure_complete(units: list[PlannedUnit]) -> None:
    missing = [u.name for u in units if u.filler is None or u.reviewer is None]
    if missing:
        raise ValidationFailed("以下填报单位缺少填报人或审核人：" + "、".join(missing),
                               code="unit_missing_people", details={"units": missing})


def rolling_submissions(db: Session, version_id: int) -> dict[str, AuditLog]:
    rows = db.scalars(select(AuditLog).where(AuditLog.action == "rolling_unit_submitted",
                                             AuditLog.object_type == "rolling_unit",
                                             AuditLog.object_id.like(f"{version_id}:%"))
                      .order_by(AuditLog.id)).all()
    return {r.object_id.split(":", 1)[1]: r for r in rows}


def rolling_units(db: Session, v: BudgetVersion) -> list[dict]:
    subs = rolling_submissions(db, v.id)
    out = []
    for p in plan_units(db):
        sub = subs.get(p.key)
        out.append({"key": p.key, "unit_type": p.unit_type, "unit_type_label": UnitType.LABELS[p.unit_type],
                    "scope_object_id": p.scope_object_id, "name": p.name,
                    "filler_id": p.filler.id if p.filler else None,
                    "filler_name": p.filler.name if p.filler else None,
                    "submitted": sub is not None, "submitted_at": fmt_dt(sub.occurred_at) if sub else None})
    return out


def start_rolling(db: Session, actor: Actor, *, today: date, link: str) -> BudgetVersion:
    year, quarter = today.year, quarter_of(today)
    if rolling_version(db, year, quarter) is not None:
        raise Conflict(f"{year} Q{quarter} 滚动更新已发起，同一季度只能发起一次", code="rolling_exists")
    source = latest_forecast_source(db, year)
    if source is None:
        raise Conflict(f"{year} 年度还没有年初原始目标，不能发起滚动更新", code="no_target")
    units = plan_units(db)
    ensure_complete(units)
    v = BudgetVersion(year=year, type=VersionType.ROLLING_DRAFT, version_no=quarter, quarter=quarter,
                      name=f"{year} Q{quarter} 滚动预测稿", source_version_id=source.id, created_by=actor.id)
    db.add(v)
    db.flush()
    copy_version_rows(db, source.id, v.id)
    audit(db, actor, action="rolling_started", object_type="budget_version", object_id=v.id,
          after={"year": year, "quarter": quarter, "source_version_id": source.id})
    fillers = {p.filler.id: p.filler for p in units if p.filler}
    role_users = {u.id: u for role in ROLLING_ROLES for u in users_with_role(db, role)}
    notify(db, biz_type="rolling_started", biz_id=v.id, users=list({**role_users, **fillers}.values()),
           title="【滚动预测更新】", name=f"{year} Q{quarter} 滚动预测更新",
           object_name=f"开放 {quarter * 3 - 2}–12 月驱动", period=f"{year} Q{quarter}", link=link)
    return v


def latest_forecast_source(db: Session, year: int) -> BudgetVersion | None:
    """滚动预测的来源：本年度最近一次带单元数据的快照，否则当前目标。"""
    snaps = db.scalars(select(BudgetVersion).where(BudgetVersion.year == year,
                                                   BudgetVersion.type == VersionType.SNAPSHOT)
                       .order_by(BudgetVersion.quarter.desc())).all()
    for s in snaps:
        if data_version_id(db, s) == s.id:
            return s
    return current_target(db, year)


def submit_rolling_unit(db: Session, actor: Actor, version_id: int, unit_key: str) -> dict:
    v = get_version(db, version_id)
    if v.type != VersionType.ROLLING_DRAFT:
        raise Conflict("滚动预测已发布，不能再提交", code="rolling_closed")
    unit = next((p for p in plan_units(db) if p.key == unit_key), None)
    if unit is None:
        raise NotFound("填报单位不存在")
    if unit.filler is None or unit.filler.id != actor.id:
        from app.core.errors import Forbidden
        raise Forbidden()
    if unit_key in rolling_submissions(db, v.id):
        raise Conflict("已提交，不能重复提交", code="already_submitted")
    audit(db, actor, action="rolling_unit_submitted", object_type="rolling_unit", object_id=f"{v.id}:{unit_key}",
          after={"name": unit.name})
    return {"key": unit_key, "submitted": True}


def _revert_unsubmitted(db: Session, v: BudgetVersion, unsubmitted: list[PlannedUnit]) -> None:
    """未提交单位按来源版本数值计算（从未提交则取来源版本数值，DEC-F08-03）。只恢复本季度及以后月份。"""
    src = v.source_version_id
    start = date(v.year, v.quarter * 3 - 2, 1)
    params = {"v": v.id, "s": src, "start": start}
    for p in unsubmitted:
        if p.unit_type == UnitType.PLATFORM:
            db.execute(text(
                "UPDATE platform_unit t SET spu_count = s.spu_count, avg_sales = s.avg_sales, avg_price = s.avg_price, "
                "discount_rate = s.discount_rate, refund_rate = s.refund_rate, ad_rate = s.ad_rate, "
                "commission_rate = s.commission_rate FROM platform_unit s WHERE t.version_id = :v AND "
                "s.version_id = :s AND t.month >= :start AND s.month = t.month AND s.store_id = t.store_id AND "
                "s.site_id = t.site_id AND s.category_id = t.category_id AND s.is_new = t.is_new AND t.store_id = :o"),
                {**params, "o": p.scope_object_id})
        elif p.unit_type == UnitType.B2B:
            db.execute(text(
                "UPDATE b2b_unit t SET sales_local = s.sales_local, refund_rate = s.refund_rate, "
                "promotion_rate = s.promotion_rate, other_opex_rate = s.other_opex_rate, "
                "commission_rate = s.commission_rate, inventory_claim_rate = s.inventory_claim_rate "
                "FROM b2b_unit s, b_customer c WHERE t.version_id = :v AND s.version_id = :s AND t.month >= :start "
                "AND s.month = t.month AND s.customer_id = t.customer_id AND c.id = t.customer_id "
                "AND c.department_id = :o"), {**params, "o": p.scope_object_id})
        elif p.unit_type == UnitType.COST_RATIO:
            db.execute(text(
                "UPDATE channel_category_ratio t SET purchase_cost_rate = s.purchase_cost_rate "
                "FROM channel_category_ratio s WHERE t.version_id = :v AND s.version_id = :s AND t.month >= :start "
                "AND s.month = t.month AND s.channel_id = t.channel_id AND s.site_id = t.site_id "
                "AND s.category_id = t.category_id"), params)
            db.execute(text(
                "UPDATE channel_site_ratio t SET inventory_claim_rate = s.inventory_claim_rate, "
                "other_opex_rate = s.other_opex_rate FROM channel_site_ratio s WHERE t.version_id = :v AND "
                "s.version_id = :s AND t.month >= :start AND s.month = t.month AND s.channel_id = t.channel_id "
                "AND s.site_id = t.site_id"), params)
            db.execute(text(
                "UPDATE b2b_unit t SET purchase_cost_rate = s.purchase_cost_rate FROM b2b_unit s "
                "WHERE t.version_id = :v AND s.version_id = :s AND t.month >= :start AND s.month = t.month "
                "AND s.customer_id = t.customer_id"), params)
        elif p.unit_type == UnitType.LOGISTICS_RATIO:
            db.execute(text(
                "UPDATE channel_category_ratio t SET first_leg_rate = s.first_leg_rate, "
                "last_mile_rate = s.last_mile_rate, storage_rate = s.storage_rate, tariff_rate = s.tariff_rate "
                "FROM channel_category_ratio s WHERE t.version_id = :v AND s.version_id = :s AND t.month >= :start "
                "AND s.month = t.month AND s.channel_id = t.channel_id AND s.site_id = t.site_id "
                "AND s.category_id = t.category_id"), params)
            db.execute(text(
                "UPDATE b2b_unit t SET first_leg_rate = s.first_leg_rate, last_mile_rate = s.last_mile_rate, "
                "storage_rate = s.storage_rate, tariff_rate = s.tariff_rate FROM b2b_unit s "
                "WHERE t.version_id = :v AND s.version_id = :s AND t.month >= :start AND s.month = t.month "
                "AND s.customer_id = t.customer_id"), params)
        elif p.unit_type == UnitType.DEPT_EXPENSE:
            db.execute(text(
                "UPDATE dept_expense t SET amount = s.amount FROM dept_expense s WHERE t.version_id = :v AND "
                "s.version_id = :s AND t.month >= :start AND s.month = t.month AND s.department_id = t.department_id "
                "AND s.account_id = t.account_id AND t.department_id = :o"), {**params, "o": p.scope_object_id})
    db.flush()
    if unsubmitted:
        recalc_platform_units(db, v.id)
        recalc_b2b_units(db, v.id)


def write_snapshot_months(db: Session, v: BudgetVersion, months_actual: set[date], data_vid: int) -> None:
    forecast = forecast_monthly(db, data_vid)
    actual = actual_monthly(db, sorted(months_actual)) if months_actual else {}
    for m in year_months(v.year):
        if m in months_actual:
            line, source = actual[m], "actual"
        else:
            line, source = forecast.get(m, PlLine()), "forecast"
        db.add(SnapshotMonth(version_id=v.id, month=m, source=source, revenue_cny=line.revenue,
                             gross_profit=line.gross, net_profit=line.net))
    db.flush()


def publish_rolling(db: Session, actor: Actor, version_id: int, *, confirm_unsubmitted: bool, today: date) -> dict:
    v = get_version(db, version_id)
    if v.type != VersionType.ROLLING_DRAFT or v.locked:
        raise Conflict("该滚动预测已发布为快照，快照不可修改", code="version_locked")
    subs = rolling_submissions(db, v.id)
    unsubmitted = [p for p in plan_units(db) if p.key not in subs]
    if unsubmitted and not confirm_unsubmitted:
        raise Conflict("仍有填报人未提交本季度更新", code="unsubmitted_units",
                       details={"units": [{"name": p.name, "filler_name": p.filler.name if p.filler else None}
                                          for p in unsubmitted]})
    _revert_unsubmitted(db, v, unsubmitted)
    months_actual = actual_months(db, v.year)
    now = clock.now()
    through = max(months_actual) if months_actual else None
    v.type = VersionType.SNAPSHOT
    v.name = f"{v.year} Q{v.quarter} 滚动预测快照"
    v.published_on = today
    v.approved_by = actor.id
    v.approved_at = now
    v.adjust_reason = (f"1–{through.month} 月实际 + {through.month + 1}–12 月最新提交驱动"
                       if through and through.month < 12 else
                       ("全年实际" if through else "全年最新提交驱动"))
    db.flush()
    write_snapshot_months(db, v, months_actual, v.id)
    v.locked = True
    db.flush()
    audit(db, actor, action="snapshot_published", object_type="budget_version", object_id=v.id,
          after={"quarter": v.quarter, "published_on": today, "actual_months": sorted(fmt_month(m)
                                                                                     for m in months_actual),
                 "unsubmitted": [p.name for p in unsubmitted]})
    return {"id": v.id}


def publish_original(db: Session, actor: Actor, *, today: date) -> BudgetVersion:
    year = today.year
    if quarter_of(today) != 1:
        raise Conflict("只有预算年度第一季度可以以年初原始目标发布快照", code="not_first_quarter")
    if rolling_version(db, year, 1) is not None:
        raise Conflict(f"{year} Q1 已发起滚动更新或已发布快照", code="rolling_exists")
    original = original_target(db, year)
    if original is None:
        raise Conflict(f"{year} 年度还没有年初原始目标", code="no_target")
    v = BudgetVersion(year=year, type=VersionType.SNAPSHOT, version_no=1, quarter=1,
                      name=f"{year} Q1 滚动预测快照", source_version_id=original.id, published_on=today,
                      approved_by=actor.id, approved_at=clock.now(), created_by=actor.id,
                      adjust_reason="以年初原始目标发布")
    db.add(v)
    db.flush()
    write_snapshot_months(db, v, set(), data_version_id(db, original))
    v.locked = True
    db.flush()
    audit(db, actor, action="snapshot_published", object_type="budget_version", object_id=v.id,
          after={"quarter": 1, "published_on": today, "mode": "original_target",
                 "source_version_id": original.id})
    return v


# ---------------------------------------------------------------------------
# 版本对比（AC-F08-08）
# ---------------------------------------------------------------------------
def _sum_pairs(rows) -> tuple[Decimal, Decimal]:
    rev = sum((r for r, _ in rows), ZERO)
    gross = sum((g for _, g in rows), ZERO)
    return rev, gross


def version_dimension_totals(db: Session, v: BudgetVersion, dims: str, ctx) -> dict[tuple, tuple[Decimal, Decimal]]:
    """按维度汇总全年人民币收入与毛利（服务端按数据范围过滤）。"""
    vid = data_version_id(db, v)
    out: dict[tuple, list[Decimal]] = defaultdict(lambda: [ZERO, ZERO])
    if dims == "channel":
        allowed = None
        if not ctx.all_company:
            allowed = set(db.scalars(select(Store.id).where(ctx.store_clause(Store.id, Store.channel_id))))
        for (_m, store_id), (r, g, _src) in version_store_monthly(db, v).items():
            if allowed is not None and store_id not in allowed:
                continue
            out[(store_id,)][0] += r
            out[(store_id,)][1] += g
    elif dims == "category":
        q = (select(PlatformUnit.category_id, PlatformUnit.is_new,
                    func.coalesce(func.sum(PlatformUnit.revenue_cny), 0),
                    func.coalesce(func.sum(PlatformUnit.gross_profit), 0))
             .where(PlatformUnit.version_id == vid,
                    ctx.store_clause(PlatformUnit.store_id, PlatformUnit.channel_id))
             .group_by(PlatformUnit.category_id, PlatformUnit.is_new))
        for cat, is_new, r, g in db.execute(q):
            out[(cat, is_new)] = [r, g]
    elif dims == "customer":
        q = (select(B2bUnit.customer_id, func.coalesce(func.sum(B2bUnit.revenue_cny), 0),
                    func.coalesce(func.sum(B2bUnit.gross_profit), 0))
             .where(B2bUnit.version_id == vid, ctx.customer_clause(B2bUnit.customer_id))
             .group_by(B2bUnit.customer_id))
        for cust, r, g in db.execute(q):
            out[(cust,)] = [r, g]
    else:
        raise ValidationFailed("维度只能是 channel / category / customer")
    return {k: (val[0], val[1]) for k, val in out.items()}


def company_totals(db: Session, v: BudgetVersion) -> PlLine:
    total = PlLine()
    for line, _src in version_company_monthly(db, v).values():
        total.revenue += line.revenue
        total.gross += line.gross
        total.dept += line.dept
        total.other += line.other
    return total

