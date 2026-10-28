"""试用版演示数据（模拟）：补齐 2026 年未导入的基础数据，并走完 2027 年度预算闭环与 2027 年 1–3 月实际。

在 scripts.seed（主数据）与 scripts.import_ops_history（用户真实的 2026 年 1–9 月经营表，可选）之后运行：
    cd app/backend && python -m scripts.seed_demo [--database-url URL]
已写过演示数据时直接退出并提示（幂等）；库中已有非本脚本写入的 2027 年编制任务或实际数时不写入。

写入方式：尽量调用 services 里的真实业务函数（导入、填报、提交、审批、锁定、预警评估、快照），
派生值、审计日志、版本锁定与页面操作一致；全部步骤在同一个数据库事务内完成，失败则整体不写入。
业务时间按演示时间线推进（可注入时钟），结束后恢复。

1. 2026 年（缺什么补什么，已导入的真实数据不动）
   - SKU 对照表：库中没有 SKU 时上传演示对照表（每个品类 7 个 SPU，含 2026 年上架的新品）；
   - 金蝶实际：2026 年 1–9 月都没有实际时，按「历史金蝶」导入模拟数（店铺、B 端、部门费用、其他损益）；
     已有真实实际（经营历史表）时不模拟，只为有 2026 实际的店铺、客户、部门编制 2027 预算；
   - 当月平均汇率：2026 年 1–9 月各币种；
   - BI 实际：按该月该店铺金蝶收入折本币后拆到品类 / SKU（与金蝶差异多在 ±2% 内，每月个别店铺超过 3%）。
2. 2027 年度预算：发布编制任务 → 各填报单位按 2026 实际 × 增长率填驱动 → 提交 → 部门审核（含一次退回重提）
   → 财务负责人提交 CEO → CEO 通过，锁定为「年初原始目标」。
3. 2027 年 1–3 月实际：当月平均汇率、金蝶月度实际（导入后按生效预警规则评估）、BI 实际；Q1 滚动预测快照。
"""
from __future__ import annotations

import argparse
import random
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from io import BytesIO
from pathlib import Path

from openpyxl import Workbook
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.calc.periods import add_months, fmt_month, month_end, year_months
from app.config import get_settings
from app.core.audit import write_audit
from app.core.clock import TZ, clock
from app.core.scope import load_scope
from app.db import get_engine
from app.models import (Alert, AuditLog, B2bUnit, BCustomer, BudgetAccount, BudgetTask, BudgetVersion, Category,
                        Channel, ChannelCategoryRatio, ChannelSiteRatio, CompanyOtherPl, Department, DeptExpense,
                        FillingUnit, FxBudget, ImportBatch, KingdeeAccountMap, KingdeeActual, PlatformUnit,
                        Rule, RuleVersion, Site, Sku, Spu, Store, User, UserRole, UserScope)
from app.models.enums import (ImportSource, ImportStatus, Role, RuleType, RuleVersionStatus, ScopeType, UnitStatus,
                              UnitType)
from app.services import approval_units, filling, importer, masterdata, rules, tasking, versions
from app.services import prior_actuals as PA
from app.services import roles as roles_svc
from app.services.importer import is_new_product
from app.services.versions import Actor, as_actor
from scripts import seed_data as SD

MARK_ACTION = "demo_seed_completed"
YEAR = 2027
PRIOR = YEAR - 1
PRIOR_MONTHS = [date(PRIOR, m, 1) for m in range(1, 10)]     # 2026 年 1–9 月
ACTUAL_MONTHS = [date(YEAR, m, 1) for m in range(1, 4)]      # 2027 年 1–3 月
NEW_CHANNEL_START = date(YEAR, 1, 1)                          # 演示：新渠道 2027-01 起放量，Q1 可演示连续 2 个月预警

ZERO = Decimal(0)
ONE = Decimal(1)
HUNDRED = Decimal(100)
Q2 = Decimal("0.01")
Q4 = Decimal("0.0001")

KINGDEE_HEADER = ["期间", "金蝶科目", "科目名称", "部门", "平台/店铺", "站点", "客户", "摘要", "发生额"]
BI_HEADER = ["月份", "店铺", "站点", "SKU", "销量", "本币销售额", "币种", "广告费", "平台费用"]
SKU_HEADER = ["SKU", "SPU 编码", "品类", "首次上架日期"]

# ---------------------------------------------------------------------------
# 模拟参数（默认值；有 2026 实际时以实际为准）
# ---------------------------------------------------------------------------
CATEGORY_CODE = {"框镜": "FM", "灯镜": "LM", "镜柜": "MC", "浴室门": "SD", "浴室柜": "BV"}
CATEGORY_WEIGHT = {"框镜": "0.24", "灯镜": "0.30", "镜柜": "0.20", "浴室门": "0.10", "浴室柜": "0.16"}
CATEGORY_PRICE_USD = {"框镜": "89.99", "灯镜": "169.99", "镜柜": "239.99", "浴室门": "459.99", "浴室柜": "629.99"}
# 采购成本占比相对渠道站点平均值的品类差异（浴室门 / 浴室柜 体积大、成本高）
CATEGORY_PURCHASE_OFFSET = {"框镜": "-0.010", "灯镜": "-0.025", "镜柜": "0.005", "浴室门": "0.020",
                            "浴室柜": "0.010"}
CATEGORY_FIRST_LEG_OFFSET = {"浴室门": "0.010", "浴室柜": "0.008"}
# 每个品类的 SPU：(尺寸, 首次上架日期)；2025-04、2026-03、2026-08 上架的为演示期内的新品
SPU_PLAN = [("2030", date(2022, 4, 18)), ("2436", date(2023, 3, 6)), ("3036", date(2023, 10, 16)),
            ("2448", date(2024, 6, 3)), ("3048", date(2025, 4, 21)), ("3660", date(2026, 3, 16)),
            ("4060", date(2026, 8, 24))]
SKU_COLORS = ["WH", "BK", "GD"]
CURRENCY_PRICE_FACTOR = {"USD": "1", "CAD": "1.36", "GBP": "0.79", "EUR": "0.92", "CNY": "7.10"}

# 无 2026 实际时店铺月收入（人民币）= 渠道基数 × 站点系数 ÷ 同渠道同站点店铺数
CHANNEL_BASE = {"Amazon": 6500000, "Wayfair": 2600000, "Home Depot": 1800000, "Lowe's": 1200000, "独立站": 600000,
                "TikTok Shop": 400000}
DEFAULT_CHANNEL_BASE = 500000
SITE_FACTOR = {"US": "1", "CA": "0.30", "UK": "0.25", "DE": "0.20"}
SEASON_2026 = ["0.93", "0.86", "0.97", "0.98", "1.00", "0.97", "1.06", "1.02", "0.99"]
Q4_FACTOR = {10: "1.03", 11: "1.24", 12: "1.13"}
NEW_CHANNEL_RAMP_BASE = Decimal(180000)   # 新渠道首月人民币收入，此后每月 +12%
NEW_CHANNEL_RAMP_STEP = Decimal("1.12")

# 渠道默认费率（无 2026 实际时）
DEFAULT_COMMISSION = {"Amazon": "0.15", "Wayfair": "0.17", "Home Depot": "0.12", "Lowe's": "0.12", "独立站": "0.03",
                      "TikTok Shop": "0.08"}
DEFAULT_PROMOTION = {"Amazon": "0.10", "Wayfair": "0.05", "Home Depot": "0.03", "Lowe's": "0.03", "独立站": "0.15",
                     "TikTok Shop": "0.18"}
DEFAULT_DISCOUNT = {"独立站": "0.12", "TikTok Shop": "0.15"}
PLATFORM_DEFAULTS = {"refund": "0.060", "purchase_cost": "0.320", "first_leg": "0.060", "last_mile": "0.080",
                     "tariff": "0.040", "storage": "0.020", "inventory_claim": "0.003", "other_opex": "0.010"}
B2B_DEFAULTS = {"refund": "0.020", "commission": "0", "promotion": "0.010", "inventory_claim": "0",
                "other_opex": "0.005", "purchase_cost": "0.450", "first_leg": "0.050", "last_mile": "0.020",
                "storage": "0.010", "tariff": "0.040"}
B2B_BASE = [3800000, 2400000, 1700000, 1200000]
B2B_GROWTH = Decimal("0.10")
# 部门费用月度模板（人民币，部门系数 0.6～1.4）
DEPT_TEMPLATE = {"工资薪酬": 180000, "社保公积金": 45000, "培训费": 4000, "员工关怀费": 6000, "差旅费": 12000,
                 "办公费": 6000, "房租物业": 22000, "招聘费": 5000, "软件服务费": 8000, "业务招待费": 5000}
DEPT_TEMPLATE_DEFAULT = 3000
# 当月平均汇率：基准 × (1 + 月度波动)
FX_ACTUAL_BASE = {"USD": "7.18", "CAD": "5.27", "GBP": "9.26", "EUR": "7.83"}
FX_DRIFT = {**{date(PRIOR, m, 1): d for m, d in zip(range(1, 10), ["0", "-0.004", "0.003", "0.006", "0.001",
                                                                   "-0.002", "-0.005", "-0.007", "-0.009"])},
            **{date(YEAR, m, 1): d for m, d in zip(range(1, 4), ["-0.012", "-0.015", "-0.011"])}}

GP_ITEMS = ("revenue", "refund", "purchase_cost", "commission", "promotion", "first_leg", "last_mile", "tariff",
            "storage", "inventory_claim", "other_opex")
