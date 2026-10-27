"""FLOW-04 验收（API 层，真实路由 + 数据库）：期望值逐字取自 TDD验收契约 FLOW-04。

陈思雨新增店铺「Wayfair-CA-01」（Wayfair、加拿大、CAD）→ 出现在编制任务生成的平台渠道单位、填报店铺切换下拉与导入校验主数据中；
再新增同名店铺 → 「店铺名称已存在」且不新增；Lowes-US-02 停用后发布编制任务并导入含 Lowes-US-02 行的金蝶与 BI 文件 →
不生成填报单位、不在新填报中列出，但导入校验通过并入库；林晓把 TikTok-US-01 标记为新渠道、起始月 2027-03 →
2027-03 至 2028-02 各月「新渠道」，2028-03 起常规渠道；财务BP 视角看不到新渠道标记控件。
"""
from datetime import date

from sqlalchemy import func, select

from app.calc.periods import add_months, fmt_month
from app.models import BiActualAgg, Channel, FillingUnit, KingdeeActual, Site, Store, UserScope
from tests.acceptance.e1_helpers import DEADLINE, KINGDEE_HEADER, XLSX, People, uid, xlsx

BI_HEADER = ["月份", "店铺", "站点", "SKU", "销量", "本币销售额", "币种", "广告费", "平台费用"]
SKU_HEADER = ["SKU", "SPU 编码", "品类", "首次上架日期"]


def _import(bp, name, source, header, rows):
    r = bp.post("/api/imports", files={"file": (name, xlsx(header, rows), XLSX)}, data={"source": source})
    assert r.status_code == 200, r.text
    b = bp.get(f"/api/imports/{r.json()['id']}").json()
    return b


