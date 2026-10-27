"""E3（FLOW-21~32）验收场景前置数据：只写契约「初始状态」，待验收动作由测试 / 浏览器经接口完成。

API 验收测试（pytest，事务回滚）与浏览器 E2E 播种（e3_env.py，提交到 budget_acc3）共用同一份前置数据。
期望值不在这里出现；只放契约写明的输入数。
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal as D

from app.models import BudgetTask, FillingUnit
from app.models.enums import UnitStatus, UnitType, VersionType
from tests.g4 import builders as B
from tests.g4.scenarios import flow25 as _flow25


def _monthly(total_rev, total_gross):
    return {m: (D(total_rev) / 12, D(total_gross) / 12) for m in range(1, 13)}


def flow21(g3):
    """V1 / V2：Wayfair-US-01 全年人民币收入 V1 10,000,000.00、V2 5,800,000.00，毛利 V1 2,000,000.00、
    V2 1,160,000.00；其他维度不变，部门费用两版相同。"""
    common = {"Amazon-US-01": _monthly(8000000, 1600000), "HomeDepot-US-01": _monthly(3000000, 600000)}
    v1 = g3.make_version(stores={**common, "Wayfair-US-01": _monthly(10000000, 2000000)},
                         depts={"人力资源部": 1200000})
    v2 = g3.make_version(vtype=VersionType.ADJUSTED_TARGET, version_no=2, quarter=1,
                         stores={**common, "Wayfair-US-01": _monthly(5800000, 1160000)},
                         depts={"人力资源部": 1200000}, approved_at="2027-03-15 10:00")
    return v1, v2


def flow25(db, **kw):
    return _flow25(db, **kw)


def flow26_category(db, with_may_kingdee: bool = True):
    """只有 Amazon-US-01：浴室柜 · 新品预算 SPU 10、销量 1,200（单 SPU 平均 120）、平均单价 80.00、折扣率 10%、
    预算汇率 7.12（种子）；BI 实际 SPU 9、销量 1,100、USD 77,000.00、当月平均汇率 7.2000。2027-05 只有金蝶。"""
    v = B.version(db, 2027, VersionType.ORIGINAL_TARGET, "V1 年初原始目标")
    B.platform_unit(db, v, "Amazon-US-01", "2027-04", "浴室柜", True, spu=10, avg_sales="120", avg_price="80.00",
                    discount="0.10")
    B.fx_actual(db, "2027-04", "USD", "7.2000")
    bi = B.batch(db, "bi", "2027-04", "BI_2027-04_销售明细.xlsx")
    B.bi_agg(db, bi, "2027-04", "Amazon-US-01", "浴室柜", True, spu=9, qty="1100", revenue_local="77000.00",
             revenue_cny="554400.00")
    if with_may_kingdee:
        kd = B.batch(db, "kingdee", "2027-05")
        B.kingdee(db, kd, "2027-05", "平台销售收入", "500000.00", store_name="Amazon-US-01")
    return v


def flow26_dept(db, v=None):
    """人力资源部培训费全年预算 1,200,000.00（每月 100,000.00）、2027-01～04 累计实际 500,000.00。"""
    v = v or B.version(db, 2027, VersionType.ORIGINAL_TARGET, "V1 年初原始目标")
    for m in range(1, 13):
        B.dept_expense(db, v, "人力资源部", "培训费", f"2027-{m:02d}", "100000.00")
    for m, amount in ((1, "100000.00"), (2, "120000.00"), (3, "130000.00"), (4, "150000.00")):
        kd = B.batch(db, "kingdee", f"2027-{m:02d}")
        B.kingdee(db, kd, f"2027-{m:02d}", "培训费", amount, dept_name="人力资源部")
    return v


# FLOW-27：每月 (人民币收入, 部门费用, 实际净利润)，采购成本 = 收入 − 部门费用 − 净利润
ACTUAL_2027 = {1: ("36200000.00", "1500000.00", "1010000.00"), 2: ("36200000.00", "1500000.00", "1010000.00"),
               3: ("30000000.00", "1350000.00", "1260000.00"), 4: ("9600000.00", "1450000.00", "320000.00")}
ACTUAL_2026 = {m: ("25000000.00", "1250000.00", "0.00") for m in range(1, 5)}


def _import_month(db, year, month, revenue, dept_exp, net_profit, source="kingdee"):
    ym = f"{year}-{month:02d}"
    b = B.batch(db, source, ym)
    purchase = D(revenue) - D(dept_exp) - D(net_profit)
    B.kingdee(db, b, ym, "平台销售收入", revenue, store_name="Amazon-US-01")
    B.kingdee(db, b, ym, "采购成本", str(purchase), store_name="Amazon-US-01")
    B.kingdee(db, b, ym, "工资薪酬", dept_exp, dept_name="人力资源部")


def flow27(db):
    """1–4 月实际净利润合计 3,600,000.00；原始目标同期 4,000,000.00；调整后目标同期 3,750,000.00；
    2027-01～04 部门费用 5,800,000.00、收入 112,000,000.00；2026-01～04 分别 5,000,000.00、100,000,000.00；
    2027-04 Q2 快照预测净利润 500,000.00 / 收入 10,000,000.00，实际 320,000.00 / 9,600,000.00；
    2027-03 Q1 快照预测净利润率 5.00%，实际 4.20%（1,260,000.00 ÷ 30,000,000.00）。"""
    orig = B.version(db, 2027, VersionType.ORIGINAL_TARGET, "V1 年初原始目标")
    adj = B.version(db, 2027, VersionType.ADJUSTED_TARGET, "V2 2027Q2 目标调整", version_no=2)
    for m in range(1, 5):
        B.raw_platform_unit(db, orig, "Amazon-US-01", f"2027-{m:02d}", revenue_cny="20000000.00",
                            gross_profit="1000000.00")
        B.raw_platform_unit(db, adj, "Amazon-US-01", f"2027-{m:02d}", revenue_cny="20000000.00",
                            gross_profit="750000.00" if m == 4 else "1000000.00")
    for m, vals in ACTUAL_2027.items():
        _import_month(db, 2027, m, *vals)
    for m, vals in ACTUAL_2026.items():
        _import_month(db, 2026, m, *vals, source="kingdee-history")
    q1 = B.version(db, 2027, VersionType.SNAPSHOT, "Q1 快照（以年初原始目标发布）", quarter=1,
                   published_on=date(2027, 1, 4))
    for m in (1, 2, 3):
        B.snapshot_month(db, q1, f"2027-{m:02d}", revenue="10000000.00", net_profit="500000.00")
    q2 = B.version(db, 2027, VersionType.SNAPSHOT, "2027Q2 滚动预测快照", version_no=2, quarter=2,
                   published_on=date(2027, 4, 10))
    for m in (4, 5, 6):
        B.snapshot_month(db, q2, f"2027-{m:02d}", revenue="10000000.00", net_profit="500000.00")
    return orig, adj


def flow27_2028(db):
    """另造一年度（2028）同期目标合计 −50,000.00；上年同期（2027-05）未导入。"""
    v = B.version(db, 2028, VersionType.ORIGINAL_TARGET, "V1 2028 年初原始目标")
    for m, gp in ((1, "-30000.00"), (2, "-20000.00"), (3, "0.00"), (4, "0.00"), (5, "0.00")):
        B.raw_platform_unit(db, v, "Amazon-US-01", f"2028-{m:02d}", revenue_cny="1000000.00", gross_profit=gp)
    for m in range(1, 6):
        _import_month(db, 2028, m, "1000000.00", "100000.00", "10000.00")
    return v


def flow28(db):
    """FLOW-25 场景 + 市场部展会费预算与实际（部门费用报告市场部展会费行）。"""
    versions = _flow25(db)
    target = versions["target"]
    for m in range(1, 13):
        B.dept_expense(db, target, "市场部", "展会费", f"2027-{m:02d}", "50000.00")
    kd = B.batch(db, "kingdee", "2027-03")
    B.kingdee(db, kd, "2027-03", "展会费", "40000.00", dept_name="市场部")
    B.kingdee(db, kd, "2027-03", "平台销售收入", "100000.00", store_name="Amazon-US-01")
    return versions


def flow32(db):
    """FLOW-25 场景 + 人力资源部培训费（部门费用报告）+ Amazon-US-01 平台填报单位（预算表）。"""
    versions = _flow25(db)
    target = versions["target"]
    for m in range(1, 13):
        B.dept_expense(db, target, "人力资源部", "培训费", f"2027-{m:02d}", "100000.00")
    kd = B.batch(db, "kingdee", "2027-01")
    B.kingdee(db, kd, "2027-01", "培训费", "123456.785", dept_name="人力资源部")
    task = BudgetTask(name="2027 年度预算编制", year=2027, deadline=date(2026, 12, 20), version_id=target.id)
    db.add(task)
    db.flush()
    us = B.store(db, "Amazon-US-01")
    unit = FillingUnit(task_id=task.id, version_id=target.id, unit_type=UnitType.PLATFORM, scope_object_id=us.id,
                       name="Amazon-US-01", filler_id=B.user_id(db, "wanghao"),
                       reviewer_id=B.user_id(db, "zhaolei"), status=UnitStatus.SUBMITTED)
    db.add(unit)
    db.flush()
    return versions, unit