COST_ITEMS = GP_ITEMS[1:]
OTHER_ITEMS = ("finance_cost", "fx_gain_loss", "non_operating", "income_tax")


class DemoError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------
def D(v) -> Decimal:
    return v if isinstance(v, Decimal) else Decimal(str(v))


def q2(v: Decimal) -> Decimal:
    return v.quantize(Q2, ROUND_HALF_UP)


def q4(v: Decimal) -> Decimal:
    return v.quantize(Q4, ROUND_HALF_UP)


def rnd(*key) -> random.Random:
    """按键确定的随机数（每次运行结果相同）。"""
    return random.Random("demo:" + ":".join(str(k) for k in key))


def jitter(lo: str, hi: str, *key) -> Decimal:
    return D(f"{rnd(*key).uniform(float(lo), float(hi)):.4f}")


def clamp_rate(v: Decimal) -> Decimal:
    return q4(min(max(v, ZERO), D("0.9")))


def pct(rate: Decimal) -> str:
    """比率 → 填报输入的百分数文本（最多 2 位小数）。"""
    return format(q2(rate * HUNDRED), "f")


def at(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=TZ)


def xlsx(header: list, rows: list[list]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(header)
    for r in rows:
        ws.append(r)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


@dataclass
class SpuInfo:
    id: int
    code: str
    category_id: int
    first: date
    skus: list[str]
    price_usd: Decimal
    weight: Decimal


@dataclass
class Demo:
    db: Session
    settings: object
    data_dir: Path
    real_prior: bool = False    # 运行前库中已有 2026 实际（经营历史表 / 金蝶）：只为有实际的店铺、客户、部门编制
    log: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    # ---- 人员 ----
    def user(self, userid: str) -> User:
        u = self.db.scalar(select(User).where(User.dingtalk_userid == userid))
        if u is None:
            raise DemoError(f"找不到人员 {userid}，请先运行 python -m scripts.seed")
        return u

    def actor(self, userid: str) -> Actor:
        return as_actor(self.db, self.user(userid))

    def actor_of(self, user_id: int) -> Actor:
        return as_actor(self.db, self.db.get(User, user_id))

    def say(self, text: str) -> None:
        self.log.append(text)
        print(text, flush=True)


PEOPLE = {p[0]: p for p in SD.PEOPLE}
FINANCE_HEAD = next(p[0] for p in SD.PEOPLE if "finance_head" in p[3])
FINANCE_BP = next(p[0] for p in SD.PEOPLE if "finance_bp" in p[3])
CEO = next(p[0] for p in SD.PEOPLE if "ceo" in p[3])


# ---------------------------------------------------------------------------
# 幂等检查
# ---------------------------------------------------------------------------
def already_done(db: Session) -> bool:
    return db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == MARK_ACTION)) > 0


def foreign_data(db: Session) -> str | None:
    if db.scalar(select(func.count()).select_from(BudgetTask).where(BudgetTask.year == YEAR)):
        return f"库中已有 {YEAR} 年度编制任务"
    if db.scalar(select(func.count()).select_from(BudgetVersion).where(BudgetVersion.year == YEAR)):
        return f"库中已有 {YEAR} 年度预算版本"
    if db.scalar(select(func.count()).select_from(ImportBatch).where(
            ImportBatch.status == ImportStatus.EFFECTIVE, ImportBatch.period >= date(YEAR, 1, 1))):
        return f"库中已有 {YEAR} 年实际数"
    return None


# ---------------------------------------------------------------------------
# 主数据辅助
# ---------------------------------------------------------------------------
def active_stores(db: Session) -> list[Store]:
    return list(db.scalars(select(Store).where(Store.is_active.is_(True)).order_by(Store.id)))


def channels(db: Session) -> dict[int, Channel]:
    return {c.id: c for c in db.scalars(select(Channel))}


def sites(db: Session) -> dict[int, Site]:
    return {s.id: s for s in db.scalars(select(Site))}


def categories(db: Session) -> list[Category]:
    return list(db.scalars(select(Category).order_by(Category.sort, Category.id)))


def account_codes(db: Session) -> dict[int, tuple[str, str]]:
    """预算科目 → (金蝶科目编码, 科目名称)，同一科目多个编码时取编码最小者。"""
    out: dict[int, tuple[str, str]] = {}
    for m in db.scalars(select(KingdeeAccountMap).where(KingdeeAccountMap.account_id.is_not(None))
                        .order_by(KingdeeAccountMap.kingdee_code)):
        out.setdefault(m.account_id, (m.kingdee_code, m.kingdee_name or ""))
    return out


def item_accounts(db: Session) -> dict[str, BudgetAccount]:
    out: dict[str, BudgetAccount] = {}
    for a in db.scalars(select(BudgetAccount).where(BudgetAccount.is_dept_expense.is_(False))
                        .order_by(BudgetAccount.is_active.desc(), BudgetAccount.sort, BudgetAccount.id)):
        if a.pl_item:
            out.setdefault(a.pl_item, a)
    return out


def dept_accounts(db: Session) -> list[BudgetAccount]:
    return masterdata.dept_expense_accounts(db)


def new_channel_store(db: Session) -> Store | None:
    return db.scalar(select(Store).where(Store.name == SD.NEW_CHANNEL_STORE[0]))


def store_start(db: Session, store: Store) -> date | None:
    return filling.new_channel_start(db, store)


def currencies_in_use(db: Session) -> list[str]:
    cur = set(db.scalars(select(Store.currency))) | set(db.scalars(select(BCustomer.currency)))
    return sorted(c for c in cur if c and c != "CNY")


def effective_kingdee_months(db: Session) -> set[date]:
    return versions.actual_months(db)


def effective_bi_months(db: Session) -> set[date]:
    return set(db.scalars(select(ImportBatch.period).where(ImportBatch.source == ImportSource.BI,
                                                           ImportBatch.status == ImportStatus.EFFECTIVE,
                                                           ImportBatch.period.is_not(None))))


# ---------------------------------------------------------------------------
# 导入（与页面同一服务流程：上传 → 校验 → 确认）
# ---------------------------------------------------------------------------
def run_import(demo: Demo, actor: Actor, source: str, file_name: str, header: list, rows: list[list]) -> dict:
    db = demo.db
    batch = importer.create_batch(db, actor, source=source, file_name=file_name, content=xlsx(header, rows),
                                  data_dir=demo.data_dir)
    db.commit()
    importer.validate_batch(db, batch.id)
    view = importer.batch_view(db, db.get(ImportBatch, batch.id))
    if view["status"] != "passed":
        issues = "；".join(f"第 {i['row']} 行 {i['type']} {i['name'] or ''}" for i in view["issues"][:10])
        raise DemoError(f"{file_name} 校验未通过：{issues}")
    if view["needs_overwrite"]:
        raise DemoError(f"{file_name} 的期间已有实际数，演示脚本不覆盖：{'、'.join(view['periods'])}")
    result = importer.confirm_batch(db, actor, batch.id, overwrite=False, base_url=demo.settings.APP_BASE_URL)
    db.commit()
    alerts = result.get("alerts") or {}
    demo.say(f"  导入 {file_name}：{len(rows)} 行，期间 {'、'.join(view['periods'])}"
             + (f"，新增预警 {alerts.get('created', 0)} 条" if alerts.get("created") else ""))
    return result


# ---------------------------------------------------------------------------
# 人员范围：新店铺分给同渠道运营；部门预算专员覆盖有负责人的部门
# ---------------------------------------------------------------------------
def _save_scopes(demo: Demo, user: User, *, departments=None, stores=None) -> None:
    db = demo.db
    snap = roles_svc.snapshot(db, user.id)
    scopes = snap["scopes"]
    deps = sorted(set(scopes[ScopeType.DEPARTMENT]) | set(departments or []))
    sts = sorted(set(scopes[ScopeType.STORE]) | set(stores or []))
    if deps == sorted(scopes[ScopeType.DEPARTMENT]) and sts == sorted(scopes[ScopeType.STORE]):
        return
    before, after = roles_svc.save_user_roles(db, user, snap["roles"], deps, scopes[ScopeType.CHANNEL], sts,
                                              scopes[ScopeType.CUSTOMER])
    write_audit(db, action="assign_roles", object_type="user_role", object_id=user.id, before=before, after=after,
                actor=demo.actor(FINANCE_HEAD))


def participating_stores(demo: Demo) -> list[Store]:
    """参与编制与 2027 模拟实际的店铺：全部启用店铺；库中已有真实 2026 实际时，只取有 2026 收入的店铺与新渠道演示店铺
    （没有实际的样例店铺按默认值编预算会与真实数据不可比）。"""
    db = demo.db
    stores = active_stores(db)
    if not demo.real_prior:
        return stores
    new_store = new_channel_store(db)
    return [s for s in stores if (new_store is not None and s.id == new_store.id)
            or any(v.get("revenue", ZERO) > 0 for v in prior_store_items(db, s.id).values())]


def participating_customers(demo: Demo) -> list[BCustomer]:
    db = demo.db
    customers = list(db.scalars(select(BCustomer).where(BCustomer.is_active.is_(True)).order_by(BCustomer.id)))
    if not demo.real_prior:
        return customers
    return [c for c in customers
            if any(v.get("revenue", ZERO) > 0 for v in PA.by_month(db, PRIOR, customer_ids=[c.id]).values())]


