"""E4 验收用后端进程（库 budget_acc4、端口 8014、钉钉替身 8024）。

就是产品应用 app.main.create_app（真实路由、权限、数据库），环境变量在导入前可覆盖（如 APP_ENV=prod 验证 RULE-07）；
E4_STATIC_DIR 指向另行构建的前端产物目录（不改动共享的 app/static）。开发配置下额外挂一条验收控制接口：
- POST /_e2e/outbox  立即投递发件箱到钉钉替身（等同调度器每分钟一次的投递）
启动：cd app/backend && .venv/bin/uvicorn tests.acceptance.e4_server:app --port 8014
"""
import os

for k, v in dict(DATABASE_URL="postgresql+psycopg://budget:budget@127.0.0.1:5432/budget_acc4", APP_ENV="dev",
                 DEV_IDENTITY_SWITCH="true", SCHEDULER_ENABLED="false", DINGTALK_BASE_URL="http://127.0.0.1:8024",
                 DINGTALK_APP_KEY="stub", DINGTALK_APP_SECRET="stub", DINGTALK_AGENT_ID="10001",
                 DINGTALK_CORP_ID="ding-stub", APP_BASE_URL="http://127.0.0.1:8014").items():
    os.environ.setdefault(k, v)

from pathlib import Path  # noqa: E402

from fastapi import APIRouter, Request  # noqa: E402

import app.main as m  # noqa: E402
from app.config import load_settings  # noqa: E402
from app.core.clock import clock  # noqa: E402
from app.dingtalk.outbox import process_outbox  # noqa: E402

if os.environ.get("E4_STATIC_DIR"):
    m.STATIC_DIR = Path(os.environ["E4_STATIC_DIR"]).resolve()

app = m.create_app(load_settings())

if app.state.settings.APP_ENV == "dev":
    ctl = APIRouter()

    @ctl.post("/_e2e/outbox")
    def flush_outbox(request: Request):
        with request.app.state.session_maker() as db:
            result = process_outbox(db, request.app.state.dingtalk, clock.now())
            db.commit()
        return result

    @ctl.get("/_e2e/recompute")
    def recompute(store: str, month: str):
        """RULE-08 独立重算：按 CMP-F06-01 公式从驱动值直接算该店铺当月人民币收入合计（不读系统算好的收入列）。"""
        from decimal import ROUND_HALF_UP, Decimal

        from sqlalchemy import text
        with app.state.session_maker() as db:
            rows = db.execute(text(
                "SELECT pu.spu_count, pu.avg_sales, pu.avg_price, pu.discount_rate, fx.rate FROM platform_unit pu "
                "JOIN store s ON s.id = pu.store_id JOIN budget_version v ON v.id = pu.version_id "
                "JOIN fx_budget fx ON fx.year = v.year AND fx.currency = s.currency "
                "WHERE s.name = :s AND pu.month = to_date(:m, 'YYYY-MM') AND v.type = 'draft'"),
                {"s": store, "m": month}).all()
        total = Decimal(0)
        for spu, sales, price, disc, fx in rows:
            total += Decimal(spu or 0) * (sales or 0) * (price or 0) * (1 - (disc or 0)) * fx
        return {"total": format(total.quantize(Decimal("0.01"), ROUND_HALF_UP), ",f"), "rows": len(rows)}

    app.include_router(ctl)
    app.router.routes.insert(0, app.router.routes.pop())
