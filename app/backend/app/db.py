"""SQLAlchemy 2 同步引擎与会话。

路由通过 Depends(get_db) 取会话（来自 app.state.session_maker），业务处理结束时由路由自行 commit；
测试中以 dependency_overrides 替换为事务内会话，结束即回滚。
"""
from collections.abc import Iterator
from functools import lru_cache

from fastapi import Request
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


@lru_cache
def get_engine(url: str) -> Engine:
    # 会话时区固定为北京时间：timestamptz 读出即带 +08:00（PRD §3.2.1 通用约定）
    return create_engine(url, pool_pre_ping=True, connect_args={"options": "-c timezone=Asia/Shanghai"})


def session_factory(url: str) -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(url), expire_on_commit=False)


def get_db(request: Request) -> Iterator[Session]:
    db = request.app.state.session_maker()
    try:
        yield db
    finally:
        db.close()
