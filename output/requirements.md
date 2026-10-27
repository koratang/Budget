# 预算管理平台 Requirements Contract

## Metadata

- work_type: feature
- workflow_mode: standard
- revision: 4
- scope: 本期
- source_prd: PRD详细版.md
- status: active

> 本期 = 用户确认的完整闭环（state.json OQ-1 选 A；scene-anchor.md V1 确认）。现金流预算、金蝶星空 WebAPI 自动取数属于后续阶段，不在本契约中建 REQ。

## External capability configuration

| Capability | Credential owner | Configuration actor | Surface | Scope | Lifecycle | Stage | Requirement IDs |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 钉钉企业内部应用（登录、工作通知） | 信息数字化部 | 信息数字化部 | deployment-secret | system | 部署时写入 AppKey/AppSecret；凭据轮换时由信息数字化部更新部署配置并重启服务 | 本期 | REQ-F01-01, REQ-F03-01, REQ-F11-02 |

## Capability prerequisites

| Prerequisite | Status | Owner | Evidence or deadline | Fallback | Stage | Requirement IDs |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 钉钉开放平台企业内部应用（AppKey/AppSecret，通讯录只读与工作通知权限） | committed | 信息数字化部 | 2026-11-30 前完成（用户告知，OQ-22）；编制任务 2026-12-01 发布（OQ-25） | 无：用户已选钉钉登录，不提供账号密码登录 | 本期 | REQ-F01-01, REQ-F03-01, REQ-F11-02 |
| 公司内部服务器（部署网页系统） | ready | 信息数字化部 | 用户告知可部署内部网页系统（2026-10-27 PRD 访谈 OQ-6） | 无 | 本期 | REQ-F01-01 |

## Feature F01 · 钉钉登录、角色与数据权限

### US-F01-01 · 用钉钉登录并只看到自己负责的数据

- Role: 部门预算专员
- Goal: 用钉钉身份进入系统，只看到并填写本部门的预算
- Value: 不用另记账号，也不会误看、误改其他部门的数据
- Stage: 本期
- Status: active

### US-F01-02 · 给员工分配预算角色和数据范围

- Role: 财务负责人
- Goal: 为每个员工指定角色以及可见的部门、渠道或客户
- Value: 权限与职责一一对应
- Stage: 本期
- Status: active

### REQ-F01-01 · 钉钉身份登录

- Story: US-F01-01
- Stage: 本期
- Revision: 1
- Status: active

### AC-F01-01 · 已开通角色的员工进入系统

- Parent: REQ-F01-01
- Priority: P0
- EARS:

```text
WHEN 员工通过钉钉扫码或钉钉工作台免登完成身份验证，且其钉钉账号在系统中已分配至少一个角色
THE SYSTEM SHALL 进入首页并在页面显示该员工的姓名和角色名称
```

### AC-F01-02 · 未开通角色的员工被拒绝

- Parent: REQ-F01-01
- Priority: P0
- EARS:

```text
WHEN 员工钉钉身份验证成功但在系统中没有任何角色
THE SYSTEM SHALL 拒绝进入并显示「未开通预算权限，请联系财务负责人」
```

### AC-F01-03 · 停用账号无法登录

- Parent: REQ-F01-01
- Priority: P0
- EARS:

```text
WHEN 员工的钉钉账号已被企业停用或移出通讯录
THE SYSTEM SHALL 拒绝该员工登录，且已有会话在其下一次请求时失效
```

### REQ-F01-02 · 角色与数据范围分配

- Story: US-F01-02
- Stage: 本期
- Revision: 1
- Status: active

### AC-F01-04 · 分配后按新范围生效

- Parent: REQ-F01-02
- Priority: P0
- EARS:

```text
WHEN 财务负责人为某员工保存角色及数据范围（部门、渠道/店铺或 B 端客户）
THE SYSTEM SHALL 在该员工下一次页面请求时按新的角色和数据范围返回数据
```

### AC-F01-05 · 仅财务负责人可分配角色

- Parent: REQ-F01-02
- Priority: P0
- EARS:

```text
WHEN 非财务负责人角色的员工尝试打开角色分配功能
THE SYSTEM SHALL 拒绝访问并显示「无权限」
```

### REQ-F01-03 · 按角色限定数据范围

- Story: US-F01-01
- Stage: 本期
- Revision: 1
- Status: active

### AC-F01-06 · 部门角色只见本部门

- Parent: REQ-F01-03
- Priority: P0
- EARS:

```text
WHEN 部门负责人或部门预算专员查看部门费用预算、实际或报表
THE SYSTEM SHALL 只返回其被分配部门的数据
```

### AC-F01-07 · 运营只见负责渠道

- Parent: REQ-F01-03
- Priority: P0
- EARS:

```text
WHEN 运营查看或填写渠道驱动、预算、实际或偏差报告
THE SYSTEM SHALL 只返回其被分配渠道/店铺的数据
```

### AC-F01-08 · B端业务只见负责客户

- Parent: REQ-F01-03
- Priority: P0
- EARS:

```text
WHEN B端业务（美国业务部、外贸部）查看或填写 B 端预算、实际或报表
THE SYSTEM SHALL 只返回其被分配 B 端客户的数据
```

### AC-F01-09 · 物流物控只填物流比例

- Parent: REQ-F01-03
- Priority: P0
- EARS:

```text
WHEN 物流物控查看或填写预算
THE SYSTEM SHALL 只展示和允许编辑头程费率、尾程费率、仓储费率、关税率四项及其所在的渠道/站点/品类维度，不展示收入金额与利润
```

### AC-F01-10 · 管理层看全公司

- Parent: REQ-F01-03
- Priority: P0
- EARS:

```text
WHEN CEO、财务负责人或财务BP查看任意预算、实际或报表
THE SYSTEM SHALL 返回全公司全部部门、渠道和 B 端客户的数据
```

### AC-F01-11 · 越权访问被拒

- Parent: REQ-F01-03
- Priority: P0
- EARS:

```text
WHEN 员工通过链接或接口请求其数据范围以外的记录
THE SYSTEM SHALL 返回「无权限」且不返回该记录的任何字段
```

## Feature F02 · 主数据维护

### US-F02-01 · 维护预算所需的基础对照数据

