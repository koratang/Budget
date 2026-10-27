"""E1 验收（SMOKE-03、FLOW-01~10）共用：场景前置主数据、每人独立 Cookie 的客户端、常用接口操作。

前置只写契约「场景与操作」中的初始状态（主数据与人员）；待验动作一律经真实 HTTP 路由完成。
"""
from __future__ import annotations

import io
from contextlib import nullcontext

from openpyxl import Workbook
from sqlalchemy import select, update

from app.dingtalk.outbox import process_outbox
from app.models import BCustomer, Department, Store, User, UserRole, UserScope
from tests.conftest import build_client

DEADLINE = "2026-12-20"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

FLOW09_ACTIVE_STORES = ("Amazon-US-01", "Amazon-CA-01", "Wayfair-US-01", "Shopify-US-01", "TikTok-US-01")
# 15 个参与部门各需部门预算专员与部门负责人（种子只有人力资源部专员）：(专员, 负责人或 None=已有)
FLOW09_PEOPLE = {
    "产品作战部": ("许嘉", "沈卓"), "开发部": ("宋宇", "顾磊"), "研发部": ("韩冰", "钱峰"), "供应中心": ("冯涛", "陆军"),
    "运营部": ("曹敏", None), "市场部": ("邓琳", "孔亮"), "美国业务部": ("周凯", None), "视觉部": ("彭悦", "范婷"),
    "外贸部": ("江涛", None), "物流物控部": ("吕彬", None), "项目管理部": ("唐瑶", "黎明"),
    "信息数字化部": ("董杰", "邵阳"), "财务部": ("郭琪", None), "总经办": ("袁芳", None),
}


def add_user(db, userid: str, name: str, dept: str, roles: list[str], scopes: dict | None = None,
             head: bool = False) -> User:
    d = db.scalar(select(Department).where(Department.name == dept))
    u = User(dingtalk_userid=userid, name=name, union_id=f"union-{userid}", dingtalk_dept=dept, department_id=d.id,
             is_active=True)
    db.add(u)
    db.flush()
    for r in roles:
        db.add(UserRole(user_id=u.id, role_code=r))
    for scope_type, ids in (scopes or {}).items():
        for oid in ids:
            db.add(UserScope(user_id=u.id, scope_type=scope_type, object_id=oid))
    if head:
        d.head_user_id = u.id
    db.flush()
    return u


def smoke03_master(db) -> None:
    """SMOKE-03 最小种子：1 个启用店铺 Amazon-US-01、USD 2027 预算汇率 7.12（种子已有）、1 个参与部门（人力资源部），
    B端（美国业务部）/成本比例/物流比例单位与对应人员（种子已有）。"""
    db.execute(update(Store).where(Store.name != "Amazon-US-01").values(is_active=False))
    db.execute(update(Department).where(Department.name != "人力资源部").values(is_active=False))
    db.execute(update(BCustomer).where(BCustomer.name == "Bauhaus").values(is_active=False))
    db.flush()


def flow09_master(db) -> None:
    """FLOW-09：主数据恰为 5 个启用店铺 + 1 个停用店铺（Lowes-US-02）、美国业务部与外贸部各有启用客户、15 个参与部门。"""
    from sqlalchemy import delete
    extra = select(Store.id).where(Store.name.not_in((*FLOW09_ACTIVE_STORES, "Lowes-US-02")))
    db.execute(delete(UserScope).where(UserScope.scope_type == "store", UserScope.object_id.in_(extra)))
    db.execute(delete(Store).where(Store.name.not_in((*FLOW09_ACTIVE_STORES, "Lowes-US-02"))))
    db.execute(update(Store).where(Store.name == "Lowes-US-02").values(is_active=False))
    for i, (dept, (budget_name, head_name)) in enumerate(FLOW09_PEOPLE.items()):
        d = db.scalar(select(Department).where(Department.name == dept))
        add_user(db, f"e1-budget-{i}", budget_name, dept, ["dept_budget"], {"department": [d.id]})
        if head_name:
            add_user(db, f"e1-head-{i}", head_name, dept, ["dept_head"], {"department": [d.id]}, head=True)
    db.flush()


def uid(db, userid: str) -> int:
    return db.scalar(select(User.id).where(User.dingtalk_userid == userid))


class People:
    """每人一个独立 Cookie 的真实路由客户端（开发身份 /api/dev/login-as）。"""

    def __init__(self, db, dingtalk, tmp_path=None):
        self.db, self.dingtalk, self.tmp = db, dingtalk, tmp_path
        self._c = {}

    def __call__(self, userid: str):
        if userid not in self._c:
            extra = {"DATA_DIR": str(self.tmp / "data")} if self.tmp else {}
            c = build_client(self.db, self.dingtalk, **extra)
            c.app.state.import_session_factory = lambda: nullcontext(self.db)
            r = c.post("/api/dev/login-as", json={"user_id": uid(self.db, userid)})
            assert r.status_code == 200, r.text
            self._c[userid] = c
        return self._c[userid]

    def reset(self):
        self._c.clear()


