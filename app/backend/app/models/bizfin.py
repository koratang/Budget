"""DATA-F15-01 业财分析工作区（REQ-F15-01）：财务指标、业务指标维度填报、政策事件各存一份 JSON 文档。

计算（勾稽、派生、分析模型）全部在前端引擎完成，服务端只做按部分存取、乐观锁与审计（DEC-029）。
"""
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

SECTION_KEYS = ("indicators", "biz_dim", "policy")


class BizfinSection(Base):
    __tablename__ = "bizfin_section"
    __table_args__ = (CheckConstraint("key IN ('indicators', 'biz_dim', 'policy')", name="key"),)
    key: Mapped[str] = mapped_column(String(16), primary_key=True)
    data: Mapped[dict | list] = mapped_column(JSONB, nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False)  # 仍是示例数据（未经数据管理导入正式数据）
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_by: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