- Role: 财务BP
- Goal: 维护渠道/店铺/站点、品类与 SPU/SKU、B 端客户、部门、科目映射和汇率
- Value: 预算与金蝶、BI 实际数按同一口径对得上
- Stage: 本期
- Status: active

### REQ-F02-01 · 渠道、店铺、站点与币种

- Story: US-F02-01
- Stage: 本期
- Revision: 1
- Status: active

### AC-F02-01 · 新增店铺可用于编制与导入

- Parent: REQ-F02-01
- Priority: P0
- EARS:

```text
WHEN 财务BP新增一个店铺并指定所属渠道、站点和结算币种后保存
THE SYSTEM SHALL 在预算填报、实际导入的店铺选项和校验中包含该店铺
```

### AC-F02-02 · 店铺名称与金蝶、BI 一致校验

- Parent: REQ-F02-01
- Priority: P1
- EARS:

```text
WHEN 财务BP保存的店铺名称与已有店铺名称重复
THE SYSTEM SHALL 拒绝保存并提示「店铺名称已存在」
```

### AC-F02-10 · 停用店铺

- Parent: REQ-F02-01
- Priority: P1
- EARS:

```text
WHEN 财务BP将某店铺状态设为停用
THE SYSTEM SHALL 在新预算填报中不再列出该店铺，但历史实际导入仍接受该店铺的数据
```

### REQ-F02-02 · SKU/SPU/品类对照表与新老品判定

- Story: US-F02-01
- Stage: 本期
- Revision: 1
- Status: active

### AC-F02-03 · 对照表缺字段的行被拒

- Parent: REQ-F02-02
- Priority: P0
- EARS:

```text
WHEN 财务BP上传 SKU 对照表且其中有行缺少 SKU、SPU 编码、品类或首次上架日期
THE SYSTEM SHALL 拒绝整份文件写入，并列出每个问题行的行号和缺失字段
```

### AC-F02-04 · 新品判定

- Parent: REQ-F02-02
- Priority: P0
- EARS:

```text
WHEN 系统为某月判定某 SPU 的新老品属性
THE SYSTEM SHALL 在该月最后一天早于「首次上架日期加 12 个月」时判为新品，否则判为老品
```

### REQ-F02-03 · 金蝶科目到预算科目映射

- Story: US-F02-01
- Stage: 本期
- Revision: 2
- Status: active

### AC-F02-05 · 维护映射

- Parent: REQ-F02-03
- Priority: P0
- EARS:

```text
WHEN 财务BP为一个金蝶科目编码选择对应的预算科目并保存
THE SYSTEM SHALL 在之后的每次金蝶导入中将该科目金额归集到所选预算科目
```

### AC-F02-12 · 维护预算科目清单

- Parent: REQ-F02-03
- Priority: P0
- EARS:

```text
WHEN 财务BP新增、改名或停用一个预算科目并保存
THE SYSTEM SHALL 在部门费用填报和科目映射的预算科目选项中按新清单显示；已停用科目不再出现在新填报中，但已有预算与实际数据保留
```

### REQ-F02-04 · 预算汇率与月度实际汇率

- Story: US-F02-01
- Stage: 本期
- Revision: 3
- Status: active

### AC-F02-06 · 预算汇率按年度维护

- Parent: REQ-F02-04
- Priority: P0
- EARS:

```text
WHEN 财务BP为某预算年度录入某币种对人民币的预算汇率并保存
THE SYSTEM SHALL 用该汇率折算该年度所有该币种的预算金额
```

### AC-F02-07 · 缺预算汇率阻止提交

- Parent: REQ-F02-04
- Priority: P0
- EARS:

```text
WHEN 填报内容涉及的币种在该预算年度没有预算汇率
THE SYSTEM SHALL 阻止提交并提示缺少汇率的币种代码
```

### AC-F02-08 · 月度实际汇率

- Parent: REQ-F02-04
- Priority: P0
- EARS:

```text
WHEN 财务BP为某月录入某币种的当月平均汇率并保存
THE SYSTEM SHALL 将该汇率作为该币种当月平均汇率，用于把该月 BI 本币实际收入折算为人民币并计算汇率差
```

### AC-F02-11 · 原始目标锁定后预算汇率冻结

- Parent: REQ-F02-04
- Priority: P0
- EARS:

```text
WHEN 某预算年度的年初原始目标已经 CEO 审批锁定
THE SYSTEM SHALL 禁止修改该年度已有币种的预算汇率并在汇率页显示「已随年初原始目标锁定」，同时允许为该年度尚无预算汇率的币种新增预算汇率
```

### REQ-F02-05 · B 端客户与部门清单

- Story: US-F02-01
- Stage: 本期
- Revision: 1
- Status: active

### AC-F02-09 · 新增 B 端客户

- Parent: REQ-F02-05
- Priority: P0
- EARS:

```text
WHEN 财务BP新增 B 端客户并指定负责部门（美国业务部或外贸部）与结算币种后保存
THE SYSTEM SHALL 在该负责部门的 B 端填报中列出该客户
```

## Feature F03 · 编制任务

### US-F03-01 · 下发年度编制任务并跟踪进度

- Role: 财务负责人
- Goal: 一次下发年度编制任务，随时看到谁还没交
- Value: 15 个部门按期完成填报
- Stage: 本期
- Status: active

### REQ-F03-01 · 发布编制任务

- Story: US-F03-01
- Stage: 本期
- Revision: 2
- Status: active

### AC-F03-01 · 发布即通知填报人

- Parent: REQ-F03-01
- Priority: P0
- EARS:

```text
WHEN 财务负责人发布一个包含预算年度、截止日期和参与填报单位的编制任务
THE SYSTEM SHALL 向每个参与单位的填报人发送钉钉工作通知，内容包含预算年度、截止日期和系统链接
```

### AC-F03-02 · 同一年度只允许一个进行中的编制任务

- Parent: REQ-F03-01
- Priority: P1
- EARS:

```text
WHEN 该预算年度已有未完成 CEO 审批的编制任务
THE SYSTEM SHALL 阻止发布新的同年度编制任务并提示已有任务名称
```

### AC-F03-05 · 填报单位划分

- Parent: REQ-F03-01
- Priority: P0
- EARS:

