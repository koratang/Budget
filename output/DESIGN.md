# Design System Inspired by 预算管理平台

> Category: Fintech & Crypto
> 浅色、克制、表格优先的财务工作台；用「达成条」一眼看清实际跑在时间进度前还是后。

## 视觉主题与氛围

- **视觉方向**：一本干净的电子账簿。冷灰底、白色工作面、墨蓝强调；数字是主角，界面退到后面。
- **用户情绪**：冷静的掌控感。财务和业务负责人每天面对几百行数字，界面必须让人迅速找到「哪里不对」，而不是被装饰分散注意力。
- **设计理由**：浅色适合长时间看密集表格，也方便截图进汇报材料（蓝图 §6 用户确认）；红色表示不利、绿色表示有利，符合国内财务「赤字」习惯。
- **风格定位**：介于 Apple/Rams 的克制与专业财务软件之间——小圆角、细分隔线、等宽数字，没有渐变和玻璃效果。

| 角色 | Hex | 用途 |
|---|---|---|
| 背景 | #F4F6F8 | 页面底色 |
| 工作面 | #FFFFFF | 表格、卡片 |
| 主文字 | #18202B | 数字、标题 |
| 次文字 | #5A6574 | 标签、说明 |
| 强调（墨蓝） | #1D5A92 | 主按钮、当前导航、链接 |
| 有利 | #17734A | 达成、结余 |
| 预警 | #9A5B06 | 接近阈值、待处理 |
| 不利 | #BC3127 | 超支、未达成、校验错误 |

参考先例：Stripe Dashboard（数字等宽对齐、克制的层级）、飞书多维表格（类 Excel 编辑手感）、金蝶报表（国内财务配色习惯）。

## 色彩美学

- 中性色占画面 80% 以上；`--accent` 每屏最多 2 处可见使用（主按钮 + 当前导航项）；语义色 ≤ 5%，只出现在数字、徽章和达成条上。
- 链接、悬停、焦点环都计入强调色用量；表格中的链接改用 `--fg-2` 加下划线，避免满屏墨蓝。

| Surface | Hex | 理由 |
|---|---|---|
| --bg | #F4F6F8 | 微冷灰，衬托白色工作面 |
| --surface | #FFFFFF | 表格和卡片 |
| --surface-warm | #F9FAFB | 冻结维度列、表头 |
| --surface-raised | #EEF2F6 | 悬停行、选中单元格 |
| --border | #D9DEE5 | 表格外框 |
| --border-soft | #E8EBF0 | 行分隔线 |

| Text | Hex | 对白底对比度 |
|---|---|---|
| --fg | #18202B | 16.4:1 |
| --fg-2 | #3A4452 | 9.9:1 |
| --muted | #5A6574 | 5.9:1 |

| Accent / Semantic | Hex | 对白底对比度 | 情感 |
|---|---|---|---|
| --accent | #1D5A92 | 7.2:1（白字在其上 7.2:1） | 可信、沉稳 |
| --success | #17734A | 5.9:1 | 达成 |
| --warn | #9A5B06 | 5.4:1 | 留意 |
| --danger | #BC3127 | 5.8:1 | 不利 |

语义浅底（徽章背景）用 `color-mix(in oklab, var(--danger), white 90%)` 等方式派生，深色文字在其上对比度均 ≥ 4.8:1。

## 排版与字体

- 使用系统中文字体，内网与离线可用，不加载境外字体服务（蓝图 §6、§8）。
- 所有数字列设置 `font-variant-numeric: tabular-nums` 并右对齐，金额千分位、2 位小数。

```
Font labels for catalog extraction:

Display: "PingFang SC", "Microsoft YaHei", "Hiragino Sans GB", "Noto Sans SC", system-ui, sans-serif
Body: "PingFang SC", "Microsoft YaHei", "Hiragino Sans GB", "Noto Sans SC", system-ui, sans-serif
Mono: "Cascadia Mono", Consolas, "SF Mono", Menlo, monospace
```

字号梯度 12 / 13 / 14 / 16 / 18 / 22 / 28 / 36：表格正文 13px（密度）、页面正文 14px、页面标题 22px、关键数字 28–36px。

| 场景 | letter-spacing |
|---|---|
| 关键数字（28px+） | -0.01em |
| 页面标题（22px） | -0.01em |
| 小文本（12–13px） | 0.01em |
| 按钮、标签 | 0.02em |
| 英文全大写（币种代码等） | 0.06em |
| 正文 | 0 |

