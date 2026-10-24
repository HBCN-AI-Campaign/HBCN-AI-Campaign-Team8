# 境外贷款单据智能审核平台 · 后端

Python (FastAPI) + SQLAlchemy + SQLite/PostgreSQL 的后端服务，打通
「文件解析(OCR) → 数据库 → 规则核对 → API → 鉴权」全链路。

> 配套：前端 `../frontend/`（React18 + antd5 + Vite） · OCR 服务 `../ocr_service/`
> 规则核对对接文档：[`docs/RULE_CHECK_API.md`](docs/RULE_CHECK_API.md)

---

## 已实现

| 层 | 内容 |
|---|---|
| 数据库 | 10 张表（`t_` 前缀，对齐 `database/schema_postgres.sql`）：用户/客户/单据类型/任务/单据/字段/补件/规则结果/待办/汇总 |
| 文件解析 | `parse_agent.py` 调 OCR 服务（`/file/detailed`、`/extract`）识别 PDF → 按单据类型提取结构化字段并落库 |
| 规则引擎 | 注册表模式，内置 **33 条**规则（`rules.py`）；作为对方服务不可用时的本地回退 |
| 规则核对对接 | `rule_check_client.py` + `rule_orchestrator.py`：优先调用对方 rule_check API，不可用时回退本地引擎 |
| API | 登录、仪表盘、任务 CRUD、解析、触发核对、字段更正、AI 审核流、退回/完成/补件、结果查询 |
| 鉴权 | JWT + bcrypt + 角色权限（operator 经办人 / reviewer 审核人） |

---

## 快速开始

```bash
# 1. 安装依赖（已有 .venv）
../.venv/bin/pip install -r requirements.txt

# 2. 启动服务（首次启动自动建表 + 灌入种子数据）
cd backend
../.venv/bin/python -m uvicorn app.main:app --app-dir "$(pwd)" --port 8000
# 交互式 API 文档：http://127.0.0.1:8000/docs
```

> 应用启动的 `lifespan` 会自动执行 `create_all` + `seed()`，无需手动初始化数据库。
> 改动 ORM 表结构 / 加列后需**删库重建**：`rm loan_review.db` 后重启（`create_all` 不改已存在表）。

### 默认账号（种子）

| 用户名 | 密码 | 角色 | 显示名 | 权限 |
|---|---|---|---|---|
| operator | operator123 | 业务经办人 | 张三 | 上传解析、创建任务、更正字段 |
| reviewer | reviewer123 | 审核人员 | 李四 | 启动智能审核、触发核对、看结果、退回/完成 |

### 样本任务

种子内置任务 `2026-0001`（7 份单据：授信函 / 提款指令 / 支付指令 / 商业合同 / 形式发票 / 报关单 / 运单）。

### 调用示例

```bash
# 登录拿 token（注意：form-urlencoded，不是 JSON）
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/auth/login \
  --data-urlencode "username=reviewer" --data-urlencode "password=reviewer123" \
  | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# 触发核对
curl -X POST "http://127.0.0.1:8000/api/tasks/2026-0001/run" \
  -H "Authorization: Bearer $TOKEN"
```

---

## 目录结构

```
backend/
  app/
    main.py              FastAPI 入口（lifespan 建表+种子、CORS、静态托管 /pdf 与 /uploads）
    config.py            配置（DB / OCR_BASE_URL / RULE_CHECK_* / JWT）
    database.py          SQLAlchemy engine / session
    models.py            ORM 模型（10 张 t_ 表）
    schemas.py           Pydantic DTO
    security.py          JWT + bcrypt + require_role 依赖
    seed.py              种子数据（用户 / 客户 / 样本任务 2026-0001）
    parse_agent.py       文件解析 Agent：OCR 识别 + 字段提取 + 落库
    rule_check_client.py 对接对方 rule_check API（health / check / to_payload）
    rule_orchestrator.py 核对编排：对方可用→远程，否则回退本地 rule_engine
    rule_engine/
      base.py            Rule 基类 / 注册表 / 结果结构（RuleResult / DocBundle）
      rules.py           33 条规则实现
      rule_meta.py       规则展示元数据（短名/短描述/文件类型组合）
      runner.py          执行器 + 汇总
    routers/
      auth.py            登录 / me
      customers.py       客户搜索
      tasks.py           任务 CRUD / 解析 / run / 字段更正 / AI 流 / 结果
  docs/
    RULE_CHECK_API.md    规则核对服务接口文档（给对方同事）
  requirements.txt
  .env.example
```