```text
WHEN 财务负责人发布编制任务
THE SYSTEM SHALL 按以下规则生成填报单位：平台渠道每个启用店铺一个单位（运营填报）、B 端每个负责部门一个单位（美国业务部、外贸部）、成本比例一个单位（财务BP）、物流比例一个单位（物流物控）、每个参与部门的部门费用一个单位；每个单位独立提交、审核和退回
```

### REQ-F03-02 · 填报进度与逾期提醒

- Story: US-F03-01
- Stage: 本期
- Revision: 1
- Status: active

### AC-F03-03 · 进度看板

- Parent: REQ-F03-02
- Priority: P0
- EARS:

```text
WHEN 财务负责人打开编制任务
THE SYSTEM SHALL 显示每个填报单位的状态（未开始、填报中、已提交、已退回、已通过）及已提交单位数占全部单位数的百分比
```

### AC-F03-04 · 逾期提醒

- Parent: REQ-F03-02
- Priority: P1
- EARS:

```text
WHEN 截止日期次日 09:00 仍有单位状态不是已提交或已通过
THE SYSTEM SHALL 向该单位填报人及其部门负责人发送钉钉逾期提醒
```

## Feature F04 · 收入与渠道成本驱动填报

### US-F04-01 · 运营填写平台渠道销售驱动

- Role: 运营
- Goal: 按月、渠道/店铺、站点、品类、新老品填写 SPU 数量、平均销量、平均单价和各项费率
- Value: 收入预算从品效出发，能看清渠道和品类差异
- Stage: 本期
- Status: active

### US-F04-02 · B 端业务填写客户销售预估

- Role: B端业务
- Goal: 按客户和月份填写销售额、退款率、推广费用率、其他运营费用率，以及平台佣金率和库存索赔率（默认 0）
- Value: B 端收入进入同一份利润预算
- Stage: 本期
- Status: active

### US-F04-03 · 财务BP和物流物控填写成本比例

- Role: 物流物控
- Goal: 物流物控填头程、尾程、仓储、关税比例；财务BP 填采购成本占比、库存索赔率和其他运营费用率
- Value: 各渠道和 B 端客户的毛利算得出来
- Stage: 本期
- Status: active

### REQ-F04-01 · 平台渠道驱动填报

- Story: US-F04-01
- Stage: 本期
- Revision: 1
- Status: active

### AC-F04-01 · 驱动字段

- Parent: REQ-F04-01
- Priority: P0
- EARS:

```text
WHEN 运营打开某渠道/店铺的预算填报
THE SYSTEM SHALL 按「月 × 店铺 × 站点 × 品类 × 新品/老品」提供 SPU 数量、单 SPU 平均销量、平均单价（本币）、折扣率、退款率、广告费率、佣金率七个输入项
```

### AC-F04-02 · 取值范围校验

- Parent: REQ-F04-01
- Priority: P0
- EARS:

```text
WHEN 填入的 SPU 数量不是大于等于 0 的整数、平均销量或平均单价小于 0、或任一比率不在 0% 到 100% 之间
THE SYSTEM SHALL 拒绝保存该单元格并显示该字段允许的取值范围
```

### REQ-F04-02 · B 端客户填报

- Story: US-F04-02
- Stage: 本期
- Revision: 2
- Status: active

### AC-F04-03 · B 端字段

- Parent: REQ-F04-02
- Priority: P0
- EARS:

```text
WHEN B端业务打开 B 端预算填报
THE SYSTEM SHALL 按「月 × B 端客户」提供销售额（本币）、退款率、推广费用率、其他运营费用率、平台佣金率、库存索赔率六个输入项，其中平台佣金率和库存索赔率默认值为 0%
```

### REQ-F04-03 · 成本比例填报

- Story: US-F04-03
- Stage: 本期
- Revision: 2
- Status: active

### AC-F04-04 · 采购成本占比

- Parent: REQ-F04-03
- Priority: P0
- EARS:

```text
WHEN 财务BP打开成本比例填报
THE SYSTEM SHALL 按「月 × 渠道 × 站点 × 品类」和「月 × B 端客户」提供采购成本占比输入项
```

### AC-F04-05 · 物流比例

- Parent: REQ-F04-03
- Priority: P0
- EARS:

```text
WHEN 物流物控打开物流比例填报
THE SYSTEM SHALL 按「月 × 渠道 × 站点 × 品类」和「月 × B 端客户」提供头程费率、尾程费率、仓储费率、关税率四个输入项
```

### AC-F04-11 · 库存索赔与其他运营费用比例

- Parent: REQ-F04-03
- Priority: P0
- EARS:

```text
WHEN 财务BP打开成本比例填报
THE SYSTEM SHALL 按「月 × 渠道 × 站点」提供库存索赔率和其他运营费用率两个输入项，该比例适用于该渠道站点下全部品类和新老品单元
```

### AC-F04-06 · 全年批量填充

- Parent: REQ-F04-03
- Priority: P1
- EARS:

```text
WHEN 填报人对某一维度组合选择「填充全年」并输入一个比率
THE SYSTEM SHALL 把该比率写入该组合 12 个月中尚未提交的月份
```

### REQ-F04-04 · Excel 模板填报

- Story: US-F04-01
- Stage: 本期
- Revision: 1
- Status: active

### AC-F04-07 · 下载模板

- Parent: REQ-F04-04
- Priority: P0
- EARS:

```text
WHEN 填报人点击下载填报模板
THE SYSTEM SHALL 生成仅包含其数据范围内维度组合和其负责输入项的 .xlsx 文件，并预填已保存的值
```

### AC-F04-08 · 上传有误整份不写入

- Parent: REQ-F04-04
- Priority: P0
- EARS:

```text
WHEN 上传的填报文件中任一行校验不通过
THE SYSTEM SHALL 不写入该文件的任何数据，并列出全部错误的行号、字段和原因
```

### REQ-F04-05 · 提交与锁定

- Story: US-F04-01
- Stage: 本期
- Revision: 1
- Status: active

### AC-F04-09 · 提交后锁定

- Parent: REQ-F04-05
- Priority: P0
- EARS:

```text
WHEN 填报人提交本单位的填报
THE SYSTEM SHALL 将该单位状态改为已提交，并在被退回之前禁止该单位任何人修改其内容
```

### AC-F04-10 · 同一单元并发修改

- Parent: REQ-F04-05
- Priority: P1
- EARS:

