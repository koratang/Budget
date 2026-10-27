"""样例主数据与人员（契约「测试数据」段 + 设计样例数据，真实中文）。seed.py 与钉钉替身共用人员清单。"""

DEPARTMENTS = ["产品作战部", "开发部", "研发部", "供应中心", "运营部", "市场部", "美国业务部", "视觉部", "外贸部",
               "物流物控部", "项目管理部", "信息数字化部", "人力资源部", "财务部", "总经办"]

SITES = [("US", "美国"), ("CA", "加拿大"), ("UK", "英国"), ("DE", "德国")]

CHANNELS = ["Amazon", "Wayfair", "Home Depot", "Lowe's", "独立站", "TikTok Shop"]

# (店铺, 渠道, 站点代码, 结算币种)
STORES = [
    ("Amazon-US-01", "Amazon", "US", "USD"),
    ("Amazon-CA-01", "Amazon", "CA", "CAD"),
    ("Amazon-UK-01", "Amazon", "UK", "GBP"),
    ("Amazon-DE-01", "Amazon", "DE", "EUR"),
    ("Wayfair-US-01", "Wayfair", "US", "USD"),
    ("HomeDepot-US-01", "Home Depot", "US", "USD"),
    ("Lowes-US-01", "Lowe's", "US", "USD"),
    ("Lowes-US-02", "Lowe's", "US", "USD"),
    ("Shopify-US-01", "独立站", "US", "USD"),
    ("TikTok-US-01", "TikTok Shop", "US", "USD"),
]
# TikTok-US-01 新渠道起始月（FLOW-04 中由财务负责人标记；seed.py --mark-new-channel 时预置）
NEW_CHANNEL_STORE = ("TikTok-US-01", "2027-03")

CATEGORIES = ["框镜", "灯镜", "镜柜", "浴室门", "浴室柜"]

# (客户, 负责部门, 结算币种)
B_CUSTOMERS = [("Ferguson", "美国业务部", "USD"), ("Menards", "美国业务部", "USD"), ("Bauhaus", "外贸部", "EUR")]

# 预算科目：(名称, 是否部门费用科目, 损益口径)
BUDGET_ACCOUNTS = [
    ("工资薪酬", True, None), ("社保公积金", True, None), ("培训费", True, None), ("员工关怀费", True, None),
    ("差旅费", True, None), ("办公费", True, None), ("房租物业", True, None), ("招聘费", True, None),
    ("软件服务费", True, None), ("业务招待费", True, None),
    ("平台销售收入", False, "revenue"), ("销售退款", False, "refund"), ("采购成本", False, "purchase_cost"),
    ("平台佣金", False, "commission"), ("推广费用", False, "promotion"), ("头程费", False, "first_leg"),
    ("尾程费", False, "last_mile"), ("关税", False, "tariff"), ("仓储费", False, "storage"),
    ("库存索赔", False, "inventory_claim"), ("其他运营费用", False, "other_opex"),
    ("财务费用", False, "finance_cost"), ("汇兑损益", False, "fx_gain_loss"), ("营业外收支", False, "non_operating"),
    ("所得税", False, "income_tax"),
]

# 金蝶科目编码 → 预算科目（示例；6601.99 等未列编码视为未映射）
KINGDEE_ACCOUNTS = [
    ("6001", "主营业务收入", "平台销售收入"), ("6001.01", "主营业务收入-退款", "销售退款"),
    ("6401", "主营业务成本", "采购成本"), ("6601.01", "销售费用-平台佣金", "平台佣金"),
    ("6601.02", "销售费用-推广费", "推广费用"), ("6601.03", "销售费用-头程运费", "头程费"),
    ("6601.04", "销售费用-尾程运费", "尾程费"), ("6601.05", "销售费用-关税", "关税"),
    ("6601.06", "销售费用-仓储费", "仓储费"), ("6601.07", "销售费用-其他运营费用", "其他运营费用"),
    ("6051", "其他业务收入-库存索赔", "库存索赔"),
    ("6602.01", "管理费用-工资", "工资薪酬"), ("6602.02", "管理费用-社保公积金", "社保公积金"),
    ("6602.03", "管理费用-培训费", "培训费"), ("6602.04", "管理费用-员工关怀", "员工关怀费"),
    ("6602.05", "管理费用-差旅费", "差旅费"), ("6602.06", "管理费用-办公费", "办公费"),
    ("6602.07", "管理费用-房租物业", "房租物业"), ("6602.08", "管理费用-招聘费", "招聘费"),
    ("6602.09", "管理费用-软件服务费", "软件服务费"), ("6602.10", "管理费用-业务招待费", "业务招待费"),
    ("6603", "财务费用", "财务费用"), ("6603.02", "财务费用-汇兑损益", "汇兑损益"),
    ("6711", "营业外支出", "营业外收支"), ("6801", "所得税费用", "所得税"),
]

# 2027 年度预算汇率（2026-09-30 中行中间价口径示例值，以财务BP录入为准）
FX_BUDGET_2027 = [("USD", "7.12"), ("CAD", "5.24"), ("EUR", "7.79"), ("GBP", "9.31")]

# 人员：(钉钉 userid, 姓名, 部门, 角色列表, 数据范围 {类型: [名称]}, 是否部门负责人)
PEOPLE = [
    ("linxiao", "林晓", "财务部", ["finance_head"], {}, True),
    ("zhoumingyuan", "周明远", "总经办", ["ceo"], {}, True),
    ("chensiyu", "陈思雨", "财务部", ["finance_bp"], {}, False),
    ("wanghao", "王浩", "运营部", ["operations"], {"store": ["Amazon-US-01"]}, False),
    ("lijiaqi", "李佳琪", "运营部", ["operations"], {"store": ["Amazon-CA-01", "Amazon-UK-01", "Amazon-DE-01"]}, False),
    ("huangzixuan", "黄子轩", "运营部", ["operations"],
     {"store": ["Wayfair-US-01", "HomeDepot-US-01", "Lowes-US-01", "Lowes-US-02"]}, False),
    ("tangyue", "唐悦", "运营部", ["operations"], {"store": ["Shopify-US-01", "TikTok-US-01"]}, False),
    ("zhaolei", "赵磊", "运营部", ["dept_head"], {"department": ["运营部"]}, True),
    ("sunting", "孙婷", "美国业务部", ["b2b"], {"customer": ["Ferguson", "Menards"]}, False),
    ("hanliqun", "韩立群", "美国业务部", ["dept_head"], {"department": ["美国业务部"]}, True),
    ("liuyang", "刘洋", "外贸部", ["b2b"], {"customer": ["Bauhaus"]}, False),
    ("xuwenbo", "许文博", "外贸部", ["dept_head"], {"department": ["外贸部"]}, True),
    ("jiangfan", "蒋帆", "物流物控部", ["logistics"], {}, False),
    ("hejianguo", "何建国", "物流物控部", ["dept_head"], {"department": ["物流物控部"]}, True),
    ("zhengke", "郑可", "人力资源部", ["dept_budget"], {"department": ["人力资源部"]}, False),
    ("wujing", "吴静", "人力资源部", ["dept_head"], {"department": ["人力资源部"]}, True),
    ("zhaoyiming", "赵一鸣", "视觉部", [], {}, False),  # 通讯录中存在但未分配角色（AC-F01-02）
]
