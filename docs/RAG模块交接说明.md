# RAG 模块交接说明（2026-10-19）

> 本文档写给下一个接手 RAG 的 AI（Codex）。内容包括：当前状态、架构与接口、运行方式、
> 开发过程中的关键决策与踩坑记录（含业务方的中途纠正），以及剩余工作清单。
> 目的是让接手者不重走弯路，理解“为什么这么设计”，再继续推进。

> **历史交接记录（2026-10-19），已过时。** 本文提到的 SQLite 当前引擎、8010 端口、RAGFlow 未部署及旧 UI 验收均属于早期阶段。当前模块事实请看 [RAG 模块总览](../code/rag-service/README.md) 和 [RAG 后端验收与运行](RAG后端验收与运行.md)。

---

## 0. 一页总结

RAG 模块（`code/rag-service`）已能**独立运行试用**：本地引擎（百炼 Embedding + SQLite
向量库 + OCR 客户端）跑通了「查询 / 文件导入 / 拖拽上传 UI」，**不依赖 Docker / RAGFlow**。
正式底座（RAGFlow）与主项目 AI 助手的联通**接口已预留但未接真实实例**。
OCR 由队友以 API 形式提供（`code/ocr_demo`），当前**尚未部署到任何可达位置**（已实测确认）。

一句话：**代码与接口已就绪，缺的是部署与真实数据**。

---

## 1. 当前完成度

### 已可用（实测跑通）

- `code/rag-service`（端口 8010）：
  - **本地引擎**：百炼 `qwen3.7-text-embedding-flash` + SQLite 向量库 + 余弦检索。
  - **业务视角 UI** `/ui`：居中搜索框 + 拖拽/点击上传 + 结果卡片（来源文件/相关度）+ 已入库资料。
  - **正式引擎**：RAGFlow 客户端（代码完整、单测覆盖），未接实例。
  - 引擎自动选择：配置了 RAGFlow 用 RAGFlow，否则配置了百炼用本地引擎。
- 主项目适配层 `code/backend/app/rag_service.py`：助手调 RAG 的 HTTP 客户端（scope 映射 + 证据透传）。
- 百炼 API 实测可用：LLM `qwen3.8-flash`、Embedding `qwen3.7-text-embedding-flash`、
  Web Search（`enable_search`）、以及多模态视觉 OCR（qwen3.8-flash 识图转文字）。

### 未完成（留给 Codex，详见 §9）

1. OCR 服务未部署（队友的 `ocr_demo` 还没跑起来）。
2. RAGFlow 正式实例未部署（ECS 上还没有 Docker）。
3. AI 助手与 RAG 的运行时联通（接口已就绪，只差 backend `.env` 两行）。
4. 真实业务资料入库与 `task_documents`/`law` 权限范围。

---

## 2. 架构

```text
主项目后端 ──> code/backend/app/rag_service.py（RAGClient 适配层）
                    │  HTTP + SERVICE_TOKEN
                    v
          code/rag-service（:8010，独立服务）
                    ├─ 引擎选择：RAGFlowClient ｜ LocalEngine
                    │     LocalEngine = 百炼 Embedding + SQLite 向量库 + OCR 客户端
                    └─ /ui 试用页（业务视角）
                    │
          OCR 是外部 API：code/ocr_demo（队友，独立 FastAPI，默认 :8000）
                    ↑ 通过 OCR_BASE_URL 调用，本地不装 OCR 模型
```

设计原则（写于 `docs/RAG实施规划.md`）：
- rag-service 是**独立服务**，不并入 backend/frontend，避免互相干扰。
- 主项目只通过**薄适配层**调用它，不直接接触 RAGFlow。
- 前端不暴露技术细节（Token / scope / top_k），这些都是后端与内部配置。

---

## 3. 文件清单与改动边界

### rag-service（RAG 模块，本轮主要负责）

