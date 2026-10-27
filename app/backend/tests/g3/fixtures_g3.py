"""G3 导入样例 Excel（openpyxl 生成，写入 tests/fixtures/）。

模板列按技术方案 §4.4 / PAGE-F09-01：
- 金蝶：期间（YYYY-MM）、金蝶科目、科目名称、部门、平台/店铺、站点、客户、摘要、发生额
- BI：月份（YYYY-MM）、店铺、站点、SKU、销量、本币销售额、币种、广告费、平台费用
数值以数字单元格写入（与金蝶、BI 导出一致）。行号 = Excel 行号（第 1 行为表头）。
用法：python -m tests.g3.fixtures_g3 生成全部样例；测试中 fixture_path() 缺失时自动生成。
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures"

KINGDEE_HEADER = ["期间", "金蝶科目", "科目名称", "部门", "平台/店铺", "站点", "客户", "摘要", "发生额"]
BI_HEADER = ["月份", "店铺", "站点", "SKU", "销量", "本币销售额", "币种", "广告费", "平台费用"]

# 账户简称 → (金蝶科目, 科目名称)
K = {
    "收入": ("6001", "主营业务收入"), "退款": ("6001.01", "主营业务收入-退款"), "采购": ("6401", "主营业务成本"),
    "佣金": ("6601.01", "销售费用-平台佣金"), "推广": ("6601.02", "销售费用-推广费"),
    "头程": ("6601.03", "销售费用-头程运费"), "尾程": ("6601.04", "销售费用-尾程运费"),
    "仓储": ("6601.06", "销售费用-仓储费"), "工资": ("6602.01", "管理费用-工资"),
    "差旅": ("6602.05", "管理费用-差旅费"), "办公": ("6602.06", "管理费用-办公费"),
    "房租": ("6602.07", "管理费用-房租物业"), "财务费用": ("6603", "财务费用"),
}


def kd(period: str, acct: str, amount, *, dept: str = "", store: str = "", site: str = "", customer: str = "",
       summary: str = "") -> list:
    code, name = K[acct]
    return [period, code, name, dept, store, site, customer, summary, float(Decimal(str(amount)))]


def bi(month: str, store: str, site: str, sku: str, qty, sales, currency: str, ad=0, fee=0) -> list:
    return [month, store, site, sku, float(Decimal(str(qty))), float(Decimal(str(sales))), currency,
            float(Decimal(str(ad))), float(Decimal(str(fee)))]


def write_xlsx(path: Path, header: list, rows: list[list]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook(write_only=True)
    ws = wb.create_sheet("Sheet1")
    ws.append(header)
    for r in rows:
        ws.append(r)
    wb.save(path)
    return path


# ---------------------------------------------------------------------------
# 金蝶 2027-04（FLOW-22 / FLOW-24 / RULE-05）
# ---------------------------------------------------------------------------
def kingdee_2027_04_rows(variant: str = "fixed") -> list[list]:
    """金蝶 2027-04 利润表：variant = original（首次导入）/ fixed（修正后，含仓储杂费 12,000.00 未归属）/
    errors（第 7、15、22、31 行各一个问题）。共 34 个数据行（第 2–35 行）。"""
    p = "2027-04"
    rows = [
        kd(p, "收入", 535000, store="Amazon-US-01", site="美国"),
        kd(p, "退款", 16050, store="Amazon-US-01", site="美国"),
        kd(p, "采购", 187250, store="Amazon-US-01", site="美国"),
        kd(p, "佣金", 80250, store="Amazon-US-01", site="美国"),
        kd(p, "推广", 53500, store="Amazon-US-01", site="美国"),
        kd(p, "头程", 26750, store="Amazon-US-01", site="美国"),          # 第 7 行
        kd(p, "收入", 355000, store="Wayfair-US-01", site="美国"),
        kd(p, "采购", 124250, store="Wayfair-US-01", site="美国"),
        kd(p, "佣金", 53250, store="Wayfair-US-01", site="美国"),
        kd(p, "尾程", 21300, store="Wayfair-US-01", site="美国"),
        kd(p, "收入", 98000, store="Amazon-UK-01", site="英国"),
        kd(p, "采购", 34300, store="Amazon-UK-01", site="英国"),
        kd(p, "佣金", 14700, store="Amazon-UK-01", site="英国"),
        kd(p, "工资", 186000, dept="运营部"),                               # 第 15 行
        kd(p, "工资", 98000, dept="物流物控部"),
        kd(p, "差旅", 12600, dept="物流物控部"),
        kd(p, "工资", 132000, dept="人力资源部"),
        kd(p, "办公", 8400, dept="人力资源部"),
        kd(p, "房租", 45000, dept="财务部"),
        kd(p, "收入", 120000, store="Amazon-CA-01", site="加拿大"),
        kd(p, "采购", 42000, store="Amazon-CA-01", site="加拿大"),         # 第 22 行
        kd(p, "收入", 210000, store="HomeDepot-US-01", site="美国"),
        kd(p, "采购", 73500, store="HomeDepot-US-01", site="美国"),
        kd(p, "收入", 86000, store="Lowes-US-01", site="美国"),
        kd(p, "收入", 64000, store="Shopify-US-01", site="美国"),
        kd(p, "推广", 9600, store="Shopify-US-01", site="美国"),
        kd(p, "收入", 230000, customer="Ferguson", summary="Ferguson 4 月出货"),
        kd(p, "采购", 80500, customer="Ferguson"),
        kd(p, "工资", 64000, dept="美国业务部"),
        kd(p, "推广", 18000, store="Amazon-DE-01", site="德国"),           # 第 31 行
        kd(p, "收入", 76000, store="Amazon-DE-01", site="德国"),
        kd(p, "财务费用", 5200, dept="财务部"),
        kd(p, "收入", 42000, store="TikTok-US-01", site="美国"),
        kd(p, "仓储", 12000, summary="仓储杂费"),                           # 无平台/店铺核算、非部门费用科目
    ]
    if variant == "original":
        rows[-1] = kd(p, "仓储", 11000, summary="仓储杂费")
        rows[0] = kd(p, "收入", 530000, store="Amazon-US-01", site="美国")
    if variant == "errors":
        rows[5] = ["2027/4", *rows[5][1:]]                               # 第 7 行：期间格式错误
        rows[13] = kd(p, "工资", 186000, dept="视觉二部")                    # 第 15 行：部门不在主数据中
        rows[20] = kd(p, "采购", 42000, store="Amazon-MX-01", site="")     # 第 22 行：店铺不在主数据中
        rows[29] = [p, "6601.99", "销售费用-其他", "", "Amazon-DE-01", "德国", "", "", 18000.0]  # 第 31 行：科目未映射
    return rows


def kingdee_last_row_error_rows() -> list[list]:
    rows = kingdee_2027_04_rows("fixed")
    rows[-1] = ["2027-04", "6601.99", "销售费用-其他", "", "", "", "", "仓储杂费", 12000.0]
    return rows


def kingdee_history_rows() -> list[list]:
    """历史金蝶：2025-01 至 2026-12 共 24 个期间。"""
    rows = []
    for y in (2025, 2026):
        for m in range(1, 13):
            p = f"{y}-{m:02d}"
            base = 400000 + (y - 2025) * 60000 + m * 5000
            rows += [kd(p, "收入", base, store="Amazon-US-01", site="美国"),
                     kd(p, "采购", base * Decimal("0.35"), store="Amazon-US-01", site="美国"),
                     kd(p, "工资", 90000 + m * 500, dept="人力资源部"),
                     kd(p, "工资", 85000 + m * 400, dept="物流物控部")]
    return rows


# ---------------------------------------------------------------------------
# BI（FLOW-23 / FLOW-24）
# ---------------------------------------------------------------------------
SKUS = [  # (SKU, SPU, 品类, SKU 上架日期)
    ("FM-2416-WH", "SPU-FM-2416", "框镜", "2026-03-15"),
    ("LM-3020-BK", "SPU-LM-3020", "灯镜", "2024-06-01"),
    ("MC-1810-OK", "SPU-MC-1810", "镜柜", "2025-01-10"),
    ("SD-6070-CL", "SPU-SD-6070", "浴室门", "2023-09-01"),
    ("BT-1708-WH", "SPU-BT-1708", "浴室柜", "2026-09-01"),
    ("BT-1708-GY", "SPU-BT-1708", "浴室柜", "2026-08-20"),
]


def bi_prior_2027_03_rows() -> list[list]:
    return [bi("2027-03", "Amazon-US-01", "美国", "LM-3020-BK", 300, 45000, "USD", 3600, 6750),
            bi("2027-03", "Amazon-US-01", "美国", "MC-1810-OK", 120, 30000, "USD", 2400, 4500),
            bi("2027-03", "Wayfair-US-01", "美国", "SD-6070-CL", 80, 36000, "USD", 0, 5400)]


def bi_errors_rows() -> list[list]:
    """BI 2027-03～04：SKU「BT-1701-WH」「SD-9999-XX」不在对照表，第 40 行月份「2027-4」，第 41 行站点「墨西哥」。"""
    rows = []
    for i in range(45):
        month = "2027-03" if i < 22 else "2027-04"
        sku, _spu, _cat, _d = SKUS[i % 4 + 1]
        store = "Amazon-US-01" if i % 2 == 0 else "Wayfair-US-01"
        rows.append(bi(month, store, "美国", sku, 10 + i, 1500 + i * 20, "USD", 120, 225))
    rows[4] = bi("2027-03", "Amazon-US-01", "美国", "BT-1701-WH", 12, 2280, "USD", 150, 342)
    rows[9] = bi("2027-03", "Wayfair-US-01", "美国", "SD-9999-XX", 5, 2400, "USD", 0, 360)
    rows[30] = bi("2027-04", "Amazon-US-01", "美国", "SD-9999-XX", 6, 2880, "USD", 0, 432)
    rows[38][0] = "2027-4"                       # 第 40 行
    rows[39][2] = "墨西哥"                        # 第 41 行
    return rows


def bi_fixed_rows() -> list[list]:
    """修正后：FM-2416-WH 在 2027-02 与 2027-03 各有一行（首次上架 2026-03-15 → 2 月新品、3 月老品）。"""
    return [bi("2027-02", "Amazon-US-01", "美国", "FM-2416-WH", 40, 5960, "USD", 480, 894),
            bi("2027-02", "Amazon-US-01", "美国", "LM-3020-BK", 280, 42000, "USD", 3360, 6300),
            bi("2027-03", "Amazon-US-01", "美国", "FM-2416-WH", 52, 7748, "USD", 620, 1162),
            bi("2027-03", "Amazon-US-01", "美国", "LM-3020-BK", 310, 46500, "USD", 3720, 6975),
            bi("2027-03", "Wayfair-US-01", "美国", "SD-6070-CL", 85, 38250, "USD", 0, 5737),
            bi("2027-03", "Wayfair-US-01", "美国", "BT-1708-WH", 30, 13500, "USD", 0, 2025)]


def bi_2027_04_rows() -> list[list]:
    """FLOW-24：Amazon-US-01 本币 USD 77,000.00；Wayfair-US-01 USD 50,000.00；Amazon-UK-01（GBP，缺当月汇率）。"""
    return [bi("2027-04", "Amazon-US-01", "美国", "LM-3020-BK", 300, 45000, "USD", 3600, 6750),
            bi("2027-04", "Amazon-US-01", "美国", "FM-2416-WH", 215, 32000, "USD", 2560, 4800),
            bi("2027-04", "Wayfair-US-01", "美国", "SD-6070-CL", 100, 50000, "USD", 0, 7500),
            bi("2027-04", "Amazon-UK-01", "英国", "MC-1810-OK", 90, 21000, "GBP", 1680, 3150)]


def bi_last_row_error_rows() -> list[list]:
    rows = bi_2027_04_rows()
    rows[-1] = bi("2027-04", "Amazon-UK-01", "英国", "XX-0000-ZZ", 1, 100, "GBP")
    return rows


FILES = {
    "金蝶_2027-04_利润表.xlsx": (KINGDEE_HEADER, lambda: kingdee_2027_04_rows("original")),
    "金蝶_2027-04_利润表_v2.xlsx": (KINGDEE_HEADER, lambda: kingdee_2027_04_rows("errors")),
    "金蝶_2027-04_利润表_v3.xlsx": (KINGDEE_HEADER, lambda: kingdee_2027_04_rows("fixed")),
    "金蝶_2027-04_末行出错.xlsx": (KINGDEE_HEADER, kingdee_last_row_error_rows),
    "金蝶_历史_2025-01至2026-12.xlsx": (KINGDEE_HEADER, kingdee_history_rows),
    "BI_2027-03_销售明细.xlsx": (BI_HEADER, bi_prior_2027_03_rows),
    "BI_2027-03至04_销售明细.xlsx": (BI_HEADER, bi_errors_rows),
    "BI_2027-02至03_销售明细_v2.xlsx": (BI_HEADER, bi_fixed_rows),
    "BI_2027-04_销售明细.xlsx": (BI_HEADER, bi_2027_04_rows),
    "BI_2027-04_末行出错.xlsx": (BI_HEADER, bi_last_row_error_rows),
}


def fixture_path(name: str) -> Path:
    path = FIXTURE_DIR / name
    if not path.exists():
        header, rows = FILES[name]
        write_xlsx(path, header, rows())
    return path


def generate_all() -> None:
    for name, (header, rows) in FILES.items():
        write_xlsx(FIXTURE_DIR / name, header, rows())
        print(FIXTURE_DIR / name)


if __name__ == "__main__":
    generate_all()
