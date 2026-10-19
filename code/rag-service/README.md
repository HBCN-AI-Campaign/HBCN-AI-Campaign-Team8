# HBCN RAG Service

独立的业务知识库通信模块。它不修改 `code/backend` 和 `code/frontend`，也不实现自己的切片、向量库或 Agent 循环。

当前状态：已提供两套引擎——① 正式引擎走 RAGFlow（需 Docker/RAGFlow 实例）；② 本地试运行引擎走
百炼 Embedding + SQLite 向量库 + OCR（无需 Docker），并附带 `/ui` 试用页面（查询 + 文件导入）。
本机尚未安装 Docker，因此 RAGFlow 实例和真实远端检索尚未启动；本地引擎已可运行试用。

## 运行

```powershell
cd code/rag-service
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
Copy-Item .env.example .env
.venv\Scripts\python -m uvicorn app.main:app --port 8010
```

运行前在 `.env` 配置 `SERVICE_TOKEN`；再按引擎二选一配置（见下）。`.env` 只保留在本机，不提交。

### 引擎选择

- **RAGFlow 引擎**（正式底座）：配置 `RAGFLOW_BASE_URL` / `RAGFLOW_API_KEY` 和两个 dataset ID。
- **本地引擎**（试运行，无需 Docker）：配置 `BAILIAN_BASE_URL` / `BAILIAN_API_KEY`，
  用百炼 `qwen3.7-text-embedding-flash` 生成向量并存入本地 SQLite。两者都配置时优先 RAGFlow。

### 试用 UI（本地引擎）

启动后浏览器打开 `http://127.0.0.1:8010/ui/`，粘贴 `.env` 里的 `SERVICE_TOKEN`，即可：

- **导入文件**（自动解析 + Embedding 入库）：文本直接读取；图片优先走队友 `code/ocr_demo`
  的 OCR 服务（`OCR_BASE_URL`），不可用时自动回退百炼视觉 OCR；PDF / Word / Excel 需先启动
  `code/ocr_demo`（其 PaddleOCR 环境见 `../ocr_demo/README.md`）。
- **检索查询**：返回带来源文件、相似度的证据片段；同时支持查看已入库文档列表。

## 初始化与入库（RAGFlow 引擎）

先配置 `BUSINESS_SOURCE_ROOT` 指向旧业务资料目录。以下命令默认只检查白名单，不上传：

```powershell
.venv\Scripts\python -m app.cli ingest --json
```

RAGFlow 可用并确认资料范围后，先创建或复用 dataset，再执行真实上传：

```powershell
.venv\Scripts\python -m app.cli bootstrap --json
.venv\Scripts\python -m app.cli ingest --execute --json
```

`--execute` 只会上传 `app/manifest.py` 中的白名单文件；敏感目录、视频、压缩包、样本单据和 API/云资源指南不在默认清单内。

## 部署官方 RAGFlow

部署脚本固定使用官方 `v1.0.0-rc2`，不会把 RAGFlow 源码复制进本项目：

```powershell
.\scripts\deploy-ragflow.ps1 -Start
```

脚本要求 Docker Desktop 和 Git 已安装。首次启动后访问 RAGFlow 管理页面配置 Embedding/LLM，并创建 API Key；再把 Key 写入本机 `.env` 的 `RAGFLOW_API_KEY`，不要提交。停止服务：

```powershell
.\scripts\deploy-ragflow.ps1 -Stop
```

## HTTP 契约

除 `/health` 外，接口要求：`Authorization: Bearer <SERVICE_TOKEN>`。

- `GET /api/v1/capabilities`：能力探测（含 `engine`：`ragflow` / `local` / `none`）。
- `POST /api/v1/query`：业务规则或项目设计资料的检索，返回可追溯证据。
- `POST /api/v1/documents`：以 `multipart/form-data` 接收已授权资料并索引（RAGFlow 引擎走 RAGFlow，本地引擎走 OCR + Embedding + SQLite）。
- `GET /api/v1/documents`：列出已入库文档（试用 UI 使用）。
- `GET /ui/`：本地试用页面（查询 + 文件导入 + 文档列表），仅本地引擎需要。

当前不开放 `task_documents` 和 `law`：前者需要主项目任务权限过滤，后者需要完成商业法规 API 的 MCP 授权适配。Agentic 编排由 SDK 模块负责，本服务只提供稳定的检索和入库边界。

## RAGFlow 映射

- 检索：`POST /api/v1/retrieval`。
- 上传：`POST /api/v1/datasets/{dataset_id}/documents`。
- 解析：`POST /api/v1/datasets/{dataset_id}/chunks`。

RAGFlow 由官方 GitHub 项目独立部署；本目录只做本项目协议适配。