- `app/engine.py` — 引擎工厂 + `LocalEngine`（上传/检索）、`chunk_text` 切片。
- `app/embedding.py` — 百炼 OpenAI 兼容 `/embeddings` 客户端。
- `app/local_store.py` — SQLite 向量库（documents/chunks 两表，纯 Python 余弦）。
- `app/ocr.py` — OCR 客户端：纯文本直读；PDF/Word/Excel/图片走 OCR 服务 `POST /ocr/file`；OCR 不可用且为图片时回退百炼视觉 OCR。
- `app/ragflow.py` — RAGFlow 官方 REST 映射（既有，未动）。
- `app/main.py` — 路由：`/health`、`/api/v1/capabilities`、`/api/v1/query`、
  `/api/v1/documents`(GET/POST)、`/ui`（服务端注入 Token 的试用页）。
- `app/schemas.py` — `KnowledgeScope` 含 `all`；`QueryRequest.scope` 默认 `all`、`top_k` 默认 5。
- `app/static/index.html` — 业务视角试用页（无构建、纯 HTML+JS）。
- `tests/test_local_engine.py`、`tests/test_ragflow.py` — 单测。
- `.env.example`、`.gitignore`、`README.md` — 已更新。

### backend（主项目，只按接口边界小改）

- `app/rag_service.py` — **新增**，RAG 适配层（`RAGClient.query(...)`，scope 映射 knowledge_base→business_rules+project_design）。
- `app/config.py` — **新增** `RAG_BASE_URL` / `RAG_SERVICE_TOKEN` / `RAG_REQUEST_TIMEOUT`。
- `app/assistant_service.py` — **只改** `_rag_search`：改为「本地证据 + RAG 知识库证据」合并，RAG 异常回退本地。
- `requirements.txt` — 加 `httpx==0.28.1`。
- `.env.example`、`README.md` — 补充 RAG 配置说明。
- `tests/test_rag_service.py` — **新增**。

### 明确“没动过”的队友文件

`code/ocr_demo/`（队友 OCR）、`parse_agent.py`、`review_agent.py`、`rule_engine/`、
`models.py`、`security.py`、`routers/tasks.py`、`routers/auth.py`、前端全部文件。

---

## 4. 接口契约

### rag-service HTTP（除 /health 与 /ui 外都要 `Authorization: Bearer <SERVICE_TOKEN>`）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 健康检查（无鉴权） |
| GET | `/ui` | 试用页（服务端注入 Token，无鉴权，仅本地试用） |
| GET | `/api/v1/capabilities` | 能力探测，返回 `engine`（ragflow/local/none） |
| POST | `/api/v1/query` | 检索，body `{query, scope?, top_k?}` |
| POST | `/api/v1/documents` | 导入，multipart `file` + 可选 `scope`（默认 business_rules） |
| GET | `/api/v1/documents` | 已入库文档列表 |

- `scope` 取值：`business_rules` / `project_design` / `all`（默认，两库合并去重排序）/
  `task_documents`（未开放，501）/ `law`（未开放，501）。
- 查询响应：`{query, scope, evidence:[{content, document_id, document_name, page, score, metadata}], warnings}`。

### backend 适配层签名

```python
RAGClient().query(query=..., scope="knowledge_base", task_code=None, top_k=6, agentic=True, include_external_law=False)
# 返回 {"evidence": [...], "warnings": [...]}
```

scope 映射：`knowledge_base → business_rules + project_design`；`task_documents`/`law` 暂返回空+提示。

---

## 5. 配置与密钥位置

- **百炼 API Key**（不要提交）：在共享文件夹
  `汇丰竞赛8组共享文件夹/04设备API等文件/AI-Campaign-2026-Team8-apiKey-7722271-refresh/*.csv`
  （字段 `apiKey` / `openAiCompatible`）。已写入本地 `code/rag-service/.env`（gitignored）。
  - OpenAI 兼容地址：`https://llm-tlndh47wd9ustbss.cn-beijing.maas.aliyuncs.com/compatible-mode/v1`
  - Embedding 模型：`qwen3.7-text-embedding-flash`；视觉兜底：`qwen3.8-flash`。
