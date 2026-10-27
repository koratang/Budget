"""E2 浏览器验收用后端进程（库 budget_acc2、端口 8012、钉钉替身 8022）。

就是产品应用 app.main.create_app（真实路由、权限、数据库、托管 static 构建产物），只额外挂两条验收控制接口：
- POST /_e2e/clock {"now": "2027-05-12 09:00" | null}  设置可注入时钟（契约场景日期）
- POST /_e2e/outbox                                    立即投递发件箱到钉钉替身（等同调度器每分钟一次的投递）
启动：cd app/backend && .venv/bin/uvicorn tests.acceptance.e2_server:app --port 8012
"""
import os

os.environ.update(DATABASE_URL="postgresql+psycopg://budget:budget@127.0.0.1:5432/budget_acc2", APP_ENV="dev",
                  DEV_IDENTITY_SWITCH="true", SCHEDULER_ENABLED="false", DINGTALK_BASE_URL="http://127.0.0.1:8022",
                  DINGTALK_APP_KEY="stub", DINGTALK_APP_SECRET="stub", DINGTALK_AGENT_ID="10001",
                  DINGTALK_CORP_ID="ding-stub", APP_BASE_URL="http://127.0.0.1:8012")

from datetime import datetime  # noqa: E402

from fastapi import APIRouter, Request  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from app.config import load_settings  # noqa: E402
from app.core.clock import TZ, clock  # noqa: E402
from app.dingtalk.outbox import process_outbox  # noqa: E402
from app.main import create_app  # noqa: E402

app = create_app(load_settings())
ctl = APIRouter()


class ClockIn(BaseModel):
    now: str | None = None


@ctl.post("/_e2e/clock")
def set_clock(body: ClockIn):
    clock.set_now(datetime.strptime(body.now, "%Y-%m-%d %H:%M").replace(tzinfo=TZ) if body.now else None)
    return {"now": clock.now().isoformat()}


@ctl.post("/_e2e/outbox")
def flush_outbox(request: Request):
    with request.app.state.session_maker() as db:
        result = process_outbox(db, request.app.state.dingtalk, clock.now())
        db.commit()
    return result


app.include_router(ctl)
# 控制路由须排在 SPA 回退之前
app.router.routes.insert(0, app.router.routes.pop())
