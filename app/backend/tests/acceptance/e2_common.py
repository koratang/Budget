"""E2（FLOW-11~20）验收共用：经真实路由（TestClient）构造契约写明的前置状态。

同一套构造既用于 pytest 验收（事务回滚的测试库），也用于浏览器 E2E 前置（e2_setup 直接写 budget_acc2）。
前置只做契约「初始状态」里的事（发布任务、预置比例、已导入实际、已生成的 V1/V2 等），待验收动作留给各测试 / 浏览器步骤。
"""
from __future__ import annotations

import io
from contextlib import nullcontext
from datetime import datetime
from decimal import Decimal

from openpyxl import Workbook
from sqlalchemy import select

from app.core.clock import TZ, clock
from app.models import FillingUnit, User
from tests.g2.helpers import (account, category_id, customer, minimal_units, pu_key, store, uid, unit_by_name)

D = Decimal
MAR = "2027-03"
FLOW11_DRIVERS = {"spu_count": "10", "avg_sales": "120", "avg_price": "80.00", "discount_rate": "10",
                  "refund_rate": "5", "ad_rate": "12", "commission_rate": "15"}
# FLOW-20：Amazon-US-01 浴室柜老品每月驱动 → 人民币收入 15 × 72.35 × 77.65 × 7.12 = 600,000.003（显示 ¥ 600,000.00）
V1_DRIVERS = {"spu_count": "15", "avg_sales": "72.35", "avg_price": "77.65"}
KINGDEE_HEADER = ["期间", "金蝶科目", "科目名称", "部门", "平台/店铺", "站点", "客户", "摘要", "发生额"]


def at(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=TZ)