```text
WHEN 填报人保存某单元格时，该单元格在其打开页面之后已被其他人保存过
THE SYSTEM SHALL 拒绝本次保存，提示「该数据已被 {姓名} 于 {时间} 修改，请刷新后再改」
```

## Feature F05 · 部门费用预算与专项预留额度

### US-F05-01 · 部门预算专员填本部门费用

- Role: 部门预算专员
- Goal: 按预算科目和月份填写本部门费用，并为培训、福利等活动设置专项预留额度
- Value: 固定费用有额度可管，临时请示有据可查
- Stage: 本期
- Status: active

### REQ-F05-01 · 部门费用填报

- Story: US-F05-01
- Stage: 本期
- Revision: 1
- Status: active

### AC-F05-01 · 按科目×月填报

- Parent: REQ-F05-01
- Priority: P0
- EARS:

```text
WHEN 部门预算专员打开本部门费用填报
THE SYSTEM SHALL 按「预算科目 × 月」提供人民币金额输入项
```

### AC-F05-02 · 历史参考

- Parent: REQ-F05-01
- Priority: P0
- EARS:

```text
WHEN 部门预算专员查看某预算科目的填报行
THE SYSTEM SHALL 在同一行显示该部门该科目上一年同月实际金额和最近 12 个已导入月份的实际合计；无历史实际时显示「无历史数据」
```

### REQ-F05-02 · 专项预留额度

- Story: US-F05-01
- Stage: 本期
- Revision: 1
- Status: active

### AC-F05-03 · 创建专项

- Parent: REQ-F05-02
- Priority: P0
- EARS:

```text
WHEN 部门预算专员新增专项预留额度并填写名称、所属预算科目、金额和计划月份
THE SYSTEM SHALL 将该金额计入该部门该科目该月的预算，并在专项列表中显示该专项
```

### AC-F05-04 · 专项历史参考

- Parent: REQ-F05-02
- Priority: P1
- EARS:

```text
WHEN 查看专项预留额度列表
THE SYSTEM SHALL 为每个专项显示其所属预算科目在上一年的全年实际金额
```

### AC-F05-05 · 登记专项使用

- Parent: REQ-F05-02
- Priority: P0
- EARS:

```text
WHEN 财务BP为某专项登记一笔实际使用（金额、日期、金蝶凭证号）
THE SYSTEM SHALL 更新该专项的已用金额和剩余金额，剩余金额等于预留金额减已用金额
```

## Feature F06 · 预算计算

### US-F06-01 · 自动算出各层利润

- Role: 财务BP
- Goal: 驱动填完即得到从收入、毛利到公司净利润的完整预算
- Value: 不再手工汇总 Excel
- Stage: 本期
- Status: active

### REQ-F06-01 · 平台渠道单元计算

- Story: US-F06-01
- Stage: 本期
- Revision: 2
- Status: active

### AC-F06-01 · 销量与收入

- Parent: REQ-F06-01
- Priority: P0
- EARS:

```text
WHEN 某单元的驱动值被保存
THE SYSTEM SHALL 计算 销量 = SPU 数量 × 单 SPU 平均销量，收入（本币）= 销量 × 平均单价 × (1 − 折扣率)
```

### AC-F06-02 · 人民币折算

- Parent: REQ-F06-01
- Priority: P0
- EARS:

```text
WHEN 计算某单元的人民币收入
THE SYSTEM SHALL 使用 收入（本币）× 该币种该预算年度的预算汇率
```

### AC-F06-03 · 退款与各项费用

- Parent: REQ-F06-01
- Priority: P0
- EARS:

```text
WHEN 计算某单元的退款和各项费用
THE SYSTEM SHALL 以人民币收入为基数，分别乘以退款率、采购成本占比、佣金率、广告费率（推广费用）、头程费率、尾程费率、关税率、仓储费率、库存索赔率、其他运营费用率得到退款及各项金额
```

### AC-F06-04 · 毛利与毛利率

- Parent: REQ-F06-01
- Priority: P0
- EARS:

```text
WHEN 计算某单元的毛利
THE SYSTEM SHALL 计算 毛利 = 人民币收入 − 退款 − 采购成本 − 佣金 − 推广费用 − 头程费 − 尾程费 − 关税 − 仓储费 + 库存索赔 − 其他运营费用，毛利率 = 毛利 ÷ 人民币收入（人民币收入为 0 时毛利率显示为「—」）
```

### REQ-F06-02 · B 端与公司层计算

- Story: US-F06-01
- Stage: 本期
- Revision: 2
- Status: active

### AC-F06-05 · B 端毛利

- Parent: REQ-F06-02
- Priority: P0
- EARS:

```text
WHEN 计算某 B 端客户某月的毛利
THE SYSTEM SHALL 以 人民币收入 = 销售额（本币）× 预算汇率 为基数，按 AC-F06-03 与 AC-F06-04 相同的公式计算该客户的退款、各项费用、毛利和毛利率
```

### AC-F06-06 · 公司层其他损益

- Parent: REQ-F06-02
- Priority: P0
- EARS:

```text
WHEN 财务BP按月填写公司层其他损益项目（财务费用、汇兑损益、营业外收支、所得税）
THE SYSTEM SHALL 将其计入公司净利润，且不分摊到任何渠道、品类或部门
```

### AC-F06-07 · 公司净利润

- Parent: REQ-F06-02
- Priority: P0
- EARS:

```text
WHEN 计算某月公司净利润
THE SYSTEM SHALL 计算 公司净利润 = 全部平台渠道毛利 + 全部 B 端毛利 − 全部部门费用 + 公司层其他损益（损失为负数）
```

### AC-F06-08 · 双币展示

- Parent: REQ-F06-02
- Priority: P0
- EARS:

```text
WHEN 展示任一渠道、店铺或 B 端客户的收入
THE SYSTEM SHALL 同时显示本币金额（含币种代码）和人民币金额
```

### AC-F06-09 · 金额精度

- Parent: REQ-F06-02
- Priority: P0
- EARS:

```text
WHEN 显示或导出任一金额
THE SYSTEM SHALL 按四舍五入保留 2 位小数，且任一合计行与其明细行显示值之和的差额不超过 0.01 元乘以明细行数
```

## Feature F07 · 审核审批与目标锁定