def public_owner(db: Session) -> Department | None:
    """公司公共费用（2026 实际中负责部门不在主数据、记为未分部门的管理费用）2027 年起的归口部门：CEO 所在部门。
    部门费用预算必须落在部门上（平台没有「公司公共」预算），归口后预算与实际同口径对比。"""
    ceo = db.scalar(select(User).where(User.dingtalk_userid == CEO))
    return db.get(Department, ceo.department_id) if ceo is not None and ceo.department_id else None


def depts_with_prior(db: Session) -> set[int]:
    """有 2026 部门费用实际的部门（含归口了公司公共费用的部门）。"""
    prior = prior_dept_actuals(db)
    out = {d for d, _acc in prior if d is not None}
    owner = public_owner(db)
    if owner is not None and any(d is None for d, _acc in prior):
        out.add(owner.id)
    return out


def participating_departments(db: Session) -> list[Department]:
    """参与部门费用编制的部门：有启用负责人（审核人）的启用部门；库中已有 2026 部门费用实际时，
    只取有实际的部门（没有实际的部门按模板编预算会与真实数据不可比）。"""
    with_actual = depts_with_prior(db)
    out = []
    for d in db.scalars(select(Department).where(Department.is_active.is_(True))
                        .order_by(Department.sort, Department.id)):
        head = db.get(User, d.head_user_id) if d.head_user_id else None
        if head is not None and head.is_active and (not with_actual or d.id in with_actual):
            out.append(d)
    return out


def ensure_heads(demo: Demo) -> None:
    """有 2026 部门费用实际、但没有负责人的部门：演示中由 CEO 直管（加部门负责人角色），这些部门才能编制与审核，
    2027 模拟实际都有对应预算。"""
    db = demo.db
    headless = []
    for dept_id in sorted(depts_with_prior(db)):
        d = db.get(Department, dept_id)
        head = db.get(User, d.head_user_id) if d.head_user_id else None
        if d.is_active and (head is None or not head.is_active):
            headless.append(d)
    if not headless:
        return
    ceo = demo.user(CEO)
    snap = roles_svc.snapshot(db, ceo.id)
    scopes = snap["scopes"]
    roles = sorted(set(snap["roles"]) | {Role.DEPT_HEAD})
    deps = sorted(set(scopes[ScopeType.DEPARTMENT]) | {d.id for d in headless})
    before, after = roles_svc.save_user_roles(db, ceo, roles, deps, scopes[ScopeType.CHANNEL],
                                              scopes[ScopeType.STORE], scopes[ScopeType.CUSTOMER])
    write_audit(db, action="assign_roles", object_type="user_role", object_id=ceo.id, before=before, after=after,
                actor=demo.actor(FINANCE_HEAD))
    demo.say(f"  以下部门有 {PRIOR} 年费用实际但没有负责人，演示中由 CEO {ceo.name} 直管审核："
             f"{'、'.join(d.name for d in headless)}")


def ensure_scopes(demo: Demo) -> None:
    db = demo.db
    ops = list(db.scalars(select(User).join(UserRole, UserRole.user_id == User.id)
                          .where(UserRole.role_code == Role.OPERATIONS, User.is_active.is_(True)).order_by(User.id)))
    if not ops:
        raise DemoError("没有运营人员，无法生成平台渠道填报单位")
    for store in participating_stores(demo):
        holders = [u for u in ops if store.id in load_scope(db, u.id, [Role.OPERATIONS]).store_ids]
        if holders:
            continue
        same_channel = [u for u in ops if db.scalar(
            select(func.count()).select_from(UserScope).join(Store, Store.id == UserScope.object_id)
            .where(UserScope.user_id == u.id, UserScope.scope_type == ScopeType.STORE,
                   Store.channel_id == store.channel_id))]
        pick = same_channel[0] if same_channel else min(
            ops, key=lambda u: (len(load_scope(db, u.id, [Role.OPERATIONS]).store_ids), u.id))
        _save_scopes(demo, pick, stores=[store.id])
        demo.say(f"  店铺 {store.name} 没有填报人，分给运营 {pick.name}")
    budget_users = list(db.scalars(select(User).join(UserRole, UserRole.user_id == User.id)
                                   .where(UserRole.role_code == Role.DEPT_BUDGET, User.is_active.is_(True))
                                   .order_by(User.id)))
    if not budget_users:
        return
    covered = set(db.scalars(select(UserScope.object_id).join(UserRole, UserRole.user_id == UserScope.user_id)
                             .where(UserRole.role_code == Role.DEPT_BUDGET,
                                    UserScope.scope_type == ScopeType.DEPARTMENT)))
    missing = [d for d in participating_departments(db) if d.id not in covered]
    if missing:
        _save_scopes(demo, budget_users[0], departments=[d.id for d in missing])
        demo.say(f"  部门预算专员 {budget_users[0].name} 增加负责：{'、'.join(d.name for d in missing)}")


# ---------------------------------------------------------------------------
# SKU 对照表与品类构成
# ---------------------------------------------------------------------------
def ensure_sku_table(demo: Demo) -> None:
    db = demo.db
    if masterdata.sku_count(db):
        demo.say(f"  SKU 对照表已有 {masterdata.sku_count(db)} 个 SKU，沿用")
        return
    rows = []
    for ci, cat in enumerate(categories(db)):
        prefix = CATEGORY_CODE.get(cat.name, f"C{ci + 1}")
        for j, (size, listed) in enumerate(SPU_PLAN):
            first = listed + timedelta(days=9 * ci)
            spu = f"SPU-{prefix}-{size}"
            for k in range(2 + (ci + j) % 2):
                rows.append([f"{prefix}-{size}-{SKU_COLORS[k]}", spu, cat.name,
                             (first + timedelta(days=20 * k)).isoformat()])
    bp = demo.user(FINANCE_BP)
    actor = demo.actor(FINANCE_BP)
    res = masterdata.upload_sku_mapping(db, bp.id, "SKU对照表_演示.xlsx", xlsx(SKU_HEADER, rows))
    write_audit(db, action="sku_upload_validate", object_type="import_batch", object_id=res["id"],
                after={"status": res["status"], "issues": len(res["issues"]), "file_name": res["file_name"]},
                actor=actor)
    if res["status"] != "passed":
        raise DemoError(f"演示 SKU 对照表校验未通过：{res['issues'][:5]}")
    batch = masterdata.get_sku_batch(db, res["id"])
    done = masterdata.confirm_sku_mapping(db, bp.id, batch)
    write_audit(db, action="sku_upload_confirm", object_type="import_batch", object_id=batch.id,
                after={"added": done["added"], "updated": done["updated"], "file_name": batch.file_name}, actor=actor)
    demo.say(f"  上传 SKU 对照表：{len(rows)} 个 SKU")


def catalog(db: Session) -> list[SpuInfo]:
    cat_names = {c.id: c.name for c in categories(db)}
    skus: dict[int, list[str]] = defaultdict(list)
    for code, spu_id in db.execute(select(Sku.code, Sku.spu_id).order_by(Sku.code)):
        skus[spu_id].append(code)
    out = []
    for spu in db.scalars(select(Spu).order_by(Spu.code)):
        if not skus.get(spu.id):
            continue
        base = D(CATEGORY_PRICE_USD.get(cat_names.get(spu.category_id, ""), "199.99"))
        out.append(SpuInfo(spu.id, spu.code, spu.category_id, spu.first_listed_on, skus[spu.id],
                           q2(base * jitter("0.85", "1.15", "price", spu.code)),
                           jitter("0.75", "1.25", "weight", spu.code)))
    return out


def spu_shares(db: Session, cat: list[SpuInfo], store: Store, month: date) -> list[tuple[SpuInfo, Decimal]]:
    """店铺当月在售 SPU 的收入占比：品类权重 × 店铺品类偏好，品类内按 SPU 权重（新品 × 0.85）。"""
    names = {c.id: c.name for c in categories(db)}
    active = [s for s in cat if s.first <= month_end(month)]
    by_cat: dict[int, list[SpuInfo]] = defaultdict(list)
    for s in active:
        by_cat[s.category_id].append(s)
    n = len(names) or 1
    cat_w = {cid: D(CATEGORY_WEIGHT.get(names.get(cid, ""), str(round(1 / n, 4))))
             * jitter("0.85", "1.15", "tilt", store.name, names.get(cid, cid)) for cid in by_cat}
    total_w = sum(cat_w.values(), ZERO)
    out = []
    for cid, items in by_cat.items():
        ws = {s.id: s.weight * (D("0.85") if is_new_product(s.first, month) else ONE) for s in items}
        tot = sum(ws.values(), ZERO)
        for s in items:
            out.append((s, cat_w[cid] / total_w * ws[s.id] / tot))
    return out


def price_factor(currency: str) -> Decimal:
    return D(CURRENCY_PRICE_FACTOR.get(currency, "1"))


# ---------------------------------------------------------------------------
# 汇率
# ---------------------------------------------------------------------------
def fx_actual_rate(db: Session, currency: str, month: date) -> Decimal | None:
    base = FX_ACTUAL_BASE.get(currency)
    if base is None:
        budget = db.scalar(select(FxBudget.rate).where(FxBudget.year == YEAR, FxBudget.currency == currency))
        if budget is None:
            return None
        base = budget
    return q4(D(base) * (ONE + D(FX_DRIFT.get(month, "0"))))


