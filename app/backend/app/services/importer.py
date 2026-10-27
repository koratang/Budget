"""实际数导入管线 CMP-F09-01（DEC-008 两段式；AC-F09-01~09、AC-F11-01、NFR-002、NFR-004）。

1. 上传：原文件存 DATA_DIR/uploads/{年}/{月}/{批次ID}.{扩展名}，记录文件名、大小、SHA-256、上传人，批次「校验中」。
2. 校验（后台线程）：calamine 读取 → 按表头定位列 → 主数据一次载入内存逐行校验，收集全部错误；
   有错误 → 「校验失败」，不写任何业务数据；无错误 → COPY 写入暂存表，「待确认」。
3. 确认（单一事务）：按期间拆为逻辑批次；同来源同期间的旧生效批次标「已被替换」（行保留、不再参与计算）；
   暂存 → 实际数表（金蝶：客户辅助核算、未归属渠道；BI：明细 + 按 SKU 对照表归集到品类 × 新老品）；
   预警评估（只取生效规则版本）；审计；删除暂存。需覆盖而未确认覆盖时 409 且不写入。

批次结构：上传批次（parent_batch_id 为空）+ 每个期间一个逻辑批次（period、parent_batch_id）；
实际数行挂在逻辑批次上，「已生效」逻辑批次的行才参与计算。
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.calc.periods import add_months, fmt_month, month_end
from app.core.clock import clock
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.money import MoneyError, dec_str, fmt_cny, fmt_foreign, to_decimal
from app.models import (BCustomer, BudgetAccount, Department, ImportBatch, ImportStaging,
                        KingdeeAccountMap, Site, Sku, Spu, Store, User)
from app.models.enums import ImportSource, ImportStatus
from app.services import alerting, masterdata
from app.services.versions import CHANNEL_ITEMS, Actor, audit, fmt_dt

SOURCE_LABELS = {ImportSource.KINGDEE: "金蝶月度", ImportSource.KINGDEE_HISTORY: "历史金蝶",
                 ImportSource.BI: "BI 双月"}
FAMILY = {ImportSource.KINGDEE: (ImportSource.KINGDEE, ImportSource.KINGDEE_HISTORY),
          ImportSource.KINGDEE_HISTORY: (ImportSource.KINGDEE, ImportSource.KINGDEE_HISTORY),
          ImportSource.BI: (ImportSource.BI,)}
API_STATUS = {ImportStatus.VALIDATING: "validating", ImportStatus.VALIDATION_FAILED: "failed",
              ImportStatus.PENDING_CONFIRM: "passed", ImportStatus.EFFECTIVE: "imported"}
HISTORY_MAX_PERIODS = 24
INTERRUPT_AFTER = timedelta(minutes=10)

KINGDEE_COLUMNS = {"period": ("期间",), "code": ("金蝶科目", "科目编码"), "dept": ("部门",),
                   "store": ("平台/店铺", "店铺"), "site": ("站点",), "amount": ("发生额",)}
KINGDEE_OPTIONAL = {"code_name": ("科目名称",), "customer": ("客户",), "summary": ("摘要",)}
BI_COLUMNS = {"month": ("月份",), "store": ("店铺",), "site": ("站点",), "sku": ("SKU",), "qty": ("销量",),
              "sales": ("本币销售额",), "currency": ("币种",), "ad_fee": ("广告费",), "platform_fee": ("平台费用",)}

# 问题类型：库内英文代码 → 中文问题类型、处理方式、主数据页链接
ISSUE_TYPES = {
    "header": ("表头不符", "按模板表头修正后重新上传", None),
    "period_format": ("期间格式错误", "改为 YYYY-MM 后重新上传", None),
    "month_format": ("月份格式错误", "改为 YYYY-MM 后重新上传", None),
    "dept_not_found": ("部门不在主数据中", "到 B端客户与部门 维护", "/master/customers"),
    "store_not_found": ("店铺不在主数据中", "到 渠道与店铺 维护", "/master/stores"),
    "site_not_found": ("站点不在主数据中", "到 渠道与店铺 维护", "/master/stores"),
    "account_unmapped": ("金蝶科目未映射", "到 科目映射 维护", "/master/accounts"),
    "sku_unmapped": ("SKU 未映射", "到 SKU 对照表 维护", "/master/sku"),
    "amount_format": ("数值格式错误", "修正为数字后重新上传", None),
    "currency_mismatch": ("币种与店铺结算币种不一致", "到 渠道与店铺 核对", "/master/stores"),
    "too_many_periods": ("期间数超过上限", f"历史文件最多 {HISTORY_MAX_PERIODS} 个期间", None),
    "empty_file": ("文件没有数据行", "按模板填写后重新上传", None),
    "unreadable": ("文件无法读取", "确认为 .xlsx / .xls 后重新上传", None),
}
_MONTH_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


class ImportFileError(Exception):
    def __init__(self, code: str, value: str = ""):
        super().__init__(code)
        self.code, self.value = code, value


# ---------------------------------------------------------------------------
# 读取
# ---------------------------------------------------------------------------
def read_rows(path: Path) -> list[tuple[int, list]]:
    """读取第一个工作表：返回 [(Excel 行号, 单元格值列表)]，第 1 行为表头。"""
    from python_calamine import CalamineWorkbook
    try:
        wb = CalamineWorkbook.from_path(str(path))
        sheet = wb.get_sheet_by_index(0)
        rows = sheet.to_python(skip_empty_area=False)
    except Exception as e:  # calamine 对损坏文件抛多种异常，统一视为文件无法读取
        raise ImportFileError("unreadable", str(e)[:120]) from e
    return [(i + 1, list(r)) for i, r in enumerate(rows)]


def cell_text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return format(Decimal(str(v)), "f").rstrip("0").rstrip(".") if v != int(v) else str(int(v))
    if isinstance(v, (datetime, date)):
        return v.isoformat()[:10]
    return str(v).strip()


def cell_decimal(v) -> Decimal:
    """Excel 数值以浮点存储：按其十进制文本转换，避免二进制误差进入金额（DEC-005）。"""
    if v is None or (isinstance(v, str) and not v.strip()):
        return Decimal(0)
    if isinstance(v, bool):
        raise MoneyError("不是数字")
    if isinstance(v, float):
        return Decimal(repr(v))
    return to_decimal(v)


def parse_period(v) -> date | None:
    if isinstance(v, datetime):
        return date(v.year, v.month, 1)
    if isinstance(v, date):
        return date(v.year, v.month, 1)
    m = _MONTH_RE.match(cell_text(v))
    return date(int(m.group(1)), int(m.group(2)), 1) if m else None


def locate_columns(header: list, spec: dict, optional: dict | None = None) -> dict[str, int]:
    names = [cell_text(h) for h in header]
    found, missing = {}, []
    for key, aliases in spec.items():
        idx = next((names.index(a) for a in aliases if a in names), None)
        if idx is None:
            missing.append(aliases[0])
        else:
            found[key] = idx
    if missing:
        raise ImportFileError("header", "缺少列：" + "、".join(missing))
    for key, aliases in (optional or {}).items():
        idx = next((names.index(a) for a in aliases if a in names), None)
        if idx is not None:
            found[key] = idx
    return found


def _get(row: list, idx: int | None):
    return row[idx] if idx is not None and idx < len(row) else None


def _err(errors: list, row, error: str, value: str = "", **extra) -> None:
    """库内错误：type = 英文错误代码（G1 科目映射页按 account_unmapped 识别），type_label = 中文问题类型。"""
    errors.append({"row": row, "type": error, "type_label": ISSUE_TYPES[error][0], "value": value, **extra})


# ---------------------------------------------------------------------------
# 校验：金蝶（月度 / 历史）
# ---------------------------------------------------------------------------
def _site_lookup(db: Session) -> dict[str, Site]:
    out = {}
    for s in db.scalars(select(Site)):
        out[s.code] = s
        out[s.name] = s
    return out


def validate_kingdee(db: Session, rows: list[tuple[int, list]], source: str) -> tuple[list[dict], list[dict]]:
    header_row, header = rows[0]
    cols = locate_columns(header, KINGDEE_COLUMNS, KINGDEE_OPTIONAL)
    depts = {d.name: d.id for d in db.scalars(select(Department))}
    stores = masterdata.import_store_lookup(db)          # 店铺名称 → (店铺 ID, 站点 ID)，含停用店铺
    sites = _site_lookup(db)
    customers = {c.name: c.id for c in db.scalars(select(BCustomer))}
    accounts = {a.id: a for a in db.scalars(select(BudgetAccount))}
    mapping = masterdata.account_map_lookup(db)          # 金蝶科目编码 → 预算科目 ID（只含已映射）
    code_names = dict(db.execute(select(KingdeeAccountMap.kingdee_code, KingdeeAccountMap.kingdee_name)).all())
    errors: list[dict] = []
    staged: list[dict] = []
    periods: set[date] = set()
    for row_no, r in rows[1:]:
        if all(cell_text(v) == "" for v in r):
            continue
        ok = True
        raw_period = _get(r, cols["period"])
        period = parse_period(raw_period)
        if period is None:
            _err(errors, row_no, "period_format", cell_text(raw_period))
            ok = False
        dept_name = cell_text(_get(r, cols["dept"]))
        dept_id = None
        if dept_name:
            dept_id = depts.get(dept_name)
            if dept_id is None:
                _err(errors, row_no, "dept_not_found", dept_name)
                ok = False
        store_name = cell_text(_get(r, cols["store"]))
        store = None
        if store_name:
            store = stores.get(store_name)
            if store is None:
                _err(errors, row_no, "store_not_found", store_name)
                ok = False
        site_name = cell_text(_get(r, cols["site"]))
        site = None
        if site_name:
            site = sites.get(site_name)
            if site is None or (store is not None and site.id != store[1]):
                _err(errors, row_no, "site_not_found", f"{store_name} · {site_name}" if site and store else site_name)
                ok = False
        elif store is not None:
            site = db.get(Site, store[1])
        code = cell_text(_get(r, cols["code"]))
        account_id = mapping.get(code)
        if account_id is None:
            name = cell_text(_get(r, cols.get("code_name"))) or code_names.get(code) or ""
            _err(errors, row_no, "account_unmapped", f"{code} {name}".strip(), code=code, name=name or None)
            ok = False
        try:
            # 金额约定（与 G4 报表一致）：各科目存发生额绝对值，收入 / 费用按科目性质区分
            amount = abs(cell_decimal(_get(r, cols["amount"])))
        except MoneyError:
            _err(errors, row_no, "amount_format", cell_text(_get(r, cols["amount"])))
            ok = False
        if not ok:
            continue
        account = accounts[account_id]
        customer_id = customers.get(cell_text(_get(r, cols.get("customer")))) if store is None else None
        unassigned = (store is None and customer_id is None and not account.is_dept_expense
                      and account.pl_item in CHANNEL_ITEMS)
        periods.add(period)
        staged.append({"row_no": row_no, "month": period.isoformat(), "department_id": dept_id,
                       "store_id": store[0] if store else None, "site_id": site.id if site else None,
                       "customer_id": customer_id, "kingdee_code": code, "account_id": account.id,
                       "amount": format(amount, "f"), "unassigned": unassigned,
                       "summary": cell_text(_get(r, cols.get("summary")))[:256] or None})
    if not errors and not staged:
        _err(errors, header_row + 1, "empty_file")
    if source == ImportSource.KINGDEE_HISTORY and len(periods) > HISTORY_MAX_PERIODS:
        _err(errors, header_row, "too_many_periods", f"{len(periods)} 个期间")
    return errors, staged


# ---------------------------------------------------------------------------
# 校验：BI
# ---------------------------------------------------------------------------
def is_new_product(first_listed: date, month: date) -> bool:
    """AC-F02-04：该月最后一天 < 首次上架日期 + 12 个月 → 新品。"""
    return month_end(month) < add_months(first_listed, 12)


def validate_bi(db: Session, rows: list[tuple[int, list]], source: str) -> tuple[list[dict], list[dict]]:
    header_row, header = rows[0]
    cols = locate_columns(header, BI_COLUMNS)
    stores = masterdata.import_store_lookup(db)          # 含停用店铺（AC-F02-10）
    currencies = dict(db.execute(select(Store.id, Store.currency)).all())
    sites = _site_lookup(db)
    skus = {code: (sku_id, spu_id, cat_id, first)
            for code, sku_id, spu_id, cat_id, first in db.execute(
                select(Sku.code, Sku.id, Spu.id, Spu.category_id, Spu.first_listed_on).join(Spu, Spu.id == Sku.spu_id))}
    errors: list[dict] = []
    unmapped: dict[str, list[int]] = {}
    staged: list[dict] = []
    for row_no, r in rows[1:]:
        if all(cell_text(v) == "" for v in r):
            continue
        ok = True
        raw_month = _get(r, cols["month"])
        month = parse_period(raw_month)
        if month is None:
            _err(errors, row_no, "month_format", cell_text(raw_month))
            ok = False
        store_name = cell_text(_get(r, cols["store"]))
        store = stores.get(store_name)
        if store is None:
            _err(errors, row_no, "store_not_found", store_name)
            ok = False
        site_name = cell_text(_get(r, cols["site"]))
        site = sites.get(site_name)
        if site is None or (store is not None and site.id != store[1]):
            _err(errors, row_no, "site_not_found", site_name)
            ok = False
        code = cell_text(_get(r, cols["sku"]))
        sku = skus.get(code)
        if sku is None:
            unmapped.setdefault(code, []).append(row_no)
            ok = False
        values = {}
        for key in ("qty", "sales", "ad_fee", "platform_fee"):
            try:
                values[key] = cell_decimal(_get(r, cols[key]))
            except MoneyError:
                _err(errors, row_no, "amount_format", cell_text(_get(r, cols[key])))
                ok = False
        currency = cell_text(_get(r, cols["currency"])).upper()
        if store is not None and currency != currencies[store[0]]:
            _err(errors, row_no, "currency_mismatch", f"{store_name} · {currency or '空'}")
            ok = False
        if not ok:
            continue
        sku_id, spu_id, cat_id, first = sku
        staged.append({"row_no": row_no, "month": month.isoformat(), "store_id": store[0], "site_id": site.id,
                       "sku_id": sku_id, "spu_id": spu_id, "category_id": cat_id,
                       "is_new": is_new_product(first, month), "qty": format(values["qty"], "f"),
                       "sales": format(values["sales"], "f"), "currency": currency,
                       "ad_fee": format(values["ad_fee"], "f"), "platform_fee": format(values["platform_fee"], "f")})
    for code, row_nos in unmapped.items():
        _err(errors, row_nos[0], "sku_unmapped", code, count=len(row_nos))
    if not errors and not staged:
        _err(errors, header_row + 1, "empty_file")
    return errors, staged


VALIDATORS = {ImportSource.KINGDEE: validate_kingdee, ImportSource.KINGDEE_HISTORY: validate_kingdee,
              ImportSource.BI: validate_bi}


# ---------------------------------------------------------------------------
# 上传与校验
# ---------------------------------------------------------------------------
def upload_dir(data_dir: Path, now: datetime) -> Path:
    path = Path(data_dir) / "uploads" / f"{now.year:04d}" / f"{now.month:02d}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def create_batch(db: Session, actor: Actor, *, source: str, file_name: str, content: bytes, data_dir: Path,
                 request=None) -> ImportBatch:
    if source not in VALIDATORS:
        raise ValidationFailed("导入类型只能是 kingdee / kingdee-history / bi", code="invalid_source")
    if not file_name.lower().endswith((".xlsx", ".xls")):
        raise ValidationFailed("只支持 .xlsx / .xls 文件", code="invalid_file_type")
    now = clock.now()
    batch = ImportBatch(source=source, file_name=file_name[:256], file_size=len(content),
                        sha256=hashlib.sha256(content).hexdigest(), status=ImportStatus.VALIDATING,
                        uploaded_by=actor.id, uploaded_at=now)
    db.add(batch)
    db.flush()
    ext = Path(file_name).suffix.lower()
    path = upload_dir(data_dir, now) / f"{batch.id}{ext}"
    path.write_bytes(content)
    batch.file_path = str(path)
    audit(db, actor, action="import_uploaded", object_type="import_batch", object_id=batch.id, request=request,
          after={"source": source, "file_name": batch.file_name, "file_size": batch.file_size,
                 "sha256": batch.sha256})
    return batch


def _copy_staging(db: Session, batch_id: int, staged: list[dict]) -> None:
    """psycopg COPY 写入暂存表（DEC-008）。"""
    raw = db.connection().connection.driver_connection
    with raw.cursor() as cur:
        with cur.copy("COPY import_staging (batch_id, row_no, data) FROM STDIN") as cp:
            for item in staged:
                cp.write_row((batch_id, item["row_no"], json.dumps(item, ensure_ascii=False)))


def validate_batch(db: Session, batch_id: int) -> ImportBatch:
    """解析并校验（后台线程或测试中同步调用）；完成后提交。"""
    batch = db.get(ImportBatch, batch_id)
    if batch is None or batch.status != ImportStatus.VALIDATING:
        return batch
    try:
        rows = read_rows(Path(batch.file_path))
        if not rows:
            raise ImportFileError("empty_file")
        errors, staged = VALIDATORS[batch.source](db, rows, batch.source)
    except ImportFileError as e:
        errors, staged = [], []
        _err(errors, 1, e.code, e.value)
        rows = []
    batch.row_count = len(staged) if not errors else max(len(rows) - 1, 0)
    batch.validated_at = clock.now()
    if errors:
        batch.status = ImportStatus.VALIDATION_FAILED
        batch.errors = errors
    else:
        _copy_staging(db, batch.id, staged)
        batch.status = ImportStatus.PENDING_CONFIRM
        batch.errors = []
    db.commit()
    return batch


def run_validation(session_factory, batch_id: int) -> None:
    """后台任务入口：使用独立会话（session_factory 返回上下文管理器）。"""
    with session_factory() as db:
        try:
            validate_batch(db, batch_id)
        except Exception:
            db.rollback()
            batch = db.get(ImportBatch, batch_id)
            if batch is not None and batch.status == ImportStatus.VALIDATING:
                batch.status = ImportStatus.INTERRUPTED
                batch.validated_at = clock.now()
                db.commit()
            raise


# ---------------------------------------------------------------------------
# 批次视图（API-F09-02）
# ---------------------------------------------------------------------------
def issues_view(errors: list[dict] | None) -> list[dict]:
    out = []
    for e in errors or []:
        label, action, link = ISSUE_TYPES.get(e.get("type"), (e.get("type_label"), None, None))
        row = e["row"]
        if e.get("type") == "sku_unmapped":
            row = f"第 {row:,} 行起 · 共 {e.get('count', 1)} 行"
        out.append({"row": row, "type": label, "code": e.get("type"), "name": e.get("value") or None,
                    "action": action, "link": link})
    return out


def staged_periods(db: Session, batch_id: int) -> list[date]:
    rows = db.scalars(select(text("DISTINCT (data->>'month')::date")).select_from(ImportStaging)
                      .where(ImportStaging.batch_id == batch_id))
    return sorted(rows)


def existing_effective(db: Session, source: str, periods: list[date], *, lock: bool = False) -> list[ImportBatch]:
    q = select(ImportBatch).where(ImportBatch.source.in_(FAMILY[source]), ImportBatch.period.in_(periods),
                                  ImportBatch.status == ImportStatus.EFFECTIVE,
                                  ImportBatch.parent_batch_id.is_not(None)).order_by(ImportBatch.period)
    return list(db.scalars(q.with_for_update() if lock else q))


def overwrite_info(db: Session, source: str, periods: list[date]) -> list[dict]:
    """被覆盖的旧批次（按上传批次分组）：期间、文件名、导入人、导入时间（AC-F09-03、AC-F09-09）。"""
    groups: dict[int, list[ImportBatch]] = defaultdict(list)
    for child in existing_effective(db, source, periods):
        groups[child.parent_batch_id].append(child)
    out = []
    for parent_id, children in groups.items():
        parent = db.get(ImportBatch, parent_id)
        who = db.get(User, parent.confirmed_by or parent.uploaded_by)
        out.append({"periods": [fmt_month(c.period) for c in children], "file_name": parent.file_name,
                    "imported_by": who.name if who else "", "imported_at": fmt_dt(parent.confirmed_at)})
    return out


def kingdee_summary(db: Session, batch_id: int) -> dict:
    rows = db.execute(text(
        "SELECT a.pl_item, a.is_dept_expense, (s.data->>'unassigned')::boolean AS un, s.data->>'kingdee_code' AS code, "
        "count(*) AS n, sum((s.data->>'amount')::numeric) AS amt FROM import_staging s "
        "JOIN budget_account a ON a.id = (s.data->>'account_id')::int WHERE s.batch_id = :b "
        "GROUP BY 1, 2, 3, 4 ORDER BY 4"), {"b": batch_id}).all()
    names = dict(db.execute(select(KingdeeAccountMap.kingdee_code, KingdeeAccountMap.kingdee_name)).all())
    revenue = sum((amt for item, _d, _u, _c, _n, amt in rows if item == "revenue"), Decimal(0))
    cost = sum((amt for item, _d, _u, _c, _n, amt in rows if item != "revenue"), Decimal(0))
    unassigned = [{"code": code, "name": names.get(code) or "", "rows": n, "amount": dec_str(amt),
                   "amount_display": fmt_cny(amt)} for _i, _d, un, code, n, amt in rows if un]
    un_total = sum((amt for _i, _d, un, _c, _n, amt in rows if un), Decimal(0))
    return {"revenue_total": dec_str(revenue), "revenue_total_display": fmt_cny(revenue),
            "cost_total": dec_str(cost), "cost_total_display": fmt_cny(cost), "unassigned": unassigned,
            "unassigned_total": dec_str(un_total), "unassigned_total_display": fmt_cny(un_total)}


def bi_summary(db: Session, batch_id: int, limit: int = 200) -> dict:
    sku_count = db.scalar(text("SELECT count(DISTINCT data->>'sku_id') FROM import_staging WHERE batch_id = :b"),
                          {"b": batch_id})
    rows = db.execute(text(
        "SELECT (s.data->>'month')::date AS m, st.name, si.name, c.name, (s.data->>'is_new')::boolean, "
        "sum((s.data->>'qty')::numeric), sum((s.data->>'sales')::numeric), s.data->>'currency' "
        "FROM import_staging s JOIN store st ON st.id = (s.data->>'store_id')::int "
        "JOIN site si ON si.id = (s.data->>'site_id')::int JOIN category c ON c.id = (s.data->>'category_id')::int "
        "WHERE s.batch_id = :b GROUP BY 1, 2, 3, 4, 5, 8, c.sort ORDER BY 1, 2, c.sort, 5 DESC LIMIT :n"),
        {"b": batch_id, "n": limit}).all()
    return {"sku_count": sku_count, "rule": "该月最后一天早于首次上架日期加 12 个月为新品，否则为老品",
            "preview": [{"month": fmt_month(m), "store": st, "site": si, "category": c, "is_new": nw,
                         "is_new_label": "新品" if nw else "老品", "qty": dec_str(q),
                         "sales_local": dec_str(s), "sales_local_display": fmt_foreign(s, cur), "currency": cur}
                        for m, st, si, c, nw, q, s, cur in rows]}


def batch_view(db: Session, batch: ImportBatch) -> dict:
    if (batch.status == ImportStatus.VALIDATING and batch.uploaded_at
            and clock.now() - batch.uploaded_at > INTERRUPT_AFTER):
        # 校验线程已不在（如服务重启）：标为「校验中断，请重新上传」，避免悬挂
        batch.status = ImportStatus.INTERRUPTED
        db.commit()
    uploader = db.get(User, batch.uploaded_by)
    data = {
        "id": batch.id, "source": batch.source, "source_label": SOURCE_LABELS.get(batch.source, batch.source),
        "status": API_STATUS.get(batch.status, batch.status), "status_code": batch.status,
        "status_label": ImportStatus.LABELS[batch.status], "file_name": batch.file_name,
        "row_count": batch.row_count, "uploaded_by": uploader.name if uploader else "",
        "uploaded_at": fmt_dt(batch.uploaded_at), "validated_at": fmt_dt(batch.validated_at),
        "validation_seconds": str(round((batch.validated_at - batch.uploaded_at).total_seconds(), 1))
        if batch.validated_at and batch.uploaded_at else None,
        "issues": issues_view(batch.errors) if batch.status == ImportStatus.VALIDATION_FAILED else [],
        "needs_overwrite": False, "overwrite": [], "periods": [], "summary": None,
    }
    if batch.status == ImportStatus.VALIDATION_FAILED:
        errs = batch.errors or []
        data["issue_counts"] = _issue_counts(errs)
        data["unmapped_skus"] = [e["value"] for e in errs if e.get("type") == "sku_unmapped"]
    if batch.status == ImportStatus.PENDING_CONFIRM:
        periods = staged_periods(db, batch.id)
        data["periods"] = [fmt_month(p) for p in periods]
        info = overwrite_info(db, batch.source, periods)
        data["overwrite"] = info
        data["needs_overwrite"] = bool(info)
        data["summary"] = bi_summary(db, batch.id) if batch.source == ImportSource.BI else kingdee_summary(db, batch.id)
    if batch.status in (ImportStatus.EFFECTIVE, ImportStatus.REPLACED):
        children = db.scalars(select(ImportBatch).where(ImportBatch.parent_batch_id == batch.id)
                              .order_by(ImportBatch.period)).all()
        data["periods"] = [fmt_month(c.period) for c in children]
    return data


def _issue_counts(errors: list[dict]) -> list[dict]:
    counts: dict[str, int] = defaultdict(int)
    for e in errors:
        counts[ISSUE_TYPES.get(e.get("type"), (e.get("type_label"),))[0]] += 1
    return [{"type": k, "count": v} for k, v in counts.items()]


# ---------------------------------------------------------------------------
# 确认入库（API-F09-03）
# ---------------------------------------------------------------------------
_KINGDEE_INSERT = text(
    "INSERT INTO kingdee_actual (batch_id, row_no, month, department_id, store_id, site_id, customer_id, "
    "kingdee_code, account_id, amount, unassigned, summary) "
    "SELECT :child, s.row_no, (s.data->>'month')::date, (s.data->>'department_id')::int, "
    "(s.data->>'store_id')::int, (s.data->>'site_id')::int, (s.data->>'customer_id')::int, s.data->>'kingdee_code', "
    "(s.data->>'account_id')::int, (s.data->>'amount')::numeric, (s.data->>'unassigned')::boolean, "
    "s.data->>'summary' FROM import_staging s WHERE s.batch_id = :parent AND (s.data->>'month')::date = :m")
_BI_SKU_INSERT = text(
    "INSERT INTO bi_actual_sku (batch_id, row_no, month, store_id, site_id, sku_id, qty, sales_local, currency, "
    "ad_fee, platform_fee) SELECT :child, s.row_no, (s.data->>'month')::date, (s.data->>'store_id')::int, "
    "(s.data->>'site_id')::int, (s.data->>'sku_id')::int, (s.data->>'qty')::numeric, (s.data->>'sales')::numeric, "
    "s.data->>'currency', (s.data->>'ad_fee')::numeric, (s.data->>'platform_fee')::numeric "
    "FROM import_staging s WHERE s.batch_id = :parent AND (s.data->>'month')::date = :m")
_BI_AGG_INSERT = text(
    "INSERT INTO bi_actual_agg (batch_id, month, store_id, site_id, category_id, is_new, spu_count, qty, "
    "revenue_local, currency, revenue_cny) "
    "SELECT :child, x.m, x.store_id, x.site_id, x.category_id, x.is_new, count(DISTINCT x.spu_id), sum(x.qty), "
    "sum(x.sales), x.currency, sum(x.sales) * max(fx.rate) FROM ("
    " SELECT (s.data->>'month')::date AS m, (s.data->>'store_id')::int AS store_id, "
    " (s.data->>'site_id')::int AS site_id, (s.data->>'category_id')::int AS category_id, "
    " (s.data->>'is_new')::boolean AS is_new, (s.data->>'spu_id')::int AS spu_id, (s.data->>'qty')::numeric AS qty, "
    " (s.data->>'sales')::numeric AS sales, s.data->>'currency' AS currency "
    " FROM import_staging s WHERE s.batch_id = :parent AND (s.data->>'month')::date = :m) x "
    "LEFT JOIN fx_actual fx ON fx.month = x.m AND fx.currency = x.currency "
    "GROUP BY x.m, x.store_id, x.site_id, x.category_id, x.is_new, x.currency")


def confirm_batch(db: Session, actor: Actor, batch_id: int, *, overwrite: bool, base_url: str,
                  request=None) -> dict:
    """确认入库：调用方负责 commit；任何异常由调用方回滚，整次确认不留痕（RULE-05）。"""
    parent = db.scalar(select(ImportBatch).where(ImportBatch.id == batch_id).with_for_update())
    if parent is None or parent.parent_batch_id is not None:
        raise NotFound("导入批次不存在")
    if parent.status != ImportStatus.PENDING_CONFIRM:
        raise Conflict("该批次不是待确认状态", code="batch_not_pending",
                       details={"status": ImportStatus.LABELS[parent.status]})
    periods = staged_periods(db, parent.id)
    old_children = existing_effective(db, parent.source, periods, lock=True)
    if old_children and overwrite is not True:
        raise Conflict("所选期间已有导入数据，请确认覆盖", code="needs_overwrite",
                       details={"overwrite": overwrite_info(db, parent.source, periods)})
    now = clock.now()
    old_by_period = {c.period: c for c in old_children}
    replaced = []
    for period in periods:
        child = ImportBatch(source=parent.source, period=period, parent_batch_id=parent.id,
                            file_name=parent.file_name, file_path=parent.file_path, file_size=parent.file_size,
                            sha256=parent.sha256, status=ImportStatus.EFFECTIVE, uploaded_by=parent.uploaded_by,
                            uploaded_at=parent.uploaded_at, validated_at=parent.validated_at, confirmed_at=now,
                            confirmed_by=actor.id)
        db.add(child)
        db.flush()
        old = old_by_period.get(period)
        if old is not None:
            old.status = ImportStatus.REPLACED
            old.replaced_by_batch_id = child.id
            replaced.append(old)
        params = {"child": child.id, "parent": parent.id, "m": period}
        if parent.source == ImportSource.BI:
            child.row_count = db.execute(_BI_SKU_INSERT, params).rowcount
            db.execute(_BI_AGG_INSERT, params)
        else:
            child.row_count = db.execute(_KINGDEE_INSERT, params).rowcount
    db.flush()
    # 旧上传批次的全部期间都被替换 → 上传批次「已被替换」；部分被替换保持「已生效」（DEC-F09-01）
    for old_parent_id in {c.parent_batch_id for c in replaced}:
        remaining = db.scalar(select(func.count()).select_from(ImportBatch).where(
            ImportBatch.parent_batch_id == old_parent_id, ImportBatch.status == ImportStatus.EFFECTIVE))
        if remaining == 0:
            old_parent = db.get(ImportBatch, old_parent_id)
            old_parent.status = ImportStatus.REPLACED
            old_parent.replaced_by_batch_id = parent.id
    db.execute(ImportStaging.__table__.delete().where(ImportStaging.batch_id == parent.id))
    parent.status = ImportStatus.EFFECTIVE
    parent.confirmed_at = now
    parent.confirmed_by = actor.id
    db.flush()
    stats = alerting.evaluate(db, periods, base_url=base_url, import_batch_id=parent.id, actor=actor)
    audit(db, actor, action="import_confirmed", object_type="import_batch", object_id=parent.id, request=request,
          after={"source": parent.source, "file_name": parent.file_name, "periods": [fmt_month(p) for p in periods],
                 "overwrite": bool(replaced),
                 "replaced": [{"batch_id": c.id, "period": fmt_month(c.period), "file_name": c.file_name}
                              for c in replaced],
                 "alerts_created": stats["created"], "alerts_updated": stats["updated"]})
    view = batch_view(db, parent)
    view["alerts"] = stats
    return view


def discard_batch(db: Session, actor: Actor, batch_id: int) -> dict:
    batch = db.scalar(select(ImportBatch).where(ImportBatch.id == batch_id).with_for_update())
    if batch is None or batch.parent_batch_id is not None:
        raise NotFound("导入批次不存在")
    if batch.status != ImportStatus.PENDING_CONFIRM:
        raise Conflict("该批次不是待确认状态", code="batch_not_pending")
    db.execute(ImportStaging.__table__.delete().where(ImportStaging.batch_id == batch.id))
    batch.status = ImportStatus.DISCARDED
    audit(db, actor, action="import_discarded", object_type="import_batch", object_id=batch.id,
          after={"file_name": batch.file_name})
    db.flush()
    return batch_view(db, batch)


# ---------------------------------------------------------------------------
# 导入记录与概览（API-F09-04）
# ---------------------------------------------------------------------------
def list_records(db: Session, source: str | None = None) -> list[dict]:
    q = (select(ImportBatch).where(ImportBatch.parent_batch_id.is_(None),
                                   ImportBatch.status.in_((ImportStatus.EFFECTIVE, ImportStatus.REPLACED)))
         .order_by(ImportBatch.confirmed_at.desc(), ImportBatch.id.desc()))
    if source:
        q = q.where(ImportBatch.source.in_(FAMILY.get(source, (source,))) if source != ImportSource.BI
                    else ImportBatch.source == ImportSource.BI)
    out = []
    for parent in db.scalars(q):
        children = db.scalars(select(ImportBatch).where(ImportBatch.parent_batch_id == parent.id)
                              .order_by(ImportBatch.period)).all()
        replaced = []
        for c in children:
            if c.status == ImportStatus.REPLACED and c.replaced_by_batch_id:
                by = db.get(ImportBatch, c.replaced_by_batch_id)
                who = db.get(User, by.confirmed_by) if by and by.confirmed_by else None
                replaced.append({"period": fmt_month(c.period), "by_file_name": by.file_name if by else "",
                                 "by": who.name if who else "", "at": fmt_dt(by.confirmed_at) if by else None})
        who = db.get(User, parent.confirmed_by or parent.uploaded_by)
        periods = [fmt_month(c.period) for c in children]
        out.append({"id": parent.id, "source": parent.source, "source_label": SOURCE_LABELS.get(parent.source),
                    "periods": periods, "period_text": _period_text(periods), "file_name": parent.file_name,
                    "row_count": parent.row_count, "imported_by": who.name if who else "",
                    "imported_at": fmt_dt(parent.confirmed_at), "status": parent.status,
                    "status_label": "生效" if parent.status == ImportStatus.EFFECTIVE else "已被替换",
                    "replaced": replaced})
    return out


def _period_text(periods: list[str]) -> str:
    if not periods:
        return "—"
    return periods[0] if len(periods) == 1 else f"{periods[0]} 至 {periods[-1]}（{len(periods)} 个期间）"


def overview(db: Session, today: date) -> dict:
    def latest(sources) -> str | None:
        m = db.scalar(select(func.max(ImportBatch.period)).where(ImportBatch.source.in_(sources),
                                                                 ImportBatch.status == ImportStatus.EFFECTIVE))
        return fmt_month(m) if m else None
    kd = {p for p in db.scalars(select(ImportBatch.period).where(
        ImportBatch.source.in_(FAMILY[ImportSource.KINGDEE]), ImportBatch.status == ImportStatus.EFFECTIVE,
        ImportBatch.period.is_not(None)))}
    start = date(today.year - 2, 1, 1)
    grid = [{"month": fmt_month(add_months(start, i)), "imported": add_months(start, i) in kd} for i in range(24)]
    return {"kingdee_latest": latest(FAMILY[ImportSource.KINGDEE]), "bi_latest": latest((ImportSource.BI,)),
            "history_grid": grid, "history_imported": sum(g["imported"] for g in grid),
            "has_records": db.scalar(select(func.count()).select_from(ImportBatch).where(
                ImportBatch.status.in_((ImportStatus.EFFECTIVE, ImportStatus.REPLACED)))) > 0}



# ---------------------------------------------------------------------------
# BI 与金蝶核对（API-F09-05；AC-F09-07、AC-F02-08）
# ---------------------------------------------------------------------------
OVER_LIMIT = Decimal("0.03")


def reconciliation(db: Session, month: date, *, channel_id: int | None = None, over_only: bool = False) -> dict:
    """按「月 × 店铺 × 站点」：BI 折人民币 = BI 本币销售额 × 当月平均汇率；差异率 =（BI 折人民币 − 金蝶收入）÷ 金蝶收入。"""
    from app.models import BiActualAgg, Channel, FxActual, KingdeeActual

    def effective(sources) -> list[int]:
        return list(db.scalars(select(ImportBatch.id).where(ImportBatch.source.in_(sources),
                                                            ImportBatch.status == ImportStatus.EFFECTIVE,
                                                            ImportBatch.period == month)))
    bi_ids, kd_ids = effective((ImportSource.BI,)), effective(FAMILY[ImportSource.KINGDEE])
    def periods(sources) -> set[date]:
        return set(db.scalars(select(ImportBatch.period).where(ImportBatch.source.in_(sources),
                                                               ImportBatch.status == ImportStatus.EFFECTIVE,
                                                               ImportBatch.period.is_not(None))))
    months_ready = sorted(periods((ImportSource.BI,)) & periods(FAMILY[ImportSource.KINGDEE]))
    base = {"month": fmt_month(month), "ready_months": [fmt_month(m) for m in months_ready],
            "bi_imported": bool(bi_ids), "kingdee_imported": bool(kd_ids), "rows": [], "kpis": None, "rates": []}
    if not bi_ids or not kd_ids:
        return base
    bi = {(s, si): v for s, si, v in db.execute(
        select(BiActualAgg.store_id, BiActualAgg.site_id, func.sum(BiActualAgg.revenue_local))
        .where(BiActualAgg.batch_id.in_(bi_ids)).group_by(BiActualAgg.store_id, BiActualAgg.site_id))}
    kd = {(s, si): v for s, si, v in db.execute(
        select(KingdeeActual.store_id, KingdeeActual.site_id, func.sum(KingdeeActual.amount))
        .join(BudgetAccount, BudgetAccount.id == KingdeeActual.account_id)
        .where(KingdeeActual.batch_id.in_(kd_ids), BudgetAccount.pl_item == "revenue",
               KingdeeActual.store_id.is_not(None))
        .group_by(KingdeeActual.store_id, KingdeeActual.site_id))}
    rates = dict(db.execute(select(FxActual.currency, FxActual.rate).where(FxActual.month == month)).all())
    stores = {s.id: s for s in db.scalars(select(Store))}
    channels = {c.id: c for c in db.scalars(select(Channel))}
    sites = {s.id: s for s in db.scalars(select(Site))}
    rows, used_rates = [], {}
    zero = Decimal(0)
    # 核对对象为 BI 中出现的组合；金蝶无对应收入时按 0 计（差异率「—」，标注「金蝶无收入」）
    for key in sorted(set(bi), key=lambda k: (stores[k[0]].channel_id, stores[k[0]].id)):
        store, site = stores[key[0]], sites.get(key[1])
        channel = channels[store.channel_id]
        local, kingdee = bi.get(key), kd.get(key, zero)
        rate = rates.get(store.currency) if store.currency != "CNY" else Decimal(1)
        row = {"store_id": store.id, "store": store.name, "site": site.name if site else "", "channel": channel.name,
               "channel_id": channel.id, "currency": store.currency,
               "bi_local": dec_str(local), "bi_local_display": fmt_foreign(local, store.currency) if local is not None
               else "—", "rate": format(rate.quantize(Decimal("0.0001")), "f") if rate is not None else None,
               "kingdee": dec_str(kingdee), "kingdee_display": fmt_cny(kingdee), "bi_cny": None, "bi_cny_display": "—",
               "diff": None, "diff_display": "—", "diff_rate": None, "diff_rate_display": "—", "over": False,
               "note": None, "counted": True}
        if rate is None:
            row.update(counted=False, note=f"缺少 {fmt_month(month)} 汇率（{store.currency} 当月平均汇率未录入）")
        else:
            used_rates[store.currency] = rate
            bi_cny = (local or zero) * rate
            diff = bi_cny - kingdee
            row.update(bi_cny=dec_str(bi_cny), bi_cny_display=fmt_cny(bi_cny), diff=dec_str(diff),
                       diff_display=_signed_cny(diff))
            if kingdee == 0:
                row.update(over=bool(bi_cny), note="金蝶无收入" if bi_cny else None)
            else:
                ratio = diff / kingdee
                row.update(diff_rate=dec_str(ratio * 100), diff_rate_display=_signed_pct(ratio),
                           over=abs(ratio) > OVER_LIMIT)
        rows.append(row)
    counted = [r for r in rows if r["counted"]]
    bi_total = sum((Decimal(r["bi_cny"]) for r in counted), zero)
    kd_total = sum((Decimal(r["kingdee"]) for r in counted), zero)
    base["kpis"] = {"combos": len(counted), "over": sum(r["over"] for r in counted),
                    "bi_cny_total": dec_str(bi_total), "bi_cny_total_display": fmt_cny(bi_total),
                    "kingdee_total": dec_str(kd_total), "kingdee_total_display": fmt_cny(kd_total),
                    "missing_rate": [r["note"] for r in rows if not r["counted"]]}
    base["rates"] = [{"currency": c, "rate": format(r.quantize(Decimal("0.0001")), "f")} for c, r in sorted(used_rates.items())]
    if channel_id:
        rows = [r for r in rows if r["channel_id"] == channel_id]
    if over_only:
        rows = [r for r in rows if r["over"]]
    base["rows"] = rows
    base["channels"] = [{"id": c.id, "name": c.name} for c in sorted(channels.values(), key=lambda c: c.sort)]
    return base


def _signed_cny(value: Decimal) -> str:
    text_ = fmt_cny(abs(value))
    return ("+" if value > 0 else "−" if value < 0 else "") + text_


def _signed_pct(ratio: Decimal) -> str:
    from app.core.money import fmt_percent
    return fmt_percent(ratio, 2, signed=True)
