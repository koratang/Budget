"""实际数导入与核对（API-F09-01~05）：/imports、/reconciliation。

上传后在后台线程校验（BackgroundTasks，同步函数由 Starlette 放入线程池，不阻塞其他请求，NFR-002）；
校验使用独立会话：默认 app.state.session_maker，测试可设置 app.state.import_session_factory。
上传、确认、放弃仅财务BP；查看导入记录财务BP 与财务负责人；核对财务BP、财务负责人、CEO。
"""
from datetime import date

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.calc.periods import fmt_month, parse_month
from app.core.auth import CurrentUser
from app.core.clock import clock
from app.core.errors import NotFound, ValidationFailed
from app.core.scope import require_roles
from app.db import get_db
from app.models import ImportBatch
from app.models.enums import Role
from app.services import importer
from app.services.versions import Actor

router = APIRouter(prefix="", tags=["imports"])

UPLOADERS = (Role.FINANCE_BP,)
VIEWERS = (Role.FINANCE_BP, Role.FINANCE_HEAD)


def _actor(current: CurrentUser) -> Actor:
    return Actor(user=current.user, roles=current.roles, auth_source=current.auth_source)


def _session_factory(request: Request):
    factory = getattr(request.app.state, "import_session_factory", None)
    return factory or request.app.state.session_maker


@router.post("/imports")
async def upload(request: Request, background: BackgroundTasks, file: UploadFile = File(...),
                 source: str = Form(...), year: int | None = Form(None),
                 current: CurrentUser = Depends(require_roles(*UPLOADERS)), db: Session = Depends(get_db)):
    content = await file.read()
    batch = importer.create_batch(db, _actor(current), source=source, file_name=file.filename or "未命名.xlsx",
                                  content=content, data_dir=request.app.state.settings.DATA_DIR, request=request,
                                  year=year)
    db.commit()
    background.add_task(importer.run_validation, _session_factory(request), batch.id)
    return {"id": batch.id, "status": "validating", "file_name": batch.file_name, "source": batch.source}


@router.get("/imports")
def records(source: str | None = None, current: CurrentUser = Depends(require_roles(*VIEWERS)),
            db: Session = Depends(get_db)):
    return {"records": importer.list_records(db, source), **importer.overview(db, clock.today()),
            "can_upload": current.has_role(*UPLOADERS)}


def _batch(db: Session, batch_id: int) -> ImportBatch:
    batch = db.get(ImportBatch, batch_id)
    if batch is None or batch.parent_batch_id is not None:
        raise NotFound("导入批次不存在")
    return batch


@router.get("/imports/{batch_id}", dependencies=[Depends(require_roles(*VIEWERS))])
def batch_status(batch_id: int, db: Session = Depends(get_db)):
    return importer.batch_view(db, _batch(db, batch_id))


class ConfirmIn(BaseModel):
    overwrite: bool = False


@router.post("/imports/{batch_id}/confirm")
def confirm(batch_id: int, body: ConfirmIn, request: Request,
            current: CurrentUser = Depends(require_roles(*UPLOADERS)), db: Session = Depends(get_db)):
    try:
        view = importer.confirm_batch(db, _actor(current), batch_id, overwrite=body.overwrite,
                                      base_url=request.app.state.settings.APP_BASE_URL, request=request)
        db.commit()
    except Exception:
        db.rollback()  # 整次确认回滚：原批次仍生效、新批次未生效、无预警与通知（RULE-05）
        raise
    return view


@router.post("/imports/{batch_id}/create-missing")
def create_missing(batch_id: int, request: Request, current: CurrentUser = Depends(require_roles(*UPLOADERS)),
                   db: Session = Depends(get_db)):
    """经营历史表：补建缺少的店铺 / B 端客户 / 管理费用科目后重新校验。"""
    view = importer.create_missing_master(db, _actor(current), batch_id, request=request)
    db.commit()
    return view


@router.post("/imports/{batch_id}/discard")
def discard(batch_id: int, current: CurrentUser = Depends(require_roles(*UPLOADERS)),
            db: Session = Depends(get_db)):
    view = importer.discard_batch(db, _actor(current), batch_id)
    db.commit()
    return view


@router.get("/reconciliation", dependencies=[Depends(require_roles(Role.FINANCE_BP, Role.FINANCE_HEAD, Role.CEO))])
def reconciliation(month: str | None = None, channel_id: int | None = None, over_only: bool = False,
                   db: Session = Depends(get_db)):
    if month:
        try:
            m = parse_month(month)
        except ValueError as e:
            raise ValidationFailed("月份格式应为 YYYY-MM") from e
    else:
        ready = importer.reconciliation(db, date(1900, 1, 1))["ready_months"]
        m = parse_month(ready[-1]) if ready else clock.today().replace(day=1)
    data = importer.reconciliation(db, m, channel_id=channel_id, over_only=over_only)
    data["month"] = fmt_month(m)
    return data
