# AI 助手底座通信契约

本模块提供后端智能服务、通信协议和一个隔离的前端助手页面。现有审核/RAG页面不改；前端入口只增加 `/assistant` 路由和顶栏跳转，其他前端、任务编排器和专项审核 Agent 都通过 `/api/assistant` 调用它。

## 技术选型

| 层 | 选型 | 边界 |
| --- | --- | --- |
| Agent 编排 | OpenAI Agents SDK Python `0.4.2` | Agent、function tool、流式事件；通过 OpenAI-compatible client 接入模型服务 |
| 模型服务 | 汇丰提供的阿里云百炼团队 API | `AI_BASE_URL` / `AI_API_KEY` / `AI_MODEL`；密钥只放运行环境，不进仓库 |
| RAG | 现有 `rag_service.RAGClient` | 助手只调用 `search_knowledge_base` 工具，不依赖 RAGFlow 返回格式 |
| API | FastAPI + JSON + SSE | 会话持久化在 `assistant_sessions` / `assistant_messages` |

前端沿用仓库已有的 Vue 3 + Element Plus，不新增 React、Tailwind 或另一套状态系统。组件形态参考官方成熟方案 [`@assistant-ui/vue`](https://www.assistant-ui.com/docs/vue) 的 runtime、tool event 和 streaming 设计，通信层则适配本项目已有的 FastAPI SSE 契约。助手页面的代码边界如下：

- `code/frontend/src/assistant/api.ts`：只负责 `/api/assistant` 请求和 SSE 解析。
- `code/frontend/src/assistant/types.ts`：会话、消息、步骤和引用的前端契约。
- `code/frontend/src/assistant/markdown.ts`：使用成熟的 `marked` 解析 GFM Markdown，并由 `DOMPurify` 清理不可信模型输出；原始 HTML 和远程图片不渲染。
- `code/frontend/src/views/AssistantView.vue`：三栏助手界面、执行步骤时间线、工具检索轨迹（`tool` 事件）和证据引用面板，并提供一键复制回复。
- `code/frontend/src/router/index.ts`、`code/frontend/src/layouts/MainLayout.vue`：仅提供页面入口，不改变现有业务页面。

`openai-agents==0.4.2` 是当前仓库 `pydantic==2.10.3` 的兼容锁定版本，同时锁定 `openai==2.44.0`。这是因为 `openai==2.45.0` 起新增的 usage 字段会让该 Agents SDK 版本在运行前初始化失败。更新 SDK 时必须重新验证 FastAPI/Pydantic 依赖和网关的 Chat Completions 兼容性。

## 权限和业务边界

- 所有助手接口需要 JWT。
- 会话按 `user_id` 隔离；业务经办人只能带入自己提交的任务，审核人员可以读取任务上下文。
- 助手可以读取任务材料、规则结果和 RAG 证据，生成解释、风险摘要和人工复核草稿。
- 助手不能写入任务状态、改写 `CheckResult`、调用 `/complete` 或 `/return`，也不能直接给出贷款最终审批结论。
- 低置信度、证据冲突或无证据时必须提示人工确认。

## 接口

### `GET /api/assistant/capabilities`

返回 SDK、模型网关、RAG 是否配置以及是否支持流式事件。

### `GET /api/assistant/sessions`

返回当前用户的会话列表。

### `POST /api/assistant/sessions`

```json
{"title":"提款材料核对","task_code":"FOL LN20260315-008"}
```

`task_code` 可省略。带入任务时会立即执行数据级权限校验。

### `GET /api/assistant/sessions/{session_id}`

返回会话消息、执行步骤和引用。

### `POST /api/assistant/sessions/{session_id}/messages/stream`

请求：

```json
{"content":"请解释当前不通过项，并列出需要人工核对的材料","task_code":"FOL LN20260315-008"}
```

响应为 `text/event-stream`。每条事件是标准 SSE 的 `event` + JSON `data`：

| 事件 | 关键字段 | 用途 |
| --- | --- | --- |
| `message_start` | `message_id`, `task_code` | 创建本轮助手消息 |
| `step` | `step.key`, `step.label`, `step.status` | 展示执行步骤时间线；不暴露模型内部思维链 |
| `tool` | `tool.name`, `tool.status` | 展示知识库/证据工具开始和完成 |
| `delta` | `delta` | 增量渲染回答文本 |
| `citations` | `citations[]` | 文件、规则或知识库证据引用 |
| `message_end` | `message` | 本轮持久化消息和最终状态 |
| `error` | `message` | 可恢复错误 |

前端只需按事件类型更新自己的状态机，不需要知道 Agent SDK 的内部对象。

## 时序图

```mermaid
sequenceDiagram
    actor U as 用户/前端
    participant API as FastAPI assistant router
    participant DB as AssistantSession/Message
    participant Agent as OpenAI Agents SDK
    participant GW as 汇丰百炼 OpenAI-compatible API
    participant RAG as 现有 RAG 适配层
    participant Task as 任务/规则只读数据

    U->>API: POST /sessions/{id}/messages/stream
    API->>DB: 校验 user_id 与 task_code 权限
    API->>Task: 读取任务材料、规则结果
    API-->>U: message_start + step(context)
    API->>Agent: Agent + 受控 search_knowledge_base tool
    Agent->>RAG: 查询任务材料/知识库
    RAG-->>Agent: 证据片段与来源
    Agent->>GW: OpenAI-compatible 流式请求
    loop 增量输出
        GW-->>Agent: 文本 delta
        Agent-->>API: delta / tool 事件
        API-->>U: SSE 事件
    end
    API-->>U: citations + message_end
    API->>DB: 持久化用户消息和助手消息
```

## 运行配置

本项目默认使用汇丰比赛提供的百炼团队 API。复制 `code/backend/.env.example` 为 `.env`，并配置：

```dotenv
AI_BASE_URL=https://llm-tlndh47wd9ustbss.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
AI_API_KEY=<从汇丰安全渠道获取的 refresh 后团队密钥>
AI_MODEL=qwen3.8-flash
AI_REQUEST_TIMEOUT=45
RAG_BASE_URL=http://127.0.0.1:8010
RAG_SERVICE_TOKEN=<与 rag-service 的 SERVICE_TOKEN 相同>
RAG_REQUEST_TIMEOUT=15
```

`AI_API_KEY` 应由本机环境变量或部署平台 Secret 注入；团队成员从 Git 拉取代码后，需通过汇丰指定的安全渠道取得同一团队的有效 refresh 密钥，再在各自运行环境设置该变量。不要把 CSV、密钥、`.env` 或密钥写入前端构建变量，也不要通过 Git/聊天记录分发。生产部署还需由部署负责人把该 Secret 配置到 HSBC ECS 的服务运行环境。仅拉取仓库不会自动获得团队密钥，这是凭证管理的必要边界。

本地启动完整助手时，先启动 `code/rag-service`（端口 `8010`），并在两个服务的忽略 `.env` 中分别配置 `SERVICE_TOKEN` 和同值的 `RAG_SERVICE_TOKEN`。RAG 的百炼 Embedding/视觉模型使用汇丰团队 API Key；rag-service 的 `SERVICE_TOKEN` 只是内部服务鉴权，不是模型 API Key。部署到 ECS 时将 `RAG_BASE_URL` 改为服务可达的内网地址，并把两项 Secret 配置到后端运行环境。`rag_available` 表示连接配置已启用；实际检索依赖 RAG 服务已启动且对应知识库已索引。

可在 PowerShell 当前进程中设置本地密钥后启动后端：

```powershell
$env:AI_API_KEY = "<从汇丰安全渠道获取的 refresh 后团队密钥>"
python -m uvicorn app.main:app --port 8000
```

Linux/macOS 服务进程可通过部署平台 Secret 或 systemd `EnvironmentFile` 注入相同变量。未配置模型服务时，接口仍可启动并返回本地演示回答；该模式仅用于界面联调，不代表模型 API 已配置成功。