def ensure_fx_actual(demo: Demo, months: list[date]) -> None:
    db = demo.db
    bp = demo.user(FINANCE_BP)
    n = 0
    for m in months:
        for cur in currencies_in_use(db):
            if masterdata.actual_fx_rate(db, m, cur) is not None:
                continue
            rate = fx_actual_rate(db, cur, m)
            if rate is None:
                continue
            row, before = masterdata.save_actual_fx(db, bp.id, fmt_month(m), cur, format(rate, "f"))
            write_audit(db, action="save_fx_actual", object_type="fx_actual", object_id=f"{fmt_month(m)}-{cur}",
                        before={"rate": before} if before is not None else None, after={"rate": row.rate},
                        actor=demo.actor(FINANCE_BP))
            n += 1
    if n:
        demo.say(f"  录入当月平均汇率 {n} 条（{fmt_month(months[0])} 至 {fmt_month(months[-1])}）")
    demo.stats["fx_actual"] = demo.stats.get("fx_actual", 0) + n


def ensure_budget_fx(demo: Demo) -> None:
    db = demo.db
    have = set(db.scalars(select(FxBudget.currency).where(FxBudget.year == YEAR)))
    for cur in currencies_in_use(db):
        if cur in have:
            continue
        rate = fx_actual_rate(db, cur, date(PRIOR, 9, 1))
        if rate is None:
            raise DemoError(f"{YEAR} 年度缺少 {cur} 预算汇率，且无法推算，请先在「汇率」中录入")
        row, before, _n = masterdata.save_budget_fx(db, demo.user(FINANCE_BP).id, YEAR, cur, format(rate, "f"))
        write_audit(db, action="save_fx_budget", object_type="fx_budget", object_id=f"{YEAR}-{cur}",
                    before=None, after={"rate": row.rate}, actor=demo.actor(FINANCE_BP))
        demo.say(f"  补录 {YEAR} 年度 {cur} 预算汇率 {rate}")


# ---------------------------------------------------------------------------
# 2026 年模拟金蝶实际（只补没有实际的月份）
# ---------------------------------------------------------------------------
def default_store_revenue(db: Session, store: Store) -> Decimal:
    ch = db.get(Channel, store.channel_id)
    site = db.get(Site, store.site_id)
    peers = db.scalar(select(func.count()).select_from(Store).where(Store.channel_id == store.channel_id,
                                                                    Store.site_id == store.site_id,
                                                                    Store.is_active.is_(True))) or 1
    base = D(CHANNEL_BASE.get(ch.name, DEFAULT_CHANNEL_BASE)) * D(SITE_FACTOR.get(site.code, "0.30"))
    return base / peers


def default_platform_rates(db: Session, store: Store) -> dict[str, Decimal]:
    ch = db.get(Channel, store.channel_id)
    site = db.get(Site, store.site_id)
    rates = {k: D(v) for k, v in PLATFORM_DEFAULTS.items()}
    rates["commission"] = D(DEFAULT_COMMISSION.get(ch.name, "0.12"))
    rates["promotion"] = D(DEFAULT_PROMOTION.get(ch.name, "0.08"))
    if site.code != "US":
        rates["tariff"] = D("0.020")
    return rates


def default_customer_revenue(customer: BCustomer, index: int) -> Decimal:
    return D(B2B_BASE[index % len(B2B_BASE)])


def dept_factor(dept: Department) -> Decimal:
    return D("0.6") + D(rnd("dept-factor", dept.name).randint(0, 4) * 2) / 10


def dept_template(dept: Department, account: BudgetAccount) -> Decimal:
    return D(DEPT_TEMPLATE.get(account.name, DEPT_TEMPLATE_DEFAULT)) * dept_factor(dept)


def simulate_prior_kingdee(demo: Demo) -> None:
    db = demo.db
    done = effective_kingdee_months(db)
    months = [m for m in PRIOR_MONTHS if m not in done]
    if not months:
        demo.say(f"  {PRIOR} 年 1–9 月已有实际（经营历史表或金蝶），不模拟金蝶实际")
        return
    if demo.real_prior:
        demo.say(f"  {PRIOR} 年部分月份已有真实实际，缺少的 {'、'.join(fmt_month(m) for m in months)} 不模拟"
                 "（避免与真实数据混在一起），编制时按已有月份推算")
        return
    codes = account_codes(db)
    items = item_accounts(db)
    site_by = sites(db)
    rows: list[list] = []
    new_store = new_channel_store(db)

    def row(m: date, account: BudgetAccount, amount: Decimal, *, dept: str = "", store: Store | None = None,
            customer: str = "", summary: str) -> None:
        code = codes.get(account.id)
        if code is None or amount <= 0:
            return
        rows.append([fmt_month(m), code[0], code[1], dept, store.name if store else "",
                     site_by[store.site_id].code if store else "", customer, summary, float(q2(amount))])

    for m in months:
        season = D(SEASON_2026[m.month - 1])
        month_gp = ZERO
        month_rev = ZERO
        for store in active_stores(db):
            if new_store is not None and store.id == new_store.id:
                continue  # 新渠道 2027 年才开始放量，2026 年无实际
            rev = q2(default_store_revenue(db, store) * season * jitter("0.95", "1.05", "rev26", store.name, m))
            rates = default_platform_rates(db, store)
            month_rev += rev
            month_gp += rev
            row(m, items["revenue"], rev, store=store, summary=f"{fmt_month(m)} 平台销售收入")
            for item in COST_ITEMS:
                amt = q2(rev * rates[item] * jitter("0.94", "1.06", "cost26", store.name, m, item))
                month_gp += amt if item == "inventory_claim" else -amt
                row(m, items[item], amt, store=store, summary=f"{fmt_month(m)} {items[item].name}")
        for i, c in enumerate(db.scalars(select(BCustomer).where(BCustomer.is_active.is_(True))
                                         .order_by(BCustomer.id))):
            rev = q2(default_customer_revenue(c, i) * season * jitter("0.93", "1.07", "b2b26", c.name, m))
            month_rev += rev
            month_gp += rev
            row(m, items["revenue"], rev, customer=c.name, summary=f"{fmt_month(m)} B端销售收入")
            for item in COST_ITEMS:
                rate = D(B2B_DEFAULTS[item])
                amt = q2(rev * rate * jitter("0.94", "1.06", "b2bcost26", c.name, m, item))
                month_gp += amt if item == "inventory_claim" else -amt
                row(m, items[item], amt, customer=c.name, summary=f"{fmt_month(m)} {items[item].name}")
        unassigned = q2(month_rev * D("0.002"))
        month_gp -= unassigned
        row(m, items["storage"], unassigned, summary=f"{fmt_month(m)} 海外仓公共仓储（未分店铺）")
        dept_total = ZERO
        for dept in participating_departments(db):
            for acc in dept_accounts(db):
                lumpy = D("2") if acc.name == "培训费" and m.month in (3, 7) else ONE
                amt = q2(dept_template(dept, acc) / D("1.05") * lumpy
                         * jitter("0.94", "1.06", "dept26", dept.name, acc.name, m))
                dept_total += amt
                row(m, acc, amt, dept=dept.name, summary=f"{fmt_month(m)} {acc.name}")
        other = {"finance_cost": q2(D(11000) * jitter("0.8", "1.2", "fin26", m)),
                 "fx_gain_loss": q2(D(6000) * jitter("0.5", "1.5", "fx26", m)),
                 "non_operating": q2(D(2000) * jitter("0.5", "1.5", "nop26", m))}
        pre_tax = month_gp - dept_total - sum(other.values(), ZERO)
        other["income_tax"] = q2(max(pre_tax, ZERO) * D("0.15"))
        for item, amt in other.items():
            if item in items:
                row(m, items[item], amt, summary=f"{fmt_month(m)} {items[item].name}")
    file_name = f"金蝶_历史_{fmt_month(months[0])}至{fmt_month(months[-1])}_演示.xlsx"
    run_import(demo, demo.actor(FINANCE_BP), ImportSource.KINGDEE_HISTORY, file_name, KINGDEE_HEADER, rows)
    demo.stats["kingdee_prior_rows"] = len(rows)


# ---------------------------------------------------------------------------
# BI 实际：按金蝶收入拆到 SKU
# ---------------------------------------------------------------------------
def bi_rows(demo: Demo, months: list[date], rates: dict[int, dict[str, Decimal]]) -> list[list]:
    db = demo.db
    cat = catalog(db)
    if not cat:
        raise DemoError("SKU 对照表为空，无法生成 BI 实际")
    stores = {s.id: s for s in db.scalars(select(Store))}
    site_by = sites(db)
    rows: list[list] = []
    for m in months:
        kd = {s: rev for (mm, s), (rev, _gp) in versions.actual_store_monthly(db, [m]).items() if mm == m and rev > 0}
        flagged = sorted(kd)[(m.month + m.year) % len(kd)] if kd else None
        for store_id in sorted(kd):
            store = stores[store_id]
            fx = masterdata.actual_fx_rate(db, m, store.currency) if store.currency != "CNY" else ONE
            if fx is None:
                continue
            r = rnd("bi-diff", store.name, m)
            diff = D(f"{r.uniform(0.034, 0.045):.4f}") * (1 if r.random() < 0.5 else -1) if store_id == flagged \
                else D(f"{r.uniform(-0.021, 0.021):.4f}")
            local_total = kd[store_id] / fx * (ONE + diff)
            shares = spu_shares(db, cat, store, m)
            noisy = [(s, sh * jitter("0.90", "1.10", "bi-spu", store.name, s.code, m)) for s, sh in shares]
            tot = sum((x for _, x in noisy), ZERO)
            disc = D(DEFAULT_DISCOUNT.get(db.get(Channel, store.channel_id).name, "0.08"))
            sr = rates.get(store_id) or default_platform_rates(db, store)
            for s, w in noisy:
                spu_local = local_total * w / tot
                splits = [D("0.6"), D("0.4")] if len(s.skus) == 2 else [D("0.5"), D("0.3"), D("0.2")][:len(s.skus)]
                if len(splits) != len(s.skus):
                    splits = [ONE / len(s.skus)] * len(s.skus)
                for sku, part in zip(s.skus, splits):
                    sales = q2(spu_local * part)
                    if sales <= 0:
                        continue
                    unit = s.price_usd * price_factor(store.currency) * (ONE - disc)
                    qty = max(int((sales / unit).quantize(ONE, ROUND_HALF_UP)), 1)
                    rows.append([fmt_month(m), store.name, site_by[store.site_id].code, sku, qty, float(sales),
                                 store.currency, float(q2(sales * sr["promotion"])),
                                 float(q2(sales * sr["commission"]))])
    return rows