### US-F07-01 · 逐级审核后由 CEO 拍板

- Role: CEO
- Goal: 审批财务负责人提交的全公司预算并锁定为年度目标
- Value: 目标一经锁定不被随意改动
- Stage: 本期
- Status: active

### US-F07-02 · 部门负责人审核本部门

- Role: 部门负责人
- Goal: 审核本部门填报，通过或退回
- Value: 部门对自己的数负责
- Stage: 本期
- Status: active

### REQ-F07-01 · 三级审批流程

- Story: US-F07-02
- Stage: 本期
- Revision: 1
- Status: active

### AC-F07-01 · 部门审核

- Parent: REQ-F07-01
- Priority: P0
- EARS:

```text
WHEN 某单位提交填报
THE SYSTEM SHALL 将该单位放入其部门负责人的待审核列表，并向该部门负责人发送钉钉工作通知
```

### AC-F07-02 · 退回必填原因

- Parent: REQ-F07-01
- Priority: P0
- EARS:

```text
WHEN 审核人选择退回但未填写退回原因
THE SYSTEM SHALL 阻止退回并提示「请填写退回原因」
```

### AC-F07-03 · 退回后可重新编辑

- Parent: REQ-F07-01
- Priority: P0
- EARS:

```text
WHEN 审核人填写原因并退回某单位
THE SYSTEM SHALL 将该单位状态改为已退回、解除其编辑锁定、在其填报页显示退回原因，并向填报人发送钉钉工作通知
```

### AC-F07-04 · 未全部通过不能提交 CEO

- Parent: REQ-F07-01
- Priority: P0
- EARS:

```text
WHEN 财务负责人提交 CEO 审批时仍有单位未通过部门审核
THE SYSTEM SHALL 阻止提交并列出未通过的单位名称
```

### REQ-F07-02 · CEO 审批锁定年初原始目标

- Story: US-F07-01
- Stage: 本期
- Revision: 1
- Status: active

### AC-F07-05 · 锁定原始目标

- Parent: REQ-F07-02
- Priority: P0
- EARS:

```text
WHEN CEO 审批通过全公司预算
THE SYSTEM SHALL 将该版本保存为「年初原始目标」，此后任何角色都不能直接修改该版本的数值
```

### AC-F07-06 · CEO 退回

- Parent: REQ-F07-02
- Priority: P0
- EARS:

```text
WHEN CEO 填写原因并退回全公司预算
THE SYSTEM SHALL 将编制任务退回财务负责人并显示原因，财务负责人可以把指定单位退回给其填报人
```

## Feature F08 · 版本、季度调整与滚动预测

### US-F08-01 · 每季度正式调整一次目标

- Role: 财务负责人
- Goal: 每季度发起一次目标调整，经审批后形成新的目标版本
- Value: 目标贴近实际，原始目标仍保留用于评估
- Stage: 本期
- Status: active

### US-F08-02 · 运营每季度更新滚动预测

- Role: 运营
- Goal: 每季度更新剩余月份的销售驱动
- Value: 管理层看到最新的全年预期
- Stage: 本期
- Status: active

### REQ-F08-01 · 季度目标调整

- Story: US-F08-01
- Stage: 本期
- Revision: 2
- Status: active

### AC-F08-01 · 每季度最多一次

- Parent: REQ-F08-01
- Priority: P0
- EARS:

```text
WHEN 当前自然季度内已有一次经 CEO 审批通过的目标调整
THE SYSTEM SHALL 阻止财务负责人发起新的目标调整
```

### AC-F08-02 · 只能调整未来月份

- Parent: REQ-F08-01
- Priority: P0
- EARS:

```text
WHEN 填报人在目标调整中编辑数值
THE SYSTEM SHALL 只允许修改尚未导入金蝶实际的月份
```

### AC-F08-03 · 调整原因必填

- Parent: REQ-F08-01
- Priority: P0
- EARS:

```text
WHEN 填报人提交目标调整时未填写调整原因
THE SYSTEM SHALL 阻止提交并提示「请填写调整原因」
```

### AC-F08-04 · 调整审批与生效

- Parent: REQ-F08-01
- Priority: P0
- EARS:

```text
WHEN 目标调整中每个参与单位依次经部门负责人、财务负责人审核通过，且 CEO 对整次调整一次性审批通过
THE SYSTEM SHALL 生成新的「调整后目标」版本，记录版本号、审批人、审批时间和调整原因，并保留年初原始目标与此前全部版本不变
```

### REQ-F08-02 · 季度滚动预测

- Story: US-F08-02
- Stage: 本期
- Revision: 1
- Status: active

### AC-F08-05 · 发起滚动更新

- Parent: REQ-F08-02
- Priority: P0
- EARS:

```text
WHEN 财务负责人发起某季度的滚动预测更新
THE SYSTEM SHALL 向运营、B端业务、物流物控和财务BP发送钉钉工作通知，并只开放本季度及以后月份的驱动供其更新
```

### AC-F08-06 · 已过月份取实际

- Parent: REQ-F08-02
- Priority: P0
- EARS:

```text
WHEN 生成滚动预测的全年数据
THE SYSTEM SHALL 对已导入金蝶实际的月份使用实际数，对其余月份使用最新提交的驱动计算值
```

### AC-F08-07 · 发布快照

- Parent: REQ-F08-02
- Priority: P0
- EARS:

```text
WHEN 财务负责人发布某季度滚动预测
THE SYSTEM SHALL 保存一个不可修改的快照，标注发布日期和所属季度，供预测准确度计算使用
```

### AC-F08-09 · 第一季度以原始目标作快照

- Parent: REQ-F08-02
- Priority: P1
- EARS:

```text
WHEN 财务负责人在预算年度第一季度选择「以年初原始目标发布」
THE SYSTEM SHALL 直接以年初原始目标的月度数据生成第一季度滚动预测快照，不需要各填报人重新提交
```

### REQ-F08-03 · 版本查看与对比

- Story: US-F08-01
- Stage: 本期
- Revision: 2
- Status: active

### AC-F08-08 · 两版本对比

- Parent: REQ-F08-03
- Priority: P1
- EARS:

```text
WHEN 用户选择任意两个预算版本进行对比
THE SYSTEM SHALL 按其数据范围列出每个维度组合在两个版本中的收入和毛利及其差额，并只在公司合计行列出两个版本的净利润及其差额
```