- **rag-service `.env`**（本地，已配好，勿提交）：`SERVICE_TOKEN`、`BAILIAN_BASE_URL`、
  `BAILIAN_API_KEY`、`EMBEDDING_MODEL`、`LOCAL_STORE_PATH=rag_store.sqlite3`、
  `OCR_BASE_URL=http://127.0.0.1:8000`、`OCR_VISION_MODEL`、`CHUNK_SIZE/OVERLAP`。
- **backend `.env`**（本地，未加 RAG 项）：联助手时再补 `RAG_BASE_URL`、`RAG_SERVICE_TOKEN`。
- ECS：公网 `101.201.232.81`，SSH `root@101.201.232.81:22`（密码在 `04设备API等文件/AI-Campaign-2026-Team08-ECS登录信息/*.txt`）。

---

## 6. 运行与验证

```powershell
# rag-service（已在 .venv，直接用）
cd code/rag-service
.\.venv\Scripts\python -m uvicorn app.main:app --port 8010
# 试用页：http://127.0.0.1:8010/ui （无需填任何东西）

# 单测
$env:HBCN_TEST_SOURCE_ROOT='E:\2026_AgentStudy\Python_code\HBCN_AI_Campaign_Team8_Clever\汇丰竞赛8组共享文件夹'
.\.venv\Scripts\python -m unittest discover -s tests   # 11 个用例通过

# backend 单测
cd code/backend
.\.venv\Scripts\python -m unittest discover -s tests   # 12 个用例通过
```

已验证：文本与扫描图片导入、视觉 OCR、Embedding、查询（默认 scope=all）、文档列表、UI 全链路。

---

## 7. 开发历程：关键决策与业务方纠正（给 Codex 看“为什么这么设计”）

### 第一轮：摸底
- 结论：rag-service 代码已写好但没接真实 RAGFlow（本机无 Docker）；主项目缺 `backend/app/rag_service.py` 适配层，`assistant_service.py` 里 `from .rag_service import RAGClient` 会 ImportError 被吞掉。
- 实测百炼 LLM / Embedding / Web Search 全部可用。

### 第二轮：补齐主项目对接
- 新增 `backend/app/rag_service.py`、`config.py` 加 RAG 配置、`_rag_search` 改为“本地证据+RAG证据合并”（保证任务上下文不因 RAG 未配置而丢失）。

### 第三轮：业务方要求“先把 RAG 独立跑起来试用”
- **决策**：RAGFlow 需要 Docker，本机没有 → 新增**本地引擎**（百炼 Embedding + SQLite），让 RAG 不依赖 Docker 就能跑；接口契约与 RAGFlow 路径完全一致，后续可无缝切换。
- **纠正①（OCR）**：我一开始试图在**本地装 PaddleOCR**（先 `pip install uv` 失败——PyPI 被代理拦截；后改用你下载的 Python 3.13.16 装 paddlepaddle/paddleocr 其实装成了）。
  业务方纠正：**OCR 是队友以 API 形式提供的，不要本地装**。→ 我停掉安装、删掉 `code/ocr_demo/.venv`（已恢复队友提交的原始状态），并 SSH 进 ECS 实测确认：ECS 只开 SSH 22 端口、没 Docker、没 OCR 服务 → **OCR 目前不可联通**，需队友部署后把 `OCR_BASE_URL` 指过去。
- **纠正②（UI）**：第一版试用页暴露了 Service Token 输入框、scope 下拉、top_k 输入，太“技术”。业务方要求以业务人员视角做 UI。→ 重做：去掉 Token/scope/top_k；Token 由服务端渲染 `/ui` 时静默注入（页面不显示、不存 localStorage）；文件导入改成拖拽/点击上传大框；scope/top_k 移到后端（查询默认 `all`，上传默认 `business_rules`）。
- **纠正③（文档先行）**：业务方要求先把设计写进规划文档 → 已写入 `docs/RAG实施规划.md` 的「4.1 试用 UI」。

