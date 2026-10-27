"""GET /me（API-F01-05）：当前用户、角色、数据范围摘要、可见菜单。"""
from fastapi import APIRouter, Depends

from app.config import Settings
from app.core.auth import CurrentUser, get_app_settings, get_current_user
from app.core.menus import menus_for
from app.core.scope import ScopeContext, get_scope
from app.models.enums import Role

router = APIRouter(tags=["me"])


@router.get("/me")
def me(current: CurrentUser = Depends(get_current_user), ctx: ScopeContext = Depends(get_scope),
       settings: Settings = Depends(get_app_settings)):
    user = current.user
    return {
        "user": {"id": user.id, "name": user.name, "dingtalk_userid": user.dingtalk_userid},
        "roles": [r for r in Role.ALL if r in current.roles],
        "role_names": current.role_names,
        "scopes": ctx.summary(),
        "all_company": ctx.all_company,
        "menus": menus_for(current.roles),
        "dev_switch": settings.dev_identity_enabled,
        "auth_source": current.auth_source,
    }