class Ctx:
    """db：查询用会话；client：真实应用的 TestClient（同一 Cookie 罐，login 切换身份）。"""

    def __init__(self, db, client):
        self.db = db
        self.client = client
        client.app.state.import_session_factory = lambda: nullcontext(db)

    def now(self, text: str | None) -> None:
        clock.set_now(at(text) if text else None)

    def login(self, userid: str) -> None:
        r = self.client.post("/api/dev/login-as", json={"user_id": uid(self.db, userid)})
        assert r.status_code == 200, r.text

    def userid_of(self, user_id: int) -> str:
        return self.db.get(User, user_id).dingtalk_userid

    # ---- 表格 ----
    def grid(self, url: str, tab: str | None = None) -> dict:
        r = self.client.get(url, params={"tab": tab} if tab else None)
        assert r.status_code == 200, r.text
        return r.json()

    def save(self, base_url: str, changes: list[tuple[str, str, str]], tab: str | None = None):
        g = self.grid(f"{base_url}/grid", tab)
        body = [{"row_key": k, "field": f, "value": v,
                 "base": next((r["values"].get(f) for r in g["rows"] if r["key"] == k), None)}
                for k, f, v in changes]
        return self.client.patch(f"{base_url}/cells", json=body, params={"tab": tab} if tab else None)

    def save_ok(self, base_url: str, changes, tab: str | None = None) -> dict:
        r = self.save(base_url, changes, tab)
        assert r.status_code == 200 and r.json()["errors"] == [], r.text
        return r.json()["grid"]

    # ---- 编制任务 ----
    def publish(self, units: list[dict] | None = None, when: str = "2026-12-01 09:00") -> int:
        self.now(when)
        self.login("linxiao")
        r = self.client.post("/api/tasks", json={"year": 2027, "deadline": "2026-12-20",
                                                  "units": units if units is not None else minimal_units(self.db)})
        assert r.status_code == 201, r.text
        return r.json()["task"]["id"]

    def unit(self, task_id: int, name: str) -> int:
        return unit_by_name(self.db, task_id, name).id

    def preset_flow11_ratios(self, task_id: int) -> None:
        """FLOW-11 预置：采购 30%、头程 6%、尾程 8%、仓储 2%、关税 4%、库存索赔 1%、其他运营 3%（Amazon · 美国 · 浴室柜 2027-03）。"""
        amz = store(self.db, "Amazon-US-01")
        ccr = f"ccr:{amz.channel_id}:{amz.site_id}:{category_id(self.db, '浴室柜')}"
        csr = f"csr:{amz.channel_id}:{amz.site_id}"
        cost = f"/api/filling-units/{self.unit(task_id, '成本比例（财务BP）')}"
        self.login("chensiyu")
        self.save_ok(cost, [(f"{ccr}|purchase_cost_rate", MAR, "30")], tab="platform")
        self.save_ok(cost, [(f"{csr}|inventory_claim_rate", MAR, "1"), (f"{csr}|other_opex_rate", MAR, "3")],
                     tab="site")
        self.login("jiangfan")
        lg = f"/api/filling-units/{self.unit(task_id, '物流比例（物流物控）')}"
        self.save_ok(lg, [(f"{ccr}|first_leg_rate", MAR, "6"), (f"{ccr}|last_mile_rate", MAR, "8"),
                          (f"{ccr}|storage_rate", MAR, "2"), (f"{ccr}|tariff_rate", MAR, "4")], tab="platform")

    def preset_ferguson_ratios(self, task_id: int) -> None:
        """FLOW-12 预置：Ferguson 采购 55%、头程 5%、尾程 2%、仓储 1%、关税 7%（2027-03）。"""
        fer = customer(self.db, "Ferguson").id
        self.login("chensiyu")
        self.save_ok(f"/api/filling-units/{self.unit(task_id, '成本比例（财务BP）')}",
                     [(f"b2bc:{fer}|purchase_cost_rate", MAR, "55")], tab="b2b")
        self.login("jiangfan")
        self.save_ok(f"/api/filling-units/{self.unit(task_id, '物流比例（物流物控）')}",
                     [(f"b2bc:{fer}|first_leg_rate", MAR, "5"), (f"b2bc:{fer}|last_mile_rate", MAR, "2"),
                      (f"b2bc:{fer}|storage_rate", MAR, "1"), (f"b2bc:{fer}|tariff_rate", MAR, "7")], tab="b2b")

    def fill_flow11_drivers(self, task_id: int) -> None:
        self.login("wanghao")
        self.save_ok(f"/api/filling-units/{self.unit(task_id, 'Amazon-US-01')}",
                     [(pu_key(self.db, "Amazon-US-01", "浴室柜", True, k), MAR, v) for k, v in FLOW11_DRIVERS.items()])

    def fill_flow12_sales(self, task_id: int) -> None:
        fer = customer(self.db, "Ferguson").id
        self.login("sunting")
        self.save_ok(f"/api/filling-units/{self.unit(task_id, 'B端 · 美国业务部')}",
                     [(f"b2b:{fer}|sales_local", MAR, "200,000.00"), (f"b2b:{fer}|refund_rate", MAR, "2"),
                      (f"b2b:{fer}|promotion_rate", MAR, "3"), (f"b2b:{fer}|other_opex_rate", MAR, "1")])

    def fill_hr_300k(self, task_id: int) -> None:
        self.login("zhengke")
        self.save_ok(f"/api/filling-units/{self.unit(task_id, '人力资源部')}",
                     [(f"de:{account(self.db, '工资薪酬').id}|amount", MAR, "300000")])

    # ---- 年初原始目标 V1（完整编制 → 两级审核 → CEO 通过并锁定）----
    def build_v1(self) -> int:
        """V1：Amazon-US-01 浴室柜老品 1–12 月驱动 15 × 72.35 × 77.65 USD（每月 ¥ 600,000.00），其余单位各填 1 格。"""
        task_id = self.publish()
        amz_cells = [(pu_key(self.db, "Amazon-US-01", "浴室柜", False, k), f"2027-{m:02d}", v)
                     for m in range(1, 13) for k, v in V1_DRIVERS.items()]
        hr = account(self.db, "工资薪酬").id
        fer = customer(self.db, "Ferguson").id
        amz = store(self.db, "Amazon-US-01")
        ccr = f"ccr:{amz.channel_id}:{amz.site_id}:{category_id(self.db, '浴室柜')}"
        plan = {"Amazon-US-01": ("wanghao", "zhaolei", amz_cells),
                "B端 · 美国业务部": ("sunting", "hanliqun", [(f"b2b:{fer}|sales_local", MAR, "200000")]),
                "成本比例（财务BP）": ("chensiyu", "linxiao", [(f"{ccr}|purchase_cost_rate", MAR, "30")]),
                "物流比例（物流物控）": ("jiangfan", "hejianguo", [(f"{ccr}|first_leg_rate", MAR, "6")]),
                "人力资源部": ("zhengke", "wujing", [(f"de:{hr}|amount", MAR, "100000")])}
        for name, (filler, head, cells) in plan.items():
            unit_id = self.unit(task_id, name)
            tab = "platform" if name in ("成本比例（财务BP）", "物流比例（物流物控）") else None
            self.login(filler)
            self.save_ok(f"/api/filling-units/{unit_id}", cells, tab=tab)
            r = self.client.post(f"/api/filling-units/{unit_id}/submit")
            assert r.status_code == 200, r.text
            self.login(head)
            r = self.client.post(f"/api/approvals/unit/{unit_id}/approve")
            assert r.status_code == 200, r.text
        self.login("linxiao")
        assert self.client.post(f"/api/tasks/{task_id}/submit-to-ceo").status_code == 200
        self.now("2026-12-28 17:30")
        self.login("zhoumingyuan")
        r = self.client.post(f"/api/approvals/task/{task_id}/approve")
        assert r.status_code == 200 and r.json()["status"] == "completed", r.text
        return self.db.scalar(select(FillingUnit.version_id).where(FillingUnit.task_id == task_id).limit(1))

    # ---- 季度目标调整全流程（用于构造 V2 前置）----
    def run_adjustment(self, when: str, edits: dict[str, list[tuple[str, str, str]]], reason: str,
                       approve_at: str) -> dict:
        """在 when 发起调整；edits = {单位名: [(row_key, 月, 值)]}；所有单位提交 → 部门负责人 → 财务负责人 → CEO。"""
        self.now(when)
        self.login("linxiao")
        r = self.client.post("/api/versions/adjustments")
        assert r.status_code == 200, r.text
        adj_id = r.json()["id"]
        units = list(self.db.scalars(select(FillingUnit).where(FillingUnit.adjustment_id == adj_id)
                                     .order_by(FillingUnit.id)))
        for u in units:
            self.login(self.userid_of(u.filler_id))
            if u.name in edits:
                self.save_ok(f"/api/filling-units/{u.id}", edits[u.name])
            r = self.client.post(f"/api/filling-units/{u.id}/submit", json={"adjust_reason": reason})
            assert r.status_code == 200, r.text
        self.approve_adjustment_units(units)
        self.now(approve_at)
        self.login("zhoumingyuan")
        r = self.client.post(f"/api/approvals/adjustment/{adj_id}/approve")
        assert r.status_code == 200, r.text
        return r.json()

    def approve_adjustment_units(self, units, skip: tuple[int, ...] = ()) -> None:
        for level in ("dept", "finance"):
            for u in units:
                if u.id in skip:
                    continue
                self.db.refresh(u)
                who = self.userid_of(u.reviewer_id) if level == "dept" else "linxiao"
                self.login(who)
                r = self.client.post(f"/api/approvals/adjustment-unit/{u.id}/approve")
                assert r.status_code == 200, (u.name, level, r.text)

    # ---- 金蝶实际导入（陈思雨经导入接口上传并确认）----
    def import_kingdee(self, rows: list[list], file_name: str) -> dict:
        wb = Workbook()
        ws = wb.active
        ws.append(KINGDEE_HEADER)
        for r in rows:
            ws.append(r)
        buf = io.BytesIO()
        wb.save(buf)
        self.login("chensiyu")
        r = self.client.post("/api/imports", data={"source": "kingdee"},
                             files={"file": (file_name, buf.getvalue(), "application/vnd.ms-excel")})
        assert r.status_code == 200, r.text
        batch = self.client.get(f"/api/imports/{r.json()['id']}").json()
        assert batch["status"] == "passed", batch
        r = self.client.post(f"/api/imports/{batch['id']}/confirm", json={"overwrite": True})
        assert r.status_code == 200, r.text
        return r.json()


def kd(period: str, code: str, name: str, amount, *, dept: str = "", store_name: str = "", site: str = "") -> list:
    return [period, code, name, dept, store_name, site, "", "", float(D(str(amount)))]


def actual_rows_2027(months: list[int], amz_april: str = "554400") -> list[list]:
    rows = []
    for m in months:
        p = f"2027-{m:02d}"
        rev = amz_april if m == 4 else "580000"
        rows += [kd(p, "6001", "主营业务收入", rev, store_name="Amazon-US-01", site="美国"),
                 kd(p, "6401", "主营业务成本", "190000", store_name="Amazon-US-01", site="美国"),
                 kd(p, "6602.01", "管理费用-工资", "100000", dept="人力资源部")]
    return rows
