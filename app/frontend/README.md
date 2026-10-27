# 预算管理平台 · 前端

Vite + Vue 3 + TypeScript + Element Plus + RevoGrid。构建产物输出到 `../backend/app/static`（每次构建清空该目录），由 FastAPI 同源托管。

## 命令

| 命令 | 说明 |
|---|---|
| `npm ci` | 按 `package-lock.json` 安装（精确版本） |
| `npm run dev` | 开发服务器，`/api` 代理到 `http://127.0.0.1:8000` |
| `npm run build` | 类型检查 + **生产构建**（不含开发身份切换，DEC-013） |
| `npm run build:dev` | 类型检查 + 开发模式构建（含开发身份切换），用于本机验收 SMOKE-01 由后端托管登录页 |
| `npm run test` | Vitest 单测（happy-dom） |
| `npm run typecheck` | 只做 vue-tsc 类型检查 |

## 依赖版本

技术方案 §2.3 锁定的版本全部按原版本安装，无替换：
vue 3.5.44、vite 8.3.5、@vitejs/plugin-vue 6.0.10、vue-router 5.4.0、pinia 4.1.0、element-plus 2.14.7、@element-plus/icons-vue 2.3.2、@revolist/revogrid 4.29.1、@revolist/vue3-datagrid 4.29.1、typescript 6.0.3、vue-tsc 3.3.13、dingtalk-jsapi 3.2.9、vitest 5.0.5。

技术方案未列、为单测和类型检查补充的开发依赖：@vue/test-utils 2.5.1、happy-dom 21.0.4、@types/node 22.20.5。

构建环境：本开发容器用 Node 22.22.0（技术方案锁定 24.22.1 LTS；Vite 8 / Vitest 5 均支持 Node ≥ 22.12）。

## 开发身份切换（DEC-002 / DEC-013）

- 构建期常量 `__DEV_IDENTITY_SWITCH__ = (mode !== 'production')`（`vite.config.ts` 的 `define`）。
- 登录页只通过该常量动态引用 `DevIdentitySwitch.vue`；生产构建中常量为 false，组件与文案被整段剔除。可用 `grep -r "开发模式身份切换" ../backend/app/static` 检查，应无结果。
- 开发构建中，还要 `GET /api/auth/dev-users` 返回 200 才会渲染（后端生产配置下返回 404）。

## 目录

```
src/
  api/client.ts        fetch 封装：携带 Cookie；ApiError；401 跳 /login?redirect=；403 → code=forbidden「无权限」；download / upload
  api/types.ts         /api/me 等共用类型、角色中文名
  api/dingtalk.ts      钉钉内置浏览器识别与免登授权码（dingtalk-jsapi 按需加载）
  stores/user.ts       当前用户（/api/me）、菜单可见性、退出
  stores/dict.ts       字典缓存：dict.load(key, url)
  stores/ui.ts         面包屑末级文字覆盖：ui.setCrumbTitle('Amazon-US-01')
  router/routes.ts     30 个路由（开发约定路由表）+ 侧栏分组
  router/index.ts      路由注册与守卫（未登录跳 /login?redirect=）
  components/          共用组件（见下）
  pages/PAGE-Fxx-xx.vue  每页一个文件；除登录页外为占位，由功能组替换正文
  styles/              tokens.css、app.css（复制自 output/）、element-theme.css（Element Plus 变量对齐 tokens）、base.css
```

页面文件约定：根元素带 `data-page-id`，页内写 `<div class="page-head"><h1 class="page-title">…</h1></div>`；面包屑由 AppShell 按路由 meta 生成（分组 / 上级页 / 本页）。

## 共用组件

| 组件 | CMP | 用法要点 |
|---|---|---|
| `AppShell.vue` | CMP-F00-01 | 路由外壳；侧栏按 `/api/me` 的 `menus` 显示；子页高亮上级菜单（`aria-current="page"`）；后端不可用时显示错误态 |
| `BudgetGrid.vue` | CMP-F04-01 | props：`columns`、`rows`、`locked`、`errors`、`flags`、`height`；事件 `save(changes, 'edit' \| 'paste')`；插槽 `over-limit` |
| `PageState.vue` | — | `state="empty\|loading\|error\|forbidden"`，或传 `:error="apiError"` 自动判断（403 → 无权限）；事件 `retry`；插槽 `action` |
| `AchievementBar.vue` | CMP-F10-01 | `rate`、`progress`（百分数字符串）、`kind="revenue\|expense\|neutral"`、可选 `level` 覆盖、`showValue` |
| `ImportResultPanel.vue` | CMP-F09-02 | `upload-url`、`status-url`、`confirm-url`（null 表示无确认步骤）、`fields`；事件 `imported/failed/passed`；插槽 `summary`、`issues-summary`、`imported` |
| `ExportButton.vue` | CMP-F14-01 | `view`、`filters`；调用 `GET /api/export?view=&filters=<JSON>` 下载 |
| `MoneyCell.vue` | — | `value`（十进制字符串）、`display`（后端格式化值优先）、`direction="higher-better\|lower-better\|none"` 或 `favorable`、`currency` |

