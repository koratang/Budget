"""G1 场景测试共用：按钉钉 userid 以开发身份登录、按名称取主数据 ID、生成 xlsx。"""
import io

from openpyxl import Workbook
from sqlalchemy import select

from app.models import BCustomer, BudgetAccount, Channel, Department, Site, Store, User
from tests.conftest import build_client


def uid(db, userid: str) -> int:
    return db.scalar(select(User.id).where(User.dingtalk_userid == userid))


def login(db, dingtalk, userid: str):
    """独立会话的客户端（每人一个 Cookie），以开发身份登录。"""
    c = build_client(db, dingtalk)
    r = c.post("/api/dev/login-as", json={"user_id": uid(db, userid)})
    assert r.status_code == 200, r.text
    return c


def id_of(db, model, name: str) -> int:
    return db.scalar(select(model.id).where(model.name == name))


def store_id(db, name):
    return id_of(db, Store, name)


def channel_id(db, name):
    return id_of(db, Channel, name)


def dept_id(db, name):
    return id_of(db, Department, name)


def customer_id(db, name):
    return id_of(db, BCustomer, name)


def account_id(db, name):
    return id_of(db, BudgetAccount, name)


def site_id(db, code):
    return db.scalar(select(Site.id).where(Site.code == code))


def xlsx(rows: list[list]) -> bytes:
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
