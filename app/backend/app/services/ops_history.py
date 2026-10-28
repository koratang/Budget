"""经营历史表导入（REQ-F09-03）：各渠道店铺月度毛利明细 + 管理费用明细，按年度整表上传。

表格结构（财务部现行经营分析表）：
- 「<渠道>-RMB」工作表：A 列为店铺分块名（汇总 / 店铺 / 验证行），B 列为项目，表头「1月 … 12月」为人民币金额。
  只取店铺分块；汇总与「…验证」「净销售额-CA」等核对分块跳过。「TO B-RMB」的分块是 B 端客户。
- 「管理费用RMB」工作表：项目、说明、负责部门，「1月实际 … 12月实际」为人民币金额（「N月预算」列不导入）。

入库口径与金蝶实际一致（写入 kingdee_actual，按月拆为逻辑批次，与金蝶月度 / 历史金蝶同属一族，后导入者覆盖同期间）：
- 店铺分块的项目按毛利口径映射到损益口径科目（收入、退款、采购成本……库存索赔、其他运营费用）；
  金额保留表内符号，库存索赔在表内为负数（冲减成本），入库取相反数作为正向项目。
- 管理费用按「项目」（说明恰为某预算科目名时按说明）匹配预算科目；负责部门在主数据中则记入该部门，否则记入公司公共（部门为空）。
- 某店铺某月全部项目为 0 或空视为当月无数据，不入库；公式错误单元格（#REF! 等）跳过并提示。
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.money import MoneyError
from app.models import BCustomer, BudgetAccount, Channel, Department, Site, Store

OPS_CODE = "ops-history"
MGMT_SHEET = "管理费用RMB"
CHANNEL_SHEET_SUFFIX = "-RMB"
B2B_SHEET = "TO B-RMB"

# 店铺分块项目 → 损益口径（同一口径可有多个写法）
ITEM_ALIASES: dict[str, tuple[str, ...]] = {
    "revenue": ("收入",),
    "refund": ("售后退款",),
    "purchase_cost": ("商品成本",),
    "first_leg": ("头程物流",),
    "last_mile": ("尾程物流",),
    "tariff": ("关税成本",),
    "commission": ("平台佣金",),
    "promotion": ("推广费用",),
    "storage": ("仓储费用",),
    "other_opex": ("运营费用（软件费用等）", "其他运营费用（软件费用等）"),
    "inventory_claim": ("库存索赔金额",),
}
GP_LABEL_PREFIX = ("毛利额",)          # 表内毛利额（用于核对，不入库）
GP_TOLERANCE = Decimal(1)              # 重算毛利与表内毛利额相差超过 1 元时提示
_MONTH_HEADER = re.compile(r"^(1[0-2]|[1-9])月$")
_MGMT_MONTH_HEADER = re.compile(r"^(1[0-2]|[1-9])月实际$")
_SKIP_BLOCK = re.compile(r"(验证|^汇总$|^净销售额|^毛利润额)")
_MGMT_SKIP_ITEMS = ("管理费用合计", "合计")

SITE_CURRENCY = {"US": "USD", "CA": "CAD", "UK": "GBP", "DE": "EUR"}
# 渠道名称匹配：去掉空格、撇号，忽略大小写；表名 / 分块前缀 → 平台渠道的常见别名
_CHANNEL_ALIASES = {"homedepot": ("home depot",), "shopify": ("独立站", "shopify"), "tiktok": ("tiktok shop", "tiktok")}


class OpsWorkbookError(Exception):
    def __init__(self, code: str, value: str = ""):
        super().__init__(code)
        self.code = code
        self.value = value


@dataclass
class StoreBlock:
    sheet: str
    name: str
    row_no: int                                      # 分块首行（Excel 行号）
    items: dict[str, dict[int, Decimal]] = field(default_factory=dict)   # 损益口径 → {月: 金额}
    sheet_gp: dict[int, Decimal] = field(default_factory=dict)           # 表内毛利额
    error_cells: list[tuple[int, str, int]] = field(default_factory=list)  # (行号, 项目, 月)

    @property
    def is_b2b(self) -> bool:
        return self.sheet == B2B_SHEET

    def months(self) -> list[int]:
        return sorted({m for vals in self.items.values() for m, v in vals.items() if v != 0})


@dataclass
class MgmtRow:
    row_no: int
    item: str
    note: str
    dept: str
    values: dict[int, Decimal]
    error_months: list[int]


@dataclass
class OpsWorkbook:
    blocks: list[StoreBlock]
    mgmt: list[MgmtRow]
    mgmt_error_cells: list[tuple[int, str, int]]


def _text(v) -> str:
    from app.services.importer import cell_text  # 与金蝶 / BI 导入同一 Excel 读取边界（RULE-01）
    return cell_text(v)


def _is_error_cell(v) -> bool:
    return isinstance(v, str) and v.strip().startswith("#")


def _amount(v) -> Decimal | None:
    """单元格金额：空 → None；数字 → Decimal（按十进制文本转换）；其他文本抛 MoneyError。"""
    from app.services.importer import cell_decimal  # 与金蝶 / BI 导入同一 Excel 读取边界（RULE-01）
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    return cell_decimal(v)


def read_workbook(path: Path) -> OpsWorkbook:
    from python_calamine import CalamineWorkbook
    try:
        wb = CalamineWorkbook.from_path(str(path))
        names = list(wb.sheet_names)
    except Exception as e:  # calamine 对损坏文件抛多种异常，统一视为文件无法读取
        raise OpsWorkbookError("unreadable", str(e)[:120]) from e
    channel_sheets = [n for n in names if n.strip().endswith(CHANNEL_SHEET_SUFFIX) and n.strip() != MGMT_SHEET]
    if not channel_sheets and MGMT_SHEET not in names:
        raise OpsWorkbookError("ops_no_sheets", "、".join(names[:8]))
    blocks: list[StoreBlock] = []
    for name in channel_sheets:
        rows = wb.get_sheet_by_name(name).to_python(skip_empty_area=False)
        if not rows:
            continue
        header = [_text(h) for h in rows[0]]
        month_cols = {int(_MONTH_HEADER.match(h).group(1)): i for i, h in enumerate(header) if _MONTH_HEADER.match(h)}
        if len(header) < 2 or not month_cols:
            raise OpsWorkbookError("ops_header", f"{name}：缺少「1月…12月」表头")
        current: StoreBlock | None = None
        for idx, r in enumerate(rows[1:], start=2):
            r = list(r) + [None] * (len(header) - len(r))
            block_name = _text(r[0])
            if block_name:
                current = None if _SKIP_BLOCK.search(block_name) else StoreBlock(sheet=name.strip(), name=block_name,
                                                                                  row_no=idx)
                if current is not None:
                    blocks.append(current)
            label = _text(r[1])
            if current is None or not label:
                continue
            key = next((k for k, aliases in ITEM_ALIASES.items() if label in aliases), None)
            is_gp = label.startswith(GP_LABEL_PREFIX)
            if key is None and not is_gp:
                continue
            if key is not None and key in current.items:
                continue                      # 同一分块重复项目只取第一行
            vals: dict[int, Decimal] = {}
            for m, ci in month_cols.items():
                raw = r[ci] if ci < len(r) else None
                if _is_error_cell(raw):
                    if key is not None:
                        current.error_cells.append((idx, label, m))
                    continue
                try:
                    v = _amount(raw)
                except MoneyError:
                    if key is not None:
                        current.error_cells.append((idx, label, m))
                    continue
                if v is not None:
                    vals[m] = v
            if is_gp:
                current.sheet_gp = current.sheet_gp or vals
            else:
                current.items[key] = vals
    mgmt: list[MgmtRow] = []
    mgmt_errors: list[tuple[int, str, int]] = []
    if MGMT_SHEET in names:
        rows = wb.get_sheet_by_name(MGMT_SHEET).to_python(skip_empty_area=False)
        header = [_text(h) for h in rows[0]] if rows else []
        cols = {h: i for i, h in enumerate(header)}
        month_cols = {int(_MGMT_MONTH_HEADER.match(h).group(1)): i for i, h in enumerate(header)
                      if _MGMT_MONTH_HEADER.match(h)}
        if "项目" not in cols or not month_cols:
            raise OpsWorkbookError("ops_header", f"{MGMT_SHEET}：缺少「项目」「1月实际…」表头")
        for idx, r in enumerate(rows[1:], start=2):
            r = list(r) + [None] * (len(header) - len(r))
            item = _text(r[cols["项目"]])
            if not item or item in _MGMT_SKIP_ITEMS:
                continue
            vals, errs = {}, []
            for m, ci in month_cols.items():
                raw = r[ci]
                if _is_error_cell(raw):
                    errs.append(m)
                    continue
                try:
                    v = _amount(raw)
                except MoneyError:
                    errs.append(m)
                    continue
                if v is not None:
                    vals[m] = v
            mgmt.append(MgmtRow(row_no=idx, item=item, note=_text(r[cols["说明"]]) if "说明" in cols else "",
                                dept=_text(r[cols["负责部门"]]) if "负责部门" in cols else "", values=vals,
                                error_months=errs))
            mgmt_errors += [(idx, item, m) for m in errs]
    return OpsWorkbook(blocks=blocks, mgmt=mgmt, mgmt_error_cells=mgmt_errors)


def gross_profit(items: dict[str, dict[int, Decimal]], month: int) -> Decimal:
    """平台毛利口径（AC-F06-03）：收入 − 退款 − 各项成本费用 + 库存索赔（表内库存索赔为负数，直接相减即加回）。"""
    z = Decimal(0)
    total = items.get("revenue", {}).get(month, z)
    for k in ITEM_ALIASES:
        if k != "revenue":
            total -= items.get(k, {}).get(month, z)
    return total


# ---------------------------------------------------------------------------
# 主数据匹配
# ---------------------------------------------------------------------------
def _norm(s: str) -> str:
    return re.sub(r"[\s'’‘`]", "", s).lower()


def _account_maps(db: Session) -> tuple[dict[str, BudgetAccount], dict[str, BudgetAccount]]:
    """(损益口径 → 毛利口径科目, 科目名称 → 科目)。同一口径多个科目时取排序最前的启用科目。"""
    by_item: dict[str, BudgetAccount] = {}
    by_name: dict[str, BudgetAccount] = {}
    for a in db.scalars(select(BudgetAccount).order_by(BudgetAccount.is_active.desc(), BudgetAccount.sort,
                                                       BudgetAccount.id)):
        by_name.setdefault(a.name, a)
        if not a.is_dept_expense and a.pl_item:
            by_item.setdefault(a.pl_item, a)
    return by_item, by_name


def mgmt_account(row: MgmtRow, by_name: dict[str, BudgetAccount]) -> BudgetAccount | None:
    """说明恰为某预算科目名称时按说明（如「财务费用 / 汇兑损益」），否则按项目名称。"""
    if row.note and row.note in by_name:
        return by_name[row.note]
    return by_name.get(row.item)


def validate(db: Session, path: Path, year: int | None) -> tuple[list[dict], list[dict]]:
    """返回 (问题列表, 暂存行)。问题带 warning=True 的只提示不阻断。"""
    errors: list[dict] = []

    def err(row, code, value="", **extra):
        errors.append({"row": row, "type": code, "value": value, **extra})

    if year is None:
        err(1, "ops_year_missing")
        return errors, []
    try:
        wb = read_workbook(path)
    except OpsWorkbookError as e:
        err(1, e.code, e.value)
        return errors, []
    stores = {s.name: s for s in db.scalars(select(Store))}
    customers = {c.name: c for c in db.scalars(select(BCustomer))}
    depts = {d.name: d.id for d in db.scalars(select(Department))}
    by_item, by_name = _account_maps(db)
    staged: list[dict] = []
    seq = 0

    def stage(month: int, *, account: BudgetAccount, amount: Decimal, store: Store | None = None,
              customer: BCustomer | None = None, dept_id: int | None = None, summary: str) -> None:
        nonlocal seq
        seq += 1
        staged.append({"row_no": seq, "month": date(year, month, 1).isoformat(), "department_id": dept_id,
                       "store_id": store.id if store else None, "site_id": store.site_id if store else None,
                       "customer_id": customer.id if customer else None, "kingdee_code": OPS_CODE,
                       "account_id": account.id, "amount": format(amount, "f"), "unassigned": False,
                       "summary": summary[:256]})

    missing_items = [k for k in ITEM_ALIASES if k not in by_item]
    for k in missing_items:
        err(1, "account_unmapped", f"缺少损益口径为 {k} 的预算科目")
    for b in wb.blocks:
        months = b.months()
        if not months:
            continue
        store = customer = None
        if b.is_b2b:
            customer = customers.get(b.name)
            if customer is None:
                err(b.row_no, "customer_not_found", b.name, sheet=b.sheet)
                continue
        else:
            store = stores.get(b.name)
            if store is None:
                err(b.row_no, "store_not_found", b.name, sheet=b.sheet)
                continue
        for row_no, label, m in b.error_cells:
            err(row_no, "ops_error_cell", f"{b.sheet} · {b.name} · {label} · {m}月", warning=True)
        for m in months:
            gp = gross_profit(b.items, m)
            sheet_gp = b.sheet_gp.get(m)
            if sheet_gp is not None and abs(gp - sheet_gp) > GP_TOLERANCE:
                err(b.row_no, "ops_gp_mismatch", f"{b.sheet} · {b.name} · {m}月",
                    warning=True, recalc=format(gp, "f"), sheet=format(sheet_gp, "f"))
            if missing_items:
                continue
            for k, vals in b.items.items():
                v = vals.get(m)
                if v is None or v == 0:
                    continue
                stage(m, account=by_item[k], amount=-v if k == "inventory_claim" else v, store=store,
                      customer=customer, summary=f"{b.sheet} · {b.name} · {ITEM_ALIASES[k][0]}")
    unmatched_depts: dict[str, int] = {}
    for r in wb.mgmt:
        acc = mgmt_account(r, by_name)
        if acc is None:
            if any(v != 0 for v in r.values.values()):
                err(r.row_no, "mgmt_account_not_found", r.item)
            continue
        dept_id = depts.get(r.dept)
        if dept_id is None and r.dept and any(v != 0 for v in r.values.values()):
            unmatched_depts.setdefault(r.dept, r.row_no)
        for m in r.error_months:
            err(r.row_no, "ops_error_cell", f"{MGMT_SHEET} · {r.item} · {m}月实际", warning=True)
        for m, v in sorted(r.values.items()):
            if v == 0:
                continue
            stage(m, account=acc, amount=v, dept_id=dept_id,
                  summary=f"{MGMT_SHEET} · {r.item}{' · ' + r.note if r.note else ''}")
    for name, row_no in unmatched_depts.items():
        err(row_no, "ops_dept_public", name, warning=True)
    if not [e for e in errors if not e.get("warning")] and not staged:
        err(1, "empty_file")
    return errors, staged


# ---------------------------------------------------------------------------
# 补建缺少的主数据（店铺 / B 端客户 / 部门费用科目）
# ---------------------------------------------------------------------------
def _site_of(name: str, sites: dict[str, Site]) -> Site | None:
    for token in reversed(re.split(r"[-_\s]+", name)):
        s = sites.get(token.upper())
        if s is not None:
            return s
    return None


def _channel_candidate(sheet: str, block: str) -> str:
    base = sheet[: -len(CHANNEL_SHEET_SUFFIX)].strip() if sheet.endswith(CHANNEL_SHEET_SUFFIX) else sheet
    if base.lower() in ("others", "other", "其他"):
        base = re.split(r"[-_]", block)[0].strip() or block
    return base


def _match_channel(candidate: str, channels: list[Channel]) -> Channel | None:
    keys = {_norm(candidate)} | {_norm(a) for a in _CHANNEL_ALIASES.get(_norm(candidate), ())}
    for ch in channels:
        if _norm(ch.name) in keys:
            return ch
    return None


def missing_plan(db: Session, errors: list[dict]) -> dict:
    """根据校验问题给出补建计划（店铺的渠道、站点、结算币种由表名与店铺名推断，建后可在主数据页修改）。"""
    sites = {s.code.upper(): s for s in db.scalars(select(Site))}
    channels = list(db.scalars(select(Channel).order_by(Channel.sort, Channel.id)))
    depts = list(db.scalars(select(Department).order_by(Department.sort, Department.id)))
    default_site = sites.get("US") or (next(iter(sites.values())) if sites else None)
    stores, customers, accounts = [], [], []
    for e in errors:
        t = e.get("type")
        if t == "store_not_found" and e.get("sheet"):
            name = e["value"]
            cand = _channel_candidate(e["sheet"], name)
            ch = _match_channel(cand, channels)
            site = _site_of(name, sites) or default_site
            stores.append({"name": name, "channel": ch.name if ch else cand, "new_channel": ch is None,
                           "site": site.name if site else None, "site_code": site.code if site else None,
                           "currency": SITE_CURRENCY.get(site.code.upper(), "USD") if site else "USD"})
        elif t == "customer_not_found":
            name = e["value"]
            dept = next((d for d in depts if d.name.rstrip("部") and d.name.rstrip("部") in name), None) or \
                next((d for d in depts if d.name == "美国业务部"), None) or (depts[0] if depts else None)
            customers.append({"name": name, "department": dept.name if dept else None, "currency": "USD"})
        elif t == "mgmt_account_not_found":
            accounts.append({"name": e["value"]})
    return {"stores": stores, "customers": customers, "accounts": accounts,
            "count": len(stores) + len(customers) + len(accounts)}


def create_missing(db: Session, plan: dict) -> dict:
    """按补建计划新建主数据；名称已存在的跳过（并发或重复点击）。返回新建数量。"""
    sites = {s.code: s for s in db.scalars(select(Site))}
    channels = {c.name: c for c in db.scalars(select(Channel))}
    depts = {d.name: d for d in db.scalars(select(Department))}
    created = {"stores": 0, "channels": 0, "customers": 0, "accounts": 0}
    max_sort = db.scalar(select(func.max(Channel.sort))) or 0
    for s in plan["stores"]:
        if db.scalar(select(Store.id).where(Store.name == s["name"])) is not None or s["site_code"] is None:
            continue
        ch = channels.get(s["channel"])
        if ch is None:
            max_sort += 1
            ch = Channel(name=s["channel"], sort=max_sort)
            db.add(ch)
            db.flush()
            channels[ch.name] = ch
            created["channels"] += 1
        db.add(Store(name=s["name"], channel_id=ch.id, site_id=sites[s["site_code"]].id, currency=s["currency"]))
        created["stores"] += 1
    for c in plan["customers"]:
        if db.scalar(select(BCustomer.id).where(BCustomer.name == c["name"])) is not None or c["department"] is None:
            continue
        db.add(BCustomer(name=c["name"], department_id=depts[c["department"]].id, currency=c["currency"]))
        created["customers"] += 1
    acc_sort = db.scalar(select(func.max(BudgetAccount.sort))) or 0
    for a in plan["accounts"]:
        if db.scalar(select(BudgetAccount.id).where(BudgetAccount.name == a["name"])) is not None:
            continue
        acc_sort += 1
        db.add(BudgetAccount(name=a["name"], is_dept_expense=True, pl_item=None, sort=acc_sort))
        created["accounts"] += 1
    db.flush()
    return created


def summary(db: Session, staged_rows: list[dict]) -> dict:
    """待确认摘要：按渠道表汇总店铺数、期间、收入与毛利；管理费用合计。"""
    from app.models import BudgetAccount as BA
    accounts = {a.id: a for a in db.scalars(select(BA))}
    by_sheet: dict[str, dict] = defaultdict(lambda: {"stores": set(), "revenue": Decimal(0), "gp": Decimal(0)})
    mgmt_total, mgmt_rows, months = Decimal(0), 0, set()
    for d in staged_rows:
        acc = accounts[int(d["account_id"])]
        amt = Decimal(d["amount"])
        months.add(d["month"][:7])
        sheet = d["summary"].split(" · ")[0]
        if sheet == MGMT_SHEET:
            mgmt_total += amt
            mgmt_rows += 1
            continue
        g = by_sheet[sheet]
        g["stores"].add(d["summary"].split(" · ")[1])
        if acc.pl_item == "revenue":
            g["revenue"] += amt
            g["gp"] += amt
        elif acc.pl_item == "inventory_claim":
            g["gp"] += amt
        else:
            g["gp"] -= amt
    return {"months": sorted(months),
            "sheets": [{"sheet": k, "stores": len(v["stores"]), "revenue": format(v["revenue"], "f"),
                        "gross_profit": format(v["gp"], "f")} for k, v in by_sheet.items()],
            "mgmt_total": format(mgmt_total, "f"), "mgmt_rows": mgmt_rows}
