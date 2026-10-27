"""钉钉网关、通知发件箱与调度器。"""
from fastapi import Request

from app.dingtalk.gateway import DingTalkClient


def get_dingtalk(request: Request) -> DingTalkClient:
    """路由依赖：应用级钉钉客户端（create_app 中创建，测试可替换 app.state.dingtalk）。"""
    return request.app.state.dingtalk
