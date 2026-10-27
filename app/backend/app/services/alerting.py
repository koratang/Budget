"""预警评估器 CMP-F11-01（AC-F11-01~05、AC-F12-05，SEQ-F09-01，技术方案 4.8.4）。

- 只读取每条预警规则当前「生效」版本（AC-F12-05）；对受影响月份逐规则评估。
- 去重：唯一键（规则版本, 对象类型, 对象 ID, 期间），INSERT … ON CONFLICT DO UPDATE 只更新指标值；
  只有新插入的预警写通知发件箱（AC-F11-02）。已处理的预警再次命中：状态保持，置 updated_after_resolve。
- 通知只含规则名称（版本）、对象、期间与系统链接，不含金额与指标值（AC-F11-04、NFR-005）。
- 指标值以小数存储（0.1333 表示 13.33 个百分点 / 13.33%）；构成说明写入审计日志 after.parts，供列表与详情展示。
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import case, func, literal_column, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.calc.periods import add_months, fmt_month, quarter_of
from app.core.clock import clock
from app.core.money import fmt_percent, round_to, to_decimal
from app.models import (Alert, BiActualAgg, BudgetAccount, BudgetVersion, Category, Channel, Department, DeptExpense,
                        ImportBatch, KingdeeActual, PlatformUnit, Reserve, Rule, RuleVersion, SnapshotMonth, Store,
                        User, UserScope)
from app.models.enums import AlertStatus, ImportSource, ImportStatus, Role, RuleType, RuleVersionStatus, ScopeType
from app.services.versions import (ZERO, Actor, actual_months, actual_monthly, actual_store_monthly,
                                   audit, current_target, data_version_id, forecast_store_monthly, notify,
                                   users_with_role)

HUNDRED = Decimal(100)
TWELVE = Decimal(12)
NOTICE_TITLE = "【预算预警】"


@dataclass
class Hit:
    object_type: str
    object_id: str
    object_name: str
    period: date
    value: Decimal
    parts: list[str]
    period_text: str
    receivers: list[User]


def compare(value: Decimal, comparator: str, threshold: Decimal) -> bool:
    return {"lt": value < threshold, "gt": value > threshold, "lte": value <= threshold,
            "gte": value >= threshold}[comparator]


def pct(value: Decimal) -> str:
    return fmt_percent(value, 2)


def pp_text(value: Decimal) -> str:
    """小数 → 「+13.33 个百分点」。"""
    q = round_to(value * HUNDRED, 2)
    sign = "−" if q < 0 else "+"
    return f"{sign}{abs(q):.2f} 个百分点"


# ---------------------------------------------------------------------------
# 接收人（AC-F11-04）
# ---------------------------------------------------------------------------
class Receivers:
    def __init__(self, db: Session):
        self.db = db
        self.finance_heads = users_with_role(db, Role.FINANCE_HEAD)
        self.ceos = users_with_role(db, Role.CEO)
        self.operations = users_with_role(db, Role.OPERATIONS)
        scopes: dict[int, dict[str, set[int]]] = defaultdict(lambda: defaultdict(set))
        for uid, st, oid in db.execute(select(UserScope.user_id, UserScope.scope_type, UserScope.object_id)):
            scopes[uid][st].add(oid)
        self.scopes = scopes

    def _head_of(self, dept_id: int | None) -> User | None:
        if dept_id is None:
            return None
        dept = self.db.get(Department, dept_id)
        return self.db.get(User, dept.head_user_id) if dept and dept.head_user_id else None

    def store_operations(self, store: Store) -> list[User]:
        return [u for u in self.operations if store.id in self.scopes[u.id][ScopeType.STORE]
                or store.channel_id in self.scopes[u.id][ScopeType.CHANNEL]]

    def resolve(self, roles: list[str], *, department_id: int | None = None, store: Store | None = None,
                all_operations: bool = False) -> list[User]:
        out: dict[int, User] = {}
        ops: list[User] = []
        if store is not None:
            ops = self.store_operations(store)
        elif all_operations:
            ops = [u for u in self.operations if self.scopes[u.id][ScopeType.STORE]
                   or self.scopes[u.id][ScopeType.CHANNEL]]
        if "dept_head" in roles:
            heads = [self._head_of(department_id)] if department_id is not None else \
                [self._head_of(u.department_id) for u in ops]
            out.update({h.id: h for h in heads if h is not None})
        if "operations" in roles:
            out.update({u.id: u for u in ops})
        if "finance_head" in roles:
            out.update({u.id: u for u in self.finance_heads})
        if "ceo" in roles:
            out.update({u.id: u for u in self.ceos})
        return list(out.values())


# ---------------------------------------------------------------------------
# 指标计算
# ---------------------------------------------------------------------------
def _effective_kingdee_ids(db: Session, months: list[date]) -> list[int]:
    return list(db.scalars(select(ImportBatch.id).where(
        ImportBatch.source.in_((ImportSource.KINGDEE, ImportSource.KINGDEE_HISTORY)),
        ImportBatch.status == ImportStatus.EFFECTIVE, ImportBatch.period.in_(months))))


def dept_budget(db: Session, year: int) -> dict[int, Decimal]:
    target = current_target(db, year)
    if target is None:
        return {}
    vid = data_version_id(db, target)
    out: dict[int, Decimal] = defaultdict(lambda: ZERO)
    for dept_id, amount in db.execute(select(DeptExpense.department_id, func.sum(DeptExpense.amount))
                                      .where(DeptExpense.version_id == vid).group_by(DeptExpense.department_id)):
        out[dept_id] += amount
    for dept_id, amount in db.execute(select(Reserve.department_id, func.sum(Reserve.amount))
                                      .where(Reserve.version_id == vid).group_by(Reserve.department_id)):
        out[dept_id] += amount
    return dict(out)


def dept_actual_cumulative(db: Session, month: date) -> dict[int, Decimal]:
    months = [date(month.year, m, 1) for m in range(1, month.month + 1)]
    ids = _effective_kingdee_ids(db, months)
    if not ids:
        return {}
    rows = db.execute(select(KingdeeActual.department_id, func.sum(KingdeeActual.amount))
                      .join(BudgetAccount, BudgetAccount.id == KingdeeActual.account_id)
                      .where(KingdeeActual.batch_id.in_(ids), BudgetAccount.is_dept_expense.is_(True),
                             KingdeeActual.department_id.is_not(None))
                      .group_by(KingdeeActual.department_id))
    return {d: a for d, a in rows}


def _usage_metrics(db: Session, month: date, metric: str) -> dict[int, tuple[Decimal, list[str]]]:
    budget = dept_budget(db, month.year)
    actual = dept_actual_cumulative(db, month)
    progress = Decimal(month.month) / TWELVE
    out = {}
    for dept_id, total in budget.items():
        if total <= 0:
            continue
        usage = actual.get(dept_id, ZERO) / total
        if metric == "usage_minus_time_progress":
            out[dept_id] = (usage - progress, [f"使用率 {pct(usage)}，时间进度 {pct(progress)}"])
        else:
            out[dept_id] = (usage, [f"累计使用率 {pct(usage)}"])
    return out


def _is_new_channel_month(store: Store, channel: Channel, month: date) -> bool:
    start = store.new_channel_start if store.is_new_channel else (
        channel.new_channel_start if channel.is_new_channel else None)
    return start is not None and start <= month < add_months(start, 12)


def _achievement(db: Session, month: date) -> dict[int, Decimal]:
    target = current_target(db, month.year)
    if target is None or month not in actual_months(db, month.year):
        return {}
    budget = {s: r for (m, s), (r, _g) in forecast_store_monthly(db, data_version_id(db, target)).items() if m == month}
    actual = {s: r for (m, s), (r, _g) in actual_store_monthly(db, [month]).items()}
    return {s: actual.get(s, ZERO) / b for s, b in budget.items() if b > 0}


def _category_margin_diff(db: Session, month: date) -> dict[int, tuple[Decimal, list[str]]]:
    target = current_target(db, month.year)
    if target is None or month not in actual_months(db, month.year):
        return {}
    vid = data_version_id(db, target)
    budget = {c: (r, g) for c, r, g in db.execute(
        select(PlatformUnit.category_id, func.sum(PlatformUnit.revenue_cny), func.sum(PlatformUnit.gross_profit))
        .where(PlatformUnit.version_id == vid, PlatformUnit.month == month).group_by(PlatformUnit.category_id))}
    bi_ids = list(db.scalars(select(ImportBatch.id).where(ImportBatch.source == ImportSource.BI,
                                                          ImportBatch.status == ImportStatus.EFFECTIVE,
                                                          ImportBatch.period == month)))
    if not bi_ids:
        return {}
    share: dict[int, dict[int, Decimal]] = defaultdict(dict)
    for store_id, cat_id, rev in db.execute(
            select(BiActualAgg.store_id, BiActualAgg.category_id, func.sum(BiActualAgg.revenue_cny))
            .where(BiActualAgg.batch_id.in_(bi_ids), BiActualAgg.revenue_cny.is_not(None))
            .group_by(BiActualAgg.store_id, BiActualAgg.category_id)):
        share[store_id][cat_id] = rev
    store_kd = {s: v for (m, s), v in actual_store_monthly(db, [month]).items()}
    act: dict[int, list[Decimal]] = defaultdict(lambda: [ZERO, ZERO])
    for store_id, cats in share.items():
        total = sum(cats.values(), ZERO)
        if total <= 0 or store_id not in store_kd:
            continue
        rev, gross = store_kd[store_id]
        for cat_id, r in cats.items():
            act[cat_id][0] += rev * r / total
            act[cat_id][1] += gross * r / total
    out = {}
    for cat_id, (br, bg) in budget.items():
        ar, ag = act.get(cat_id, [ZERO, ZERO])
        if not br or ar <= 0:
            continue
        b_margin, a_margin = bg / br, ag / ar
        out[cat_id] = (a_margin - b_margin, [f"实际毛利率 {pct(a_margin)}，预算毛利率 {pct(b_margin)}"])
    return out


def _forecast_deviation(db: Session, month: date) -> tuple[Decimal, list[str]] | None:
    snap = db.scalar(select(BudgetVersion).where(BudgetVersion.year == month.year,
                                                 BudgetVersion.quarter == quarter_of(month),
                                                 BudgetVersion.type == "snapshot"))
    if snap is None or month not in actual_months(db, month.year):
        return None
    row = db.scalar(select(SnapshotMonth).where(SnapshotMonth.version_id == snap.id, SnapshotMonth.month == month,
                                                SnapshotMonth.source == "forecast"))
    actual = actual_monthly(db, [month]).get(month)
    if row is None or actual is None or not row.revenue_cny or not actual.revenue:
        return None
    pred, act = row.net_profit / row.revenue_cny, actual.net / actual.revenue
    return abs(pred - act), [f"快照预测净利率 {pct(pred)}，实际净利率 {pct(act)}"]


# ---------------------------------------------------------------------------
# 评估
# ---------------------------------------------------------------------------
def effective_alert_rules(db: Session) -> list[tuple[Rule, RuleVersion]]:
    return list(db.execute(select(Rule, RuleVersion).join(RuleVersion, RuleVersion.rule_id == Rule.id)
                           .where(Rule.type == RuleType.ALERT,
                                  RuleVersion.status == RuleVersionStatus.EFFECTIVE)).all())


def _applies(applies: dict, *, department_id=None, store: Store | None = None, channel: Channel | None = None,
             category_id=None, month: date | None = None) -> bool:
    kind, ids = applies.get("type", "all"), set(applies.get("ids") or [])
    if kind == "all":
        return True
    if kind == "department":
        return department_id is not None and (not ids or department_id in ids)
    if kind == "category":
        return category_id is not None and (not ids or category_id in ids)
    if kind == "channel":
        return store is not None and (not ids or store.channel_id in ids)
    if kind == "new_channel":
        return store is not None and channel is not None and _is_new_channel_month(store, channel, month)
    return False


def rule_hits(db: Session, rv: RuleVersion, month: date, rec: Receivers) -> list[Hit]:
    c = rv.content
    metric, comparator = c.get("metric"), c.get("comparator")
    threshold = to_decimal(c.get("threshold", "0"))
    k = max(int(c.get("consecutive_months") or 1), 1)
    months = [add_months(month, -i) for i in range(k - 1, -1, -1)]
    if any(m.year != month.year for m in months):
        return []
    applies = c.get("applies_to") or {"type": "all"}
    roles = list(c.get("receivers") or [])
    period_text = fmt_month(month) if k == 1 else f"{fmt_month(months[0])} 至 {fmt_month(month)}"
    hits: list[Hit] = []
    if metric in ("usage_minus_time_progress", "usage_rate"):
        series = [_usage_metrics(db, m, metric) for m in months]
        for dept_id, (value, parts) in series[-1].items():
            if not _applies(applies, department_id=dept_id):
                continue
            values = [s.get(dept_id) for s in series]
            if any(v is None or not compare(v[0], comparator, threshold) for v in values):
                continue
            dept = db.get(Department, dept_id)
            hits.append(Hit("department", str(dept_id), dept.name, month, value, parts, period_text,
                            rec.resolve(roles, department_id=dept_id)))
    elif metric == "revenue_achievement":
        series = [_achievement(db, m) for m in months]
        for store_id, value in series[-1].items():
            store = db.get(Store, store_id)
            channel = db.get(Channel, store.channel_id)
            if not all(_applies(applies, store=store, channel=channel, month=m) for m in months):
                continue
            values = [s.get(store_id) for s in series]
            if any(v is None or not compare(v, comparator, threshold) for v in values):
                continue
            hits.append(Hit("store", str(store_id), store.name, month, value, ["、".join(pct(v) for v in values)],
                            period_text, rec.resolve(roles, store=store)))
    elif metric == "gross_margin_diff":
        series = [_category_margin_diff(db, m) for m in months]
        for cat_id, (value, parts) in series[-1].items():
            if not _applies(applies, category_id=cat_id):
                continue
            values = [s.get(cat_id) for s in series]
            if any(v is None or not compare(v[0], comparator, threshold) for v in values):
                continue
            cat = db.get(Category, cat_id)
            hits.append(Hit("category", str(cat_id), f"{cat.name}（全部平台渠道）", month, value, parts, period_text,
                            rec.resolve(roles, all_operations=True)))
    elif metric == "forecast_deviation_pp":
        series = [_forecast_deviation(db, m) for m in months]
        if all(s is not None and compare(s[0], comparator, threshold) for s in series) and applies.get(
                "type", "all") == "all":
            value, parts = series[-1]
            hits.append(Hit("company", "company", "公司", month, value, parts, period_text, rec.resolve(roles)))
    return hits


def alert_link(base_url: str, alert_id: int) -> str:
    return f"{base_url.rstrip('/')}/alerts?id={alert_id}"


def evaluate(db: Session, months: list[date], *, base_url: str, import_batch_id: int | None = None,
             actor: Actor | None = None) -> dict:
    """对受影响月份评估全部生效预警规则；返回 {created, updated}。在调用方事务内执行（只 flush）。"""
    rec = Receivers(db)
    stats = {"created": 0, "updated": 0}
    now = clock.now()
    for rule, rv in effective_alert_rules(db):
        threshold = to_decimal(rv.content.get("threshold", "0"))
        for month in sorted(set(months)):
            for hit in rule_hits(db, rv, month, rec):
                stmt = (pg_insert(Alert)
                        .values(rule_version_id=rv.id, object_type=hit.object_type, object_id=hit.object_id,
                                object_name=hit.object_name, period=hit.period, metric_value=hit.value,
                                threshold=threshold, status=AlertStatus.OPEN, notify_status="pending",
                                import_batch_id=import_batch_id, created_at=now, updated_at=now)
                        .on_conflict_do_update(
                            constraint="uq_alert_hit",
                            set_={"metric_value": hit.value, "updated_at": now, "object_name": hit.object_name,
                                  "updated_after_resolve": case((Alert.status == AlertStatus.RESOLVED, True),
                                                                else_=Alert.updated_after_resolve)})
                        .returning(Alert.id, literal_column("(xmax = 0)").label("inserted")))
                alert_id, inserted = db.execute(stmt).one()
                after = {"metric_value": hit.value, "parts": hit.parts, "period_text": hit.period_text,
                         "import_batch_id": import_batch_id}
                extra = {"actor_name": "预警评估器"} if actor is None else {}
                if inserted:
                    stats["created"] += 1
                    audit(db, actor, action="alert_created", object_type="alert", object_id=alert_id, after=after,
                          **extra)
                    notify(db, biz_type="alert", biz_id=alert_id, users=hit.receivers, title=NOTICE_TITLE,
                           name=f"{rule.name}（v{rv.version_no}）", object_name=hit.object_name,
                           period=hit.period_text, link=alert_link(base_url, alert_id))
                else:
                    stats["updated"] += 1
                    audit(db, actor, action="alert_updated", object_type="alert", object_id=alert_id, after=after,
                          **extra)
    db.flush()
    db.expire_all()
    return stats


def last_parts(db: Session, alert_ids: list[int]) -> dict[int, dict]:
    """各预警最近一次评估的构成说明（审计 after）。"""
    from app.models import AuditLog
    if not alert_ids:
        return {}
    rows = db.execute(select(AuditLog.object_id, AuditLog.after, AuditLog.occurred_at, AuditLog.action)
                      .where(AuditLog.object_type == "alert",
                             AuditLog.action.in_(("alert_created", "alert_updated")),
                             AuditLog.object_id.in_([str(i) for i in alert_ids]))
                      .order_by(AuditLog.id)).all()
    out: dict[int, dict] = {}
    for oid, after, _at, _action in rows:
        out[int(oid)] = after or {}
    return out

