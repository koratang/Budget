"""角色与权限（API-F01-07）：员工列表、保存角色与数据范围。

功能组路由桩：由对应功能组填写。每个业务路由必须声明认证与权限依赖
（Depends(get_scope) / Depends(require_roles(...))），查询经 ScopeContext 过滤（NFR-003）。
"""
from fastapi import APIRouter

router = APIRouter(prefix="/admin", tags=["roles"])
