"""预算规则库（DATA-F12-01/02；AC-F12-01~07，技术方案 4.8.3）。

规则版本只插入：新建 / 修改都生成「待审批」新版本（可信度必选）；财务负责人通过驱动假设、预警规则即生效，
额度标准再经 CEO；新版本生效时原生效版本转「历史」；退回（原因必填）后为「已退回」不生效，提交人修改后重新
提交生成新的版本号。同一规则已有待审批（含待CEO审批）版本时禁止再提交（409）。

跨组审批接口：type = rule-version，pending_items / detail / approve / reject；服务函数只 flush。
预警规则内容（JSONB）：{"kind": "alert", "metric", "comparator", "threshold"（小数字符串）,
"consecutive_months", "applies_to": {"type", "ids"}, "receivers": [...]}；接口中阈值为百分数 / 百分点字符串。
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select

from app.core.clock import clock
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.core.money import MoneyError, dec_str, to_decimal
from app.dingtalk.outbox import NoticeContentError, build_notice
from app.models import ApprovalRecord, Category, Channel, Department, Rule, RuleVersion, User
from app.models.enums import Credibility, Role, RuleType, RuleVersionStatus
from app.services.versions import Actor, as_actor, audit, fmt_dt

TYPE_RULE_VERSION = "rule-version"
HUNDRED = Decimal(100)

METRICS = {
    "revenue_achievement": ("收入达成率", "%"),
    "gross_margin_diff": ("毛利率差", "个百分点"),
    "usage_minus_time_progress": ("额度使用率减时间进度", "个百分点"),
    "usage_rate": ("额度使用率", "%"),
    "forecast_deviation_pp": ("预测偏差百分点", "个百分点"),
}
COMPARATORS = {"lt": ("低于", "<"), "gt": ("高于", ">"), "lte": ("低于等于", "≤"), "gte": ("高于等于", "≥")}
APPLIES = {"all": "全部", "new_channel": "新渠道（起始后 12 个月内）", "channel": "指定渠道",
           "department": "指定部门", "category": "指定品类"}
RECEIVERS = {"dept_head": "对象所属部门负责人", "operations": "负责该渠道的运营", "finance_head": "财务负责人",
             "ceo": "CEO"}


# ---------------------------------------------------------------------------
# 内容转换与展示
# ---------------------------------------------------------------------------
def _fmt_num(value: Decimal) -> str:
    s = dec_str(value) or "0"
    return s.replace("-", "−")


def threshold_text(content: dict) -> str:
    """阈值展示：「> 10 个百分点」「< 70%，连续 2 个月」。"""
    metric = METRICS.get(content.get("metric"), ("", ""))
    symbol = COMPARATORS.get(content.get("comparator"), ("", ""))[1]
    value = to_decimal(content.get("threshold", "0")) * HUNDRED
    unit = metric[1]
    sep = "" if unit == "%" else " "
    text = f"{symbol} {_fmt_num(value)}{sep}{unit}"
    n = int(content.get("consecutive_months") or 1)
    return f"{text}，连续 {n} 个月" if n > 1 else text


def _names(db, model, ids) -> list[str]:
    if not ids:
        return []
    return list(db.scalars(select(model.name).where(model.id.in_(ids)).order_by(model.id)))


def content_view(db, rule_type: str, content: dict) -> dict:
    """规则内容的接口形态：预警规则阈值转为百分数 / 百分点字符串，并给出展示摘要。"""
    if content.get("kind") == "alert":
        applies = content.get("applies_to") or {"type": "all"}
        if applies.get("type") in ("channel", "department", "category") and not applies.get("ids"):
            applies = {"type": "all", "ids": []}   # 指标本身限定对象类型（如部门费用），未指定清单即全部
        model = {"channel": Channel, "department": Department, "category": Category}.get(applies.get("type"))
        targets = _names(db, model, applies.get("ids")) if model else []
        applies_text = APPLIES.get(applies.get("type"), "全部") + (f"：{'、'.join(targets)}" if targets else "")
        receivers = [RECEIVERS.get(r, r) for r in content.get("receivers", [])]
        metric = METRICS.get(content.get("metric"), ("", ""))
        return {
            "kind": "alert", "metric": content.get("metric"), "metric_label": metric[0], "unit": metric[1],
            "comparator": content.get("comparator"),
            "comparator_label": COMPARATORS.get(content.get("comparator"), ("",))[0],
            "threshold": dec_str(to_decimal(content.get("threshold", "0")) * HUNDRED),
            "consecutive_months": int(content.get("consecutive_months") or 1),
            "applies_to": {"type": applies.get("type", "all"), "ids": list(applies.get("ids") or [])},
            "applies_text": applies_text, "receivers": list(content.get("receivers", [])),
            "receivers_text": "、".join(receivers),
            "summary": f"{metric[0]} {threshold_text(content)}；适用对象：{applies_text}；接收：{'、'.join(receivers)}",
        }
    if content.get("kind") == "new_channel_ramp":
        limits = content.get("limits") or []
        return {"kind": "new_channel_ramp", "unit": content.get("unit", "CNY/店铺/月"), "limits": limits,
                "text": content.get("text") or "", "summary": content.get("text") or
                "新渠道起始后第 1–12 个月逐月上限：" + "、".join(limits)}
    return {"kind": "text", "text": content.get("text", ""), "summary": content.get("text", "")}


def parse_content(db, rule_type: str, name: str, body: dict) -> tuple[dict, dict[str, str]]:
    """校验并转换提交的规则内容；返回（content, 字段错误）。"""
    errors: dict[str, str] = {}
    if rule_type == RuleType.ALERT:
        alert = body.get("alert") or {}
        metric, comparator = alert.get("metric"), alert.get("comparator")
        if metric not in METRICS:
            errors["metric"] = "请选择指标"
        if comparator not in COMPARATORS:
            errors["comparator"] = "请选择比较方式"
        threshold = None
        try:
            if str(alert.get("threshold", "")).strip() == "":
                raise MoneyError("空")
            threshold = to_decimal(alert.get("threshold")) / HUNDRED
        except MoneyError:
            errors["threshold"] = "请填写阈值（数字）"
        months = alert.get("consecutive_months")
        if not isinstance(months, int) or isinstance(months, bool) or months < 1:
            try:
                months = int(str(months))
                if months < 1:
                    raise ValueError
            except (TypeError, ValueError):
                errors["consecutive_months"] = "请填写不小于 1 的整数"
        applies = alert.get("applies_to") or {}
        if applies.get("type") not in APPLIES:
            errors["applies_to"] = "请选择适用对象"
        elif applies.get("type") in ("channel", "department", "category") and not applies.get("ids"):
            errors["applies_to"] = "请选择适用对象"
        receivers = [r for r in (alert.get("receivers") or []) if r in RECEIVERS]
        if not receivers:
            errors["receivers"] = "请至少选择一个接收角色"
        if name:
            try:  # 预警规则名称会进入钉钉通知，不能含金额样式文本（NFR-005）
                build_notice(title="【预算预警】", name=name, link="/alerts")
            except NoticeContentError:
                errors["name"] = "预警规则名称会出现在钉钉通知中，不能包含金额或带小数的数字"
        if errors:
            return {}, errors
        return {"kind": "alert", "metric": metric, "comparator": comparator, "threshold": dec_str(threshold),
                "consecutive_months": int(months),
                "applies_to": {"type": applies["type"], "ids": [int(i) for i in applies.get("ids") or []]},
                "receivers": receivers}, errors
    text = str(body.get("content_text") or "").strip()
    limits = body.get("limits")
    if rule_type == RuleType.QUOTA and limits:
        try:
            values = [dec_str(to_decimal(x)) for x in limits]
        except MoneyError:
            values = []
        if len(values) != 12:
            errors["limits"] = "请填写起始后第 1–12 个月的逐月上限（数字）"
        if errors:
            return {}, errors
        return {"kind": "new_channel_ramp", "unit": "CNY/店铺/月", "limits": values, "text": text}, errors
    if not text:
        errors["content_text"] = "请填写规则内容"
        return {}, errors
    return {"kind": "text", "text": text}, errors


def _validate(db, body: dict, *, rule_type: str, need_name: bool) -> tuple[dict, str, str, str]:
    errors: dict[str, str] = {}
    name = str(body.get("name") or "").strip()
    if need_name and not name:
        errors["name"] = "请填写规则名称"
    if rule_type not in RuleType.LABELS:
        errors["type"] = "请选择规则类型"
        content = {}
    else:
        content, content_errors = parse_content(db, rule_type, name, body)
        errors.update(content_errors)
    credibility = body.get("credibility")
    if credibility not in Credibility.LABELS:
        errors["credibility"] = "请选择可信度状态"
    basis = str(body.get("basis") or "").strip()
    if not basis:
        errors["basis"] = "请填写依据"
    if errors:
        first = next(iter(errors.values()))
        raise ValidationFailed(first, details={"fields": errors})
    return content, name, credibility, basis


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------
def _versions(db, rule_id: int) -> list[RuleVersion]:
    return list(db.scalars(select(RuleVersion).where(RuleVersion.rule_id == rule_id)
                           .order_by(RuleVersion.version_no.desc())))


def _user_name(db, uid: int | None, default: str = "系统预置") -> str:
    if uid is None:
        return default
    u = db.get(User, uid)
    return u.name if u else default


def _return_info(db, rv: RuleVersion) -> dict | None:
    if rv.status != RuleVersionStatus.RETURNED:
        return None
    rec = db.scalar(select(ApprovalRecord).where(ApprovalRecord.object_type == TYPE_RULE_VERSION,
                                                 ApprovalRecord.object_id == rv.id, ApprovalRecord.action == "reject")
                    .order_by(ApprovalRecord.id.desc()).limit(1))
    return {"reason": rv.return_reason, "by": _user_name(db, rec.approver_id, "") if rec else "",
            "at": fmt_dt(rec.created_at) if rec else None}


def version_view(db, rule: Rule, rv: RuleVersion) -> dict:
    return {
        "id": rv.id, "version_no": rv.version_no, "status": rv.status,
        "status_label": RuleVersionStatus.LABELS[rv.status], "content": content_view(db, rule.type, rv.content),
        "credibility": rv.credibility, "credibility_label": Credibility.LABELS[rv.credibility], "basis": rv.basis,
        "submitted_by_name": _user_name(db, rv.submitted_by), "submitted_at": fmt_dt(rv.submitted_at),
        "approved_by_name": _user_name(db, rv.approved_by, "") if rv.approved_by else None,
        "approved_at": fmt_dt(rv.approved_at), "effective_at": fmt_dt(rv.effective_at),
        "returned": _return_info(db, rv),
    }


def rule_summary(db, rule: Rule) -> dict:
    versions = _versions(db, rule.id)
    effective = next((v for v in versions if v.status == RuleVersionStatus.EFFECTIVE), None)
    pending = next((v for v in versions if v.status in (RuleVersionStatus.PENDING, RuleVersionStatus.PENDING_CEO)),
                   None)
    latest = versions[0] if versions else None
    return {
        "id": rule.id, "name": rule.name, "type": rule.type, "type_label": RuleType.LABELS[rule.type],
        "is_preset": rule.is_preset,
        "credibility": effective.credibility if effective else None,
        "credibility_label": Credibility.LABELS[effective.credibility] if effective else None,
        "effective_version_no": effective.version_no if effective else None,
        "effective_at": fmt_dt(effective.effective_at) if effective else None,
        "pending": {"version_no": pending.version_no, "status": pending.status,
                    "status_label": RuleVersionStatus.LABELS[pending.status],
                    "credibility_label": Credibility.LABELS[pending.credibility],
                    "waiting_for": "CEO" if pending.status == RuleVersionStatus.PENDING_CEO else "财务负责人"}
        if pending else None,
        "latest_status": latest.status if latest else None,
        "latest_version_no": latest.version_no if latest else None,
        "latest_submitter": _user_name(db, latest.submitted_by) if latest else None,
    }


def list_rules(db, *, rule_type: str | None = None, credibility: str | None = None,
               state: str | None = None) -> list[dict]:
    q = select(Rule).order_by(Rule.id)
    if rule_type:
        q = q.where(Rule.type == rule_type)
    out = [rule_summary(db, r) for r in db.scalars(q)]
    if credibility:
        out = [r for r in out if r["credibility"] == credibility]
    if state == "effective":
        out = [r for r in out if r["effective_version_no"]]
    elif state == "pending":
        out = [r for r in out if r["pending"]]
    return out


def edit_block(db, rule: Rule) -> str | None:
    pending = db.scalar(select(RuleVersion).where(
        RuleVersion.rule_id == rule.id,
        RuleVersion.status.in_((RuleVersionStatus.PENDING, RuleVersionStatus.PENDING_CEO))))
    if pending:
        return f"已有待审批版本 v{pending.version_no}，审批完成前不能再提交新版本"
    return None


def rule_detail(db, actor: Actor, rule_id: int) -> dict:
    rule = db.get(Rule, rule_id)
    if rule is None:
        raise NotFound("该规则不存在")
    versions = _versions(db, rule.id)
    data = rule_summary(db, rule)
    latest = versions[0] if versions else None
    data.update(
        versions=[version_view(db, rule, v) for v in versions],
        can_edit=actor.has_role(Role.FINANCE_BP, Role.FINANCE_HEAD),
        edit_block=edit_block(db, rule),
        resubmit=bool(latest and latest.status == RuleVersionStatus.RETURNED),
    )
    return data


# ---------------------------------------------------------------------------
# 新建与提交新版本（API-F12-01 / API-F12-02）
# ---------------------------------------------------------------------------
def _ensure_editor(actor: Actor) -> None:
    if not actor.has_role(Role.FINANCE_BP, Role.FINANCE_HEAD):
        raise Forbidden()


def create_rule(db, user, body: dict) -> Rule:
    actor = as_actor(db, user)
    _ensure_editor(actor)
    rule_type = body.get("type")
    content, name, credibility, basis = _validate(db, body, rule_type=rule_type, need_name=True)
    rule = Rule(name=name, type=rule_type, created_by=actor.id)
    db.add(rule)
    db.flush()
    rv = RuleVersion(rule_id=rule.id, version_no=1, content=content, credibility=credibility, basis=basis,
                     status=RuleVersionStatus.PENDING, submitted_by=actor.id, submitted_at=clock.now())
    db.add(rv)
    db.flush()
    audit(db, actor, action="rule_created", object_type="rule", object_id=rule.id,
          after={"name": name, "type": rule_type, "version_no": 1, "content": content, "credibility": credibility,
                 "basis": basis})
    return rule


def submit_version(db, user, rule_id: int, body: dict) -> RuleVersion:
    actor = as_actor(db, user)
    _ensure_editor(actor)
    rule = db.scalar(select(Rule).where(Rule.id == rule_id).with_for_update())
    if rule is None:
        raise NotFound("该规则不存在")
    block = edit_block(db, rule)
    if block:
        raise Conflict("该规则已有待审批版本", code="rule_pending_exists", details={"reason": block})
    body = {**body, "name": rule.name}
    content, _name, credibility, basis = _validate(db, body, rule_type=rule.type, need_name=False)
    before = _versions(db, rule.id)
    no = (db.scalar(select(func.max(RuleVersion.version_no)).where(RuleVersion.rule_id == rule.id)) or 0) + 1
    rv = RuleVersion(rule_id=rule.id, version_no=no, content=content, credibility=credibility, basis=basis,
                     status=RuleVersionStatus.PENDING, submitted_by=actor.id, submitted_at=clock.now())
    db.add(rv)
    db.flush()
    prev = before[0] if before else None
    audit(db, actor, action="rule_version_submitted", object_type="rule", object_id=rule.id,
          before={"version_no": prev.version_no, "content": prev.content, "credibility": prev.credibility,
                  "status": prev.status} if prev else None,
          after={"version_no": no, "content": content, "credibility": credibility, "basis": basis})
    return rv


# ---------------------------------------------------------------------------
# 审批（跨组接口 type = rule-version）
# ---------------------------------------------------------------------------
def _level_for(actor: Actor, rv: RuleVersion) -> str | None:
    if rv.status == RuleVersionStatus.PENDING and actor.has_role(Role.FINANCE_HEAD):
        return "finance_head"
    if rv.status == RuleVersionStatus.PENDING_CEO and actor.has_role(Role.CEO):
        return "ceo"
    return None


def pending_items(db, user) -> list[dict]:
    actor = as_actor(db, user)
    statuses = []
    if actor.has_role(Role.FINANCE_HEAD):
        statuses.append(RuleVersionStatus.PENDING)
    if actor.has_role(Role.CEO):
        statuses.append(RuleVersionStatus.PENDING_CEO)
    if not statuses:
        return []
    rows = db.execute(select(RuleVersion, Rule).join(Rule, Rule.id == RuleVersion.rule_id)
                      .where(RuleVersion.status.in_(statuses)).order_by(RuleVersion.submitted_at, RuleVersion.id))
    items = []
    for rv, rule in rows:
        prev = ("财务负责人已通过" if rv.status == RuleVersionStatus.PENDING_CEO
                else f"{_user_name(db, rv.submitted_by)} 提交")
        step = "CEO 审批" if rv.status == RuleVersionStatus.PENDING_CEO else "财务负责人审批"
        items.append({"type": TYPE_RULE_VERSION, "id": rv.id, "title": f"{rule.name}（v{rv.version_no}）",
                      "kind_label": f"规则库 · {RuleType.LABELS[rule.type]}", "prev_step": prev, "step": step,
                      "submitter": _user_name(db, rv.submitted_by),
                      "submitted_at": rv.submitted_at.isoformat() if rv.submitted_at else None,
                      "link": f"/approvals/{TYPE_RULE_VERSION}/{rv.id}"})
    return items


def _get_version(db, obj_id: int, lock: bool = False) -> tuple[RuleVersion, Rule]:
    q = select(RuleVersion).where(RuleVersion.id == obj_id)
    rv = db.scalar(q.with_for_update() if lock else q)
    if rv is None:
        raise NotFound("规则版本不存在")
    return rv, db.get(Rule, rv.rule_id)


def detail(db, user, obj_id: int) -> dict:
    actor = as_actor(db, user)
    if not actor.has_role(Role.FINANCE_HEAD, Role.CEO, Role.FINANCE_BP):
        raise Forbidden()
    rv, rule = _get_version(db, obj_id)
    effective = db.scalar(select(RuleVersion).where(RuleVersion.rule_id == rule.id,
                                                    RuleVersion.status == RuleVersionStatus.EFFECTIVE))
    records = db.execute(select(ApprovalRecord, User.name).join(User, User.id == ApprovalRecord.approver_id)
                         .where(ApprovalRecord.object_type == TYPE_RULE_VERSION, ApprovalRecord.object_id == rv.id)
                         .order_by(ApprovalRecord.id)).all()
    return {"type": TYPE_RULE_VERSION, "id": rv.id, "rule_id": rule.id, "rule_name": rule.name,
            "rule_type": rule.type, "rule_type_label": RuleType.LABELS[rule.type],
            "needs_ceo": rule.type == RuleType.QUOTA, "version": version_view(db, rule, rv),
            "effective_version": version_view(db, rule, effective) if effective and effective.id != rv.id else None,
            "records": [{"level": r.level, "action": r.action, "reason": r.reason, "approver_name": n,
                         "at": fmt_dt(r.created_at)} for r, n in records],
            "can_act": _level_for(actor, rv) is not None}


def _make_effective(db, actor: Actor, rule: Rule, rv: RuleVersion) -> RuleVersion | None:
    now = clock.now()
    old = db.scalar(select(RuleVersion).where(RuleVersion.rule_id == rule.id,
                                              RuleVersion.status == RuleVersionStatus.EFFECTIVE).with_for_update())
    if old is not None:
        old.status = RuleVersionStatus.HISTORY
        db.flush()  # 部分唯一索引：先转历史再生效
    rv.status = RuleVersionStatus.EFFECTIVE
    rv.effective_at = now
    rule.current_version_id = rv.id
    db.flush()
    return old


def approve(db, user, obj_id: int) -> dict:
    actor = as_actor(db, user)
    rv, rule = _get_version(db, obj_id, lock=True)
    level = _level_for(actor, rv)
    if level is None:
        if actor.has_role(Role.FINANCE_HEAD, Role.CEO):
            raise Conflict("状态已变化，请刷新", code="state_changed")
        raise Forbidden()
    before = rv.status
    rv.approved_by = actor.id
    rv.approved_at = clock.now()
    old = None
    if level == "finance_head" and rule.type == RuleType.QUOTA:
        rv.status = RuleVersionStatus.PENDING_CEO
        db.flush()
    else:
        old = _make_effective(db, actor, rule, rv)
    db.add(ApprovalRecord(object_type=TYPE_RULE_VERSION, object_id=rv.id, level=level, action="approve",
                          approver_id=actor.id))
    db.flush()
    audit(db, actor, action="rule_version_approved", object_type="rule", object_id=rule.id,
          before={"version_no": rv.version_no, "status": before},
          after={"version_no": rv.version_no, "status": rv.status, "level": level,
                 "history_version_no": old.version_no if old else None})
    return {"type": TYPE_RULE_VERSION, "id": rv.id, "status": rv.status,
            "status_label": RuleVersionStatus.LABELS[rv.status]}


def reject(db, user, obj_id: int, reason: str) -> dict:
    actor = as_actor(db, user)
    if not (reason or "").strip():
        raise ValidationFailed("请填写退回原因", code="reason_required")
    rv, rule = _get_version(db, obj_id, lock=True)
    level = _level_for(actor, rv)
    if level is None:
        if actor.has_role(Role.FINANCE_HEAD, Role.CEO):
            raise Conflict("状态已变化，请刷新", code="state_changed")
        raise Forbidden()
    before = rv.status
    rv.status = RuleVersionStatus.RETURNED
    rv.return_reason = reason.strip()
    db.add(ApprovalRecord(object_type=TYPE_RULE_VERSION, object_id=rv.id, level=level, action="reject",
                          reason=rv.return_reason, approver_id=actor.id))
    db.flush()
    audit(db, actor, action="rule_version_returned", object_type="rule", object_id=rule.id,
          before={"version_no": rv.version_no, "status": before},
          after={"version_no": rv.version_no, "status": rv.status, "reason": rv.return_reason})
    return {"type": TYPE_RULE_VERSION, "id": rv.id, "status": rv.status,
            "status_label": RuleVersionStatus.LABELS[rv.status]}


def options(db) -> dict:
    """新建 / 编辑表单的选项。"""
    return {
        "types": [{"value": k, "label": v} for k, v in RuleType.LABELS.items()],
        "credibility": [{"value": k, "label": v} for k, v in Credibility.LABELS.items()],
        "metrics": [{"value": k, "label": v[0], "unit": v[1]} for k, v in METRICS.items()],
        "comparators": [{"value": k, "label": v[0]} for k, v in COMPARATORS.items()],
        "applies": [{"value": k, "label": v} for k, v in APPLIES.items()],
        "receivers": [{"value": k, "label": v} for k, v in RECEIVERS.items()],
        "channels": [{"id": i, "name": n} for i, n in db.execute(select(Channel.id, Channel.name).order_by(Channel.sort))],
        "departments": [{"id": i, "name": n} for i, n in db.execute(select(Department.id, Department.name)
                                                                    .order_by(Department.sort))],
        "categories": [{"id": i, "name": n} for i, n in db.execute(select(Category.id, Category.name)
                                                                   .order_by(Category.sort))],
    }