def grid(client, unit_id: int, tab: str | None = None) -> dict:
    r = client.get(f"/api/filling-units/{unit_id}/grid", params={"tab": tab} if tab else None)
    assert r.status_code == 200, r.text
    return r.json()


def row(g: dict, key: str) -> dict:
    return next(r for r in g["rows"] if r["key"] == key)


def save(client, unit_id: int, changes: list[tuple[str, str, str]], tab: str | None = None):
    g = grid(client, unit_id, tab)
    body = []
    for key, field, value in changes:
        base = next((r["values"].get(field) for r in g["rows"] if r["key"] == key), None)
        body.append({"row_key": key, "field": field, "value": value, "base": base})
    return client.patch(f"/api/filling-units/{unit_id}/cells", json=body, params={"tab": tab} if tab else None)


def messages(db, dingtalk, stub) -> list[dict]:
    process_outbox(db, dingtalk)
    return stub.get("/_stub/messages").json()


def xlsx(header: list, rows: list[list]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(header)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# 报表前置：2027 年初原始目标（已锁定）预算 + 经导入接口生效的 2027-04 金蝶实际
# ---------------------------------------------------------------------------
KINGDEE_HEADER = ["期间", "金蝶科目", "科目名称", "部门", "平台/店铺", "站点", "客户", "摘要", "发生额"]
APRIL = "2027-04"


def report_world(db, people, stores: list[str] | None = None, depts=("人力资源部", "财务部", "市场部"),
                 customers=("Ferguson", "Menards", "Bauhaus")) -> dict:
    """前置条件：年初原始目标 V1（周明远审批、已锁定）含各店铺 2027-04 浴室柜老品收入/毛利、各 B 端客户收入/毛利、
    各部门工资预算；陈思雨经 /api/imports 导入 2027-04 金蝶实际（含店铺、客户、部门费用与一行无店铺的仓储费 = 未归属渠道）。"""
    from datetime import date, datetime
    from decimal import Decimal as D

    from app.core.clock import TZ
    from app.models import (B2bUnit, BudgetAccount, BudgetVersion, Category, DeptExpense, PlatformUnit, Site)
    from app.models.enums import VersionType

    stores = stores or list(db.scalars(select(Store.name).order_by(Store.id)))
    ceo = uid(db, "zhoumingyuan")
    v = BudgetVersion(year=2027, type=VersionType.ORIGINAL_TARGET, version_no=1, name="2027 年初原始目标 V1",
                      approved_by=ceo, approved_at=datetime(2026, 12, 28, 17, 30, tzinfo=TZ), locked=False)
    db.add(v)
    db.flush()
    cat = db.scalar(select(Category.id).where(Category.name == "浴室柜"))
    m = date(2027, 4, 1)
    for name in stores:
        s = db.scalar(select(Store).where(Store.name == name))
        db.add(PlatformUnit(version_id=v.id, month=m, channel_id=s.channel_id, store_id=s.id, site_id=s.site_id,
                            category_id=cat, is_new=False, revenue_cny=D("100000"), gross_profit=D("20000")))
    for name in customers:
        c = db.scalar(select(BCustomer).where(BCustomer.name == name))
        db.add(B2bUnit(version_id=v.id, month=m, customer_id=c.id, sales_local=D("10000"), revenue_cny=D("71200"),
                       gross_profit=D("17088")))
    salary = db.scalar(select(BudgetAccount.id).where(BudgetAccount.name == "工资薪酬"))
    for name in depts:
        d = db.scalar(select(Department.id).where(Department.name == name))
        for mm in range(1, 13):
            db.add(DeptExpense(version_id=v.id, month=date(2027, mm, 1), department_id=d, account_id=salary,
                               amount=D("25000")))
    db.flush()
    v.locked = True
    db.flush()

    site_name = dict(db.execute(select(Site.id, Site.name)).all())
    rows = []
    for name in stores:
        s = db.scalar(select(Store).where(Store.name == name))
        rows.append([APRIL, "6001", "主营业务收入", "运营部", name, site_name[s.site_id], "", "", 95000])
    for name in customers:
        rows.append([APRIL, "6001", "主营业务收入", "", "", "", name, "", 70000])
    for name in depts:
        rows.append([APRIL, "6602.01", "管理费用-工资", name, "", "", "", "", 24000])
    rows.append([APRIL, "6601.06", "销售费用-仓储费", "", "", "", "", "仓储杂费", 12000])
    bp = people("chensiyu")
    r = bp.post("/api/imports", files={"file": ("金蝶_2027-04_利润表.xlsx", xlsx(KINGDEE_HEADER, rows), XLSX)},
                data={"source": "kingdee"})
    assert r.status_code == 200, r.text
    batch = bp.get(f"/api/imports/{r.json()['id']}").json()
    assert batch["status"] == "passed", batch
    r = bp.post(f"/api/imports/{batch['id']}/confirm", json={"overwrite": False})
    assert r.status_code == 200, r.text
    return {"version_id": v.id}


FLOW03_STORES = ["Amazon-US-01", "Amazon-CA-01", "Wayfair-US-01", "Lowes-US-01"]
FLOW03_DEPTS = ("人力资源部", "财务部", "市场部")


def flow03_setup(db, people) -> int:
    """FLOW-03 前置：4 个启用店铺、3 个部门（人力资源部 / 财务部 / 市场部）、3 个 B 端客户的预算与 2027-04 实际；
    林晓经接口发布 2027 编制任务（4 个平台渠道、美国业务部与外贸部 B 端、成本比例、物流比例、3 个部门费用单位）。"""
    db.execute(update(Store).values(is_active=False))
    db.execute(update(Store).where(Store.name.in_(FLOW03_STORES)).values(is_active=True))
    fin = db.scalar(select(Department.id).where(Department.name == "财务部"))
    mkt = db.scalar(select(Department.id).where(Department.name == "市场部"))
    add_user(db, "e1-guoqi", "郭琪", "财务部", ["dept_budget"], {"department": [fin]})
    add_user(db, "e1-denglin", "邓琳", "市场部", ["dept_budget"], {"department": [mkt]})
    add_user(db, "e1-kongliang", "孔亮", "市场部", ["dept_head"], {"department": [mkt]}, head=True)
    report_world(db, people, stores=FLOW03_STORES, depts=FLOW03_DEPTS)
    lin = people("linxiao")
    cands = lin.get("/api/tasks/candidates").json()["items"]
    units = [{"unit_type": c["unit_type"], "scope_object_id": c["scope_object_id"]} for c in cands
             if c["unit_type"] != "dept_expense" or c["name"] in FLOW03_DEPTS]
    r = lin.post("/api/tasks", json={"year": 2027, "deadline": DEADLINE, "units": units})
    assert r.status_code == 201, r.text
    return r.json()["task"]["id"]


def flow06_setup(db, people) -> None:
    """FLOW-06 前置：预算科目清单含部门费用科目「市场推广费」「差旅费」「招待费」、尚无「员工关怀费」，金蝶 6601.12 未映射；
    年初原始目标（已锁定）含市场部「招待费」「市场推广费」预算；2027-03 金蝶实际含市场部招待费 5,200.00（经导入接口生效）。"""
    from datetime import date, datetime
    from decimal import Decimal as D

    from sqlalchemy import delete

    from app.core.clock import TZ
    from app.models import BudgetAccount, BudgetVersion, DeptExpense, KingdeeAccountMap
    from app.models.enums import VersionType

    care = db.scalar(select(BudgetAccount.id).where(BudgetAccount.name == "员工关怀费"))
    db.execute(delete(KingdeeAccountMap).where(KingdeeAccountMap.account_id == care))
    db.execute(delete(BudgetAccount).where(BudgetAccount.id == care))
    db.scalar(select(BudgetAccount).where(BudgetAccount.name == "业务招待费")).name = "招待费"
    db.add(BudgetAccount(name="市场推广费", is_dept_expense=True, sort=11))
    mkt = db.scalar(select(Department.id).where(Department.name == "市场部"))
    add_user(db, "e1-denglin", "邓琳", "市场部", ["dept_budget"], {"department": [mkt]})
    add_user(db, "e1-kongliang", "孔亮", "市场部", ["dept_head"], {"department": [mkt]}, head=True)
    db.flush()
    v = BudgetVersion(year=2027, type=VersionType.ORIGINAL_TARGET, version_no=1, name="2027 年初原始目标 V1",
                      approved_by=uid(db, "zhoumingyuan"), approved_at=datetime(2026, 12, 28, 17, 30, tzinfo=TZ))
    db.add(v)
    db.flush()
    for name, amount in (("招待费", "6000"), ("市场推广费", "50000")):
        acc = db.scalar(select(BudgetAccount.id).where(BudgetAccount.name == name))
        for m in (3, 4):
            db.add(DeptExpense(version_id=v.id, month=date(2027, m, 1), department_id=mkt, account_id=acc,
                               amount=D(amount)))
    db.flush()
    v.locked = True
    db.flush()
    bp = people("chensiyu")
    r = bp.post("/api/imports", files={"file": ("金蝶_2027-03_利润表.xlsx", xlsx(KINGDEE_HEADER, [
        ["2027-03", "6602.10", "管理费用-业务招待费", "市场部", "", "", "", "", 5200]]), XLSX)}, data={"source": "kingdee"})
    assert r.status_code == 200, r.text
    assert bp.get(f"/api/imports/{r.json()['id']}").json()["status"] == "passed"
    assert bp.post(f"/api/imports/{r.json()['id']}/confirm", json={"overwrite": False}).status_code == 200


def flow07_master(db) -> None:
    """FLOW-07 前置：2027 尚无 USD、EUR 预算汇率（编制期由陈思雨录入 USD）；王浩负责 Amazon-US-01 与 Amazon-DE-01（EUR）。"""
    from sqlalchemy import delete

    from app.models import FxBudget
    db.execute(delete(FxBudget).where(FxBudget.year == 2027, FxBudget.currency.in_(("USD", "EUR"))))
    de = db.scalar(select(Store.id).where(Store.name == "Amazon-DE-01"))
    db.add(UserScope(user_id=uid(db, "wanghao"), scope_type="store", object_id=de))
    db.flush()