## Feature F09 · 实际数导入

### US-F09-01 · 每月上传金蝶与 BI 实际数

- Role: 财务BP
- Goal: 上传金蝶月度和 BI 双月 Excel，系统校验后入库
- Value: 预算与实际在同一口径对比
- Stage: 本期
- Status: active

### REQ-F09-01 · 金蝶月度导入

- Story: US-F09-01
- Stage: 本期
- Revision: 1
- Status: active

### AC-F09-01 · 校验通过才入库

- Parent: REQ-F09-01
- Priority: P0
- EARS:

```text
WHEN 金蝶导入文件中存在期间格式错误、部门或店铺或站点不在主数据中、或金蝶科目未映射到预算科目的行
THE SYSTEM SHALL 不写入该文件的任何数据，并列出每个问题行的行号、问题类型和涉及的编码或名称
```

### AC-F09-02 · 无店铺的行归入未归属渠道

- Parent: REQ-F09-01
- Priority: P0
- EARS:

```text
WHEN 金蝶导入的成本或费用行没有平台/店铺辅助核算且不属于部门费用科目
THE SYSTEM SHALL 将其计入该月「未归属渠道」，并在偏差报告中单列
```

### AC-F09-03 · 重复期间覆盖确认

- Parent: REQ-F09-01
- Priority: P0
- EARS:

```text
WHEN 财务BP上传的金蝶期间已有导入数据，并在系统提示后确认覆盖
THE SYSTEM SHALL 用新文件替换该期间的全部金蝶实际数，并在导入记录中保留被替换文件的文件名、导入人和导入时间
```

### AC-F09-04 · 历史导入

- Parent: REQ-F09-01
- Priority: P0
- EARS:

```text
WHEN 财务BP按同一模板上传最多 24 个月的历史金蝶数据
THE SYSTEM SHALL 按期间逐月入库，并用于历史参考和同比计算
```

### REQ-F09-02 · BI 双月导入

- Story: US-F09-01
- Stage: 本期
- Revision: 2
- Status: active

### AC-F09-05 · SKU 未映射阻止入库

- Parent: REQ-F09-02
- Priority: P0
- EARS:

```text
WHEN BI 导入文件中存在不在 SKU 对照表中的 SKU
THE SYSTEM SHALL 不写入该文件的任何数据，并列出全部未映射的 SKU
```

### AC-F09-06 · 按品类与新老品归集

- Parent: REQ-F09-02
- Priority: P0
- EARS:

```text
WHEN BI 导入校验通过
THE SYSTEM SHALL 按 SKU 对照表把每行归集到「月 × 店铺 × 站点 × 品类 × 新品/老品」，新老品按 AC-F02-04 规则判定
```

### AC-F09-08 · BI 主数据校验

- Parent: REQ-F09-02
- Priority: P0
- EARS:

```text
WHEN BI 导入文件中存在月份格式错误、或店铺或站点不在主数据中的行
THE SYSTEM SHALL 不写入该文件的任何数据，并列出每个问题行的行号、问题类型和涉及的名称
```

### AC-F09-09 · BI 重复期间覆盖确认

- Parent: REQ-F09-02
- Priority: P0
- EARS:

```text
WHEN 财务BP上传的 BI 月份已有导入数据，并在系统提示后确认覆盖
THE SYSTEM SHALL 用新文件替换这些月份的全部 BI 实际数，并在导入记录中保留被替换文件的文件名、导入人和导入时间
```

### AC-F09-07 · 与金蝶收入核对

- Parent: REQ-F09-02
- Priority: P0
- EARS:

```text
WHEN 同一月份的 BI 与金蝶实际都已导入
THE SYSTEM SHALL 按「月 × 店铺 × 站点」用当月平均汇率把 BI 销售额折为人民币，计算差异率 =（BI 折人民币 − 金蝶收入）÷ 金蝶收入，并将差异率绝对值超过 3% 的组合标红显示
```

## Feature F10 · 偏差报告

### US-F10-01 · 看清偏差出在哪里

- Role: 财务负责人
- Goal: 每月看到预算与实际在渠道、站点、品类、新老品、部门上的偏差及原因拆分
- Value: 定目标、调资源有依据
- Stage: 本期
- Status: active

### REQ-F10-01 · 渠道×站点月度报告

- Story: US-F10-01
- Stage: 本期
- Revision: 2
- Status: active

### AC-F10-01 · 对比基准可选

- Parent: REQ-F10-01
- Priority: P0
- EARS:

```text
WHEN 用户打开某月的渠道×站点偏差报告
THE SYSTEM SHALL 允许选择年初原始目标、最新调整后目标或最新滚动预测作为对比基准，默认选最新调整后目标（无调整时为年初原始目标）
```

### AC-F10-02 · 报告内容

- Parent: REQ-F10-01
- Priority: P0
- EARS:

```text
WHEN 渠道×站点偏差报告生成
THE SYSTEM SHALL 按其数据范围逐行显示收入、退款、各项费用、毛利、毛利率的预算值、实际值、差额和达成率（实际 ÷ 预算；毛利率显示百分点差），并单列「未归属渠道」行
```

### AC-F10-12 · B 端客户行

- Parent: REQ-F10-01
- Priority: P0
- EARS:

```text
WHEN 渠道×站点偏差报告生成且用户数据范围内有 B 端客户
THE SYSTEM SHALL 在报告中以「B 端」分组按客户逐行显示收入、退款、各项费用、毛利、毛利率的预算值、实际值、差额和达成率
```

### REQ-F10-02 · 偏差拆分

- Story: US-F10-01
- Stage: 本期
- Revision: 1
- Status: active

### AC-F10-03 · 收入拆分为量差、价差、汇率差

- Parent: REQ-F10-02
- Priority: P0
- EARS:

```text
WHEN 某月某店铺站点的 BI 实际已导入
THE SYSTEM SHALL 计算 量差 = (实际销量 − 预算销量) × 预算净单价 × 预算汇率，价差 = (实际净单价 − 预算净单价) × 实际销量 × 预算汇率，汇率差 = 实际本币收入 × (实际汇率 − 预算汇率)，其中净单价 = 平均单价 × (1 − 折扣率)
```

### AC-F10-04 · 费率差

