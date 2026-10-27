# 预算管理平台 · 后端

FastAPI 单体（技术方案 v1.1、`app/开发约定.md`）。本文件写启动方式、依赖版本说明，以及供各功能组共用的接口约定。

## 启动

```bash
# 1. 数据库（本机 PostgreSQL，已建账号 budget/budget、库 budget 与 budget_test）
su postgres -c psql <<'SQL'
CREATE ROLE budget LOGIN PASSWORD 'budget';
CREATE DATABASE budget OWNER budget;  CREATE DATABASE budget_test OWNER budget;
\c budget
ALTER SCHEMA public OWNER TO budget;
\c budget_test
ALTER SCHEMA public OWNER TO budget;
SQL

# 2. 依赖
cd app/backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# 3. 迁移 + 样例数据（幂等）
.venv/bin/alembic upgrade head
.venv/bin/python -m scripts.seed            # 加 --mark-new-channel 预置 TikTok-US-01 新渠道（起始 2027-03）

# 4. 钉钉替身（端口 8090）与后端（端口 8000，开发配置）
.venv/bin/uvicorn dingtalk_stub.main:app --port 8090
APP_ENV=dev DEV_IDENTITY_SWITCH=true DINGTALK_BASE_URL=http://127.0.0.1:8090 \
DINGTALK_APP_KEY=stub DINGTALK_APP_SECRET=stub DINGTALK_AGENT_ID=10001 DINGTALK_CORP_ID=ding-stub \
  .venv/bin/uvicorn app.main:app --port 8000

# 5. 测试（使用 budget_test：每次会话重建 schema 并跑全部迁移，每个测试事务回滚）
.venv/bin/pytest -q
```

配置（环境变量或 `app/backend/.env`）：`APP_ENV`（dev/test/prod）、`DATABASE_URL`、`DEV_IDENTITY_SWITCH`、`DATA_DIR`、`APP_BASE_URL`（扫码回调与通知链接）、`SESSION_IDLE_HOURS`（默认 8）、`COOKIE_SECURE`、`SCHEDULER_ENABLED`、`BOOTSTRAP_FINANCE_HEAD_USERID`（DEC-019）、`DINGTALK_BASE_URL`（默认 `https://api.dingtalk.com`；设为替身地址时 oapi 与扫码页也指向它）、`DINGTALK_OAPI_BASE_URL`、`DINGTALK_LOGIN_BASE_URL`、`DINGTALK_APP_KEY / APP_SECRET / AGENT_ID / CORP_ID`。
`APP_ENV=prod` 时开启 `DEV_IDENTITY_SWITCH` 或缺钉钉四项凭据，进程拒绝启动（DEC-013）。

钉钉替身管理接口：`GET /_stub/messages`（已收到的工作通知）、`DELETE /_stub/messages`、`GET/POST /_stub/users`、`PATCH /_stub/users/{userid} {"active": false}`（停用）、`DELETE /_stub/users/{userid}`（移出通讯录）、`PUT /_stub/fail-receivers {"userids": [...]}`（对这些接收人返回 errcode≠0）、`GET /_stub/h5-code?userid=`、`POST /_stub/reset`。扫码页 `/oauth2/auth` 点选员工即模拟扫码，授权码 `qr-<userid>`，免登码 `h5-<userid>`。

## 依赖版本

全部按技术方案 §2.3 锁定版本安装成功（Python 3.13.17 上无需替换）：FastAPI 0.162.0、SQLAlchemy 2.1.6、psycopg[binary] 3.3.6、alembic 1.20.1、pydantic 2.14.1、pydantic-settings 2.16.1、python-calamine 0.9.0、openpyxl 3.1.5、APScheduler 3.11.3、httpx 0.28.1、pytest 9.1.1、uvicorn 0.54.0。
补充：`python-multipart 0.0.32`（导入上传的 multipart 表单所需）、`tzdata 2026.5`（Windows 上 `zoneinfo` 需要）。`requirements.txt` 为 `pip freeze` 精确锁定。
已知：starlette 1.10 对 `TestClient` 使用 httpx 给出弃用警告（建议 httpx2），不影响运行；技术方案锁定 httpx 0.28.1，暂不更换。
开发容器为 Python 3.13 与 PostgreSQL 16（技术方案锁定 3.14.10 / 18.6）；所用特性（`NULLS NOT DISTINCT`、部分唯一索引、触发器）PostgreSQL 15+ 均支持。