def import_bi(demo: Demo, months: list[date], rates: dict[int, dict[str, Decimal]]) -> int:
    rows = bi_rows(demo, months, rates)
    if not rows:
        return 0
    span = fmt_month(months[0]) if len(months) == 1 else f"{fmt_month(months[0])}至{months[-1].month:02d}"
    run_import(demo, demo.actor(FINANCE_BP), ImportSource.BI, f"BI_{span}_销售明细_演示.xlsx", BI_HEADER, rows)
    return len(rows)


# ---------------------------------------------------------------------------
# 2026 实际费率与收入基数
# ---------------------------------------------------------------------------
def prior_store_items(db: Session, store_id: int) -> dict[date, dict[str, Decimal]]:
    return PA.by_month(db, PRIOR, store_ids=[store_id])


def rates_from(items_by_month: list[dict[str, Decimal]], keys) -> dict[str, Decimal] | None:
    rev = sum((it.get("revenue", ZERO) for it in items_by_month), ZERO)
    if rev <= 0:
        return None
    return {k: clamp_rate(sum((it.get(k, ZERO) for it in items_by_month), ZERO) / rev) for k in keys}


def store_rates(db: Session) -> dict[int, dict[str, Decimal]]:
    """店铺费率：退款 / 佣金 / 推广取店铺 2026 实际，成本类取同渠道同站点 2026 实际；无实际用渠道默认。"""
    by_store = {s.id: prior_store_items(db, s.id) for s in db.scalars(select(Store))}
    pair_items: dict[tuple[int, int], list[dict]] = defaultdict(list)
    stores = {s.id: s for s in db.scalars(select(Store))}
    for sid, months in by_store.items():
        pair_items[(stores[sid].channel_id, stores[sid].site_id)].extend(months.values())
    out = {}
    for sid, store in stores.items():
        rates = default_platform_rates(db, store)
        pair = rates_from(pair_items[(store.channel_id, store.site_id)], COST_ITEMS)
        if pair:
            rates.update({k: v for k, v in pair.items() if k not in ("refund", "commission", "promotion")})
        own = rates_from(list(by_store[sid].values()), ("refund", "commission", "promotion"))
        if own:
            rates.update(own)
        out[sid] = rates
    return out


def customer_rates(db: Session, customer: BCustomer) -> dict[str, Decimal]:
    rates = {k: D(v) for k, v in B2B_DEFAULTS.items()}
    own = rates_from(list(PA.by_month(db, PRIOR, customer_ids=[customer.id]).values()), COST_ITEMS)
    if own:
        rates.update(own)
    return rates


def monthly_base(prior: dict[date, Decimal], default_month: Decimal | None) -> dict[int, Decimal]:
    """2027 各月收入基数：1–9 月取 2026 同月实际，10–12 月取 7–9 月均值 × 旺季系数；无实际用默认值 × 季节系数。"""
    out: dict[int, Decimal] = {}
    vals = {m.month: v for m, v in prior.items() if v > 0}
    if not vals:
        if default_month is None:
            return {}
        for mo in range(1, 13):
            season = D(SEASON_2026[mo - 1]) if mo <= 9 else D(Q4_FACTOR[mo])
            out[mo] = default_month * season
        return out
    tail = [vals[mo] for mo in (7, 8, 9) if mo in vals] or list(vals.values())
    avg = sum(tail, ZERO) / len(tail)
    mean_all = sum(vals.values(), ZERO) / len(vals)
    for mo in range(1, 13):
        if mo in vals:
            out[mo] = vals[mo]
        elif mo >= 10:
            out[mo] = avg * D(Q4_FACTOR[mo])
        else:
            out[mo] = mean_all * D(SEASON_2026[mo - 1])
    return out


def channel_growth(channel: Channel) -> Decimal:
    """收入同比增长 12%～20%，按渠道不同。"""
    return D("0.12") + D(rnd("channel-growth", channel.name).randint(0, 8)) / 100


# ---------------------------------------------------------------------------
# 2027 年度预算：发布 → 填报 → 提交 → 审核 → CEO 锁定
# ---------------------------------------------------------------------------
def ensure_new_channel(demo: Demo) -> None:
    db = demo.db
    store = new_channel_store(db)
    if store is None or store_start(db, store) is not None:
        return
    if any(v.get("revenue", ZERO) > 0 for v in prior_store_items(db, store.id).values()):
        demo.say(f"  {store.name} 已有 {PRIOR} 年实际，按老渠道编制")
        return
    before = masterdata.store_snapshot(store)
    masterdata.set_store_new_channel(db, store, True, fmt_month(NEW_CHANNEL_START))
    write_audit(db, action="mark_new_channel", object_type="store", object_id=store.id, before=before,
                after=masterdata.store_snapshot(store), actor=demo.actor(FINANCE_HEAD))
    demo.say(f"  标记 {store.name} 为新渠道，起始 {fmt_month(NEW_CHANNEL_START)}")


def approve_preset_rules(demo: Demo) -> None:
    db = demo.db
    pending = list(db.scalars(select(RuleVersion).join(Rule, Rule.id == RuleVersion.rule_id)
                              .where(Rule.type == RuleType.ALERT, Rule.is_preset.is_(True),
                                     RuleVersion.status == RuleVersionStatus.PENDING).order_by(RuleVersion.id)))
    for rv in pending:
        rules.approve(db, demo.actor(FINANCE_HEAD), rv.id)
    if pending:
        demo.say(f"  财务负责人审批通过预置预警规则 {len(pending)} 条")


def store_targets(demo: Demo) -> dict[int, dict[int, Decimal]]:
    """店铺 2027 各月人民币收入目标。"""
    db = demo.db
    out = {}
    chans = channels(db)
    for store in participating_stores(demo):
        start = store_start(db, store)
        prior = {m: v.get("revenue", ZERO) for m, v in prior_store_items(db, store.id).items()}
        if start is not None and start.year <= YEAR and not any(v > 0 for v in prior.values()):
            out[store.id] = {mo: q2(NEW_CHANNEL_RAMP_BASE * NEW_CHANNEL_RAMP_STEP ** (mo - start.month))
                             for mo in range(1, 13) if date(YEAR, mo, 1) >= start}
            continue
        growth = D("0.08") if start is not None else channel_growth(chans[store.channel_id])
        base = monthly_base(prior, default_store_revenue(db, store))
        out[store.id] = {mo: q2(v * (ONE + growth)) for mo, v in base.items()}
    return out


def platform_changes(demo: Demo, store: Store, targets: dict[int, Decimal], rates: dict[str, Decimal],
                     cat: list[SpuInfo]) -> list[dict]:
    db = demo.db
    fx = db.scalar(select(FxBudget.rate).where(FxBudget.year == YEAR, FxBudget.currency == store.currency))
    disc = D(DEFAULT_DISCOUNT.get(db.get(Channel, store.channel_id).name, "0.08"))
    changes = []
    for mo, rev_cny in sorted(targets.items()):
        m = date(YEAR, mo, 1)
        groups: dict[tuple[int, bool], list[tuple[SpuInfo, Decimal]]] = defaultdict(list)
        for s, share in spu_shares(db, cat, store, m):
            groups[(s.category_id, is_new_product(s.first, m))].append((s, share))
        rev_local = rev_cny / fx
        for (cid, is_new), members in groups.items():
            share = sum((sh for _, sh in members), ZERO)
            price = q2(sum((s.price_usd * sh for s, sh in members), ZERO) / share * price_factor(store.currency))
            spu = len(members)
            avg_sales = (rev_local * share / (spu * price * (ONE - disc))).quantize(Q2, ROUND_HALF_UP)
            if avg_sales <= 0:
                continue
            key = f"pu:{store.id}:{store.site_id}:{cid}:{1 if is_new else 0}"
            values = {"spu_count": str(spu), "avg_sales": format(avg_sales, "f"), "avg_price": format(price, "f"),
                      "discount_rate": pct(disc), "refund_rate": pct(rates["refund"]),
                      "ad_rate": pct(rates["promotion"]), "commission_rate": pct(rates["commission"])}
            changes += [{"row_key": f"{key}|{k}", "field": fmt_month(m), "value": v} for k, v in values.items()]
    return changes


