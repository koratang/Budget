"""预警（API-F11-01/02）。

列表：CEO、财务负责人、财务BP 看全部；其他角色只看自己是接收人或对象在其数据范围内的预警（NFR-003）。
标记已处理：仅该预警的通知接收人（未产生通知时财务负责人）可操作，处理说明必填（AC-F11-03）。
"""
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calc.periods import fmt_month
from app.core.auth import CurrentUser, get_current_user
from app.core.clock import clock
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.core.money import dec_str
from app.core.scope import ScopeContext, get_scope
from app.db import get_db
from app.dingtalk.outbox import MAX_ATTEMPTS
from app.models import Alert, AuditLog, ImportBatch, NotificationOutbox, Rule, RuleVersion, Store, User
from app.models.enums import AlertStatus, NotifyStatus, Role
from app.services import alerting
from app.services.rules import METRICS, threshold_text
from app.services.versions import Actor, audit, fmt_dt

router = APIRouter(prefix="/alerts", tags=["alerts"])

HUNDRED = Decimal(100)


def _outboxes(db: Session, alert_ids: list[int]) -> dict[int, NotificationOutbox]:
    if not alert_ids:
        return {}
    rows = db.scalars(select(NotificationOutbox).where(NotificationOutbox.biz_type == "alert",
                                                       NotificationOutbox.biz_id.in_(alert_ids)))
    return {r.biz_id: r for r in rows}


def _metric_display(metric: str, value: Decimal | None) -> str:
    if value is None:
        return "—"
    unit = METRICS.get(metric, ("", "%"))[1]
    if unit == "%":
        return f"{(value * HUNDRED).quantize(Decimal('0.01'))}%"
    return alerting.pp_text(value)


def _can_resolve(alert: Alert, outbox: NotificationOutbox | None, current: CurrentUser) -> bool:
    if alert.status != AlertStatus.OPEN:
        return False
    if outbox is not None:
        return current.user.dingtalk_userid in (outbox.receivers or [])
    return current.has_role(Role.FINANCE_HEAD)


def _visible(alert: Alert, outbox: NotificationOutbox | None, ctx: ScopeContext, current: CurrentUser,
             stores: dict[int, Store]) -> bool:
    if ctx.all_company:
        return True
    if outbox is not None and current.user.dingtalk_userid in (outbox.receivers or []):
        return True
    if alert.object_type == "department":
        return int(alert.object_id) in ctx.department_ids
    if alert.object_type == "store":
        store = stores.get(int(alert.object_id))
        return store is not None and (store.id in ctx.store_ids or store.channel_id in ctx.channel_ids)
    return False


def _row(alert: Alert, rule: Rule, rv: RuleVersion, outbox, parts: dict, current: CurrentUser,
         db: Session) -> dict:
    resolver = db.get(User, alert.resolved_by) if alert.resolved_by else None
    metric = rv.content.get("metric")
    return {
        "id": alert.id, "rule_id": rule.id, "rule_name": rule.name, "rule_version_no": rv.version_no,
        "object_type": alert.object_type, "object_name": alert.object_name, "period": fmt_month(alert.period),
        "period_text": parts.get("period_text") or fmt_month(alert.period), "metric": metric,
        "metric_value": dec_str(alert.metric_value), "metric_value_percent": dec_str(alert.metric_value * HUNDRED)
        if alert.metric_value is not None else None,
        "metric_display": _metric_display(metric, alert.metric_value), "metric_parts": parts.get("parts") or [],
        "threshold": dec_str(alert.threshold), "threshold_display": threshold_text(rv.content),
        "status": alert.status, "status_label": AlertStatus.LABELS[alert.status],
        "resolved_by_name": resolver.name if resolver else None, "resolved_at": fmt_dt(alert.resolved_at),
        "resolve_note": alert.resolve_note, "notify_status": alert.notify_status,
        "notify_status_label": NotifyStatus.LABELS[alert.notify_status],
        "updated_after_resolve": alert.updated_after_resolve, "updated_at": fmt_dt(alert.updated_at),
        "created_at": fmt_dt(alert.created_at), "can_resolve": _can_resolve(alert, outbox, current),
    }


def _load(db: Session):
    return db.execute(select(Alert, RuleVersion, Rule).join(RuleVersion, RuleVersion.id == Alert.rule_version_id)
                      .join(Rule, Rule.id == RuleVersion.rule_id).order_by(Alert.period.desc(), Alert.id.desc())).all()


@router.get("")
def list_alerts(status: str | None = None, rule_id: int | None = None, notify_status: str | None = None,
                page: int = 1, page_size: int = 20, current: CurrentUser = Depends(get_current_user),
                ctx: ScopeContext = Depends(get_scope), db: Session = Depends(get_db)):
    rows = _load(db)
    outboxes = _outboxes(db, [a.id for a, _rv, _r in rows])
    stores = {s.id: s for s in db.scalars(select(Store))}
    visible = [(a, rv, r) for a, rv, r in rows if _visible(a, outboxes.get(a.id), ctx, current, stores)]
    kpis = {"open": sum(a.status == AlertStatus.OPEN for a, _rv, _r in visible),
            "resolved": sum(a.status == AlertStatus.RESOLVED for a, _rv, _r in visible),
            "notify_failed": sum(a.notify_status == NotifyStatus.FAILED for a, _rv, _r in visible)}
    rules = sorted({(r.id, r.name) for _a, _rv, r in visible})
    filtered = [(a, rv, r) for a, rv, r in visible
                if (not status or a.status == status) and (not rule_id or r.id == rule_id)
                and (not notify_status or a.notify_status == notify_status)]
    total = len(filtered)
    page = max(page, 1)
    chunk = filtered[(page - 1) * page_size: page * page_size]
    parts = alerting.last_parts(db, [a.id for a, _rv, _r in chunk])
    last = db.scalar(select(AuditLog).where(AuditLog.action == "import_confirmed").order_by(AuditLog.id.desc())
                     .limit(1))
    last_eval = None
    if last is not None:
        batch = db.get(ImportBatch, int(last.object_id))
        last_eval = {"at": fmt_dt(last.occurred_at), "file_name": batch.file_name if batch else "",
                     "source": batch.source if batch else ""}
    return {"kpis": kpis, "rules": [{"id": i, "name": n} for i, n in rules], "total": total, "page": page,
            "page_size": page_size, "last_evaluation": last_eval, "has_any": bool(visible),
            "items": [_row(a, r, rv, outboxes.get(a.id), parts.get(a.id, {}), current, db) for a, rv, r in chunk]}