### 协作边界（业务方多次强调）
- 只通过接口对接，**不改队友文件**；要明确报告“改了什么、会不会冲突”。
- 未执行任何 `git add`/`commit`；仓库有队友并行提交（`6dc7b86 接入 AI 助手与 RAG 服务`、`3b08b82 add ocr_demo`）。

---

## 8. 技术踩坑清单（避免 Codex 重蹈）

1. **Windows + 中文**：PowerShell 控制台是 GBK，Python 输出中文会 `UnicodeEncodeError`——脚本里 `sys.stdout.reconfigure(encoding='utf-8')` 或写 UTF-8 文件再读。
2. **PowerShell 5.1**：`Invoke-WebRequest` 没有 `-Form`；传 JSON 中文易乱码——用 `curl.exe -F`，JSON 写 UTF-8 文件后 `--data-binary @file`。
3. **PyPI 被代理拦截**（`files.pythonhosted.org` 超时）；但**阿里云镜像、paddlepaddle.org.cn 可达**；能用缓存的 wheel 也行。
4. **SQLite 连接必须显式 `close()`**：`with sqlite3.connect() as conn` 只提交不关闭，Windows 下会 WinError 32（文件被占用）。
5. **百炼 Web Search**：原生 REST 里 `enable_search`/`search_options` 要放请求体**顶层**，不能包在 `extra_body`（那是 SDK 才拍平）。
6. **Token 注入 HTML**：用 `json.dumps(token)` 替换占位符，JS 里写 `const token = __SERVICE_TOKEN__ || ''`；不要写 `window.__SERVICE_TOKEN__`（会变成 `window."token"` 非法语法）。
7. **视觉 OCR**：qwen3.8-flash 多模态可用，`image_url` 传 base64 data URL，扫描件+表格都能较好识别；可作 OCR 服务不可用时的兜底。

---

## 9. 剩余工作（建议顺序）

1. **让 OCR 真正可用**：请队友把 `code/ocr_demo` 服务部署到本机或 ECS（8000 端口），
   然后改 `rag-service/.env` 的 `OCR_BASE_URL` 指向它。在此之前：文本、图片（视觉兜底）可跑；PDF/Word/Excel 会报“OCR 服务未启动”。
2. **接 AI 助手（可选，接口已就绪）**：backend `.env` 加两行
   `RAG_BASE_URL=http://127.0.0.1:8010`、`RAG_SERVICE_TOKEN=<与 rag-service/.env 一致>`，重启后端即可，助手自动把 RAG 证据作为“知识库”引用返回。
3. **RAGFlow 正式底座（可选）**：在 ECS 上装 Docker 后跑 `scripts/deploy-ragflow.ps1`，
   RAGFlow 后台配百炼 LLM/Embedding，签发 RAGFlow Key 填进 `.env`，引擎自动切到 `ragflow`（代码无需改）。
4. **数据与权限**：决定真实业务资料入库范围；`task_documents`（需主项目 task_code 权限过滤）与 `law`（需法规 MCP 授权）暂未开放。
5. **上线前安全**：`/ui` 的 Token 注入仅限本地试用；生产应由主项目后端代理，浏览器不接触 Token。

---

## 10. 安全提醒

- 不要提交 `.env`（含百炼 Key、SERVICE_TOKEN）；`.gitignore` 已覆盖 `.env`、`rag_store.sqlite3`、`.venv`。
- ECS root 密码、百炼 Key 都在共享文件夹，读取但不要输出、不要进 Git。
- 本地 `rag_store.sqlite3` 里目前只有两份演示文档（AGENTS.md、demo_scan.png），可随时删掉重灌。