## 目录要点

| 路径 | 内容 |
|---|---|
| `app/config.py` | 配置与 DEC-013 生产自检 |
| `app/db.py` | 引擎；`get_db` 依赖（会话来自 `app.state.session_maker`，路由自行 commit） |
| `app/core/errors.py` | 统一错误 `{"code","message","details"}`；`Forbidden()` 固定 403「无权限」且不带 details |
| `app/core/money.py` | Decimal 解析（拒绝 float）、百分数字符串↔小数、ROUND_HALF_UP、`¥ 1,234.56` / `$ 1,234.56 USD`、负号「−」、空值「—」 |
| `app/core/auth.py` | 会话、`get_current_user`、登录拒绝（no_role / account_disabled）、DEC-019 首位财务负责人 |
| `app/core/scope.py` | `ScopeContext`（`get_scope` 依赖）、`require_roles(...)`、物流物控字段级 `restrict_fields` / `ensure_writable_fields` |
| `app/core/audit.py` | `write_audit(db, ...)`：与业务同事务写只追加审计行 |
| `app/core/menus.py` | 侧栏可见矩阵（`/api/me` 的 `menus`） |
| `app/core/clock.py` | 可注入时钟 `clock.now()` / `clock.set_now()` |
| `app/calc/formulas.py` | CMP-F06-01 全部公式纯函数；`periods.py` 月份工具；`recalc.py` 保存后增量重算 |
| `app/dingtalk/` | 网关（主机白名单）、发件箱（`build_notice` + `enqueue_notice`）、调度器（`register_overdue_hook`） |
| `app/models/` | 42 张表（技术方案 §5.1 全部 DATA-*）；状态 / 类型代码见 `enums.py` |
| `alembic/versions/0001_initial.py` | 建表 + 触发器 + 预置 8 角色与 3 条待审批预警规则 |
| `app/api/` | `auth`、`me`、`health` 已实现；其余为功能组空桩 |

## 功能组开发约定（后端）

- **路由权限**：每个业务路由必须声明 `Depends(get_scope)` 或 `Depends(require_roles(...))`；列表查询用 `ctx.store_clause(...)` / `ctx.customer_clause(...)` / `ctx.department_clause(...)` 过滤，单条记录用 `ctx.ensure_*`；物流物控响应先过 `restrict_fields`。
- **事务**：路由内完成业务修改 → `write_audit(...)` → `enqueue_notice(...)` → `db.commit()`。
- **金额**：库中 NUMERIC、代码 Decimal；接口用 `dec_str()` 输出原值字符串、`ratio_to_percent()` 输出百分数字符串、`fmt_*` 输出显示字段（`*_display`）。
- **月份**：库中存当月 1 日（DATE），接口 `YYYY-MM`（`calc.periods.parse_month / fmt_month`）。
- **数据库兜底**：锁定版本下的预算行改删抛 SQLSTATE `BG001`「版本已锁定，不能修改」；已锁定年度改删预算汇率抛 `BG002`「已随年初原始目标锁定」；审计表改删抛 `BG003`。服务层应先行拒绝并返回 409/422，触发器只是第二道防线。
- **新迁移**：文件名前缀用功能组，例如 `0005_filling_xxx.py`，`down_revision` 接当前 head。

### 登录与身份接口（已实现，与前端对齐）