def b2b_changes(demo: Demo, unit: FillingUnit) -> list[dict]:
    db = demo.db
    changes = []
    customers = [c for c in participating_customers(demo) if c.department_id == unit.scope_object_id]
    all_ids = list(db.scalars(select(BCustomer.id).where(BCustomer.is_active.is_(True)).order_by(BCustomer.id)))
    for c in customers:
        fx = db.scalar(select(FxBudget.rate).where(FxBudget.year == YEAR, FxBudget.currency == c.currency))
        prior = {m: v.get("revenue", ZERO) for m, v in PA.by_month(db, PRIOR, customer_ids=[c.id]).items()}
        base = monthly_base(prior, default_customer_revenue(c, all_ids.index(c.id)))
        rates = customer_rates(db, c)
        for mo, v in base.items():
            sales = q2(v * (ONE + B2B_GROWTH) / fx)
            values = {"sales_local": format(sales, "f"), "refund_rate": pct(rates["refund"]),
                      "promotion_rate": pct(rates["promotion"]), "other_opex_rate": pct(rates["other_opex"]),
                      "commission_rate": pct(rates["commission"]),
                      "inventory_claim_rate": pct(rates["inventory_claim"])}
            changes += [{"row_key": f"b2b:{c.id}|{k}", "field": fmt_month(date(YEAR, mo, 1)), "value": val}
                        for k, val in values.items()]
    return changes


def _ratio_keys(db: Session, version_id: int):
    ccr = sorted(set(db.execute(select(ChannelCategoryRatio.channel_id, ChannelCategoryRatio.site_id,
                                       ChannelCategoryRatio.category_id)
                                .where(ChannelCategoryRatio.version_id == version_id)).all()))
    csr = sorted(set(db.execute(select(ChannelSiteRatio.channel_id, ChannelSiteRatio.site_id)
                                .where(ChannelSiteRatio.version_id == version_id)).all()))
    custs = sorted(set(db.scalars(select(B2bUnit.customer_id).where(B2bUnit.version_id == version_id))))
    return ccr, csr, custs


def pair_rates(db: Session, srates: dict[int, dict[str, Decimal]]) -> dict[tuple[int, int], dict[str, Decimal]]:
    out = {}
    for s in db.scalars(select(Store).order_by(Store.is_active.desc(), Store.id)):
        out.setdefault((s.channel_id, s.site_id), srates[s.id])
    return out


def ratio_changes(demo: Demo, unit: FillingUnit, srates, logistics: bool) -> list[dict]:
    db = demo.db
    ccr, csr, custs = _ratio_keys(db, unit.version_id)
    names = {c.id: c.name for c in categories(db)}
    prates = pair_rates(db, srates)
    months = [fmt_month(m) for m in year_months(YEAR)]
    changes = []
    for ch, si, cid in ccr:
        r = prates.get((ch, si)) or {k: D(v) for k, v in PLATFORM_DEFAULTS.items()}
        name = names.get(cid, "")
        if logistics:
            vals = {"first_leg_rate": clamp_rate(r["first_leg"] + D(CATEGORY_FIRST_LEG_OFFSET.get(name, "0"))),
                    "last_mile_rate": r["last_mile"], "storage_rate": r["storage"], "tariff_rate": r["tariff"]}
        else:
            vals = {"purchase_cost_rate": clamp_rate(r["purchase_cost"]
                                                     + D(CATEGORY_PURCHASE_OFFSET.get(name, "0")))}
        changes += [{"row_key": f"ccr:{ch}:{si}:{cid}|{k}", "field": m, "value": pct(v)}
                    for k, v in vals.items() for m in months]
    for cid in custs:
        r = customer_rates(db, db.get(BCustomer, cid))
        keys = ("first_leg", "last_mile", "storage", "tariff") if logistics else ("purchase_cost",)
        changes += [{"row_key": f"b2bc:{cid}|{k}_rate", "field": m, "value": pct(r[k])} for k in keys for m in months]
    if not logistics:
        for ch, si in csr:
            r = prates.get((ch, si)) or {k: D(v) for k, v in PLATFORM_DEFAULTS.items()}
            changes += [{"row_key": f"csr:{ch}:{si}|{k}_rate", "field": m, "value": pct(r[k])}
                        for k in ("inventory_claim", "other_opex") for m in months]
    return changes


def prior_other_pl(db: Session) -> dict[str, dict[int, Decimal]]:
    """2026 公司层其他损益实际（金额为支出方向）。"""
    out: dict[str, dict[int, Decimal]] = defaultdict(dict)
    batch_ids = versions.kingdee_batches_effective_at(db, PRIOR_MONTHS, None)
    for month, _s, _site, _c, _d, _u, item, is_dept, amount in versions.kingdee_rows(db, batch_ids):
        if not is_dept and item in OTHER_ITEMS:
            out[item][month.month] = out[item].get(month.month, ZERO) + amount
    return out


def other_pl_changes(demo: Demo, version_id: int) -> list[dict]:
    """公司层其他损益（损失填负数）：财务费用、汇兑损益、营业外按 2026 月均实际；所得税按月税前利润 15%。"""
    db = demo.db
    prior = prior_other_pl(db)
    defaults = {"finance_cost": D(12000), "fx_gain_loss": D(5000), "non_operating": D(2000)}
    monthly = versions.forecast_monthly(db, version_id)
    changes = []
    for m in year_months(YEAR):
        other_total = ZERO
        for item in ("finance_cost", "fx_gain_loss", "non_operating"):
            vals = list(prior.get(item, {}).values())
            amount = q2(sum(vals, ZERO) / len(vals)) if vals else defaults[item]
            other_total += amount
            changes.append({"row_key": f"opl|{item}", "field": fmt_month(m), "value": format(-amount, "f")})
        line = monthly.get(m)
        pre_tax = (line.gross - line.dept if line else ZERO) - other_total
        tax = q2(max(pre_tax, ZERO) * D("0.15"))
        changes.append({"row_key": "opl|income_tax", "field": fmt_month(m), "value": format(-tax, "f")})
    return changes


def prior_dept_actuals(db: Session) -> dict[tuple[int | None, int], dict[int, Decimal]]:
    """2026 部门费用实际：(部门或公司公共, 科目) → {月: 金额}。"""
    out: dict[tuple[int | None, int], dict[int, Decimal]] = defaultdict(dict)
    batch_ids = versions.kingdee_batches_effective_at(db, PRIOR_MONTHS, None)
    if not batch_ids:
        return out
    q = (select(KingdeeActual.department_id, KingdeeActual.account_id, KingdeeActual.month,
                func.sum(KingdeeActual.amount))
         .join(BudgetAccount, BudgetAccount.id == KingdeeActual.account_id)
         .where(KingdeeActual.batch_id.in_(batch_ids), BudgetAccount.is_dept_expense.is_(True))
         .group_by(KingdeeActual.department_id, KingdeeActual.account_id, KingdeeActual.month))
    for d, acc, m, amt in db.execute(q):
        out[(d, acc)][m.month] = amt
    return out


def dept_changes(demo: Demo, unit: FillingUnit) -> list[dict]:
    """部门费用：2026 同月实际 × 1.03～1.08；10–12 月取 7–9 月均值；部门无 2026 实际时按模板。"""
    db = demo.db
    dept = db.get(Department, unit.scope_object_id)
    prior = prior_dept_actuals(db)
    owner = public_owner(db)
    if owner is not None and dept.id == owner.id:
        # 公司公共费用归口本部门：2026 同月实际合并后作为基数
        for (d, acc), vals in list(prior.items()):
            if d is None:
                own = prior.setdefault((dept.id, acc), {})
                for mo, v in vals.items():
                    own[mo] = own.get(mo, ZERO) + v
    has_prior = any(d == dept.id for d, _a in prior)
    growth = D("1.03") + D(rnd("dept-growth", dept.name).randint(0, 5)) / 100
    accounts = list(db.scalars(select(BudgetAccount).where(BudgetAccount.id.in_(
        select(DeptExpense.account_id).where(DeptExpense.version_id == unit.version_id,
                                             DeptExpense.department_id == dept.id))).order_by(BudgetAccount.sort)))
    changes = []
    for acc in accounts:
        vals = prior.get((dept.id, acc.id), {})
        tail = [vals[mo] for mo in (7, 8, 9) if mo in vals]
        for m in year_months(YEAR):
            if has_prior:
                base = vals.get(m.month) if m.month <= 9 else (sum(tail, ZERO) / len(tail) if tail else None)
                if base is None:
                    continue
            else:
                base = dept_template(dept, acc)
            amount = q2(max(base, ZERO) * growth)
            if amount > 0:
                changes.append({"row_key": f"de:{acc.id}|amount", "field": fmt_month(m), "value": format(amount, "f")})
    return changes


def fill(demo: Demo, unit: FillingUnit, changes: list[dict]) -> None:
    db = demo.db
    filler = db.get(User, unit.filler_id)
    actor = as_actor(db, filler)
    ctx = load_scope(db, filler.id, actor.roles)
    if not changes:
        raise DemoError(f"填报单位「{unit.name}」没有可填数据")
    res = filling.save_cells(db, ctx, actor, unit.id, changes, check_base=False)
    if res["errors"]:
        raise DemoError(f"「{unit.name}」保存失败：{res['errors'][:3]}")


def submit(demo: Demo, unit: FillingUnit) -> None:
    db = demo.db
    filler = db.get(User, unit.filler_id)
    actor = as_actor(db, filler)
    filling.submit_unit(db, load_scope(db, filler.id, actor.roles), actor, demo.settings, unit.id)