---

## 主要接口（`/api/tasks` 前缀）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/parse` | 上传文件 → OCR 解析，返回建议字段（创建前预览） |
| GET  | `/dashboard` | 仪表盘统计（各状态任务数） |
| POST | `` | 创建任务（上传即创建，自动跑首次规则核对） |
| GET  | `` | 任务列表（支持 `mine` / `customer_no` 过滤） |
| GET  | `/{task_code}` | 任务详情（含单据字段 / 定位 / 置信度 / 结果统计） |
| POST | `/{task_code}/run` | 触发规则核对（reviewer） |
| PATCH| `/{task_code}/documents/{doc_id}/fields` | 更正字段值，保存后自动重核 |
| POST | `/{task_code}/ai/start` | 启动智能审核（reviewer） |
| POST | `/{task_code}/ai/complete` | 智能审核播放完成 |
| POST | `/{task_code}/ai/resolve` | 处置 AI 待决项 |
| POST | `/{task_code}/return` | 退回补件（reviewer） |
| POST | `/{task_code}/complete` | 完成审核（reviewer） |
| POST | `/{task_code}/supplement` | 经办人补件 |
| GET  | `/{task_code}/results` | 查询核对结果明细 |

> 另有 `/api/auth/*`（登录/me）、`/api/customers`（客户搜索）。
> 任务状态机：`pending → ai_reviewing → to_recheck → need_supplement → completed`。

---

## OCR 服务对接

`parse_agent.py` 通过 `OCR_BASE_URL`（默认 `http://127.0.0.1:7888`，见 `config.py`）调用 OCR 服务：
- `POST /file/detailed` — 返回全文 + blocks（含 score / box / page，用于字段定位与置信度）
- `POST /extract` — 按单据类型提取结构化字段

OCR 服务不可达时字段值降级为 `None`、流程不阻断。OCR 服务代码见 `../ocr_service/`。

---

## 规则核对服务对接（对方同事）

本平台每次核对会把任务字段 POST 给对方 rule_check 服务；对方不可用时回退本地 `rule_engine`。

- 对接契约见 **[`docs/RULE_CHECK_API.md`](docs/RULE_CHECK_API.md)**（请求/响应结构、字段枚举、curl 自测）。
- 通过环境变量配置对方地址（`backend/.env`）：

| 环境变量 | 默认 | 说明 |
|---|---|---|
| `RULE_CHECK_BASE_URL` | （空） | 对方服务根地址；**留空 = 走本地引擎** |
| `RULE_CHECK_HEALTH_PATH` | `/health` | 健康探测路径（GET） |
| `RULE_CHECK_PATH` | `/rule_check` | 核对路径（POST） |
| `RULE_CHECK_TIMEOUT` | `30.0` | 核对超时（秒） |
| `RULE_CHECK_HEALTH_TIMEOUT` | `3.0` | 健康探测超时（秒） |

---

## 切换到 PostgreSQL

1. 本地起 Postgres（或 Docker）：
   ```bash
   docker run -d --name loan-pg -e POSTGRES_USER=loan -e POSTGRES_PASSWORD=loan \
     -e POSTGRES_DB=loan_review -p 5432:5432 postgres:16
   ../.venv/bin/pip install psycopg2-binary
   ```
2. 复制 `.env.example` 为 `.env`，设置 `DATABASE_URL`：
   ```
   DATABASE_URL=postgresql+psycopg2://loan:loan@localhost:5432/loan_review
   ```
3. 重启服务。代码无需改动（SQLAlchemy 抽象）。连接池见 `DB_POOL_SIZE` / `DB_MAX_OVERFLOW`。

---

## 已知说明（POC 取舍）

- 建表用 `Base.metadata.create_all`，改表结构需手动删库重建（生产用 Alembic）。
- CORS 开放 `*`，生产须收敛白名单。
- JWT secret 在 `.env`，生产须用密钥管理服务。
- bcrypt 直接调用（绕过 passlib 与新版 bcrypt 的兼容问题）。
- SQL echo 默认开启，日志较多；生产可关闭。
