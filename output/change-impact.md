# 变更影响（requirements revision 2 → 3）

来源：Design 阶段回传的待确认项，用户 2026-10-27 决定 1A 2A 3B 4A 5A，以及由已确认决定直接推出的 6 处补充。

| Changed Source | Old→New Revision | Affected Design IDs | Artifacts | Action | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| REQ-F02-03 / AC-F02-12（新增：预算科目清单） | 1→2 | PAGE-F02-04, PAGE-F05-01 | pages/PAGE-F02-04.md/.html; 技术方案.md | 增加预算科目清单维护 | resolved |
| REQ-F02-04 / AC-F02-08（当月平均汇率）、AC-F02-11（新增：锁定后冻结） | 1→2 | PAGE-F02-05, PAGE-F09-02, PAGE-F10-02 | pages/PAGE-F02-05.*; PAGE-F09-02.*; 技术方案.md | 汇率口径与锁定 | resolved |
| REQ-F03-01 / AC-F03-05（新增：填报单位划分） | 1→2 | PAGE-F03-01, PAGE-F03-02, PAGE-F04-01 | pages/PAGE-F03-01.*; PAGE-F03-02.*; PAGE-F04-01.*; 技术方案.md | 原型已按 5A 实现，补来源引用 | resolved |
| REQ-F08-01 / AC-F08-04（CEO 整次终审） | 1→2 | PAGE-F07-01, PAGE-F07-02, PAGE-F08-01 | 对应页面; 技术方案.md 状态机 | 原型已按 4A 实现，补来源引用 | resolved |
| REQ-F08-03 / AC-F08-08（净利润只在公司合计） | 1→2 | PAGE-F08-02 | pages/PAGE-F08-02.* | 原型已如此，关闭待确认 | resolved |
| REQ-F09-02 / AC-F09-07、AC-F09-08、AC-F09-09（新增 BI 校验与覆盖） | 1→2 | PAGE-F09-01, PAGE-F09-02 | 对应页面; 技术方案.md | 补校验与覆盖 | resolved |
| REQ-F10-01 / AC-F10-12（新增：B 端行） | 1→2 | PAGE-F10-02 | pages/PAGE-F10-02.* | 增加 B 端分组行 | resolved |
| REQ-F10-03 / AC-F10-06（品效折后） | 1→2 | PAGE-F10-03 | pages/PAGE-F10-03.* | 品效口径与示例数重算 | resolved |
| REQ-F10-05 / AC-F10-08（累计达成率分母） | 1→2 | PAGE-F10-01, PAGE-F00-01 | 对应页面 | 原型已按同期累计，补口径说明与「—」 | resolved |
| REQ-F12-02 / AC-F12-07（新增：规则退回） | 1→2 | PAGE-F12-02, PAGE-F07-02 | 对应页面; 技术方案.md | 原型已提供退回，补来源引用 | resolved |

未受影响的其余页面、设计系统和蓝图保持不变。完成更新后本表状态改为 resolved，并在设计追溯矩阵中使用新 revision。

## revision 4 → 5（2026-10-28）

- 来源：用户 2026-10-28 上传 2026 年经营分析表，要求作为各渠道站点实际数和编制 2027 年预算的参考，2027 年偏差报告加同比，并优化相关界面。
- 新增：REQ-F09-03（AC-F09-10~13）经营历史表导入；REQ-F04-06（AC-F04-12~13）填报上年同月实际参考；REQ-F10-07（AC-F10-13~14）同比。已有 REQ/AC 不变。
- 设计：技术方案 v1.2 §4.11（API-F09-06、CMP-F09-03、CMP-F10-02、DATA-F09-05、DEC-027、DEC-028）；页面 PAGE-F09-01、PAGE-F04-02、PAGE-F04-03、PAGE-F10-02、PAGE-F10-04 附 revision 5 增补；追溯矩阵新增 13 行。
- 验收：TDD 契约新增 FLOW-33~35，DESIGN-12/13/22/25/27 增加新锚点；FLOW-32 导出表头随页面新增同比列。
- AI 自主判断：缺主数据一键补建与推断规则；负责部门不在主数据计入公司公共；同比用上年绝对值作分母；部门报告上年同期须全部导入才给同比。