## 前端对后端接口的约定（开发约定未细化的部分）

后端功能组实现时请对齐；如需调整，改这里和对应组件。

**登录（PAGE-F01-01）**
- `GET /api/auth/dingtalk/qr-url?redirect=<站内路径>` → `{"url": "<钉钉扫码授权页>"}`；前端点击扫码区后跳转。
- 扫码回调成功后重定向到 `redirect`（无则 `/`）；被拒时重定向到 `/login?error=no_role&name=<姓名（部门）>`、`/login?error=account_disabled` 或 `/login?error=dingtalk_unavailable`。
- `GET /api/auth/config` → `{"corp_id": "..."}`（钉钉内免登用）；`POST /api/auth/dingtalk/h5 {"auth_code"}`。
- 被拒的错误码：`no_role`（可在 `details.name` 给出姓名）、`account_disabled`。`POST /api/auth/dev-login` 同样适用。
- 已登录会话失效：任一接口 401 → 前端跳 `/login?redirect=…&expired=1`；401 的 `code` 为 `account_disabled` / `no_role` 时显示对应拒绝提示。
- `GET /api/auth/dev-users` → `[{"id", "name", "roles": ["operations"], "label"?: "王浩 · 运营（Amazon）"}]`；`roles` 为空显示「未分配角色（测试拒绝）」。
- 退出：`POST /api/auth/logout`。

**填报表格（API-F04-02 / API-F04-03）**：BudgetGrid 的数据结构见 `src/components/budgetGrid.ts`
- 列：`{key, label, kind: "dim"|"value", type: "money"|"ratio"|"number"|"text", editable, width?, group?}`；维度列冻结在左侧，相邻同 `group` 合并表头。
- 行：`{key, values: {<列 key>: "字符串值"|null}, kind?: "input"|"calc"|"total", readonly_fields?: [...]}`；`total` 行固定在底部。
- 保存：`save` 事件给出 `[{row_key, field, value, base}]`，可直接作为 `PATCH /api/filling-units/{id}/cells` 的请求体；比率「12.5%」发送为 `"12.5"`，金额去掉千分位，其余原样，由后端校验。
- 冲突、越界：页面把服务端返回的明细写入 `errors`（key = `${row_key}::${field}`，值为提示文字）；超放量写入 `flags`。

**导入批次（API-F09-01~03 及其他复用 ImportResultPanel 的上传）**：类型见 `src/components/importTypes.ts`
- 上传 `POST <upload-url>`（multipart：`file` + `fields`）→ 批次对象（至少含 `id`）。
- 轮询 `GET <status-url>` → `{id, status: "validating"|"failed"|"passed"|"imported", file_name, row_count, issues: [{row, type, name, action, link}], needs_overwrite, overwrite: {periods, file_name, imported_by, imported_at}}`。
- 确认 `POST <confirm-url> {"overwrite": true|false}` → 批次对象（`status: "imported"`）。

**导出（API-F14-01）**：`GET /api/export?view=<视图>&filters=<JSON 字符串>`，响应 `Content-Disposition` 带文件名（支持 `filename*=UTF-8''…`）。

## 验证记录

- `npm run test`：BudgetGrid（列冻结与分组、只读/锁定、单格保存带基准值、整块粘贴批量保存、错误与超放量标注）与 AchievementBar（宽度映射、费用类/收入类分级、空值）共 18 项通过。
- `npm run build` 通过；生产产物检索「开发模式身份切换」「dev-users」「dev-login」无结果，无外部 CDN 或字体请求。
- Playwright 冒烟（1280×800）：后端未启动时 `/login` 显示「钉钉登录暂不可用」错误态、页面不崩溃；模拟接口下未登录访问 `/reports/channel?month=2027-04` 跳 `/login?redirect=…`，开发身份「未分配角色」显示拒绝提示，正常身份登录后回到原链接，侧栏按 menus 显示并高亮当前页。
- 真实 Chromium 中 RevoGrid：编辑后失焦触发 1 项 save；粘贴 2×2 制表符文本触发 1 次含 4 项的 save。