- Parent: REQ-F10-02
- Priority: P0
- EARS:

```text
WHEN 某项费用的实际值已导入
THE SYSTEM SHALL 计算 费率差 = (实际费率 − 预算费率) × 实际人民币收入，实际费率 = 实际费用 ÷ 实际人民币收入
```

### AC-F10-05 · BI 未到时只显示金额差

- Parent: REQ-F10-02
- Priority: P0
- EARS:

```text
WHEN 该月 BI 实际尚未导入
THE SYSTEM SHALL 只显示金额差异，并在拆分区域显示「量价拆分待 BI 数据（最近 BI 数据截至 YYYY-MM）」
```

### REQ-F10-03 · 品类与新老品报告

- Story: US-F10-01
- Stage: 本期
- Revision: 2
- Status: active

### AC-F10-06 · 品类报告

- Parent: REQ-F10-03
- Priority: P0
- EARS:

```text
WHEN 用户打开品类偏差报告
THE SYSTEM SHALL 对已有 BI 实际的月份按「品类 × 新品/老品」显示 SPU 数量、销量、品效（单 SPU 平均销量 × 平均单价 × (1 − 折扣率)，实际品效 = 实际销售额（本币）÷ SPU 数量）、收入的预算值、实际值和差额
```

### REQ-F10-04 · 部门费用报告

- Story: US-F10-01
- Stage: 本期
- Revision: 1
- Status: active

### AC-F10-07 · 额度使用率与时间进度

- Parent: REQ-F10-04
- Priority: P0
- EARS:

```text
WHEN 用户打开部门费用报告
THE SYSTEM SHALL 按「部门 × 预算科目」显示全年预算、截至最近导入月的累计实际、额度使用率（累计实际 ÷ 全年预算）和时间进度（最近导入月份数 ÷ 12）
```

### REQ-F10-05 · 公司汇总与成功指标

- Story: US-F10-01
- Stage: 本期
- Revision: 2
- Status: active

### AC-F10-08 · 净利润达成率双口径

- Parent: REQ-F10-05
- Priority: P0
- EARS:

```text
WHEN 用户打开公司汇总
THE SYSTEM SHALL 显示截至最近导入月的累计净利润达成率 = 年初至最近导入月的实际净利润合计 ÷ 同期目标净利润合计，分别按年初原始目标和最新调整后目标计算；同期目标净利润合计小于等于 0 时显示「—」
```

### AC-F10-09 · 固定费用增速与收入增速

- Parent: REQ-F10-05
- Priority: P0
- EARS:

```text
WHEN 用户打开公司汇总且上一年同期实际已导入
THE SYSTEM SHALL 显示部门费用合计与收入合计各自相对上一年同期的增速，并在部门费用增速大于收入增速时标红
```

### AC-F10-10 · 季度预测准确度

- Parent: REQ-F10-05
- Priority: P0
- EARS:

```text
WHEN 某月金蝶实际已导入且该月所属季度有已发布的滚动预测快照
THE SYSTEM SHALL 显示该月 |快照预测净利润率 − 实际净利润率|（单位：百分点，净利润率 = 净利润 ÷ 人民币收入），并在大于 1.5 个百分点时标红
```

### REQ-F10-06 · 偏差说明

- Story: US-F10-01
- Stage: 本期
- Revision: 1
- Status: active

### AC-F10-11 · 财务BP填写说明

- Parent: REQ-F10-06
- Priority: P0
- EARS:

```text
WHEN 财务BP为某月某渠道、品类或部门的偏差保存说明文字
THE SYSTEM SHALL 在对应报告行显示该说明及填写人和填写时间，有查看权限的角色都能看到
```

## Feature F11 · 预警与钉钉通知

### US-F11-01 · 偏差超线自动提醒负责人

- Role: 部门负责人
- Goal: 本部门或负责渠道触发预警时收到钉钉提醒
- Value: 偏差不用等月度会才发现
- Stage: 本期
- Status: active

### REQ-F11-01 · 规则评估与预警记录

- Story: US-F11-01
- Stage: 本期
- Revision: 1
- Status: active

### AC-F11-01 · 导入后评估

- Parent: REQ-F11-01
- Priority: P0
- EARS:

```text
WHEN 财务BP确认一次金蝶或 BI 导入
THE SYSTEM SHALL 用规则库中全部已生效的预警规则对受影响月份重新评估，并为每个命中生成一条预警记录，包含规则名称与版本、对象、期间、指标值和阈值
```

### AC-F11-02 · 同一命中不重复

- Parent: REQ-F11-01
- Priority: P0
- EARS:

```text
WHEN 同一规则版本对同一对象同一期间已有预警记录
THE SYSTEM SHALL 更新该记录的指标值，不新增记录也不重复发送通知
```

### AC-F11-03 · 处理预警

- Parent: REQ-F11-01
- Priority: P1
- EARS:

```text
WHEN 预警接收人将预警标记为已处理并填写处理说明
THE SYSTEM SHALL 将该预警状态改为已处理并记录处理人、时间和说明
```

### REQ-F11-02 · 钉钉通知

- Story: US-F11-01
- Stage: 本期
- Revision: 1
- Status: active

### AC-F11-04 · 通知接收人

- Parent: REQ-F11-02
- Priority: P0
- EARS:

```text
WHEN 生成新的预警记录
THE SYSTEM SHALL 向规则中配置的接收角色（对象所属部门负责人、负责该渠道的运营、财务负责人；部门费用超额度时另加 CEO）发送钉钉工作通知，内容包含规则名称、对象、期间和系统链接，不包含金额
```

### AC-F11-05 · 通知失败

- Parent: REQ-F11-02
- Priority: P1
- EARS:

```text
WHEN 钉钉工作通知发送失败
THE SYSTEM SHALL 每 5 分钟重试一次、最多重试 3 次，仍失败时在预警列表中将该预警标注为「通知失败」
```

## Feature F12 · 预算规则库

### US-F12-01 · 沉淀并审批预算规则

- Role: 财务负责人
- Goal: 把驱动假设、预警规则和费用额度标准放进规则库，按状态和版本管理
- Value: 经验可传承，每条规则可追溯
- Stage: 本期
- Status: active

### REQ-F12-01 · 规则类型与状态

- Story: US-F12-01
- Stage: 本期
- Revision: 1
- Status: active

