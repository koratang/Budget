"""版本、季度调整与滚动预测（API-F08-01~06）。

功能组路由桩：由对应功能组填写。每个业务路由必须声明认证与权限依赖
（Depends(get_scope) / Depends(require_roles(...))），查询经 ScopeContext 过滤（NFR-003）。
"""
from fastapi import APIRouter

router = APIRouter(prefix="/versions", tags=["versions"])
