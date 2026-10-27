"""写入样例主数据与人员角色（幂等：按名称 / userid 存在即跳过）。

只写主数据与人员，不预建编制任务、不预填预算、不上传 SKU 对照表（这些是待验收动作）。
用法：
    cd app/backend && .venv/bin/python -m scripts.seed [--database-url URL] [--mark-new-channel]
--mark-new-channel：把 TikTok-US-01 预置为新渠道（起始 2027-03）。FLOW-04 中这是财务负责人的验收动作，
默认不预置；只在验收 FLOW-17 等以「已标记新渠道」为前提的场景时使用。
"""
import argparse
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calc.periods import parse_month
from app.config import get_settings
from app.db import session_factory
from app.models import (BCustomer, BudgetAccount, Category, Channel, Department, FxBudget, KingdeeAccountMap, Site,
                        Store, User, UserRole, UserScope)
from scripts import seed_data as D


def _get_or_create(db: Session, model, lookup: dict, **values):
    row = db.scalar(select(model).filter_by(**lookup))
    if row is None:
        row = model(**lookup, **values)
        db.add(row)
        db.flush()
    return row


def seed(db: Session, mark_new_channel: bool = False) -> dict:
    depts = {name: _get_or_create(db, Department, {"name": name}, sort=i)
             for i, name in enumerate(D.DEPARTMENTS, 1)}
    sites = {code: _get_or_create(db, Site, {"code": code}, name=name) for code, name in D.SITES}
    channels = {name: _get_or_create(db, Channel, {"name": name}, sort=i) for i, name in enumerate(D.CHANNELS, 1)}
    stores = {name: _get_or_create(db, Store, {"name": name}, channel_id=channels[ch].id, site_id=sites[site].id,
                                   currency=cur)
              for name, ch, site, cur in D.STORES}
    if mark_new_channel:
        store_name, start = D.NEW_CHANNEL_STORE
        stores[store_name].is_new_channel = True
        stores[store_name].new_channel_start = parse_month(start)
    for i, name in enumerate(D.CATEGORIES, 1):
        _get_or_create(db, Category, {"name": name}, sort=i)
    customers = {name: _get_or_create(db, BCustomer, {"name": name}, department_id=depts[dept].id, currency=cur)
                 for name, dept, cur in D.B_CUSTOMERS}
    accounts = {name: _get_or_create(db, BudgetAccount, {"name": name}, is_dept_expense=is_dept, pl_item=item,
                                     sort=i)
                for i, (name, is_dept, item) in enumerate(D.BUDGET_ACCOUNTS, 1)}
    for code, kname, account in D.KINGDEE_ACCOUNTS:
        _get_or_create(db, KingdeeAccountMap, {"kingdee_code": code}, kingdee_name=kname,
                       account_id=accounts[account].id)
    for cur, rate in D.FX_BUDGET_2027:
        _get_or_create(db, FxBudget, {"year": 2027, "currency": cur}, rate=Decimal(rate))

    scope_targets = {"department": depts, "store": stores, "customer": customers, "channel": channels}
    for userid, name, dept, roles, scopes, is_head in D.PEOPLE:
        user = _get_or_create(db, User, {"dingtalk_userid": userid}, name=name, union_id=f"union-{userid}",
                              dingtalk_dept=dept, department_id=depts[dept].id, is_active=True)
        for role in roles:
            _get_or_create(db, UserRole, {"user_id": user.id, "role_code": role})
        for scope_type, names in scopes.items():
            for obj in names:
                _get_or_create(db, UserScope, {"user_id": user.id, "scope_type": scope_type,
                                               "object_id": scope_targets[scope_type][obj].id})
        if is_head and depts[dept].head_user_id is None:
            depts[dept].head_user_id = user.id
    db.commit()
    return {"departments": len(depts), "stores": len(stores), "customers": len(customers),
            "accounts": len(accounts), "people": len(D.PEOPLE)}


def main() -> None:
    parser = argparse.ArgumentParser(description="写入预算管理平台样例主数据与人员")
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--mark-new-channel", action="store_true")
    args = parser.parse_args()
    url = args.database_url or get_settings().DATABASE_URL
    with session_factory(url)() as db:
        print(seed(db, mark_new_channel=args.mark_new_channel))


if __name__ == "__main__":
    main()
