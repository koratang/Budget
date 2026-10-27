"""RULE-08：计算刷新性能（NFR-001、DEC-006）。

契约期望：100 次采样的 P95 ≤ 3 秒，且每次合计值与独立按公式重算结果一致
本测试在预置 20,000 个以上预算单元的测试库中，对平台渠道填报连续保存 100 次驱动值，记录「请求发出 → 返回重算后的
表格与受影响合计」耗时（服务端增量重算 + SQL 合计 + 表格序列化）；浏览器渲染耗时另在 E2E 中抽样。
"""
import statistics
import time
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, insert, select

from app.calc.periods import year_months
from app.core.money import fmt_amount
from app.models import Category, FillingUnit, PlatformUnit, Store
from tests.g2.helpers import grid, login, minimal_units, publish, pu_key, row, save, store, unit_by_name

FX = Decimal("7.12")


def _add_bulk_units(db, version_id: int, target: int = 20000) -> int:
    base = store(db, "Amazon-US-01")
    cats = list(db.scalars(select(Category.id)))
    months = year_months(2027)
    existing = db.scalar(select(func.count()).select_from(PlatformUnit).where(PlatformUnit.version_id == version_id))
    per_store = len(cats) * len(months) * 2
    n = 0
    while existing + n * per_store < target:
        s = Store(name=f"压测店铺-{n + 1:03d}", channel_id=base.channel_id, site_id=base.site_id, currency="USD")
        db.add(s)
        db.flush()
        db.execute(insert(PlatformUnit), [dict(version_id=version_id, month=m, channel_id=s.channel_id, store_id=s.id,
                                                site_id=s.site_id, category_id=c, is_new=nw, spu_count=3,
                                                avg_sales=Decimal("40"), avg_price=Decimal("59.99"))
                                           for m in months for c in cats for nw in (True, False)])
        n += 1
    db.flush()
    return db.scalar(select(func.count()).select_from(PlatformUnit).where(PlatformUnit.version_id == version_id))


def _expected_month_revenue(db, store_id: int, month) -> str:
    total = Decimal(0)
    for u in db.scalars(select(PlatformUnit).where(PlatformUnit.store_id == store_id, PlatformUnit.month == month)
                        .execution_options(populate_existing=True)):
        total += Decimal(u.spu_count) * u.avg_sales * u.avg_price * (1 - u.discount_rate) * FX
    return fmt_amount(total)


def test_rule_08_save_refresh_p95(seeded, client):
    db = seeded
    task_id = publish(client, db, minimal_units(db)).json()["task"]["id"]
    unit = unit_by_name(db, task_id, "Amazon-US-01")
    count = _add_bulk_units(db, unit.version_id)
    assert count >= 20000
    s = store(db, "Amazon-US-01")
    cats = ["框镜", "灯镜", "镜柜", "浴室门", "浴室柜"]
    months = year_months(2027)
    login(client, db, "wanghao")
    g = grid(client, unit.id)
    durations = []
    for i in range(100):
        cat, is_new, month = cats[i % 5], (i // 5) % 2 == 0, months[i % 12]
        field = f"{month:%Y-%m}"
        value = str((Decimal(10 + i) * Decimal("1.5")).quantize(Decimal("0.1"), ROUND_HALF_UP))
        changes = [(pu_key(db, "Amazon-US-01", cat, is_new, "spu_count"), field, str(5 + i % 7)),
                   (pu_key(db, "Amazon-US-01", cat, is_new, "avg_sales"), field, value),
                   (pu_key(db, "Amazon-US-01", cat, is_new, "avg_price"), field, "79.99")]
        t0 = time.perf_counter()
        r = save(client, unit.id, changes, g)
        durations.append(time.perf_counter() - t0)
        assert r.status_code == 200 and r.json()["errors"] == [], r.text
        g = r.json()["grid"]
        assert row(g, "total|revenue_cny")["values"][field] == _expected_month_revenue(db, s.id, month)
    durations.sort()
    p50 = statistics.median(durations)
    p95 = durations[int(len(durations) * 0.95) - 1]
    print(f"\nRULE-08 实测：预算单元 {count} 个，保存 100 次，P50 {p50 * 1000:.0f} ms，"
          f"P95 {p95 * 1000:.0f} ms，最大 {durations[-1] * 1000:.0f} ms")
    assert p95 <= 3.0
    assert db.scalar(select(func.count()).select_from(FillingUnit).where(FillingUnit.task_id == task_id)) == 5
