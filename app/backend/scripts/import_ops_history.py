"""命令行导入经营历史表（试用版首次启动用；与页面「实际数导入 → 经营历史表」同一服务流程）。

用法：
    cd app/backend && python -m scripts.import_ops_history <文件.xlsx> --year 2026 [--create-missing] [--as 陈思雨]
--create-missing：只缺主数据时按页面同一推断规则补建后重新校验。已有同期间数据时不覆盖，直接退出并提示。
"""
import argparse
import sys
from pathlib import Path

from sqlalchemy import select

from app.config import get_settings
from app.db import session_factory
from app.models import ImportBatch, User
from app.models.enums import ImportSource
from app.services import importer
from app.services.versions import as_actor


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--create-missing", action="store_true")
    ap.add_argument("--as", dest="user", default="陈思雨")
    args = ap.parse_args()
    settings = get_settings()
    path = Path(args.file)
    with session_factory(settings.DATABASE_URL)() as db:
        user = db.scalar(select(User).where(User.name == args.user))
        if user is None:
            print(f"找不到用户 {args.user}")
            return 1
        actor = as_actor(db, user)
        batch = importer.create_batch(db, actor, source=ImportSource.OPS_HISTORY, file_name=path.name,
                                      content=path.read_bytes(), data_dir=settings.DATA_DIR, year=args.year)
        db.commit()
        importer.validate_batch(db, batch.id)
        view = importer.batch_view(db, db.get(ImportBatch, batch.id))
        if view["status"] == "failed" and args.create_missing and view.get("missing_master"):
            view = importer.create_missing_master(db, actor, batch.id)
            db.commit()
            print(f"已补建：{view['created']}")
        if view["status"] != "passed":
            for i in view["issues"]:
                if not i["warning"]:
                    print(f"{i['row']} {i['type']} {i['name'] or ''}")
            print("校验未通过，未写入")
            return 1
        if view["needs_overwrite"]:
            importer.discard_batch(db, actor, batch.id)
            db.commit()
            print("这些期间已有实际数，未覆盖：" + "、".join(view["periods"]))
            return 0
        importer.confirm_batch(db, actor, batch.id, overwrite=False, base_url=settings.APP_BASE_URL)
        db.commit()
        print(f"已导入 {args.year} 年经营历史表：{'、'.join(view['periods'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