def test_flow_04(seeded, dingtalk, tmp_path):
    db = seeded
    p = People(db, dingtalk, tmp_path)
    bp, lin = p("chensiyu"), p("linxiao")
    wayfair = db.scalar(select(Channel.id).where(Channel.name == "Wayfair"))
    ca = db.scalar(select(Site.id).where(Site.code == "CA"))
    body = {"channel_id": wayfair, "name": "Wayfair-CA-01", "site_id": ca, "currency": "CAD", "is_active": True}
    r = bp.post("/api/master/stores", json=body)
    assert r.status_code == 201, r.text
    new_id = r.json()["id"]
    before = db.scalar(select(func.count()).select_from(Store))
    r = bp.post("/api/master/stores", json=body)
    assert r.status_code == 422 and r.json()["message"] == "店铺名称已存在"
    assert db.scalar(select(func.count()).select_from(Store)) == before

    lowes2 = db.scalar(select(Store).where(Store.name == "Lowes-US-02"))
    r = bp.put(f"/api/master/stores/{lowes2.id}", json={"channel_id": lowes2.channel_id, "name": lowes2.name,
                                                        "site_id": lowes2.site_id, "currency": lowes2.currency,
                                                        "is_active": False})
    assert r.status_code == 200 and r.json()["is_active"] is False

    # 运营黄子轩负责 Wayfair 店铺：林晓把新店铺加入其范围（发布前置：每个单位须有填报人）
    hz = uid(db, "huangzixuan")
    scope = sorted(db.scalars(select(UserScope.object_id).where(UserScope.user_id == hz,
                                                                UserScope.scope_type == "store")))
    r = lin.put(f"/api/admin/users/{hz}/roles", json={"roles": ["operations"], "stores": scope + [new_id]})
    assert r.status_code == 200, r.text

    cands = lin.get("/api/tasks/candidates").json()["items"]
    names = [c["name"] for c in cands if c["unit_type"] == "platform"]
    assert "Wayfair-CA-01" in names and "Lowes-US-02" not in names
    units = [{"unit_type": c["unit_type"], "scope_object_id": c["scope_object_id"]} for c in cands
             if c["unit_type"] in ("platform", "cost_ratio", "logistics_ratio") or c["name"] == "人力资源部"]
    r = lin.post("/api/tasks", json={"year": 2027, "deadline": DEADLINE, "units": units})
    assert r.status_code == 201, r.text
    task_id = r.json()["task"]["id"]
    pu = sorted(db.scalars(select(FillingUnit.name).where(FillingUnit.task_id == task_id,
                                                          FillingUnit.unit_type == "platform")))
    assert "Wayfair-CA-01" in pu and "Lowes-US-02" not in pu
    # 填报店铺切换下拉（我的填报中的平台渠道单位）
    mine = [u["name"] for u in p("huangzixuan").get("/api/filling-units", params={"mine": 1}).json()["items"]
            if u["unit_type"] == "platform"]
    assert "Wayfair-CA-01" in mine and "Lowes-US-02" not in mine

    # SKU 对照表（导入 BI 的前置）
    r = bp.post("/api/master/sku-mapping/upload", files={"file": ("SKU对照表.xlsx", xlsx(SKU_HEADER, [
        ["BC-2201-WH", "SPU-BC-2201", "浴室柜", "2025-06-01"]]), XLSX)})
    assert r.status_code == 200 and r.json()["status"] == "passed", r.text
    assert bp.post(f"/api/master/sku-mapping/upload/{r.json()['id']}/confirm").status_code == 200

    kd = _import(bp, "金蝶_2027-04_利润表.xlsx", "kingdee", KINGDEE_HEADER, [
        ["2027-04", "6001", "主营业务收入", "运营部", "Lowes-US-02", "US", "", "", 32000],
        ["2027-04", "6001", "主营业务收入", "运营部", "Wayfair-CA-01", "CA", "", "", 18000],
        ["2027-04", "6001", "主营业务收入", "运营部", "TikTok-US-01", "US", "", "", 5000],
    ])
    assert kd["status"] == "passed" and kd["issues"] == [], kd
    assert bp.post(f"/api/imports/{kd['id']}/confirm", json={"overwrite": False}).status_code == 200
    bi = _import(bp, "BI_2027-04_销售明细.xlsx", "bi", BI_HEADER, [
        ["2027-04", "Lowes-US-02", "US", "BC-2201-WH", 40, 4800, "USD", 300, 600],
        ["2027-04", "Wayfair-CA-01", "CA", "BC-2201-WH", 10, 2500, "CAD", 100, 200],
    ])
    assert bi["status"] == "passed" and bi["issues"] == [], bi
    assert all("店铺不在主数据" not in (i.get("type") or "") for i in bi["issues"] + kd["issues"])
    assert bp.post(f"/api/imports/{bi['id']}/confirm", json={"overwrite": False}).status_code == 200
    for sid in (lowes2.id, new_id):
        assert db.scalar(select(func.count()).select_from(KingdeeActual).where(KingdeeActual.store_id == sid)) == 1
        assert db.get(Store, sid).name in ("Lowes-US-02", "Wayfair-CA-01")
        assert db.scalar(select(func.count()).select_from(BiActualAgg).where(BiActualAgg.store_id == sid)) == 1

    # 新渠道标记
    tk = db.scalar(select(Store.id).where(Store.name == "TikTok-US-01"))
    r = lin.put(f"/api/master/stores/{tk}/new-channel", json={"is_new": True, "start": "2027-03"})
    assert r.status_code == 200, r.text
    for k in range(12):
        month = fmt_month(add_months(date(2027, 3, 1), k))
        row = next(s for s in lin.get("/api/master/stores", params={"month": month}).json()["stores"]
                   if s["name"] == "TikTok-US-01")
        assert row["new_channel"]["is_new"] is True, month
    row = next(s for s in lin.get("/api/master/stores", params={"month": "2028-03"}).json()["stores"]
               if s["name"] == "TikTok-US-01")
    assert row["new_channel"]["is_new"] is False
    # 渠道×站点偏差按月显示「新渠道」徽章：导入 TikTok-US-01 2027-03 至 2028-03 的金蝶实际后逐月查看
    months = [fmt_month(add_months(date(2027, 3, 1), k)) for k in range(13)]
    kd = _import(bp, "金蝶_TikTok_2027-03至2028-03.xlsx", "kingdee", KINGDEE_HEADER,
                 [[m, "6001", "主营业务收入", "运营部", "TikTok-US-01", "US", "", "", 5000] for m in months
                  if m != "2027-04"])
    assert kd["status"] == "passed", kd
    assert bp.post(f"/api/imports/{kd['id']}/confirm", json={"overwrite": False}).status_code == 200
    for m in months:
        rows = lin.get("/api/reports/channel-site", params={"month": m}).json()["rows"]
        tk_row = next(x for x in rows if x["name"] == "TikTok-US-01")
        assert tk_row["is_new_channel"] is (m != "2028-03"), m
    assert bp.get("/api/master/stores").json()["can_mark_new_channel"] is False
    r = bp.put(f"/api/master/stores/{tk}/new-channel", json={"is_new": True, "start": "2027-03"})
    assert r.status_code == 403 and r.json()["message"] == "无权限"
