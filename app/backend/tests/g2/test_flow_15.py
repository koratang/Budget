"""FLOW-15：提交后锁定与单元格级乐观锁（AC-F04-09、AC-F04-10、DEC-007）。

契约期望：提交后单位状态「已提交」，「我的填报」入口变为「查看」；任何人写入被拒并提示「已提交，退回后才能修改」，
数值不变；冲突场景王浩保存被拒并提示「该数据已被 刘畅 于 2026-12-18 10:05 修改，请刷新后再改」，单元值保持 130
"""
from datetime import datetime

from app.core.clock import TZ, clock
from app.models.enums import Role
from tests.g2.helpers import (add_user, grid, login, minimal_units, publish, pu_key, row, save, store, submit,
                              unit_by_name)

MAR = "2027-03"


def test_flow_15_submitted_unit_is_locked(seeded, client):
    db = seeded
    task_id = publish(client, db, minimal_units(db)).json()["task"]["id"]
    unit_id = unit_by_name(db, task_id, "Amazon-US-01").id
    key = pu_key(db, "Amazon-US-01", "浴室柜", True, "spu_count")
    login(client, db, "wanghao")
    assert save(client, unit_id, [(key, MAR, "10")]).json()["errors"] == []
    r = submit(client, unit_id)
    assert r.status_code == 200 and r.json()["status"] == "submitted" and r.json()["status_label"] == "已提交"
    mine = client.get("/api/filling-units?mine=1").json()["items"]
    item = next(m for m in mine if m["id"] == unit_id)
    assert item["editable"] is False and item["locked"] is True  # 入口为「查看 · 已锁定」

    for who in ("wanghao", "chensiyu"):
        login(client, db, who)
        g = grid(client, unit_id)
        r = save(client, unit_id, [(key, MAR, "99")], g)
        assert r.status_code == 409, (who, r.text)
        assert r.json()["message"] == "已提交，退回后才能修改"
        assert row(grid(client, unit_id), key)["values"][MAR] == "10"


def test_flow_15_concurrent_save_conflict(seeded, client):
    db = seeded
    s = store(db, "Amazon-US-01")
    add_user(db, "liuchang", "刘畅", "运营部", [Role.OPERATIONS], {"store": [s.id]})
    task_id = publish(client, db, minimal_units(db)).json()["task"]["id"]
    unit_id = unit_by_name(db, task_id, "Amazon-US-01").id
    key = pu_key(db, "Amazon-US-01", "浴室柜", True, "avg_sales")

    # 两人同时打开 Amazon-US-01
    login(client, db, "wanghao")
    g_wang = grid(client, unit_id)
    login(client, db, "liuchang")
    g_liu = grid(client, unit_id)

    clock.set_now(datetime(2026, 12, 18, 10, 5, tzinfo=TZ))
    login(client, db, "liuchang")
    r = save(client, unit_id, [(key, MAR, "130")], g_liu)
    assert r.status_code == 200 and r.json()["errors"] == [], r.text

    clock.set_now(datetime(2026, 12, 18, 10, 7, tzinfo=TZ))
    login(client, db, "wanghao")
    r = save(client, unit_id, [(key, MAR, "125")], g_wang)
    assert r.status_code == 200
    errs = r.json()["errors"]
    assert len(errs) == 1 and errs[0]["code"] == "conflict"
    assert errs[0]["message"] == "该数据已被 刘畅 于 2026-12-18 10:05 修改，请刷新后再改"
    assert row(grid(client, unit_id), key)["values"][MAR] == "130.0"
