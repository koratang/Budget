"""主数据（API-F02-01~06）：渠道/店铺、SKU 对照表、B 端客户与部门、科目映射、汇率、预算科目。

功能组路由桩：由对应功能组填写。每个业务路由必须声明认证与权限依赖
（Depends(get_scope) / Depends(require_roles(...))），查询经 ScopeContext 过滤（NFR-003）。
"""
from fastapi import APIRouter

router = APIRouter(prefix="/master", tags=["masterdata"])