def build_budget(demo: Demo) -> BudgetVersion:
    db = demo.db
    head = demo.actor(FINANCE_HEAD)
    clock.set_now(at(f"{PRIOR}-12-01 09:30"))
    candidates = tasking.unit_candidates(db)
    stores = {s.id for s in participating_stores(demo)}
    b2b_depts = {c.department_id for c in participating_customers(demo)}
    in_scope = [c for c in candidates
                if (c.unit_type != UnitType.PLATFORM or c.scope_object_id in stores)
                and (c.unit_type != UnitType.B2B or c.scope_object_id in b2b_depts)]
    no_data = [c.name for c in candidates if c not in in_scope]
    if no_data:
        demo.say(f"  以下单位没有 {PRIOR} 年实际，不参与本次编制：{'、'.join(no_data)}")
    ok = [c for c in in_scope if c.filler is not None and c.reviewer is not None]
    skipped = [c.name for c in in_scope if c not in ok]
    if skipped:
        demo.say(f"  以下单位缺少填报人或审核人，不参与本次编制：{'、'.join(skipped)}")
    res = tasking.publish_task(db, head, demo.settings, year=YEAR, deadline=date(PRIOR, 12, 20),
                               units=[{"unit_type": c.unit_type, "scope_object_id": c.scope_object_id} for c in ok])
    task = db.get(BudgetTask, res["task"]["id"])
    units = list(db.scalars(select(FillingUnit).where(FillingUnit.task_id == task.id).order_by(FillingUnit.id)))
    demo.say(f"  发布「{task.name}」：{len(units)} 个填报单位，截止 {task.deadline}")

    cat = catalog(db)
    srates = store_rates(db)
    targets = store_targets(demo)
    by_type: dict[str, list[FillingUnit]] = defaultdict(list)
    for u in units:
        by_type[u.unit_type].append(u)
    day = 3
    for u in by_type[UnitType.PLATFORM]:
        clock.set_now(at(f"{PRIOR}-12-{day:02d} 10:00") + timedelta(minutes=u.id % 50))
        store = db.get(Store, u.scope_object_id)
        fill(demo, u, platform_changes(demo, store, targets.get(store.id, {}), srates[store.id], cat))
        submit(demo, u)
        day = min(day + 1, 12)
    clock.set_now(at(f"{PRIOR}-12-08 15:00"))
    for u in by_type[UnitType.B2B]:
        fill(demo, u, b2b_changes(demo, u))
        submit(demo, u)
    clock.set_now(at(f"{PRIOR}-12-09 11:00"))
    for u in by_type[UnitType.LOGISTICS_RATIO]:
        fill(demo, u, ratio_changes(demo, u, srates, logistics=True))
        submit(demo, u)
    clock.set_now(at(f"{PRIOR}-12-10 14:00"))
    for u in by_type[UnitType.DEPT_EXPENSE]:
        fill(demo, u, dept_changes(demo, u))
        submit(demo, u)
    clock.set_now(at(f"{PRIOR}-12-11 16:00"))
    for u in by_type[UnitType.COST_RATIO]:
        fill(demo, u, ratio_changes(demo, u, srates, logistics=False))
        fill(demo, u, other_pl_changes(demo, u.version_id))
        submit(demo, u)

    # 部门审核：第一个平台渠道单位先退回一次（推广费率偏高），修改后重新提交再通过
    clock.set_now(at(f"{PRIOR}-12-14 10:00"))
    returned = by_type[UnitType.PLATFORM][0] if by_type[UnitType.PLATFORM] else None
    if returned is not None:
        approval_units.reject(db, demo.actor_of(returned.reviewer_id), returned.id,
                              f"推广费率高于 {PRIOR} 年实际水平，请按 2026 年 7–9 月实际下调 0.5 个百分点后重新提交")
        clock.set_now(at(f"{PRIOR}-12-15 09:40"))
        rows = db.scalars(select(PlatformUnit).where(PlatformUnit.version_id == returned.version_id,
                                                     PlatformUnit.store_id == returned.scope_object_id,
                                                     PlatformUnit.spu_count > 0)).all()
        fill(demo, returned, [{"row_key": f"pu:{r.store_id}:{r.site_id}:{r.category_id}:{1 if r.is_new else 0}|ad_rate",
                               "field": fmt_month(r.month), "value": pct(max(r.ad_rate - D("0.005"), ZERO))}
                              for r in rows])
        submit(demo, returned)
    clock.set_now(at(f"{PRIOR}-12-16 10:00"))
    for u in units:
        db.refresh(u)
        if u.status == UnitStatus.SUBMITTED:
            approval_units.approve(db, demo.actor_of(u.reviewer_id), u.id)
    clock.set_now(at(f"{PRIOR}-12-22 10:00"))
    tasking.submit_to_ceo(db, head, demo.settings, task.id)
    clock.set_now(at(f"{PRIOR}-12-28 17:30"))
    approval_units.approve(db, demo.actor(CEO), task.id, obj_type="task")
    db.flush()
    version = db.get(BudgetVersion, task.version_id)
    db.refresh(version)
    demo.say(f"  CEO 审批通过，锁定为「{version.name}」（V{version.version_no}）")
    return version


# ---------------------------------------------------------------------------
# 2027 年 1–3 月实际（金蝶月度）
# ---------------------------------------------------------------------------
def achievement(demo: Demo, store: Store, m: date, low_store_id: int | None) -> Decimal:
    if store_start(demo.db, store) is not None:
        return {1: D("0.74"), 2: D("0.62"), 3: D("0.58")}[m.month]
    if store.id == low_store_id:
        return {1: D("0.81"), 2: D("0.78"), 3: D("0.83")}[m.month]
    return jitter("0.96", "1.12", "ach", store.name, m)


def actual_month_rows(demo: Demo, version: BudgetVersion, m: date) -> list[list]:
    db = demo.db
    codes = account_codes(db)
    items = item_accounts(db)
    site_by = sites(db)
    stores = {s.id: s for s in db.scalars(select(Store))}
    rows: list[list] = []

    def row(account: BudgetAccount | None, amount: Decimal, *, dept: str = "", store: Store | None = None,
            customer: str = "", summary: str) -> None:
        if account is None or account.id not in codes or amount <= 0:
            return
        code, name = codes[account.id]
        rows.append([fmt_month(m), code, name, dept, store.name if store else "",
                     site_by[store.site_id].code if store else "", customer, summary, float(q2(amount))])

    fields = [getattr(PlatformUnit, k if k != "revenue" else "revenue_cny") for k in GP_ITEMS]
    platform = db.execute(select(PlatformUnit.store_id, *[func.coalesce(func.sum(f), 0) for f in fields])
                          .where(PlatformUnit.version_id == version.id, PlatformUnit.month == m)
                          .group_by(PlatformUnit.store_id)).all()
    budget_rev = {sid: vals[0] for sid, *vals in platform if vals[0] > 0}
    regular = [sid for sid in budget_rev if store_start(db, stores[sid]) is None]
    low_store = min(regular, key=lambda sid: (budget_rev[sid], sid)) if len(regular) > 2 else None
    total_rev = ZERO
    for sid, *vals in platform:
        if vals[0] <= 0:
            continue
        store = stores[sid]
        ach = achievement(demo, store, m, low_store)
        lines = dict(zip(GP_ITEMS, vals))
        rev = q2(lines["revenue"] * ach)
        total_rev += rev
        row(items.get("revenue"), rev, store=store, summary=f"{fmt_month(m)} 平台销售收入")
        for item in COST_ITEMS:
            factor = jitter("0.96", "1.04", "cost27", store.name, m, item)
            if item == "first_leg" and m.month == 3:
                factor *= D("1.20")   # 3 月海运价格上涨，头程费用明显上升
            row(items.get(item), q2(lines[item] * ach * factor), store=store,
                summary=f"{fmt_month(m)} {items[item].name if item in items else item}")
    b2b_fields = [getattr(B2bUnit, k if k != "revenue" else "revenue_cny") for k in GP_ITEMS]
    for cid, *vals in db.execute(select(B2bUnit.customer_id, *[func.coalesce(func.sum(f), 0) for f in b2b_fields])
                                 .where(B2bUnit.version_id == version.id, B2bUnit.month == m)
                                 .group_by(B2bUnit.customer_id)).all():
        if vals[0] <= 0:
            continue
        c = db.get(BCustomer, cid)
        ach = jitter("0.90", "1.08", "b2b-ach", c.name, m)
        for item, v in zip(GP_ITEMS, vals):
            factor = ach * (ONE if item == "revenue" else jitter("0.96", "1.04", "b2bcost27", c.name, m, item))
            row(items.get(item), q2(v * factor), customer=c.name,
                summary=f"{fmt_month(m)} {items[item].name if item in items else item}")
        total_rev += q2(vals[0] * ach)
    row(items.get("storage"), q2(total_rev * D("0.002")), summary=f"{fmt_month(m)} 海外仓公共仓储（未分店铺）")

    # 部门费用：参与编制的部门按预算 × 波动；其中部门预算专员所在部门 1 月有一笔年初集中招聘费用
    depts = {d.id: d for d in db.scalars(select(Department))}
    budget_user = db.scalar(select(User).join(UserRole, UserRole.user_id == User.id)
                            .where(UserRole.role_code == Role.DEPT_BUDGET).order_by(User.id).limit(1))
    hot_dept = budget_user.department_id if budget_user else None
    budgeted = set()
    dept_rows = db.execute(select(DeptExpense.department_id, DeptExpense.account_id, DeptExpense.amount)
                           .where(DeptExpense.version_id == version.id, DeptExpense.month == m)).all()
    month_total: dict[int, Decimal] = defaultdict(lambda: ZERO)
    for d, acc, amt in dept_rows:
        budgeted.add(d)
        month_total[d] += amt
    for d, acc, amt in dept_rows:
        if amt <= 0:
            continue
        account = db.get(BudgetAccount, acc)
        actual = amt * jitter("0.94", "1.04", "dept27", depts[d].name, account.name, m)
        if d == hot_dept and m.month == 1 and account.name == "招聘费":
            actual += month_total[d] * D("1.4")
        row(account, q2(actual), dept=depts[d].name, summary=f"{fmt_month(m)} {account.name}")
    if hot_dept in budgeted and m.month == 1 and not any(
            db.get(BudgetAccount, acc).name == "招聘费" and d == hot_dept for d, acc, _a in dept_rows):
        big = max((r for r in dept_rows if r[0] == hot_dept), key=lambda r: r[2])
        row(db.get(BudgetAccount, big[1]), q2(month_total[hot_dept] * D("1.4")), dept=depts[hot_dept].name,
            summary=f"{fmt_month(m)} 年初集中招聘")
    # 没有 2027 预算的部门不模拟实际（公司公共费用已归口 CEO 所在部门编制与核算），预算与实际同口径
    for item, amt in db.execute(select(CompanyOtherPl.item, CompanyOtherPl.amount)
                                .where(CompanyOtherPl.version_id == version.id, CompanyOtherPl.month == m)).all():
        row(items.get(item), q2(abs(amt) * jitter("0.85", "1.10", "opl27", item, m)),
            summary=f"{fmt_month(m)} {items[item].name if item in items else item}")
    return rows