def _get(db: Session, alert_id: int, ctx: ScopeContext, current: CurrentUser):
    row = db.execute(select(Alert, RuleVersion, Rule).join(RuleVersion, RuleVersion.id == Alert.rule_version_id)
                     .join(Rule, Rule.id == RuleVersion.rule_id).where(Alert.id == alert_id)).first()
    if row is None:
        raise NotFound("预警不存在")
    alert, rv, rule = row
    outbox = _outboxes(db, [alert.id]).get(alert.id)
    stores = {s.id: s for s in db.scalars(select(Store))}
    if not _visible(alert, outbox, ctx, current, stores):
        raise Forbidden()
    return alert, rv, rule, outbox


@router.get("/{alert_id}")
def alert_detail(alert_id: int, current: CurrentUser = Depends(get_current_user),
                 ctx: ScopeContext = Depends(get_scope), db: Session = Depends(get_db)):
    alert, rv, rule, outbox = _get(db, alert_id, ctx, current)
    history = db.scalars(select(AuditLog).where(AuditLog.object_type == "alert",
                                                AuditLog.object_id == str(alert.id)).order_by(AuditLog.id)).all()
    parts = next((h.after for h in reversed(history) if h.action in ("alert_created", "alert_updated")), {}) or {}
    data = _row(alert, rule, rv, outbox, parts, current, db)
    receivers = []
    if outbox is not None:
        names = dict(db.execute(select(User.dingtalk_userid, User.name)
                                .where(User.dingtalk_userid.in_(outbox.receivers))).all())
        receivers = [names.get(u, u) for u in outbox.receivers]
    changes = []
    for h in history:
        after = h.after or {}
        if h.action == "alert_created":
            batch = db.get(ImportBatch, after.get("import_batch_id")) if after.get("import_batch_id") else None
            changes.append({"at": fmt_dt(h.occurred_at), "text": "生成预警" + (
                f"（触发导入：{batch.file_name}）" if batch else "")})
        elif h.action == "alert_updated":
            value = Decimal(after["metric_value"]) if after.get("metric_value") is not None else None
            changes.append({"at": fmt_dt(h.occurred_at),
                            "text": f"再次命中，指标值更新为 {_metric_display(rv.content.get('metric'), value)}；"
                                    "未新增记录、未重复通知"})
        elif h.action == "alert_resolved":
            changes.append({"at": fmt_dt(h.occurred_at), "text": f"{h.actor_name} 标记已处理"})
    attempts = []
    if outbox is not None:
        for i, log in enumerate(outbox.attempt_log or []):
            attempts.append({"no": i + 1, "label": "首次发送" if i == 0 else f"第 {i} 次重试",
                             "at": log.get("at", "")[:16].replace("T", " "), "ok": log.get("ok"),
                             "error": log.get("error")})
    data.update(receivers=receivers, changes=changes, attempts=attempts, max_attempts=MAX_ATTEMPTS,
                notice_preview={"title": outbox.params.get("title"), "name": outbox.params.get("name"),
                                "object": outbox.params.get("object_name"), "period": outbox.params.get("period"),
                                "link_text": "预算管理平台 › 预算预警"} if outbox else None,
                # 部门对象无对应报表（部门费用报告已删除）：不给链接，详情页不显示「查看相关报表」
                report_link={"store": "/reports/channel", "category": "/reports/category",
                             "company": "/reports/company"}.get(alert.object_type))
    return data


class ResolveIn(BaseModel):
    note: str | None = None


@router.post("/{alert_id}/resolve")
def resolve(alert_id: int, body: ResolveIn, current: CurrentUser = Depends(get_current_user),
            ctx: ScopeContext = Depends(get_scope), db: Session = Depends(get_db)):
    alert, rv, rule, outbox = _get(db, alert_id, ctx, current)
    note = (body.note or "").strip()
    if not note:
        raise ValidationFailed("请填写处理说明", code="resolve_note_required")
    if alert.status != AlertStatus.OPEN:
        raise Conflict("该预警已处理", code="already_resolved")
    if not _can_resolve(alert, outbox, current):
        raise Forbidden()
    alert.status = AlertStatus.RESOLVED
    alert.resolved_by = current.user.id
    alert.resolved_at = clock.now()
    alert.resolve_note = note
    db.flush()
    audit(db, Actor(user=current.user, roles=current.roles, auth_source=current.auth_source),
          action="alert_resolved", object_type="alert", object_id=alert.id,
          before={"status": AlertStatus.OPEN}, after={"status": alert.status, "note": note})
    data = _row(alert, rule, rv, outbox, alerting.last_parts(db, [alert.id]).get(alert.id, {}), current, db)
    db.commit()
    return data