行高：正文 1.55，表格行高固定 32px（单元格内文字 1.25）。

## 间距与布局

- 4px 基准；表格单元格内边距 6px 10px；卡片内边距 16px；区块间距 24px。
- 应用框架：左侧导航 224px（可收起为 56px）+ 顶栏 52px + 内容区（最大 1680px，左右 24px）。仅支持 ≥ 1280px 桌面宽度（NFR-006）。
- 层级用底色而非阴影：页面 `--bg`，工作面 `--surface`，冻结列和表头 `--surface-warm`；只有弹窗和下拉使用 `--elev-float`。

## 组件设计

交互哲学：**色彩响应型**——悬停、选中、激活都通过底色或边框色变化表达，全站不用阴影浮起、不用位移。

```css
/* 应用框架 */
.app { display: grid; grid-template-columns: 224px 1fr; min-height: 100vh; background: var(--bg); color: var(--fg); font-family: var(--font-body); font-size: var(--text-base); line-height: var(--leading-body); }
.sidebar { background: var(--surface); border-right: 1px solid var(--border); padding: var(--space-3) var(--space-2); }
.nav-group { font-size: var(--text-xs); color: var(--muted); letter-spacing: 0.01em; padding: var(--space-3) var(--space-3) var(--space-1); }
.nav-item { display: flex; align-items: center; gap: var(--space-2); height: 34px; padding: 0 var(--space-3); border-radius: var(--radius-md); color: var(--fg-2); text-decoration: none; transition: background var(--motion-fast) var(--ease-standard), color var(--motion-fast) var(--ease-standard); }
.nav-item:hover { background: var(--surface-raised); color: var(--fg); }
.nav-item:active { background: var(--border-soft); }
.nav-item:focus-visible { outline: none; box-shadow: var(--focus-ring); }
.nav-item[aria-current="page"] { background: color-mix(in oklab, var(--accent), white 90%); color: var(--accent); font-weight: 600; }
.topbar { height: 52px; display: flex; align-items: center; justify-content: space-between; padding: 0 var(--container-gutter-desktop); background: var(--surface); border-bottom: 1px solid var(--border); }
.main { padding: var(--section-y-desktop) var(--container-gutter-desktop); max-width: var(--container-max); }
.page-title { font-family: var(--font-display); font-size: var(--text-2xl); letter-spacing: var(--tracking-display); line-height: var(--leading-tight); margin: 0 0 var(--space-4); }

/* 按钮 */
.btn { display: inline-flex; align-items: center; gap: var(--space-2); height: 32px; padding: 0 var(--space-4); border-radius: var(--radius-md); border: 1px solid var(--border); background: var(--surface); color: var(--fg); font-size: var(--text-sm); letter-spacing: 0.02em; cursor: pointer; transition: background var(--motion-fast) var(--ease-standard), border-color var(--motion-fast) var(--ease-standard); }
.btn:hover { background: var(--surface-raised); border-color: var(--muted); }
.btn:active { background: var(--border-soft); }
.btn:focus-visible { outline: none; box-shadow: var(--focus-ring); }
.btn[disabled] { color: var(--muted); background: var(--surface-warm); cursor: not-allowed; }
.btn-primary { background: var(--accent); border-color: var(--accent); color: var(--accent-on); }
.btn-primary:hover { background: var(--accent-hover); border-color: var(--accent-hover); }
.btn-primary:active { background: var(--accent-active); }
.btn-primary:focus-visible { box-shadow: var(--focus-ring); }
.btn-danger { color: var(--danger); border-color: color-mix(in oklab, var(--danger), white 60%); }
.btn-danger:hover { background: color-mix(in oklab, var(--danger), white 92%); }
.btn-danger:active { background: color-mix(in oklab, var(--danger), white 86%); }
.btn-danger:focus-visible { box-shadow: 0 0 0 3px color-mix(in oklab, var(--danger), transparent 70%); }

/* 卡片 / 关键数 */
.card { background: var(--surface); border: 1px solid var(--border-soft); border-radius: var(--radius-lg); padding: var(--space-4); transition: border-color var(--motion-fast) var(--ease-standard); }
.card:hover { border-color: var(--border); }
.card:active { border-color: var(--muted); }
.card:focus-visible { outline: none; box-shadow: var(--focus-ring); }
.kpi-label { font-size: var(--text-sm); color: var(--muted); }
.kpi-value { font-size: var(--text-3xl); letter-spacing: var(--tracking-display); font-variant-numeric: tabular-nums; line-height: var(--leading-tight); }

/* 输入 */
.input, .select { height: 32px; padding: 0 var(--space-3); border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--surface); color: var(--fg); font-size: var(--text-sm); transition: border-color var(--motion-fast) var(--ease-standard); }
.input:hover, .select:hover { border-color: var(--muted); }
.input:active, .select:active { border-color: var(--fg-2); }
.input:focus-visible, .select:focus-visible { outline: none; border-color: var(--accent); box-shadow: var(--focus-ring); }
.input[aria-invalid="true"] { border-color: var(--danger); }
.field-error { color: var(--danger); font-size: var(--text-xs); margin-top: var(--space-1); }

/* 数据表格（含类 Excel 填报） */
.table-wrap { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-lg); overflow: auto; }
.table { border-collapse: separate; border-spacing: 0; width: 100%; font-size: var(--text-sm); }
.table th { position: sticky; top: 0; z-index: 2; background: var(--surface-warm); color: var(--fg-2); font-weight: 600; text-align: left; height: 34px; padding: 0 10px; border-bottom: 1px solid var(--border); white-space: nowrap; }
.table td { height: 32px; padding: 0 10px; border-bottom: 1px solid var(--border-soft); white-space: nowrap; }
.table td.num, .table th.num { text-align: right; font-variant-numeric: tabular-nums; }
.table td.dim { position: sticky; left: 0; z-index: 1; background: var(--surface-warm); }
.table tbody tr { transition: background var(--motion-fast) var(--ease-standard); }
.table tbody tr:hover td { background: var(--surface-raised); }
.table tr.total td { font-weight: 600; background: var(--surface-warm); border-top: 1px solid var(--border); }
.cell-edit { cursor: cell; }
.cell-edit:hover { box-shadow: inset 0 0 0 1px var(--border); }
.cell-edit:active { box-shadow: inset 0 0 0 1px var(--muted); }
.cell-edit:focus-visible { outline: none; box-shadow: inset 0 0 0 2px var(--accent); background: var(--surface); }
.cell-edit[aria-invalid="true"] { box-shadow: inset 0 0 0 2px var(--danger); background: color-mix(in oklab, var(--danger), white 94%); }
.cell-locked { color: var(--muted); background: var(--surface-warm); }
.neg, .bad { color: var(--danger); }
.good { color: var(--success); }

/* 徽章（状态） */
.badge { display: inline-flex; align-items: center; height: 22px; padding: 0 var(--space-2); border-radius: var(--radius-sm); font-size: var(--text-xs); letter-spacing: 0.02em; background: var(--surface-raised); color: var(--fg-2); }
.badge-good { background: color-mix(in oklab, var(--success), white 90%); color: var(--success); }
.badge-warn { background: color-mix(in oklab, var(--warn), white 88%); color: var(--warn); }
.badge-bad { background: color-mix(in oklab, var(--danger), white 90%); color: var(--danger); }
.badge-info { background: color-mix(in oklab, var(--accent), white 90%); color: var(--accent); }

/* 设计签名：达成条 */
.attain { position: relative; width: 96px; height: 6px; border-radius: var(--radius-pill); background: var(--border-soft); overflow: visible; }
.attain > .fill { position: absolute; inset: 0 auto 0 0; border-radius: var(--radius-pill); background: var(--fg-2); transition: width var(--motion-base) var(--ease-standard); }
.attain.is-good > .fill { background: var(--success); }
.attain.is-warn > .fill { background: var(--warn); }
.attain.is-bad > .fill { background: var(--danger); }
.attain > .tick { position: absolute; top: -3px; width: 2px; height: 12px; background: var(--fg); border-radius: 1px; }

/* 标签页 */
.tabs { display: flex; gap: var(--space-1); border-bottom: 1px solid var(--border); margin-bottom: var(--space-4); }
.tab { padding: var(--space-2) var(--space-3); color: var(--fg-2); border-bottom: 2px solid transparent; text-decoration: none; transition: color var(--motion-fast) var(--ease-standard), border-color var(--motion-fast) var(--ease-standard); }
.tab:hover { color: var(--fg); border-bottom-color: var(--border); }
.tab:active { color: var(--fg); }
.tab:focus-visible { outline: none; box-shadow: var(--focus-ring); }
.tab[aria-selected="true"] { color: var(--fg); border-bottom-color: var(--fg); font-weight: 600; }

/* 弹窗与轻提示 */
.modal-backdrop { position: fixed; inset: 0; background: color-mix(in oklab, var(--fg), transparent 60%); display: grid; place-items: center; }
.modal { width: 480px; background: var(--surface-overlay); border-radius: var(--radius-lg); box-shadow: var(--elev-float); padding: var(--space-6); animation: modal-in var(--motion-base) var(--ease-standard); }
.toast { position: fixed; top: 64px; right: 24px; padding: var(--space-3) var(--space-4); background: var(--fg); color: var(--surface); border-radius: var(--radius-md); font-size: var(--text-sm); animation: toast-in var(--motion-base) var(--ease-standard); }

/* 页面状态 */
.state { padding: var(--space-12) var(--space-6); text-align: center; color: var(--muted); }
.state-title { color: var(--fg); font-size: var(--text-lg); margin-bottom: var(--space-2); }
.skeleton { height: 12px; border-radius: var(--radius-sm); background: var(--border-soft); animation: pulse 1.2s var(--ease-standard) infinite; }

@keyframes modal-in { from { opacity: 0; transform: scale(0.98); } to { opacity: 1; transform: none; } }
@keyframes toast-in { from { opacity: 0; } to { opacity: 1; } }
@keyframes pulse { 50% { opacity: 0.5; } }
.fade-in { animation: toast-in var(--motion-base) var(--ease-standard) both; }
.fade-in:nth-child(2) { animation-delay: 40ms; }
.fade-in:nth-child(3) { animation-delay: 80ms; }
.fade-in:nth-child(4) { animation-delay: 120ms; }

@media (prefers-reduced-motion: reduce) {
  .modal, .toast, .fade-in, .skeleton { animation: none; }
  .attain > .fill, .nav-item, .btn, .tab, .table tbody tr { transition: none; }
}
```