### AC-F12-01 · 新建规则

- Parent: REQ-F12-01
- Priority: P0
- EARS:

```text
WHEN 财务BP或财务负责人新建规则并选择类型（驱动假设、预警规则、额度标准）、填写内容和依据
THE SYSTEM SHALL 保存为待审批状态，并要求在「未验证经验、历史观察、已验证」中选择一个可信度状态
```

### AC-F12-02 · 预警规则可配置项

- Parent: REQ-F12-01
- Priority: P0
- EARS:

```text
WHEN 编辑预警规则
THE SYSTEM SHALL 提供指标（收入达成率、毛利率差、额度使用率减时间进度、额度使用率、预测偏差百分点）、比较方式、阈值、连续月数、适用对象和接收角色这些字段
```

### AC-F12-03 · 初始规则

- Parent: REQ-F12-01
- Priority: P0
- EARS:

```text
WHEN 系统首次部署
THE SYSTEM SHALL 预置三条状态为「未验证经验」的待审批预警规则：新渠道连续 2 个月收入达成率低于 70%；部门费用额度使用率超出时间进度 10 个百分点以上；品类毛利率比预算低 3 个百分点以上
```

### REQ-F12-02 · 审批与版本

- Story: US-F12-01
- Stage: 本期
- Revision: 2
- Status: active

### AC-F12-04 · 审批生效

- Parent: REQ-F12-02
- Priority: P0
- EARS:

```text
WHEN 财务负责人审批通过一条驱动假设或预警规则（额度标准类须再经 CEO 审批通过）
THE SYSTEM SHALL 生成该规则的新版本并设为生效，原生效版本转为历史版本
```

### AC-F12-05 · 只评估生效版本

- Parent: REQ-F12-02
- Priority: P0
- EARS:

```text
WHEN 系统评估预警规则
THE SYSTEM SHALL 只使用每条规则当前生效的版本，待审批和历史版本不参与评估
```

### AC-F12-06 · 版本历史

- Parent: REQ-F12-02
- Priority: P1
- EARS:

```text
WHEN 用户查看某条规则
THE SYSTEM SHALL 列出其全部版本的内容、可信度状态、依据、提交人、审批人和生效时间
```

### AC-F12-07 · 规则审批退回

- Parent: REQ-F12-02
- Priority: P1
- EARS:

```text
WHEN 审批人填写退回原因并退回一条待审批规则
THE SYSTEM SHALL 将该规则版本状态改为已退回且不生效，向提交人显示退回原因，提交人可修改后重新提交
```

## Feature F13 · 新渠道标记与保守放量

### US-F13-01 · 新渠道单独用保守规则

- Role: 财务负责人
- Goal: 把新开渠道单独标记，填报时受放量规则约束
- Value: 避免新渠道预算过度乐观
- Stage: 本期
- Status: active

### REQ-F13-01 · 新渠道标记与放量提示

- Story: US-F13-01
- Stage: 本期
- Revision: 1
- Status: active

### AC-F13-01 · 标记新渠道

- Parent: REQ-F13-01
- Priority: P0
- EARS:

```text
WHEN 财务负责人将某渠道或店铺标记为新渠道并设置起始月
THE SYSTEM SHALL 在起始月起 12 个月内把该渠道显示为新渠道，满 12 个月后自动转为常规渠道
```

### AC-F13-02 · 超出放量上限须写理由

- Parent: REQ-F13-01
- Priority: P0
- EARS:

```text
WHEN 运营为新渠道填报的某月人民币收入超过规则库中生效的新渠道放量上限
THE SYSTEM SHALL 在该单元格标注「超出新渠道放量规则」，并在填写超出理由之前阻止提交
```

## Feature F14 · Excel 导出

### US-F14-01 · 导出预算和报告

- Role: 财务BP
- Goal: 把预算表和偏差报告导出为 Excel
- Value: 便于汇报和线下分析
- Stage: 本期
- Status: active

### REQ-F14-01 · 导出

- Story: US-F14-01
- Stage: 本期
- Revision: 1
- Status: active

### AC-F14-01 · 按权限导出

- Parent: REQ-F14-01
- Priority: P0
- EARS:

```text
WHEN 用户在预算表或任一偏差报告页面点击导出
THE SYSTEM SHALL 生成 .xlsx 文件，列与页面当前显示一致，且只包含该用户数据范围内的行
```

## Non-functional requirements

### NFR-001 · 计算刷新时间

- Applies-to: REQ-F06-01, REQ-F06-02
- Revision: 1
- Status: active
- Measure: 预算数据量不超过 20,000 个预算单元时，保存一个驱动值后页面上受影响的合计刷新完成时间 P95 ≤ 3 秒（在公司内网、连续 100 次保存采样）

### NFR-002 · 导入校验时间

- Applies-to: REQ-F09-01, REQ-F09-02
- Revision: 1
- Status: active
- Measure: 不超过 50,000 行的 Excel 文件，从上传完成到显示校验结果 ≤ 60 秒

### NFR-003 · 服务端权限过滤

- Applies-to: REQ-F01-03, REQ-F14-01
- Revision: 1
- Status: active
- Measure: 所有数据查询与导出接口在服务端按用户数据范围过滤；越权请求 100% 返回无权限且不含记录字段

### NFR-004 · 审计记录

- Applies-to: REQ-F01-02, REQ-F07-02, REQ-F08-01, REQ-F09-01, REQ-F12-02
- Revision: 1
- Status: active
- Measure: 对角色分配、目标版本、目标调整、导入和规则库的每次修改记录操作人、时间、修改前后值，保留不少于 3 年，任何角色不能删除

### NFR-005 · 财务数据不外发

- Applies-to: REQ-F11-02, REQ-F03-01
- Revision: 1
- Status: active
- Measure: 系统不向公司以外的服务发送任何金额或明细数据；钉钉通知只含规则或任务名称、对象、期间和链接；系统不调用外部大模型

### NFR-006 · 部署与浏览器

- Applies-to: REQ-F01-01
- Revision: 1
- Status: active
- Measure: 部署在公司内部服务器；在 Chrome 与 Edge 当前及前一个大版本、以及钉钉内置浏览器中，全部功能可用且页面无横向滚动错位（桌面宽度 ≥ 1280 像素）
