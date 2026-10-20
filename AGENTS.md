# AGENTS.md — 境外贷款单据智能审核平台

> HBCN AI Campaign · Team 8 · 本文件给 AI 编码助手看（人类请读 `code/README.md`）

## 项目概览

境外贷款单据智能审核系统：经办人上传单据 → **解析 Agent** 识别字段 → **规则引擎**
硬核检查 → **专项审核 Agent** 处理外部能力项 → 给出通过 / 不通过 / 需人工处置结论。

- 后端：FastAPI + SQLAlchemy（Python）
- 前端：Vite + React 18 + TypeScript + Ant Design 5；助手使用 Ant Design X
- 两个核心模块当前是 **Mock 桩**，待协作实现：
  - `code/backend/app/parse_agent.py` — 文件解析 Agent（OCR/LLM 识别字段 + 定位原文位置）
  - `code/backend/app/review_agent.py` — 专项审核 Agent（节假日/汇率/提单验真/制裁名单/法规检索）

## 技术栈决策（重要 · 2026-10-20）

- **自有前端统一 React**：`code/frontend` 和 `code/rag-service/ui` 均为 Vite + React + TypeScript；助手入口为 `src/views/AssistantView.tsx`。
- RAG UI 构建产物仍输出到 `app/static/ui-build`，由 rag-service 在 `/ui/` 提供。不要覆盖 RAG 会话负责的后端与适配层。
- 新功能使用 React；聊天、消息、执行轨迹优先采用成熟上游组件，只编写本项目业务适配，不自建通用 Agent 框架或聊天组件库。选型及许可证记录在模块文档。
- 助手底层使用 `code/assistant-runtime` 的 OpenCode SDK；模型凭证只在服务端配置，使用汇丰提供的 API，不依赖个人 CC Switch。

## 目录结构

- `code/backend/` — 后端，源码全在 `app/`（入口 `app/main.py`）
  - `app/rule_engine/` 规则引擎（注册表模式）；`app/routers/` auth/tasks 路由
  - `app/sample_pdfs/` 样本 PDF（随仓库分发）；`app/uploads/` 运行时产物（已 gitignore）
- `code/frontend/` — 前端，源码全在 `src/`
- `code/rag-service/knowledge-base/` — 境外/跨境贷款法规与汇丰公开资料知识库（`catalog.json` 为索引，`README.md` 说明来源与下载方式；`docs/` 存 PDF/文本，已 gitignore）
- `mockup/` — 各成员 HTML 设计稿，按 `mockup_<名字>.html` 命名

## 环境与运行命令

后端（在 `code/backend` 下）：

```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m app.seed                                  # 初始化种子数据
.venv\Scripts\python -m uvicorn app.main:app --port 8000          # 启动，/docs 看 API
```

前端（在 `code/frontend` 下）：

```
npm install
npm run dev      # Vite 开发服务器，端口 5173，/api 代理到后端 8000
npm run build    # tsc -b 类型检查 + vite build（提交前必须通过）
npm test         # 助手接口、Markdown 安全与 React 交互回归
```

后端端口冲突时，在 `code/frontend/.env.local` 设置 `HBCN_API_TARGET`；不要把 RAG 端口当作主业务 API。RAG UI 在 `code/rag-service/ui` 下执行 `npm ci && npm run build`。

## 代码约定

- 后端分层：`models / schemas / routers / rule_engine / security` 各司其职，不跨层混写
- 前端：React 函数组件 + hooks，Zustand 管理鉴权，React Router 管理受保护路由；JSON 请求在 `src/api.ts`，助手 JSON/SSE 在 `src/assistant/api.ts`
- 两个 Agent 的输入/输出契约见各自文件顶部 docstring；**替换 Mock 实现时保持接口不变**
- 提交前确认 `npm run build` 通过（前端类型检查）

## 测试

- 助手后端回归：`cd code/backend && python -m unittest tests.test_assistant_api`；前端：`cd code/frontend && npm test && npm run build`
- 其他后端改动后至少确认 `uvicorn` 能正常启动、`/docs` 可访问
- 新增逻辑尽量补测试；接口契约以 docstring 为准

## 安全注意事项

- 禁止提交 `.env`（含 JWT 密钥、DB 配置），模板用 `.env.example`
- 禁止提交 `uploads/` 里的真实业务 PDF（含敏感单据）
- JWT 鉴权与角色权限在 `app/security.py`，不可绕过

## 提交约定

- 按模块提交，**不要 `git add .`**（避免卷入队友改动）
- 提交信息格式：`模块: 说明`，例如 `review_agent: 实现提单验真`
