"""契约场景数据（期望值来自 TDD验收契约.md，构造时只写前置条件）。"""
from datetime import date

from app.models.enums import VersionType

from tests.g4 import builders as B


def flow25(db, *, with_adjustment: bool = True, with_b2b: bool = True) -> dict:
    """FLOW-25：Amazon-US-01 2027-04（最新调整后目标：销量 1,200、平均单价 80.00、折扣率 10%、广告费率 12%），
    BI 销量 1,100、本币 USD 77,000.00、当月平均汇率 7.2000、金蝶收入 554,400.00、推广费用 73,000.00；
    另有 Ferguson 客户与未归属渠道 12,000.00；2027-05 金蝶已导入、BI 最近截至 2027-04。"""
    orig = B.version(db, 2027, VersionType.ORIGINAL_TARGET, "V1 年初原始目标")
    # 年初原始目标与最新滚动预测取不同销量，用于验证基准切换
    B.platform_unit(db, orig, "Amazon-US-01", "2027-04", "浴室柜", True, spu=10, avg_sales="130", avg_price="80.00",
                    discount="0.10", ad_rate="0.12")
    B.platform_unit(db, orig, "Amazon-CA-01", "2027-04", "框镜", False, spu=5, avg_sales="40", avg_price="90.00",
                    discount="0.10", ad_rate="0.08")
    target = orig
    if with_adjustment:
        adj = B.version(db, 2027, VersionType.ADJUSTED_TARGET, "V2 2027Q2 目标调整", version_no=2)
        B.platform_unit(db, adj, "Amazon-US-01", "2027-04", "浴室柜", True, spu=10, avg_sales="120",
                        avg_price="80.00", discount="0.10", ad_rate="0.12")
        B.platform_unit(db, adj, "Amazon-CA-01", "2027-04", "框镜", False, spu=5, avg_sales="40", avg_price="90.00",
                        discount="0.10", ad_rate="0.08")
        target = adj
    roll = B.version(db, 2027, VersionType.SNAPSHOT, "Q2 滚动预测快照", quarter=2, published_on=date(2027, 4, 10))
    B.platform_unit(db, roll, "Amazon-US-01", "2027-04", "浴室柜", True, spu=10, avg_sales="110", avg_price="80.00",
                    discount="0.10", ad_rate="0.12")
    if with_b2b:
        for v in {orig.id: orig, target.id: target}.values():
            B.b2b_unit(db, v, "Ferguson", "2027-04", sales_local="100000.00", refund_rate="0.03",
                       purchase_cost_rate="0.40")
    B.fx_actual(db, "2027-04", "USD", "7.2000")
    B.fx_actual(db, "2027-04", "CAD", "5.2410")
    kd4 = B.batch(db, "kingdee", "2027-04", "金蝶_2027-04_利润表_v2.xlsx")
    B.kingdee(db, kd4, "2027-04", "平台销售收入", "554400.00", store_name="Amazon-US-01")
    B.kingdee(db, kd4, "2027-04", "推广费用", "73000.00", store_name="Amazon-US-01")
    B.kingdee(db, kd4, "2027-04", "平台销售收入", "130000.00", store_name="Amazon-CA-01")
    B.kingdee(db, kd4, "2027-04", "推广费用", "11000.00", store_name="Amazon-CA-01")
    if with_b2b:
        B.kingdee(db, kd4, "2027-04", "平台销售收入", "700000.00", customer_name="Ferguson")
        B.kingdee(db, kd4, "2027-04", "采购成本", "290000.00", customer_name="Ferguson")
    B.kingdee(db, kd4, "2027-04", "仓储费", "12000.00", unassigned=True)
    bi = B.batch(db, "bi", "2027-04", "BI_2027-03_04.xlsx")
    B.bi_agg(db, bi, "2027-04", "Amazon-US-01", "浴室柜", True, spu=9, qty="1100", revenue_local="77000.00",
             revenue_cny="554400.00")
    B.bi_agg(db, bi, "2027-04", "Amazon-CA-01", "框镜", False, spu=5, qty="190", revenue_local="25000.00",
             revenue_cny="131025.00")
    kd5 = B.batch(db, "kingdee", "2027-05", "金蝶_2027-05_利润表.xlsx")
    B.kingdee(db, kd5, "2027-05", "平台销售收入", "500000.00", store_name="Amazon-US-01")
    B.kingdee(db, kd5, "2027-05", "仓储费", "8000.00", unassigned=True)
    return {"orig": orig, "target": target, "roll": roll}
