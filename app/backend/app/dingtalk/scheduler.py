"""进程内调度器 CMP-F00-03（APScheduler BackgroundScheduler，时区 Asia/Shanghai，单进程部署，DEC-004）。

任务：
- 每分钟：发送到期的通知发件箱（含失败重试）。
- 每日 09:00：逾期检查钩子（编制任务组用 register_overdue_hook 注册，AC-F03-04）。
- 每 10 分钟增量、每日 02:00 全量：钉钉通讯录同步，离职 / 停用用户标为停用（DEC-012）。
时钟：各任务函数都接收 now，调度器传 clock.now()；测试直接调用 run_* 并传入可控时间。
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.auth import sync_user_from_directory
from app.core.clock import TZ, clock
from app.dingtalk.gateway import DingTalkClient
from app.dingtalk.outbox import process_outbox
from app.models import User

OverdueHook = Callable[[Session, datetime], None]
_overdue_hooks: list[OverdueHook] = []
heartbeat: dict[str, datetime | None] = {"last": None}


def register_overdue_hook(fn: OverdueHook) -> OverdueHook:
    """注册每日 09:00 逾期检查（可作装饰器）。钩子在传入的会话中写发件箱，由调度器提交。"""
    if fn not in _overdue_hooks:
        _overdue_hooks.append(fn)
    return fn


def run_outbox(db: Session, client: DingTalkClient, now: datetime | None = None) -> dict:
    return process_outbox(db, client, now or clock.now())


def run_overdue_check(db: Session, now: datetime | None = None) -> None:
    now = now or clock.now()
    for hook in list(_overdue_hooks):
        hook(db, now)
    db.commit()


def run_contact_sync(db: Session, client: DingTalkClient, now: datetime | None = None) -> dict:
    """通讯录同步：新用户建本地记录（无角色）；不在通讯录或停用的本地用户标为停用并撤销会话。"""
    directory = {u.userid: u for u in client.list_users()}
    stats = {"created": 0, "disabled": 0}
    local = {u.dingtalk_userid: u for u in db.scalars(select(User))}
    for userid, info in directory.items():
        existing = local.get(userid)
        was_active = existing.is_active if existing else False
        user = sync_user_from_directory(db, userid, info)
        if existing is None and user is not None:
            stats["created"] += 1
        elif existing is not None and was_active and not user.is_active:
            stats["disabled"] += 1
    for userid, user in local.items():
        if userid not in directory and user.is_active:
            sync_user_from_directory(db, userid, None)
            stats["disabled"] += 1
    db.commit()
    return stats


def create_scheduler(session_maker: sessionmaker[Session], client: DingTalkClient) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone=TZ)

    def _job(fn: Callable[[Session], object]) -> Callable[[], None]:
        def run() -> None:
            heartbeat["last"] = clock.now()
            # 异常由 APScheduler 记录日志，下个周期再执行；会话退出时自动回滚
            with session_maker() as db:
                fn(db)
        return run

    scheduler.add_job(_job(lambda db: run_outbox(db, client)), "interval", minutes=1, id="outbox",
                      max_instances=1, coalesce=True)
    scheduler.add_job(_job(run_overdue_check), "cron", hour=9, minute=0, id="overdue",
                      max_instances=1, coalesce=True)
    scheduler.add_job(_job(lambda db: run_contact_sync(db, client)), "interval", minutes=10,
                      id="contacts_incremental", max_instances=1, coalesce=True)
    scheduler.add_job(_job(lambda db: run_contact_sync(db, client)), "cron", hour=2, minute=0,
                      id="contacts_full", max_instances=1, coalesce=True)
    return scheduler
