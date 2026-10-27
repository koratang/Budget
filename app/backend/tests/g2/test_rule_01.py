"""RULE-01：金额精度（AC-F06-09、DEC-005）。

契约期望：明细显示 0.33、0.33、0.33，合计显示 1.00，差额 0.01 ≤ 0.01 × 3；1.005 显示 1.01（四舍五入，不是银行家舍入的
1.00）；接口金额以字符串返回、数据库列为 NUMERIC，后端代码与依赖中金额路径无 float；伪造字段被忽略，派生值按服务端公式
重算；页面、接口、导出三处同值
"""
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select, text, update

from app.core.money import fmt_amount
from app.models import PlatformUnit
from tests.g2.helpers import category_id, grid, login, minimal_units, publish, pu_key, row, save, store, unit_by_name
from tests.g2.test_flow_11 import fill_flow11_drivers, preset_ratios

BACKEND = Path(__file__).resolve().parents[2]
G2_FILES = ["app/services/tasking.py", "app/services/filling.py", "app/services/dept_expense.py",
            "app/services/approval_units.py", "app/api/tasks.py", "app/api/filling.py", "app/api/dept_expense.py",
            "app/api/approvals.py"]


def test_rule_01_rounding_display():
    parts = [Decimal("0.334")] * 3
    assert [fmt_amount(p) for p in parts] == ["0.33", "0.33", "0.33"]
    total = sum(parts, Decimal(0))
    assert fmt_amount(total) == "1.00"
    diff = abs(Decimal(fmt_amount(total)) - sum(Decimal(fmt_amount(p)) for p in parts))
    assert diff == Decimal("0.01") and diff <= Decimal("0.01") * 3
    assert fmt_amount(Decimal("1.005")) == "1.01"


def test_rule_01_grid_total_from_unrounded_details(seeded, client):
    db = seeded
    task_id = publish(client, db, minimal_units(db)).json()["task"]["id"]
    unit_id = unit_by_name(db, task_id, "Amazon-US-01").id
    s = store(db, "Amazon-US-01")
    for cat in ("框镜", "灯镜", "镜柜"):
        db.execute(update(PlatformUnit).where(PlatformUnit.store_id == s.id, PlatformUnit.month == date(2027, 1, 1),
                                              PlatformUnit.category_id == category_id(db, cat),
                                              PlatformUnit.is_new.is_(True)).values(revenue_cny=Decimal("0.334")))
    login(client, db, "wanghao")
    g = grid(client, unit_id)
    details = [row(g, pu_key(db, "Amazon-US-01", c, True, "revenue_cny"))["values"]["2027-01"]
               for c in ("框镜", "灯镜", "镜柜")]
    assert details == ["0.33", "0.33", "0.33"]
    assert row(g, "total|revenue_cny")["values"]["2027-01"] == "1.00"


def test_rule_01_strings_numeric_and_forged_fields(seeded, client):
    db = seeded
    task_id = publish(client, db, minimal_units(db)).json()["task"]["id"]
    unit_id = unit_by_name(db, task_id, "Amazon-US-01").id
    preset_ratios(client, db, task_id)
    g = fill_flow11_drivers(client, db, unit_id)
    for r in g["rows"]:
        assert all(v is None or isinstance(v, str) for v in r["values"].values())
    assert all(isinstance(v, str) for v in g["kpis"].values())
    # 数据库金额列为 NUMERIC
    types = dict(db.execute(text("SELECT column_name, data_type FROM information_schema.columns "
                                 "WHERE table_name = 'platform_unit'")).all())
    for col in ("revenue_local", "revenue_cny", "gross_profit", "avg_price", "discount_rate"):
        assert types[col] == "numeric", col
    # 伪造「收入」「毛利」字段被忽略，派生值按服务端公式重算
    key = lambda item: pu_key(db, "Amazon-US-01", "浴室柜", True, item)  # noqa: E731
    r = save(client, unit_id, [(key("revenue_cny"), "2027-03", "999999999"),
                               (key("gross_profit"), "2027-03", "888888888"), (key("spu_count"), "2027-03", "20")], g)
    assert r.status_code == 200, r.text
    assert {i["row_key"] for i in r.json()["ignored"]} == {key("revenue_cny"), key("gross_profit")}
    u = db.scalar(select(PlatformUnit).where(PlatformUnit.store_id == store(db, "Amazon-US-01").id,
                                             PlatformUnit.category_id == category_id(db, "浴室柜"),
                                             PlatformUnit.is_new.is_(True), PlatformUnit.month == date(2027, 3, 1)))
    db.refresh(u)
    assert fmt_amount(u.revenue_cny) == "1,230,336.00"  # 20 × 120 × 80 × 0.9 × 7.12
    assert fmt_amount(u.gross_profit) == "196,853.76"
    assert row(r.json()["grid"], key("revenue_cny"))["values"]["2027-03"] == fmt_amount(u.revenue_cny)


def test_rule_01_no_float_in_g2_money_path():
    for rel in G2_FILES:
        src = (BACKEND / rel).read_text(encoding="utf-8")
        assert not re.search(r"\bfloat\s*\(", src), rel
        assert not re.search(r":\s*float\b|->\s*float\b", src), rel
