"""试用版演示数据脚本 scripts.seed_demo（无经营历史表路径）：补齐 2026 基础数据、2027 预算闭环、2027 年 1–3 月实际；
再次运行不重复写入。用林晓、王浩、周明远调用报表与工作台接口核对各页面都有数。"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.models import (Alert, AuditLog, BudgetTask, BudgetVersion, FillingUnit, FxActual, ImportBatch, KingdeeActual,
                        PlatformUnit, Sku, Store, User)
from app.models.enums import ImportStatus, TaskStatus, UnitStatus, VersionType
from scripts import seed_demo
from scripts.seed_data import NEW_CHANNEL_STORE
from tests.conftest import build_client, make_settings


@pytest.fixture
def demo(seeded, dingtalk, tmp_path):
    db = seeded
    result = seed_demo.run(db, make_settings(DATA_DIR=str(tmp_path / "data")), data_dir=tmp_path / "data")
    return db, dingtalk, result, tmp_path


def login(db, dingtalk, name: str):
    c = build_client(db, dingtalk)
    uid = db.scalar(select(User.id).where(User.name == name))
    r = c.post("/api/dev/login-as", json={"user_id": uid})
    assert r.status_code == 200, r.text
    return c


def get(c, url: str) -> dict:
    r = c.get(url)
    assert r.status_code == 200, (url, r.text[:300])
    return r.json()


def counts(db) -> dict:
    return {m.__name__: db.scalar(select(func.count()).select_from(m))
            for m in (BudgetTask, BudgetVersion, PlatformUnit, KingdeeActual, ImportBatch, Alert, Sku, FxActual)}


def test_budget_closed_loop_and_idempotent(demo):
    db, _dt, result, tmp_path = demo
    assert result is not None
    # 2027 年度编制任务已完成，全部单位已通过，版本锁定为年初原始目标
    task = db.scalar(select(BudgetTask).where(BudgetTask.year == 2027))
    assert task.status == TaskStatus.COMPLETED
    units = db.scalars(select(FillingUnit).where(FillingUnit.task_id == task.id)).all()
    assert len(units) >= 15 and all(u.status == UnitStatus.APPROVED for u in units)
    v1 = db.get(BudgetVersion, task.version_id)
    assert (v1.type, v1.locked, v1.name) == (VersionType.ORIGINAL_TARGET, True, "2027 年初原始目标")
    assert db.scalar(select(func.count()).select_from(BudgetVersion).where(
        BudgetVersion.year == 2027, BudgetVersion.type == VersionType.SNAPSHOT, BudgetVersion.quarter == 1)) == 1
    # 走的是真实流程：提交、退回、审核、锁定都有审计
    actions = set(db.scalars(select(AuditLog.action)))
    assert {"task.publish", "cells.edit", "unit.submit", "unit.reject", "unit.approve", "task.submit_to_ceo",
            "version.lock_original_target", "import_confirmed", "alert_created", seed_demo.MARK_ACTION} <= actions
    # 2027 年 1–3 月金蝶与 BI 实际已生效；2026 年 1–9 月模拟实际
    periods = set(db.scalars(select(ImportBatch.period).where(ImportBatch.status == ImportStatus.EFFECTIVE,
                                                              ImportBatch.period.is_not(None))))
    assert {m.isoformat()[:7] for m in periods} >= {f"2026-{m:02d}" for m in range(1, 10)} | {"2027-01", "2027-02",
                                                                                               "2027-03"}
    budget = Decimal(result["budget_revenue"])
    assert budget > Decimal("100000000")
    for q in result["q1"]:
        assert Decimal("90") <= Decimal(q["achievement"].rstrip("%")) <= Decimal("110")
    assert result["alerts"] >= 3
    # 1–3 月累计净利润达成率在 90%～105%：模拟了 2027 实际的费用对象都有对应预算（同口径）
    assert Decimal("90") <= Decimal(result["q1_net_achievement"].rstrip("%")) <= Decimal("105")

    # 幂等：再次运行直接跳过，不新增任何数据
    before = counts(db)
    assert seed_demo.run(db, make_settings(DATA_DIR=str(tmp_path / "data")), data_dir=tmp_path / "data") is None
    assert counts(db) == before


def test_pages_have_data(demo):
    db, dingtalk, _result, _tmp = demo
    tiktok = db.scalar(select(Store).where(Store.name == NEW_CHANNEL_STORE[0]))
    for name in ("林晓", "王浩", "周明远"):
        c = login(db, dingtalk, name)
        wb = get(c, "/api/workbench")
        assert wb["kingdee_latest"] == "2027-03"
        versions = get(c, "/api/versions?year=2027")["versions"]
        assert any(v["type"] == "original_target" and "已锁定" in v["status_label"] for v in versions)
        for m in ("2027-01", "2027-02", "2027-03"):
            cs = get(c, f"/api/reports/channel-site?month={m}")
            assert not cs["empty"] and cs["prior_available"] and cs["rows"]
            assert any(r["revenue"]["actual"] and Decimal(r["revenue"]["actual"]) > 0 for r in cs["rows"])
            assert any(r.get("yoy", {}).get("revenue", {}).get("growth") for r in cs["rows"])
        cat = get(c, "/api/reports/category?month=2027-03")
        assert not cat["empty"]
        kinds = {(r["kind"], Decimal(r["revenue"]["actual"]) > 0) for g in cat["groups"] for r in g["rows"]}
        assert ("新品", True) in kinds and ("老品", True) in kinds
        alerts = get(c, "/api/alerts")
        assert alerts["total"] >= 1
        if name == "王浩":
            continue
        tasks = get(c, "/api/tasks")
        assert any(t["year"] == 2027 and t["status"] == TaskStatus.COMPLETED for t in tasks["items"])
        rec = get(c, "/api/reconciliation?month=2027-03")
        assert rec["kpis"]["combos"] >= 5 and 1 <= rec["kpis"]["over"] < rec["kpis"]["combos"]
        rates = [abs(Decimal(r["diff_rate"])) for r in rec["rows"] if r["diff_rate"] is not None]
        assert all(r > 0 for r in rates) and sorted(rates)[len(rates) // 2] < 3
        assert {(a["rule_name"], a["object_name"]) for a in alerts["items"]} >= {
            ("新渠道连续 2 个月收入达成率低于 70%", tiktok.name)}
        assert any(a["rule_name"].startswith("部门费用额度使用率") for a in alerts["items"])
        company = get(c, "/api/reports/company?year=2027")
        assert company["growth"]["available"]
        assert Decimal(company["growth"]["dept_expense"]["current"]) > 0
        assert Decimal("90") <= Decimal(company["achievement"]["original"]["rate"]) <= Decimal("105")
    c = login(db, dingtalk, "林晓")
    sku = get(c, "/api/master/sku-mapping?month=2027-03")
    assert sku["summary"]["sku_count"] > 50 and sku["new_spu_count"] > 0
    fx = get(c, "/api/master/fx/actual?year=2027")
    assert all(r["rates"]["USD"] for r in fx["rows"][:3])
