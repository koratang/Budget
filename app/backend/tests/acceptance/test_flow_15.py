"""FLOW-15 提交后锁定与单元格级乐观锁（API 层验收）。期望值逐字取自 TDD验收契约.md FLOW-15：
提交后单位状态「已提交」，「我的填报」入口变为「查看」；任何人写入被拒并提示「已提交，退回后才能修改」，数值不变；
冲突场景王浩保存被拒并提示「该数据已被 刘畅 于 2026-12-18 10:05 修改，请刷新后再改」，单元值保持 130
"""
from decimal import Decimal

from app.models.enums import Role
from tests.acceptance.e2_common import MAR, Ctx
from tests.g2.helpers import add_user, pu_key, store


def _val(ctx, url, key):
    return next(r for r in ctx.grid(f"{url}/grid")["rows"] if r["key"] == key)["values"][MAR]


def test_flow_15_submit_locks(seeded, client):
    db = seeded
    ctx = Ctx(db, client)
    task = ctx.publish()
    unit_id = ctx.unit(task, "Amazon-US-01")
    url = f"/api/filling-units/{unit_id}"
    key = pu_key(db, "Amazon-US-01", "浴室柜", True, "spu_count")
    ctx.login("wanghao")
    ctx.save_ok(url, [(key, MAR, "10")])
    r = client.post(f"{url}/submit")
    assert r.status_code == 200 and r.json()["status_label"] == "已提交"
    item = next(u for u in client.get("/api/filling-units?mine=1").json()["items"] if u["id"] == unit_id)
    assert item["status_label"] == "已提交" and item["editable"] is False  # 入口为「查看 · 已锁定」
    for who in ("wanghao", "chensiyu"):
        ctx.login(who)
        r = ctx.save(url, [(key, MAR, "99")])
        assert r.status_code == 409 and r.json()["message"] == "已提交，退回后才能修改", (who, r.text)
        assert _val(ctx, url, key) == "10"


def test_flow_15_concurrent_conflict(seeded, client):
    db = seeded
    ctx = Ctx(db, client)
    add_user(db, "liuchang", "刘畅", "运营部", [Role.OPERATIONS], {"store": [store(db, "Amazon-US-01").id]})
    task = ctx.publish()
    url = f"/api/filling-units/{ctx.unit(task, 'Amazon-US-01')}"
    key = pu_key(db, "Amazon-US-01", "浴室柜", True, "avg_sales")
    ctx.now("2026-12-18 10:00")
    ctx.login("wanghao")
    base_wang = next(r for r in ctx.grid(f"{url}/grid")["rows"] if r["key"] == key)["values"][MAR]
    ctx.now("2026-12-18 10:05")
    ctx.login("liuchang")
    ctx.save_ok(url, [(key, MAR, "130")])
    ctx.now("2026-12-18 10:07")
    ctx.login("wanghao")
    r = client.patch(f"{url}/cells", json=[{"row_key": key, "field": MAR, "value": "125", "base": base_wang}])
    errs = r.json()["errors"]
    assert r.status_code == 200 and len(errs) == 1 and errs[0]["code"] == "conflict"
    assert errs[0]["message"] == "该数据已被 刘畅 于 2026-12-18 10:05 修改，请刷新后再改"
    assert Decimal(_val(ctx, url, key).replace(",", "")) == Decimal("130")
