"""全部 DATA-* 实体（技术方案 §5.1）。导入本包即注册到 Base.metadata。"""
from app.models.actuals import BiActualAgg, BiActualSku, ImportBatch, ImportStaging, KingdeeActual, VarianceNote
from app.models.auth import Role, User, UserRole, UserScope, UserSession
from app.models.base import Base
from app.models.bizfin import BizfinSection
from app.models.budget import (ApprovalRecord, B2bUnit, BudgetTask, BudgetVersion, ChannelCategoryRatio,
                               ChannelSiteRatio, CompanyOtherPl, DeptExpense, FillingUnit, PlatformUnit, Reserve,
                               ReserveUsage, SnapshotMonth, TargetAdjustment)
from app.models.master import (BCustomer, BudgetAccount, Category, Channel, Department, FxActual, FxBudget,
                               KingdeeAccountMap, Site, Sku, Spu, Store)
from app.models.rules import Alert, AuditLog, NotificationOutbox, Rule, RuleVersion

__all__ = [
    "Base",
    "Role", "User", "UserRole", "UserScope", "UserSession",
    "Channel", "Site", "Store", "Department", "BCustomer", "BudgetAccount", "KingdeeAccountMap",
    "Category", "Spu", "Sku", "FxBudget", "FxActual",
    "BudgetVersion", "BudgetTask", "TargetAdjustment", "FillingUnit", "PlatformUnit", "ChannelCategoryRatio",
    "ChannelSiteRatio", "B2bUnit", "DeptExpense", "Reserve", "ReserveUsage", "CompanyOtherPl", "SnapshotMonth",
    "ApprovalRecord",
    "ImportBatch", "ImportStaging", "KingdeeActual", "BiActualSku", "BiActualAgg", "VarianceNote",
    "Rule", "RuleVersion", "Alert", "NotificationOutbox", "AuditLog",
    "BizfinSection",
]
