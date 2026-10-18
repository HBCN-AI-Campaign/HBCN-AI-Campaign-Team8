# 境外贷款单据智能审核平台

> HBCN AI Campaign · Team 8
> 前后端一体 POC：**数据库 → 解析 Agent → 规则引擎 → 专项审核 Agent → API → 前端**

一套面向境外贷款单据的智能审核系统。业务经办人上传单据、系统自动解析识别字段，
审核人员触发核对：**规则引擎**完成可硬核对的确定性检查，**专项审核 Agent**
承接需外部能力的检查（节假日、汇率、提单验真、制裁名单、法规检索等），
最终给出通过 / 不通过 / 需人工处置的结论。

---

## 目录结构

```
code/
├── backend/            FastAPI + SQLAlchemy + SQLite 后端
│   ├── app/
│   │   ├── main.py             应用入口（CORS / 建表 / 路由挂载）
│   │   ├── config.py           配置（DB、JWT）
│   │   ├── database.py         SQLAlchemy engine / session
│   │   ├── models.py           ORM 模型
│   │   ├── schemas.py          Pydantic DTO
│   │   ├── security.py         JWT + bcrypt + 角色权限
│   │   ├── seed.py             种子数据（默认账号 + 样本任务）
│   │   ├── parse_agent.py      📌 文件解析 Agent（当前 Mock，待协作实现）
│   │   ├── review_agent.py     📌 专项审核 Agent（流程编排，待协作实现）
│   │   ├── rule_engine/        规则引擎（注册表模式，27 条规则）
│   │   └── routers/            auth / tasks 路由
│   ├── requirements.txt
│   └── .env.example
└── frontend/           Vite + Vue 3 + TS + Element Plus 前端
    ├── src/
    │   ├── views/              登录 / 仪表盘 / 创建任务 / 任务审核
    │   ├── stores/             Pinia 状态
    │   ├── router/             路由 + 鉴权守卫
    │   └── api.ts              axios 封装（/api 代理到后端）
    ├── package.json
    └── vite.config.ts
```

### 👥 团队协作分工

| 模块 | 文件 | 说明 |
|---|---|---|
| **解析 Agent** | `backend/app/parse_agent.py` | 上传单据 → 结构化字段识别（OCR/LLM）。当前为 Mock 桩实现，由对应成员替换为真实解析逻辑。 |
| **专项审核 Agent** | `backend/app/review_agent.py` | 承接规则引擎移交的 `[专项]` 项（节假日、汇率、提单验真、制裁名单、法规检索、语义翻译），调用外部能力/LLM。当前为 Mock，由对应成员实现。 |
| 规则引擎 / API / 前端 | `rule_engine/` · `routers/` · `frontend/` | 已就绪，可直接运行。 |

> 两个 Agent 的输入/输出契约见各文件顶部的 docstring；替换实现时保持接口不变即可无缝对接。

---

## 快速开始

### 前置要求

- **Python** ≥ 3.11（开发用 3.13）
- **Node.js** ≥ 18（含 npm）

### 1️⃣ 启动后端（终端 A）

```bash
cd backend

# 创建虚拟环境并安装依赖
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 初始化数据库 + 种子数据（默认账号 + 样本任务）
python -m app.seed

# 启动服务（http://127.0.0.1:8000）
uvicorn app.main:app --app-dir "$(pwd)" --port 8000
```

- 交互式 API 文档：<http://127.0.0.1:8000/docs>
- 默认使用 SQLite（零依赖，`backend/loan_review.db` 自动生成）

### 2️⃣ 启动前端（终端 B）

```bash
cd frontend

npm install        # 首次安装依赖
npm run dev        # 启动开发服务器（http://localhost:5173）
```

前端 `/api` 已配置代理到 `http://127.0.0.1:8000`，无需额外跨域配置。

### 3️⃣ 打开浏览器

访问 <http://localhost:5173>，使用下方默认账号登录。

---

## 默认账号（种子数据）

| 用户名 | 密码 | 角色 | 权限 |
|---|---|---|---|
| `operator` | `operator123` | 业务经办人（张三） | 上传解析、创建审核任务 |
| `reviewer` | `reviewer123` | 审核人员（李四） | 触发核对、查看结果、处置专项项 |

---

## 常用命令速查

| 操作 | 命令（在对应目录执行） |
|---|---|
| 后端：重建数据库 | `cd backend && python -m app.seed` |
| 后端：启动服务 | `cd backend && uvicorn app.main:app --app-dir "$(pwd)" --port 8000` |
| 前端：安装依赖 | `cd frontend && npm install` |
| 前端：开发模式 | `cd frontend && npm run dev` |
| 前端：生产构建 | `cd frontend && npm run build` |
| 前端：预览构建产物 | `cd frontend && npm run preview` |

---

## 技术栈

**后端**：FastAPI · SQLAlchemy 2.0 · Pydantic 2 · python-jose (JWT) · bcrypt · SQLite（默认）/ PostgreSQL（可选）

**前端**：Vite 6 · Vue 3.5 · TypeScript · Pinia · Vue Router 4 · Element Plus 2.9 · axios

---

## 配置（可选）

后端配置通过环境变量 / `.env` 文件管理。复制示例文件后按需修改：

```bash
cd backend
cp .env.example .env
```

| 变量 | 默认 | 说明 |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./loan_review.db` | 改为 `postgresql+psycopg2://...` 可切换 PostgreSQL（代码无需改动） |
| `JWT_SECRET` | `change-me-...` | 生产务必替换 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `480` | Token 有效期（分钟） |

---

## 常见问题

- **端口被占用**：后端 `pkill -f "uvicorn app.main:app"`；前端改 `vite.config.ts` 的 `server.port`。
- **改了后端代码没生效**：启动命令未加 `--reload`，需重启 uvicorn。
- **登录接口**：使用 OAuth2 表单编码（`username=...&password=...`），非 JSON。
- **数据库想重置**：删除 `backend/loan_review.db` 后重跑 `python -m app.seed`。
