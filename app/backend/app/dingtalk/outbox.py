"""通知发件箱（DEC-011、AC-F11-05、NFR-005）。

- 业务事务内只调用 enqueue_notice() 插入「待发送」记录，不直接调钉钉。
- 调度器每分钟调用 process_outbox()：成功 → 已发送；失败 → 尝试次数 +1，5 分钟后重试；
  首发后最多重试 3 次（共 4 次），仍失败 → 「失败」，若业务类型为预警则把预警通知状态标为「通知失败」。
- 内容只允许标题、名称、对象、期间、链接五个字符串参数；拒绝任何数值 / Decimal / 疑似金额文本。
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import clock
from app.dingtalk.gateway import DingTalkClient, DingTalkError
from app.models import Alert, NotificationOutbox
from app.models.enums import NotifyStatus, OutboxStatus

MAX_ATTEMPTS = 4                      # 首发 1 次 + 重试 3 次
RETRY_INTERVAL = timedelta(minutes=5)
BIZ_ALERT = "alert"

# 疑似金额：千分位数字、带小数的数字（百分比除外）、货币符号或「元」
_AMOUNT_PATTERNS = [
    re.compile(r"\d{1,3}(,\d{3})+"),
    re.compile(r"(?<![\d.])\d+\.\d+(?!\d|\s*%)"),
    re.compile(r"[¥$€£￥]"),
    re.compile(r"\d\s*元"),
]


class NoticeContentError(ValueError):
    """通知内容含金额或非白名单参数（NFR-005）。"""


@dataclass(frozen=True)
class NoticeContent:
    title: str
    name: str
    object_name: str
    period: str
    link: str

    def text(self) -> str:
        return "｜".join(p for p in (self.name, self.object_name, self.period) if p)


def build_notice(*, title: str, name: str, object_name: str = "", period: str = "", link: str) -> NoticeContent:
    """类型化模板：只接受五个字符串参数；数值、Decimal 与疑似金额文本一律拒绝。"""
    values = {"title": title, "name": name, "object_name": object_name, "period": period}
    for key, value in {**values, "link": link}.items():
        if not isinstance(value, str):
            raise NoticeContentError(f"通知参数 {key} 只能是文本，不能是 {type(value).__name__}")
    for key, value in values.items():
        if any(p.search(value) for p in _AMOUNT_PATTERNS):
            raise NoticeContentError(f"通知参数 {key} 疑似包含金额：{value}")
    return NoticeContent(title=title, name=name, object_name=object_name, period=period, link=link)


def to_dingtalk_msg(content: NoticeContent) -> dict[str, Any]:
    """钉钉工作通知「链接」消息。"""
    return {"msgtype": "link", "link": {"messageUrl": content.link, "picUrl": "@lALOACZwe2Rk",
                                         "title": content.title, "text": content.text()}}


def enqueue_notice(db: Session, *, biz_type: str, biz_id: int | None, receivers: list[str],
                   content: NoticeContent, now: datetime | None = None) -> NotificationOutbox | None:
    """在业务事务内写发件箱（不提交）。无接收人时不写。"""
    if not isinstance(content, NoticeContent):
        raise NoticeContentError("通知内容必须由 build_notice() 生成")
    receivers = sorted({r for r in receivers if r})
    if not receivers:
        return None
    row = NotificationOutbox(biz_type=biz_type, biz_id=biz_id, receivers=receivers, params=asdict(content),
                             status=OutboxStatus.PENDING, attempts=0, next_attempt_at=now or clock.now(),
                             attempt_log=[])
    db.add(row)
    db.flush()
    return row


def _set_alert_notify_status(db: Session, row: NotificationOutbox, status: str) -> None:
    if row.biz_type == BIZ_ALERT and row.biz_id is not None:
        alert = db.get(Alert, row.biz_id)
        if alert is not None:
            alert.notify_status = status


def process_outbox(db: Session, client: DingTalkClient, now: datetime | None = None, limit: int = 100) -> dict:
    """发送到期的发件箱记录并提交。返回 {sent, retrying, failed}。"""
    now = now or clock.now()
    rows = db.scalars(
        select(NotificationOutbox)
        .where(NotificationOutbox.status == OutboxStatus.PENDING, NotificationOutbox.next_attempt_at <= now)
        .order_by(NotificationOutbox.next_attempt_at, NotificationOutbox.id)
        .limit(limit).with_for_update(skip_locked=True)
    ).all()
    stats = {"sent": 0, "retrying": 0, "failed": 0}
    for row in rows:
        content = NoticeContent(**row.params)
        row.attempts += 1
        try:
            task_id = client.send_work_notice(list(row.receivers), to_dingtalk_msg(content))
        except DingTalkError as e:
            row.last_error = str(e)
            row.attempt_log = [*row.attempt_log, {"at": now.isoformat(), "ok": False, "error": str(e)}]
            if row.attempts >= MAX_ATTEMPTS:
                row.status = OutboxStatus.FAILED
                _set_alert_notify_status(db, row, NotifyStatus.FAILED)
                stats["failed"] += 1
            else:
                row.next_attempt_at = now + RETRY_INTERVAL
                _set_alert_notify_status(db, row, NotifyStatus.RETRYING)
                stats["retrying"] += 1
        else:
            row.status = OutboxStatus.SENT
            row.sent_at = now
            row.dingtalk_task_id = task_id
            row.last_error = None
            row.attempt_log = [*row.attempt_log, {"at": now.isoformat(), "ok": True}]
            _set_alert_notify_status(db, row, NotifyStatus.SENT)
            stats["sent"] += 1
    db.commit()
    return stats
