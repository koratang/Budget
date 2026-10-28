"""状态与类型代码（库中存英文代码，LABELS 给中文显示名）。"""


class Role:
    CEO = "ceo"
    FINANCE_HEAD = "finance_head"
    FINANCE_BP = "finance_bp"
    OPERATIONS = "operations"
    B2B = "b2b"
    LOGISTICS = "logistics"
    DEPT_HEAD = "dept_head"
    DEPT_BUDGET = "dept_budget"

    LABELS = {
        "ceo": "CEO", "finance_head": "财务负责人", "finance_bp": "财务BP", "operations": "运营",
        "b2b": "B端业务", "logistics": "物流物控", "dept_head": "部门负责人", "dept_budget": "部门预算专员",
    }
    ALL = tuple(LABELS)
    ALL_COMPANY = frozenset({"ceo", "finance_head", "finance_bp"})


class ScopeType:
    DEPARTMENT = "department"
    CHANNEL = "channel"
    STORE = "store"
    CUSTOMER = "customer"
    ALL = (DEPARTMENT, CHANNEL, STORE, CUSTOMER)


class AuthSource:
    DINGTALK = "dingtalk"
    DEV = "dev"


class TaskStatus:
    IN_PROGRESS = "in_progress"       # 进行中
    PENDING_CEO = "pending_ceo"       # 待CEO审批
    COMPLETED = "completed"           # 已完成
    LABELS = {"in_progress": "进行中", "pending_ceo": "待CEO审批", "completed": "已完成"}


class VersionType:
    DRAFT = "draft"                         # 编制稿
    ORIGINAL_TARGET = "original_target"     # 年初原始目标
    ADJUSTMENT_DRAFT = "adjustment_draft"   # 调整稿
    ADJUSTED_TARGET = "adjusted_target"     # 调整后目标
    ROLLING_DRAFT = "rolling_draft"         # 滚动预测稿
    SNAPSHOT = "snapshot"                   # 季度快照
    LABELS = {"draft": "编制稿", "original_target": "年初原始目标", "adjustment_draft": "调整稿",
              "adjusted_target": "调整后目标", "rolling_draft": "滚动预测稿", "snapshot": "季度快照"}


class UnitType:
    PLATFORM = "platform"             # 平台渠道（店铺）
    B2B = "b2b"                       # B 端（负责部门）
    COST_RATIO = "cost_ratio"         # 成本比例
    LOGISTICS_RATIO = "logistics_ratio"  # 物流比例
    DEPT_EXPENSE = "dept_expense"     # 部门费用（部门）
    LABELS = {"platform": "平台渠道", "b2b": "B端", "cost_ratio": "成本比例",
              "logistics_ratio": "物流比例", "dept_expense": "部门费用"}


class UnitStatus:
    NOT_STARTED = "not_started"       # 未开始
    FILLING = "filling"               # 填报中
    ADJUSTING = "adjusting"           # 调整中（调整单位）
    SUBMITTED = "submitted"           # 已提交
    DEPT_APPROVED = "dept_approved"   # 部门已通过（调整单位）
    APPROVED = "approved"             # 已通过
    RETURNED = "returned"             # 已退回
    LABELS = {"not_started": "未开始", "filling": "填报中", "adjusting": "调整中", "submitted": "已提交",
              "dept_approved": "部门已通过", "approved": "已通过", "returned": "已退回"}
    EDITABLE = frozenset({"not_started", "filling", "adjusting", "returned"})


class AdjustmentStatus:
    IN_PROGRESS = "in_progress"   # 调整进行中
    PENDING_CEO = "pending_ceo"   # 待CEO终审
    EFFECTIVE = "effective"       # 已生效
    LABELS = {"in_progress": "调整进行中", "pending_ceo": "待CEO终审", "effective": "已生效"}


class RuleType:
    DRIVER = "driver_assumption"   # 驱动假设
    ALERT = "alert_rule"           # 预警规则
    QUOTA = "quota_standard"       # 额度标准
    LABELS = {"driver_assumption": "驱动假设", "alert_rule": "预警规则", "quota_standard": "额度标准"}


class Credibility:
    UNVERIFIED = "unverified"   # 未验证经验
    OBSERVED = "observed"       # 历史观察
    VERIFIED = "verified"       # 已验证
    LABELS = {"unverified": "未验证经验", "observed": "历史观察", "verified": "已验证"}


class RuleVersionStatus:
    PENDING = "pending"             # 待审批
    PENDING_CEO = "pending_ceo"     # 待CEO审批
    EFFECTIVE = "effective"         # 生效
    HISTORY = "history"             # 历史
    RETURNED = "returned"           # 已退回
    LABELS = {"pending": "待审批", "pending_ceo": "待CEO审批", "effective": "生效",
              "history": "历史", "returned": "已退回"}


class AlertStatus:
    OPEN = "open"           # 未处理
    RESOLVED = "resolved"   # 已处理
    LABELS = {"open": "未处理", "resolved": "已处理"}


class NotifyStatus:
    PENDING = "pending"     # 待发送
    SENT = "sent"           # 已发送
    RETRYING = "retrying"   # 重试中
    FAILED = "failed"       # 通知失败
    LABELS = {"pending": "待发送", "sent": "已发送", "retrying": "重试中", "failed": "通知失败"}


class OutboxStatus:
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class ImportSource:
    KINGDEE = "kingdee"
    KINGDEE_HISTORY = "kingdee-history"
    OPS_HISTORY = "ops-history"             # 经营历史表：渠道店铺月度毛利 + 管理费用明细
    BI = "bi"
    SKU = "sku"
    TEMPLATE = "template"


class ImportStatus:
    VALIDATING = "validating"               # 校验中
    VALIDATION_FAILED = "validation_failed" # 校验失败
    PENDING_CONFIRM = "pending_confirm"     # 待确认
    EFFECTIVE = "effective"                 # 已生效
    REPLACED = "replaced"                   # 已被替换
    DISCARDED = "discarded"                 # 已放弃
    INTERRUPTED = "interrupted"             # 校验中断，请重新上传
    LABELS = {"validating": "校验中", "validation_failed": "校验失败", "pending_confirm": "待确认",
              "effective": "已生效", "replaced": "已被替换", "discarded": "已放弃",
              "interrupted": "校验中断，请重新上传"}


class OtherPlItem:
    FINANCE_COST = "finance_cost"     # 财务费用
    FX_GAIN_LOSS = "fx_gain_loss"     # 汇兑损益
    NON_OPERATING = "non_operating"   # 营业外收支
    INCOME_TAX = "income_tax"         # 所得税
    LABELS = {"finance_cost": "财务费用", "fx_gain_loss": "汇兑损益",
              "non_operating": "营业外收支", "income_tax": "所得税"}


def check_in(column: str, values) -> str:
    """生成 CHECK 约束表达式：column IN ('a','b')。"""
    return f"{column} IN ({', '.join(repr(v) for v in values)})"