def ensure_codes_for_dept_accounts(demo: Demo) -> None:
    """经营历史表补建的管理费用科目没有金蝶编码：按「管理费用-<科目>」补映射，金蝶月度实际才能导入。"""
    db = demo.db
    codes = account_codes(db)
    n = 0
    for acc in dept_accounts(db):
        if acc.id in codes:
            continue
        n += 1
        code = f"6602.9{n:02d}"
        while db.scalar(select(KingdeeAccountMap.id).where(KingdeeAccountMap.kingdee_code == code)):
            n += 1
            code = f"6602.9{n:02d}"
        row, before = masterdata.save_account_mapping(db, demo.user(FINANCE_BP).id, code, f"管理费用-{acc.name}",
                                                      acc.id, create_only=True)
        write_audit(db, action="save_mapping", object_type="kingdee_account_map", object_id=row.kingdee_code,
                    before=before, after={"kingdee_name": row.kingdee_name, "account_id": row.account_id},
                    actor=demo.actor(FINANCE_BP))
        demo.say(f"  补金蝶科目映射 {code} → {acc.name}")


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def summary(db: Session, version: BudgetVersion) -> dict:
    monthly = versions.forecast_monthly(db, version.id)
    rev = sum((v.revenue for v in monthly.values()), ZERO)
    gp = sum((v.gross for v in monthly.values()), ZERO)
    net = sum((v.net for v in monthly.values()), ZERO)
    actual = versions.actual_monthly(db, ACTUAL_MONTHS)
    q1 = []
    for m in ACTUAL_MONTHS:
        b, a = monthly.get(m), actual.get(m)
        q1.append({"month": fmt_month(m), "budget_revenue": format(q2(b.revenue), "f"),
                   "actual_revenue": format(q2(a.revenue), "f"),
                   "achievement": format((a.revenue / b.revenue * HUNDRED).quantize(Decimal("0.1")), "f") + "%"})
    q1_target = sum((monthly[m].net for m in ACTUAL_MONTHS if m in monthly), ZERO)
    q1_actual = sum((actual[m].net for m in ACTUAL_MONTHS if m in actual), ZERO)
    net_rate = format((q1_actual / q1_target * HUNDRED).quantize(Decimal("0.1")), "f") + "%" if q1_target > 0 else "—"
    return {"budget_revenue": format(q2(rev), "f"), "budget_gross_profit": format(q2(gp), "f"),
            "q1_net_target": format(q2(q1_target), "f"), "q1_net_actual": format(q2(q1_actual), "f"),
            "q1_net_achievement": net_rate,
            "budget_gross_margin": format((gp / rev * HUNDRED).quantize(Decimal("0.1")), "f") + "%",
            "budget_net_profit": format(q2(net), "f"), "q1": q1,
            "alerts": db.scalar(select(func.count()).select_from(Alert))}


def run(db: Session, settings, data_dir: Path | None = None) -> dict | None:
    """写入演示数据；已写过返回 None。调用方负责提交事务。"""
    demo = Demo(db=db, settings=settings, data_dir=Path(data_dir or settings.DATA_DIR))
    if already_done(db):
        print("演示数据已写入过，跳过。")
        return None
    reason = foreign_data(db)
    if reason:
        print(f"{reason}（不是演示脚本写入的），为避免混淆不写入演示数据。")
        return None
    for userid in (FINANCE_HEAD, FINANCE_BP, CEO):
        demo.user(userid)
    if not active_stores(db) or not categories(db):
        raise DemoError("主数据为空，请先运行 python -m scripts.seed")
    try:
        demo.real_prior = bool(effective_kingdee_months(db) & set(PRIOR_MONTHS))
        demo.say(f"一、补齐 {PRIOR} 年基础数据")
        clock.set_now(at(f"{PRIOR}-10-29 10:00"))
        ensure_sku_table(demo)
        clock.set_now(at(f"{PRIOR}-10-29 14:00"))
        ensure_fx_actual(demo, PRIOR_MONTHS)
        clock.set_now(at(f"{PRIOR}-10-29 15:00"))
        simulate_prior_kingdee(demo)
        srates = store_rates(db)
        have_bi = effective_bi_months(db)
        bi_count = 0
        for i, pair in enumerate([PRIOR_MONTHS[k:k + 2] for k in range(0, 9, 2)]):
            todo = [m for m in pair if m not in have_bi]
            if todo:
                clock.set_now(at(f"{PRIOR}-10-30 10:00") + timedelta(minutes=20 * i))
                bi_count += import_bi(demo, todo, srates)

        demo.say(f"二、{YEAR} 年度预算编制")
        clock.set_now(at(f"{PRIOR}-11-20 10:00"))
        approve_preset_rules(demo)
        clock.set_now(at(f"{PRIOR}-11-25 10:00"))
        ensure_new_channel(demo)
        ensure_heads(demo)
        ensure_scopes(demo)
        ensure_budget_fx(demo)
        version = build_budget(demo)

        demo.say(f"三、{YEAR} 年 1–3 月实际")
        clock.set_now(at(f"{YEAR}-01-08 10:00"))
        versions.publish_original(db, demo.actor(FINANCE_HEAD), today=clock.today())
        demo.say(f"  发布 {YEAR} Q1 滚动预测快照（以年初原始目标发布）")
        ensure_codes_for_dept_accounts(demo)
        for m in ACTUAL_MONTHS:
            nxt = add_months(m, 1)
            clock.set_now(at(f"{fmt_month(nxt)}-05 10:00"))
            ensure_fx_actual(demo, [m])
            clock.set_now(at(f"{fmt_month(nxt)}-08 10:00"))
            rows = actual_month_rows(demo, version, m)
            run_import(demo, demo.actor(FINANCE_BP), ImportSource.KINGDEE, f"金蝶_{fmt_month(m)}_利润表_演示.xlsx",
                       KINGDEE_HEADER, rows)
            if m.month in (2, 3):
                bi_months = ACTUAL_MONTHS[:2] if m.month == 2 else [m]
                clock.set_now(at(f"{fmt_month(nxt)}-10 10:00"))
                bi_count += import_bi(demo, bi_months, srates)
        clock.set_now(at(f"{YEAR}-04-10 18:00"))
        result = summary(db, version)
        result["bi_rows"] = bi_count
        write_audit(db, action=MARK_ACTION, object_type="system", object_id="seed_demo", actor_name="seed_demo",
                    after=result)
        db.flush()
    finally:
        clock.set_now(None)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="写入预算管理平台试用版演示数据（模拟）")
    parser.add_argument("--database-url", default=None)
    args = parser.parse_args()
    settings = get_settings()
    url = args.database_url or settings.DATABASE_URL
    # 整个演示在一个外层事务内：业务服务里的 commit 只释放保存点，失败时全部回滚
    conn = get_engine(url).connect()
    trans = conn.begin()
    db = Session(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)
    try:
        result = run(db, settings)
        trans.commit()
    except DemoError as e:
        trans.rollback()
        print(f"演示数据未写入：{e}")
        return 1
    except Exception:
        trans.rollback()
        print("演示数据写入失败，已全部回滚。")
        raise
    finally:
        db.close()
        conn.close()
    if result:
        print("演示数据写入完成：")
        print(f"  {YEAR} 年全年预算收入 {result['budget_revenue']}，毛利 {result['budget_gross_profit']}"
              f"（毛利率 {result['budget_gross_margin']}），净利润 {result['budget_net_profit']}")
        for q in result["q1"]:
            print(f"  {q['month']} 收入达成率 {q['achievement']}"
                  f"（预算 {q['budget_revenue']}，实际 {q['actual_revenue']}）")
        print(f"  1–3 月累计净利润达成率 {result['q1_net_achievement']}"
              f"（目标 {result['q1_net_target']}，实际 {result['q1_net_actual']}）")
        print(f"  预警 {result['alerts']} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