- `GET /api/auth/config` → `{"corp_id", "client_id", "dev_switch"}`
- `GET /api/auth/dingtalk/qr-url?redirect=` → `{"url"}`
- `GET /api/auth/dingtalk/callback?authCode=&state=` → 成功 302 到 `state`（站内路径）并设 Cookie；被拒 302 到 `/login?error=no_role&name=姓名（部门）`、`/login?error=account_disabled`、`/login?error=dingtalk_unavailable`、`/login?error=dingtalk_auth_failed`（原链接非 `/` 时附 `redirect=`）；`format=json` 时改为 JSON（拒绝 403 / 401 / 503）
- `POST /api/auth/dingtalk/h5 {"auth_code","redirect"?}`；`POST /api/auth/logout`；`GET /api/auth/session`
- 开发身份（仅 `APP_ENV=dev` 且 `DEV_IDENTITY_SWITCH=true` 注册）：`GET /api/auth/dev-users` → `[{"id","name","roles","role_names","department","label"}]`；`POST /api/dev/login-as {"user_id"}`（正式路径，契约用），`POST /api/auth/dev-login` 为同一处理的别名
- 拒绝码：`no_role`（403，`details.name`）、`account_disabled`（登录 403；已有会话 401）、`session_expired`（401）、`unauthenticated`（401）
- `GET /api/me` → `{"user","roles","role_names","scopes":{"departments","channels","stores","customers"},"all_company","menus","dev_switch","auth_source"}`

### 填报表格结构（API-F04-02 / API-F04-03，前端 `src/components/budgetGrid.ts`）

`GET /api/filling-units/{id}/grid` 返回：

```json
{"columns": [{"key": "category", "label": "品类", "kind": "dim", "type": "text"},
             {"key": "2027-03", "label": "3 月", "kind": "value", "type": "money", "editable": true, "group": "2027"}],
 "rows": [{"key": "<单元维度>|<项目>", "values": {"category": "浴室柜", "2027-03": "80"},
           "kind": "input", "readonly_fields": ["2027-01"]}],
 "...": "单位状态、合计、新渠道标注等由功能组补充"}
```

- 列：`{key, label, kind: "dim"|"value", type: "money"|"ratio"|"number"|"text", editable, width?, group?}`；`editable` 按角色裁剪（物流物控只有四项物流比例列可编辑、且收入 / 利润列不下发）。
- 行：`{key, values: {列 key: 字符串|null}, kind?: "input"|"calc"|"total", readonly_fields?}`；值一律字符串（比率为百分数字符串 `"12.5"`、金额为未舍入十进制字符串，前端只格式化不计算）。`total` 行为 SQL 聚合合计。
- `row_key` 由功能组编码，必须能唯一还原「预算单元键 + 输入项」（如 `pu:<store>:<site>:<category>:<is_new>|avg_price`）；`field` 为列 key（按月布局时为 `YYYY-MM`）。
- 保存 `PATCH /api/filling-units/{id}/cells`，请求体为 `[{row_key, field, value, base}]`；后端在行锁内比较 `base` 与当前值（DEC-007），返回重算后的行与受影响合计；失败明细建议为 `{"errors": [{"row_key","field","code":"conflict"|"out_of_range","message"}]}`，前端以 `${row_key}::${field}` 标注。

### 导入批次结构（API-F09-01~03 及复用 ImportResultPanel 的上传，前端 `src/components/importTypes.ts`）

- 上传 `POST <upload-url>`（multipart：`file` + 其他字段）→ 批次对象（至少 `id`）。
- 状态 `GET <status-url>` → `{id, status, file_name, row_count, issues: [{row, type, name, action?, link?}], needs_overwrite, overwrite: {periods, file_name, imported_by, imported_at} | null}`。
- 确认 `POST <confirm-url> {"overwrite": true|false}` → 批次对象（`status: "imported"`）；需覆盖而 `overwrite` 不为 true 时 409 且不写入。
- 接口 `status` 与库内 `import_batch.status` 的映射：`validating`→`validating`；`validation_failed`→`failed`；`pending_confirm`→`passed`；`effective`→`imported`；`replaced` / `discarded` / `interrupted` 只出现在导入记录列表（API-F09-04），不进入此面板。
- `issues[].type` 用中文问题类型（如「店铺不在主数据中」）；库内 `errors` JSONB 另存英文代码（`month_format` / `store_not_found` / `site_not_found` / `sku_unmapped` 等）供测试断言。
