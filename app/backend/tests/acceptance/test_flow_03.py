"""FLOW-03 验收（API 层：角色 × 资源矩阵，真实路由 + 数据库）：期望值逐字取自 TDD验收契约 FLOW-03。

种子含 3 个部门、4 个店铺、3 个 B 端客户；吴静、郑可打开部门费用填报 → 只见人力资源部行（部门费用报告已于 2026-10-29 删除）；
王浩打开填报与渠道×站点偏差 → 只见 Amazon-US-01 行及其合计；孙婷打开 B 端填报与偏差报告 → 只见 Ferguson、Menards；
蒋帆打开物流比例填报并调用填报数据接口 → 只含维度列与头程费率、尾程费率、仓储费率、关税率四项，响应 JSON 无收入、销量、毛利字段键。
"""
import json
import re

from tests.acceptance.e1_helpers import People, flow03_setup

FORBIDDEN_KEY = re.compile(r"revenue|sales|gross|收入|销量|毛利|profit|qty", re.I)


def _keys(obj, out=None):
    out = set() if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(k)
            _keys(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _keys(v, out)
    return out


def _mine(c):
    r = c.get("/api/filling-units", params={"mine": 1})
    assert r.status_code == 200, r.text
    return r.json()["items"]


def test_flow_03_department_roles(seeded, dingtalk, tmp_path):
    db = seeded
    p = People(db, dingtalk, tmp_path)
    flow03_setup(db, p)
    for who in ("wujing", "zhengke"):
        c = p(who)
        r = c.get("/api/dept-expense/my-unit")
        assert r.status_code == 200, r.text
        unit_id = r.json()["unit_id"]
        g = c.get(f"/api/dept-expense/{unit_id}/grid")
        assert g.status_code == 200, g.text
        assert "人力资源部" in json.dumps(g.json(), ensure_ascii=False)
        for other in ("财务部", "市场部"):
            assert other not in json.dumps(g.json()["rows"], ensure_ascii=False), (who, other)
        assert c.get("/api/reports/dept-expense", params={"year": 2027}).status_code == 404


def test_flow_03_operations(seeded, dingtalk, tmp_path):
    db = seeded
    p = People(db, dingtalk, tmp_path)
    flow03_setup(db, p)
    wang = p("wanghao")
    mine = _mine(wang)
    assert [u["name"] for u in mine] == ["Amazon-US-01"]
    g = wang.get(f"/api/filling-units/{mine[0]['id']}/grid").json()
    assert {r["values"].get("store") for r in g["rows"] if r["values"].get("store")} <= {"Amazon-US-01"}
    for other in ("Amazon-CA-01", "Wayfair-US-01", "Lowes-US-01"):
        assert other not in json.dumps(g, ensure_ascii=False)
    d = wang.get("/api/reports/channel-site", params={"month": "2027-04"}).json()
    assert [r["name"] for r in d["rows"]] == ["Amazon-US-01"]
    assert d["b2b_rows"] == [] and d["unassigned"] is None
    assert d["total"]["label"] == "合计（当前范围）"
    assert d["total"]["revenue"] == d["rows"][0]["revenue"]


def test_flow_03_b2b(seeded, dingtalk, tmp_path):
    db = seeded
    p = People(db, dingtalk, tmp_path)
    flow03_setup(db, p)
    sun = p("sunting")
    mine = _mine(sun)
    assert [u["name"] for u in mine] == ["B端 · 美国业务部"]
    g = sun.get(f"/api/filling-units/{mine[0]['id']}/grid").json()
    customers = {r["values"]["customer"] for r in g["rows"] if r.get("kind") != "total" and r["values"].get("customer")}
    assert sorted(customers) == ["Ferguson", "Menards"], customers
    assert "Bauhaus" not in json.dumps(g, ensure_ascii=False)
    d = sun.get("/api/reports/channel-site", params={"month": "2027-04"}).json()
    assert sorted(r["name"] for r in d["b2b_rows"]) == ["Ferguson", "Menards"]
    assert d["rows"] == [] and "Bauhaus" not in json.dumps(d, ensure_ascii=False)


def test_flow_03_logistics(seeded, dingtalk, tmp_path):
    db = seeded
    p = People(db, dingtalk, tmp_path)
    flow03_setup(db, p)
    jf = p("jiangfan")
    mine = _mine(jf)
    assert [u["unit_type"] for u in mine] == ["logistics_ratio"]
    for tab in (None, "b2b"):
        r = jf.get(f"/api/filling-units/{mine[0]['id']}/grid", params={"tab": tab} if tab else None)
        assert r.status_code == 200, r.text
        g = r.json()
        bad = sorted(k for k in _keys(g) if FORBIDDEN_KEY.search(k))
        assert bad == [], bad
        items = {r_["values"].get("item") for r_ in g["rows"]}
        assert items == {"头程费率", "尾程费率", "仓储费率", "关税率"}, items
        dims = [c["key"] for c in g["columns"] if c["kind"] == "dim"]
        assert all(not FORBIDDEN_KEY.search(k) for k in dims)
        editable = {c["key"] for c in g["columns"] if c.get("editable")}
        assert editable and all(re.fullmatch(r"\d{4}-\d{2}", k) for k in editable)
