"""G3 场景测试共用：按姓名登录的客户端、服务层操作人、版本与预算数据构造、导入上传助手。

预置数据只写前置条件（版本、预算数、已有导入），待验收动作在各测试中经接口完成。
"""
from __future__ import annotations

from contextlib import nullcontext
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from app.calc.periods import year_months
from app.core.clock import TZ, clock
from app.models import (BudgetAccount, BudgetVersion, Category, Department, DeptExpense, ImportBatch, PlatformUnit,
                        Rule, RuleVersion, Sku, Spu, Store, User)
from app.models.enums import ImportSource, ImportStatus, VersionType
from app.services import rules as rules_svc
from app.services.versions import as_actor
from tests.conftest import build_client
from tests.g3.fixtures_g3 import SKUS

D = Decimal


def at(text: str) -> datetime:
    """'2027-05-12 10:00' → 上海时区时间。"""
    return datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=TZ)


@pytest.fixture
def g3(seeded, dingtalk, tmp_path):
    return G3(seeded, dingtalk, tmp_path)


class G3:
    def __init__(self, db, dingtalk, tmp_path: Path):
        self.db = db
        self.dingtalk = dingtalk
        self.tmp = tmp_path
        self._clients = {}

    def set_now(self, text: str) -> None:
        """推进可控时钟；会话 8 小时无操作失效，时钟跳跃后重新登录。"""
        clock.set_now(at(text))
        self._clients.clear()

    # ---- 人员与登录 ----
    def user(self, name: str) -> User:
        return self.db.scalar(select(User).where(User.name == name))

    def actor(self, name: str):
        return as_actor(self.db, self.user(name))

    def client(self, name: str):
        if name not in self._clients:
            c = build_client(self.db, self.dingtalk, DATA_DIR=str(self.tmp / "data"))
            c.app.state.import_session_factory = lambda: nullcontext(self.db)
            r = c.post("/api/dev/login-as", json={"user_id": self.user(name).id})
            assert r.status_code == 200, r.text
            self._clients[name] = c
        return self._clients[name]

    # ---- 主数据 ----
    def store(self, name: str) -> Store:
        return self.db.scalar(select(Store).where(Store.name == name))

    def dept(self, name: str) -> Department:
        return self.db.scalar(select(Department).where(Department.name == name))

    def category(self, name: str) -> Category:
        return self.db.scalar(select(Category).where(Category.name == name))

    def account(self, name: str) -> BudgetAccount:
        return self.db.scalar(select(BudgetAccount).where(BudgetAccount.name == name))

    def add_skus(self, extra: list[tuple[str, str, str, str]] = ()) -> None:
        for code, spu_code, cat, listed in [*SKUS, *extra]:
            spu = self.db.scalar(select(Spu).where(Spu.code == spu_code))
            listed_on = date.fromisoformat(listed)
            if spu is None:
                spu = Spu(code=spu_code, category_id=self.category(cat).id, first_listed_on=listed_on)
                self.db.add(spu)
                self.db.flush()
            spu.first_listed_on = min(spu.first_listed_on, listed_on)
            self.db.add(Sku(code=code, spu_id=spu.id, listed_on=listed_on))
        self.db.flush()

    def mark_new_channel(self, store_name: str, start: str) -> None:
        s = self.store(store_name)
        s.is_new_channel = True
        s.new_channel_start = date.fromisoformat(start + "-01")
        self.db.flush()

    # ---- 版本 ----
    def make_version(self, *, vtype: str = VersionType.ORIGINAL_TARGET, version_no: int = 1, year: int = 2027,
                     quarter: int | None = None, stores: dict | None = None, depts: dict | None = None,
                     approver: str = "周明远", approved_at: str = "2026-12-28 17:30", reason: str | None = None,
                     locked: bool = True) -> BudgetVersion:
        """建版本并写入预算数据：stores = {店铺: {月份(int): (人民币收入, 毛利)}}（品类浴室柜、老品）；
        depts = {部门: 全年预算}（按 12 个月平均写入「工资薪酬」科目）。写完数据后再锁定。"""
        v = BudgetVersion(year=year, type=vtype, version_no=version_no, quarter=quarter,
                          name=f"{year} {VersionType.LABELS[vtype]} V{version_no}", adjust_reason=reason,
                          approved_by=self.user(approver).id, approved_at=at(approved_at), locked=False)
        self.db.add(v)
        self.db.flush()
        cat = self.category("浴室柜")
        for store_name, months in (stores or {}).items():
            s = self.store(store_name)
            for m, (rev, gross) in months.items():
                self.db.add(PlatformUnit(version_id=v.id, month=date(year, m, 1), channel_id=s.channel_id,
                                         store_id=s.id, site_id=s.site_id, category_id=cat.id, is_new=False,
                                         revenue_cny=D(rev), gross_profit=D(gross)))
        acct = self.account("工资薪酬")
        for dept_name, annual in (depts or {}).items():
            d = self.dept(dept_name)
            for m in year_months(year):
                self.db.add(DeptExpense(version_id=v.id, month=m, department_id=d.id, account_id=acct.id,
                                        amount=D(annual) / 12))
        self.db.flush()
        v.locked = locked
        self.db.flush()
        return v

    def fake_kingdee_months(self, months: list[str], user: str = "陈思雨") -> None:
        """只建「已生效」的金蝶逻辑批次（不含行），表示这些期间已导入金蝶实际。"""
        uid = self.user(user).id
        parent = ImportBatch(source=ImportSource.KINGDEE, file_name="金蝶_前期导入.xlsx",
                             status=ImportStatus.EFFECTIVE, uploaded_by=uid, confirmed_by=uid,
                             confirmed_at=clock.now())
        self.db.add(parent)
        self.db.flush()
        for m in months:
            self.db.add(ImportBatch(source=ImportSource.KINGDEE, period=date.fromisoformat(m + "-01"),
                                    parent_batch_id=parent.id, file_name=parent.file_name,
                                    status=ImportStatus.EFFECTIVE, uploaded_by=uid, confirmed_by=uid,
                                    confirmed_at=clock.now()))
        self.db.flush()

    # ---- 导入 ----
    def upload(self, path: Path, source: str, user: str = "陈思雨") -> dict:
        c = self.client(user)
        with open(path, "rb") as f:
            r = c.post("/api/imports", files={"file": (path.name, f.read(), "application/vnd.ms-excel")},
                       data={"source": source})
        assert r.status_code == 200, r.text
        r2 = c.get(f"/api/imports/{r.json()['id']}")
        assert r2.status_code == 200, r2.text
        return r2.json()

    def confirm(self, batch_id: int, overwrite: bool = False, user: str = "陈思雨"):
        return self.client(user).post(f"/api/imports/{batch_id}/confirm", json={"overwrite": overwrite})

    def import_file(self, path: Path, source: str, overwrite: bool = False) -> dict:
        batch = self.upload(path, source)
        assert batch["status"] == "passed", batch
        r = self.confirm(batch["id"], overwrite=overwrite)
        assert r.status_code == 200, r.text
        return r.json()

    # ---- 规则 ----
    def preset(self, name: str) -> tuple[Rule, RuleVersion]:
        rule = self.db.scalar(select(Rule).where(Rule.name == name))
        rv = self.db.scalar(select(RuleVersion).where(RuleVersion.rule_id == rule.id)
                            .order_by(RuleVersion.version_no.desc()))
        return rule, rv

    def approve_rule_version(self, rv_id: int, by: str = "林晓") -> dict:
        return rules_svc.approve(self.db, self.actor(by), rv_id)
