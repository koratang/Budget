"""DATA-F01-01 用户、DATA-F01-02 角色与数据范围、DATA-F01-03 会话。"""
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at_col
from app.models.enums import AuthSource, ScopeType, check_in


class Role(Base):
    """8 类角色（迁移 0001 预置）。"""
    __tablename__ = "role"
    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class User(Base):
    __tablename__ = "app_user"
    id: Mapped[int] = mapped_column(primary_key=True)
    dingtalk_userid: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    union_id: Mapped[str | None] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    dingtalk_dept: Mapped[str | None] = mapped_column(String(128))  # 钉钉部门名称（展示用）
    department_id: Mapped[int | None] = mapped_column(ForeignKey("department.id"))  # 预算口径所属部门
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_col()


class UserRole(Base):
    __tablename__ = "user_role"
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True)
    role_code: Mapped[str] = mapped_column(ForeignKey("role.code"), primary_key=True)


class UserScope(Base):
    """数据范围：部门 / 渠道 / 店铺 / B 端客户 + 对象 ID。"""
    __tablename__ = "user_scope"
    __table_args__ = (
        UniqueConstraint("user_id", "scope_type", "object_id"),
        CheckConstraint(check_in("scope_type", ScopeType.ALL), name="scope_type"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False, index=True)
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False)
    object_id: Mapped[int] = mapped_column(Integer, nullable=False)


class UserSession(Base):
    """会话：库中只存令牌哈希；8 小时无操作失效。"""
    __tablename__ = "user_session"
    __table_args__ = (CheckConstraint(check_in("auth_source", (AuthSource.DINGTALK, AuthSource.DEV)),
                                      name="auth_source"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False, index=True)
    auth_source: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = created_at_col()
    last_active_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
