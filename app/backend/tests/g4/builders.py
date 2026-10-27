"""G4 场景测试的数据构造：直接写入 G2 预算表与 G3 实际数表（表结构由第一期固定），只准备前置条件。"""
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.calc.periods import parse_month
from app.calc.recalc import recalc_b2b_units, recalc_platform_units
from app.models import (B2bUnit, BCustomer, BiActualAgg, BudgetAccount, BudgetVersion, Category, DeptExpense,
                        Department, FxActual, ImportBatch, KingdeeActual, PlatformUnit, SnapshotMonth, Store, User)
from app.models.enums import ImportStatus

D = Decimal


def user_id(db, userid: str) -> int:
    return db.scalar(select(User.id).where(User.dingtalk_userid == userid))


def login(client, db, userid: str) -> None:
    r = client.post("/api/dev/login-as", json={"user_id": user_id(db, userid)})
    assert r.status_code == 200, r.text


def store(db, name: str) -> Store:
    return db.scalar(select(Store).where(Store.name == name))


def customer(db, name: str) -> BCustomer:
    return db.scalar(select(BCustomer).where(BCustomer.name == name))


def dept(db, name: str) -> Department:
    return db.scalar(select(Department).where(Department.name == name))


def category(db, name: str) -> Category:
    return db.scalar(select(Category).where(Category.name == name))


def account(db, name: str) -> BudgetAccount:
    acc = db.scalar(select(BudgetAccount).where(BudgetAccount.name == name))
    if acc is None:  # 契约样例中的部门费用科目（如「展会费」）不在种子清单时补建
        acc = BudgetAccount(name=name, is_dept_expense=True, sort=99)
        db.add(acc)
        db.flush()
    return acc


def version(db, year: int, vtype: str, name: str, version_no: int = 1, quarter: int | None = None,
            published_on: date | None = None) -> BudgetVersion:
    v = BudgetVersion(year=year, type=vtype, version_no=version_no, quarter=quarter, name=name,
                      published_on=published_on)
    db.add(v)
    db.flush()
    return v


def platform_unit(db, v: BudgetVersion, store_name: str, month: str, category_name: str, is_new: bool, *,
                  spu: int, avg_sales: str, avg_price: str, discount: str, ad_rate: str = "0",
                  refund_rate: str = "0", commission_rate: str = "0") -> PlatformUnit:
    st = store(db, store_name)
    u = PlatformUnit(version_id=v.id, month=parse_month(month), channel_id=st.channel_id, store_id=st.id,
                     site_id=st.site_id, category_id=category(db, category_name).id, is_new=is_new, spu_count=spu,
                     avg_sales=D(avg_sales), avg_price=D(avg_price), discount_rate=D(discount), ad_rate=D(ad_rate),
                     refund_rate=D(refund_rate), commission_rate=D(commission_rate))
    db.add(u)
    db.flush()
    recalc_platform_units(db, v.id, unit_ids=[u.id])
    return u


def raw_platform_unit(db, v: BudgetVersion, store_name: str, month: str, *, revenue_cny: str,
                      gross_profit: str) -> PlatformUnit:
    """只写派生列（公司汇总按月目标净利润用）。"""
    st = store(db, store_name)
    u = PlatformUnit(version_id=v.id, month=parse_month(month), channel_id=st.channel_id, store_id=st.id,
                     site_id=st.site_id, category_id=category(db, "框镜").id, is_new=False,
                     revenue_cny=D(revenue_cny), gross_profit=D(gross_profit))
    db.add(u)
    db.flush()
    return u


def b2b_unit(db, v: BudgetVersion, customer_name: str, month: str, *, sales_local: str, refund_rate: str = "0",
             purchase_cost_rate: str = "0") -> B2bUnit:
    u = B2bUnit(version_id=v.id, month=parse_month(month), customer_id=customer(db, customer_name).id,
                sales_local=D(sales_local), refund_rate=D(refund_rate), purchase_cost_rate=D(purchase_cost_rate))
    db.add(u)
    db.flush()
    recalc_b2b_units(db, v.id, unit_ids=[u.id])
    return u


def dept_expense(db, v: BudgetVersion, dept_name: str, account_name: str, month: str, amount: str) -> DeptExpense:
    row = DeptExpense(version_id=v.id, month=parse_month(month), department_id=dept(db, dept_name).id,
                      account_id=account(db, account_name).id, amount=D(amount))
    db.add(row)
    db.flush()
    return row


def batch(db, source: str, month: str, file_name: str | None = None) -> ImportBatch:
    b = ImportBatch(source=source, period=parse_month(month), file_name=file_name or f"{source}_{month}.xlsx",
                    status=ImportStatus.EFFECTIVE, uploaded_by=user_id(db, "chensiyu"), row_count=0)
    db.add(b)
    db.flush()
    return b


def kingdee(db, b: ImportBatch, month: str, account_name: str, amount: str, *, store_name: str | None = None,
            customer_name: str | None = None, dept_name: str | None = None, unassigned: bool = False) -> KingdeeActual:
    st = store(db, store_name) if store_name else None
    row = KingdeeActual(batch_id=b.id, month=parse_month(month), store_id=st.id if st else None,
                        site_id=st.site_id if st else None,
                        customer_id=customer(db, customer_name).id if customer_name else None,
                        department_id=dept(db, dept_name).id if dept_name else None, kingdee_code="0000",
                        account_id=account(db, account_name).id, amount=D(amount), unassigned=unassigned)
    db.add(row)
    db.flush()
    return row


def bi_agg(db, b: ImportBatch, month: str, store_name: str, category_name: str, is_new: bool, *, spu: int,
           qty: str, revenue_local: str, revenue_cny: str | None) -> BiActualAgg:
    st = store(db, store_name)
    row = BiActualAgg(batch_id=b.id, month=parse_month(month), store_id=st.id, site_id=st.site_id,
                      category_id=category(db, category_name).id, is_new=is_new, spu_count=spu, qty=D(qty),
                      revenue_local=D(revenue_local), currency=st.currency,
                      revenue_cny=D(revenue_cny) if revenue_cny is not None else None)
    db.add(row)
    db.flush()
    return row


def fx_actual(db, month: str, currency: str, rate: str) -> None:
    db.add(FxActual(month=parse_month(month), currency=currency, rate=D(rate)))
    db.flush()


def snapshot_month(db, v: BudgetVersion, month: str, *, revenue: str, net_profit: str) -> None:
    db.add(SnapshotMonth(version_id=v.id, month=parse_month(month), source="forecast", revenue_cny=D(revenue),
                         gross_profit=D(net_profit), net_profit=D(net_profit)))
    db.flush()
