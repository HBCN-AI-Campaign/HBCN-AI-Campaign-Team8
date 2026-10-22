# 境外贷款单据智能审核平台 · 后端（垂直切片 POC）

Python (FastAPI) + SQLAlchemy + SQLite/PostgreSQL 的后端服务。本目录是**垂直切片**：
用最小代价打通「数据库 → 规则引擎 → API → 鉴权」全链路，验证技术栈与核心业务逻辑。

> 配套：前端原型 `../mockup/mockup.html` + 规则规格 `../material_set_1/checklist_rules.json`
> 架构文档：`../GeneratedACD/architecture.md`

---

## 已实现（切片范围）

| 层 | 内容 |
|---|---|
| 数据库 | `users / review_tasks / documents / check_results` 4 张表（ER 图子集 + RBAC） |
| 规则引擎 | 注册表模式，已实现 3 条：R04 币种(fail)、R03 金额(pass)、R16 汇款人(pass) |
| API | 登录、任务 CRUD、触发核对、查询结果 |
| 鉴权 | JWT + bcrypt + 角色权限（operator / reviewer） |

**验证结果**：对样本任务 `FOL LN20260315-008` 跑出 `2 通过 / 1 不通过`，
权限拦截（经办人触发核对 → 403，无 token → 401），结果持久化正常。

---

## 快速开始

```bash
# 1. 安装依赖（已有 .venv）
../.venv/bin/pip install -r requirements.txt

# 2. 初始化数据库 + 种子数据
cd backend
../.venv/bin/python -m app.seed

# 3. 启动服务
../.venv/bin/uvicorn app.main:app --app-dir "$(pwd)" --port 8000
# 交互式 API 文档：http://127.0.0.1:8000/docs
```

### 默认账号（种子）

| 用户名 | 密码 | 角色 | 权限 |
|---|---|---|---|
| operator | operator123 | 业务经办人 | 上传解析、创建任务 |
| reviewer | reviewer123 | 审核人员 | 触发核对、看结果 |

### 调用示例

```bash
# 登录拿 token
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/auth/login \
  --data-urlencode "username=reviewer" --data-urlencode "password=reviewer123" \
  | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# 触发核对
curl -X POST "http://127.0.0.1:8000/api/tasks/FOL%20LN20260315-008/run" \
  -H "Authorization: Bearer $TOKEN"
```

---

## 目录结构

```
backend/
  app/
    main.py              FastAPI 入口 + CORS + 建表
    config.py            配置（DB 路径绝对化，默认 SQLite）
    rag_service.py       RAG 服务适配层（调用独立 hbcn-rag-service）
    database.py          SQLAlchemy engine / session
    models.py            ORM 模型（切片子集 + 权限）
    schemas.py           Pydantic DTO
    security.py          JWT + bcrypt + require_role 依赖
    seed.py              种子数据
    rule_engine/
      base.py            Rule 基类 / 注册表 / 结果结构
      rules.py           规则实现（R04/R03/R16）
      runner.py          执行器 + 汇总
    routers/
      auth.py            登录 / me
      tasks.py           任务 CRUD / run / results
  requirements.txt
  .env.example
```

---

## 接入 RAG 知识库服务（可选）

助手默认使用任务本地证据（规则结果 + 单据字段）。配置独立 RAG 服务后，
`app/rag_service.py` 适配层会把 `business_rules` / `project_design` 的检索证据
追加为「知识库」引用，供证据溯源使用，不会改写规则引擎结论。

1. 先启动独立服务 `../rag-service`（端口 8010，见其 `README.md`）。
2. 在本目录 `.env` 配置（模板见 `.env.example`）：

   ```
   RAG_BASE_URL=http://127.0.0.1:8010
   RAG_SERVICE_TOKEN=<与 rag-service/.env 的 SERVICE_TOKEN 一致>
   ```

3. 重启后端。`GET /api/assistant/capabilities` 的 `rag_available` 变为 `true`；
   未配置或服务不可用时，助手自动回退本地证据，不阻断对话。

## 切换到 PostgreSQL

1. 本地起 Postgres（或 Docker）：
   ```bash
   docker run -d --name loan-pg -e POSTGRES_USER=loan -e POSTGRES_PASSWORD=loan \
     -e POSTGRES_DB=loan_review -p 5432:5432 postgres:16
   ../.venv/bin/pip install psycopg2-binary
   ```
2. 复制 `.env.example` 为 `.env`，取消 `DATABASE_URL` 注释：
   ```
   DATABASE_URL=postgresql+psycopg2://loan:loan@localhost:5432/loan_review
   ```
3. 重跑种子 + 启动。代码无需改动（SQLAlchemy 抽象）。

---

## 下一步扩展路线

按优先级，从内到外补全：

1. **补全 33 条规则** — 把 `checklist_rules.json` 其余规则按 `rules.py` 的模式逐条实现。
   每条规则 = 一个 `Rule` 子类 + `@register`。D 组用途穿透可引入 `loan-data.js` 的
   `PURPOSE_DICT` 逻辑（见 `../GeneratedACD/loan-purpose-reference.md`）。
2. **归集树 + 事件 + 汇总** — 按 ER 图补 `TreeNode / Event / SummaryReport` 表与接口。
3. **前端接真实 API** — 把 `mockup/loan-data.js` 的静态数据改为 fetch 调用本服务。
4. **Alembic 迁移** — 用 `create_all` 够 POC，生产须改 Alembic 管理 schema 版本。
5. **文件解析 / OCR** — 最后接入（最贵）。前期用结构化录入 / 样本数据绕过。
6. **权限细化** — 当前是粗粒度 RBAC，可扩展数据级权限（只看本行任务）、审计日志。

---

## 已知说明（POC 取舍）

- 建表用 `Base.metadata.create_all`，改表结构需手动删库重建（生产用 Alembic）。
- CORS 开放 `*`，生产须收敛白名单。
- JWT secret 在 `.env`，生产须用密钥管理服务。
- bcrypt 直接调用（绕过 passlib 与新版 bcrypt 的兼容问题）。