组件说明：
- **圆角 3–6px**：财务数据需要精确感，大圆角会让密集表格显得松散。
- **表格行高 32px**：一屏能看 20 行以上，又不至于点错单元格。
- **达成条**：宽 96px，填充宽度 = min(实际 ÷ 预算, 120%) 映射到条宽，超出 100% 的部分仍用同一颜色但条尾加 2px 圆角断口；竖刻度线位置 = 时间进度。颜色规则：费用类超过时间进度 10 个百分点为琥珀、超过 100% 为红；收入类低于时间进度 10 个百分点为琥珀、低于 70% 为红；其余为中性深灰。

## 动效与交互物理

- 只用 150ms / 200ms 两档，统一 `--ease-standard`。悬停为底色变化，按压为更深一档底色，焦点为墨蓝焦点环。
- 页面进场：关键数卡片依次淡入（40ms 间隔，最多 4 个）；表格不做进场动画，避免数字闪动。
- 弹窗 200ms 淡入并从 98% 缩放到 100%；轻提示 3 秒后消失。

## 品牌情感与声音

- **性格**：一位严谨、话少的财务主管——只说数字和结论，不寒暄。
- **文案**：按钮说清楚动作（「提交审核」「确认覆盖」），提示说清楚原因和下一步（「第 12 行：店铺「US-Amazon-03」不在基础数据中，请先在渠道与店铺中添加」）。
- **空状态**：一句话说明这里会出现什么 + 一个能产生数据的操作按钮，不用插画。
- **加载**：表格用灰色骨架行；按钮内显示「正在保存…」。
- **Agent 设计指令**：只用本文件的组件类与 tokens.css 变量；数字列右对齐等宽；不利红、有利绿；每屏强调色 ≤ 2 处；有达成率的行都放达成条。

## 设计禁忌

- 禁止使用超过 6px 的圆角——大圆角削弱账簿式的精确感。
- 禁止用阴影表达悬停或层级（弹窗和下拉除外）——全站统一为色彩响应，混用会让表格闪动。
- 禁止数字列左对齐或使用比例数字——对不齐的数字会直接导致看错金额。
- 禁止用绿色表示不利或红色表示有利——已与用户确认红色为不利，颠倒会误导决策。
- 禁止在钉钉通知样式或页面文案中出现「成功率提升」之类没有数据来源的宣传语——这是内部财务工具，只陈述事实。
- 禁止加载任何境外字体、图标或 CDN 资源——系统部署在公司内网，境外资源可能无法访问。
- 禁止渐变背景、玻璃拟态和装饰插画——它们会和数字争夺注意力。
