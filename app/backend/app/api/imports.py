"""实际数导入与核对（API-F09-01~05）：/imports、/reconciliation。

功能组路由桩：由对应功能组填写。每个业务路由必须声明认证与权限依赖
（Depends(get_scope) / Depends(require_roles(...))），查询经 ScopeContext 过滤（NFR-003）。
"""
from fastapi import APIRouter

router = APIRouter(prefix="", tags=["imports"])
