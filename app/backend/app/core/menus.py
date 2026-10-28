"""侧栏可见矩阵（PAGE-F00-01 §8、待确认处置「侧栏可见矩阵」；菜单 key = 前端路由 name）。

侧栏为当前用户各角色可见菜单的并集（DEC-F00-02）。矩阵未覆盖的「我的填报、部门费用、待我审批、版本管理」
按各页「适用角色」取值；报表按各页适用角色（公司汇总只开放 CEO、财务负责人、财务BP）。
菜单可见只决定入口；接口权限仍由各路由依赖强制。
"""
from app.models.enums import Role

ALL = frozenset(Role.ALL)
MANAGEMENT = frozenset({Role.CEO, Role.FINANCE_HEAD, Role.FINANCE_BP})

# 顺序即侧栏顺序
MENU_ROLES: dict[str, frozenset[str]] = {
    "workbench": ALL,
    # 预算编制
    "tasks": frozenset({Role.FINANCE_HEAD, Role.CEO}),
    "my-filling": frozenset({Role.OPERATIONS, Role.B2B, Role.FINANCE_BP, Role.LOGISTICS, Role.DEPT_BUDGET}),
    "dept-expense": frozenset({Role.DEPT_BUDGET}),
    "approvals": frozenset({Role.DEPT_HEAD, Role.FINANCE_HEAD, Role.CEO}),
    # 预算版本
    "versions": ALL,
    # 实际数
    "import": frozenset({Role.FINANCE_BP, Role.FINANCE_HEAD}),
    "reconcile": frozenset({Role.FINANCE_BP, Role.FINANCE_HEAD}),
    # 报表
    "report-company": MANAGEMENT,
    "report-channel": MANAGEMENT | {Role.OPERATIONS, Role.B2B},
    "report-category": MANAGEMENT | {Role.OPERATIONS},
    "report-dept": MANAGEMENT | {Role.DEPT_HEAD, Role.DEPT_BUDGET},
    # 业财分析（REQ-F15-01）
    "bizfin-finance": MANAGEMENT,
    "bizfin-business": MANAGEMENT,
    "bizfin-analysis": MANAGEMENT,
    "bizfin-policy": MANAGEMENT,
    "bizfin-keywork": MANAGEMENT,
    "bizfin-data": MANAGEMENT,
    # 预警与规则
    "alerts": ALL,
    "rules": MANAGEMENT,
    # 基础数据
    "stores": MANAGEMENT,
    "sku": MANAGEMENT,
    "customers": MANAGEMENT,
    "accounts": MANAGEMENT,
    "fx": MANAGEMENT,
    # 系统设置
    "roles": frozenset({Role.FINANCE_HEAD}),
}


def menus_for(roles: frozenset[str] | set[str]) -> list[str]:
    return [key for key, allowed in MENU_ROLES.items() if allowed & set(roles)]
