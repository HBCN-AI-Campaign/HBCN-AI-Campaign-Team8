# 慧眼助手总规划

跨模块协作请先看[全组接线总览](../integration/README.md)与[详细接口/时序](../integration/接口与时序.md)：区分业务专项审核与独立助手，明确RAG证据、SDK能力、任务状态和人工处置的边界；新增接口为草案，不代表本模块已实现。

> 当前实现：审核人员与 AI 先讨论，需要时邀请有任务权限的同事进入同一会话，阅读历史、共同讨论或继续问 AI。助手只提供辅助意见，审核结论必须由有权限人员确认。

## 1. 当前做到哪里

| 已实现 | 真实边界 |
|---|---|
| React 正式助手，复用 Ant Design X | [HTML 原型](../../mockup/mockup_assistant_collab.html)仅用于产品讨论 |
| 汇丰模型 → OpenCode SDK → 助手 API → 页面 | 本机真实调用已通过；密钥仅在服务端，不依赖 CC Switch |
| 同会话邀请、具名消息、撤销成员 | 仅审核人员；共享前必须关联任务；邀请不授予任务访问权或审批权 |
| 专家搜索、介绍、标签匹配推荐 | 真实账号及本人资料；不编造专家，不自动邀请 |
| 可恢复的 AI 运行及公开事件 | 幂等请求、单会话运行槽、数据库游标；协作页增量轮询 |
| 任务证据、RAG 适配、引用、折叠轨迹 | RAG 由另一模块负责；健康状态不等于检索质量保证 |
| 技能库：目录、加入/移除、版本更新提示 | 仅仓库审核发布的指引；不执行任意远程技能或上传脚本 |
| 工作流调用适配器 AssistantClient | 委托的业务 JWT；独立机器身份尚未实现 |

**尚未验收：** 汇丰 ECS/真实 PostgreSQL、多实例协调与压力测试；正文尚非模型 token 实时流。不能据此宣称生产级，或给出未经用户测试的高分。

## 2. 架构与模块边界

~~~mermaid
flowchart LR
  R[审核人员] --> UI[React 18 / Ant Design X]
  E[受邀同事] --> UI
  W[业务工作流 / Agent] -->|AssistantClient + 业务 JWT| API
  UI -->|JWT · JSON / SSE / 事件游标| API[FastAPI 助手 API]
  API --> ACL[成员身份 AND 现有任务权限]
  ACL --> DB[(会话 / 作者 / 运行 / 事件 / 审计)]
  API --> TASK[获准的任务字段 / 规则结果]
  API --> RAG[RAGClient · 现有知识库接口]
  API -->|本轮授权上下文 · 私网 token| RT[独立 runtime / OpenCode SDK]
  RT -->|服务端 HSBC key| HSBC[汇丰模型 API]
  RT --> TOOL[只读授权证据工具]
~~~

| 层 | 当前组件 / 主要文件 | 职责 |
|---|---|---|
| 界面 | React 18、Ant Design 5、Ant Design X 1.6.1；AssistantView.tsx | 上游 Sender/Bubble/Conversations/ThoughtChain；成员管理用 Ant Design Drawer/List/Modal |
| 页面适配 | useAssistant.ts、collaboration.ts | JWT 请求、状态、断线回放和目录同步；不做权限决策 |
| 业务边界 | routers/assistant*.py、assistant_collaboration.py | 会话/任务鉴权、运行调度、持久事件、审计 |
| 证据与回答 | assistant_service.py、既有 rag_service.py | 任务证据、知识检索、专家候选和答复校验；不修改审核状态 |
| Agent 执行 | code/assistant-runtime、OpenCode SDK 2.0.32 | 仅本轮只读工具；不直接读业务库或任意业务文件 |
| 数据 | assistant_models.py、独立 Alembic 迁移 | 新增助手专属表，不改队友任务表或 RAG 数据层 |

上游按锁文件安装：[Ant Design X](https://github.com/ant-design/x)（MIT）、[OpenCode](https://github.com/anomalyco/opencode)（MIT）。资源授权借鉴 [LibreChat ACL](https://www.librechat.ai/docs/features/access_control)。只写本项目业务适配，不重复引入认证/聊天框架；升级前先验证 React/Ant Design 和 SDK 兼容性。

## 3. 多人如何协作

~~~mermaid
sequenceDiagram
  actor R as 创建审核人员
  actor E as 受邀专家
  participant API as 助手 API
  participant DB as 数据库
  participant AI as OpenCode / 汇丰
  R->>API: 关联任务、与 AI 对话
  R->>API: 搜索专家，确认共享完整历史并邀请
  API->>DB: 检查角色与任务权限，保存成员/审计
  E->>API: 登录后读取同一会话历史
  E->>API: 发给成员（仅讨论，不调用模型）
  R->>API: 问 AI（content + client_message_id）
  API->>DB: 幂等校验、占用会话运行槽
  API->>AI: 历史 + 授权材料 + 技能
  AI-->>API: 公开步骤、工具结果、最终答复
  API->>DB: 保存事件和最终消息
  par 双方同步
    R->>API: 从游标读取事件
  and
    E->>API: 从游标读取事件
  end
  API-->>E: 同一答复、作者、引用；完成后折叠轨迹
~~~

- 创建者管理成员；成员可讨论/问 AI；创建者和运行发起者可停止 AI。未受邀、停用、撤权或失去任务权限的用户不能继续读取。
- 会话任务固定；切换任务须新建会话。任务授权仍沿用主站角色规则，助手没有擅自实现全平台细粒度任务 ACL。
- 每会话最多一个 AI 运行；期间仍可发讨论，新消息在后续 AI 轮次纳入上下文。
- 相同 client_message_id + 相同内容返回同一运行；同键不同内容返回 409。调用方重试须复用原键，显式重新提问用新键。
- 协作发送者约 0.7 秒读取本轮事件，旁观成员约 1.8 秒同步，目录约 5 秒刷新；隐藏标签页暂停后台同步。这不是 WebSocket/presence。
- 刷新可重建正在运行的公开轨迹；协作运行独立于事件读取连接。进程崩溃后，过期运行明确失败，不自动再次调用模型。

## 4. 数据与回答边界

~~~mermaid
erDiagram
  USERS ||--o{ ASSISTANT_SESSIONS : owns
  ASSISTANT_SESSIONS ||--o{ ASSISTANT_MESSAGES : contains
  ASSISTANT_MESSAGES ||--o| ASSISTANT_MESSAGE_AUTHORS : attributed
  USERS ||--o{ ASSISTANT_MEMBERS : joins
  ASSISTANT_SESSIONS ||--o{ ASSISTANT_MEMBERS : admits
  ASSISTANT_SESSIONS ||--o{ ASSISTANT_RUNS : executes
  ASSISTANT_SESSIONS ||--o{ ASSISTANT_EVENTS : appends
  ASSISTANT_SESSIONS ||--o{ ASSISTANT_AUDIT : records
  USERS ||--o| ASSISTANT_EXPERT_PROFILES : maintains
  USERS ||--o{ ASSISTANT_USER_SKILLS : pins
~~~

旧会话继续可用，旧用户消息归属创建者。最终消息保存步骤/引用，新增事件日志支持回放。OpenCode session 每轮临时创建并清理，业务历史由后端管理。

**过程与答案分开：** UI 仅接收公开步骤、工具、答复和引用；未知/reasoning 事件不进正文。runtime 只选成功结束且没有工具调用的最终消息，避免把工具前言当答复。后端还检查文本和人工确认提示，已有明确提醒时不重复追加。

SSE 自行管理数据库会话，不依赖已结束的 HTTP 请求会话；完整答复入库前再次检查权限与运行状态。撤权后服务端立即拒绝后续读取，在线页面在下一次同步时清除历史及任务选择；已经被对方阅读的信息无法收回。

正文目前在完整答复校验后分段显示，**不是 token 实时流**。运行中步骤/工具状态来自真实事件；不展示内部推理，不制造固定检查项假装执行。

RAG 按现有接口检索共享资料；任务字段/规则结果先经主站授权再读取。知识库不可用会显示提示，保留已有授权材料，不伪造命中。外部法规/任务文档 scope 以 RAG 模块实际接口为准。

## 5. 同学如何调用

页面入口：/assistant?task_code=任务编号，或 /assistant?session_id=会话ID。ID 不授予访问权。所有 API 均要求 Authorization: Bearer 业务JWT。

| API（前缀 /api/assistant） | 用途 |
|---|---|
| GET /capabilities；GET/POST /sessions | 就绪状态、本人及受邀会话、新建 |
| GET/DELETE /sessions/{id} | 授权历史 / 创建者删除（运行中拒绝） |
| GET /experts?session_id=&q=；PUT /experts/me | 搜索真实人员 / 本人专业资料 |
| GET/POST /sessions/{id}/members；DELETE /sessions/{id}/members/{user_id} | 查成员、邀请、撤权 |
| POST /sessions/{id}/messages | {content}：具名讨论，不调用模型 |
| POST /sessions/{id}/runs | {content,client_message_id,skill_id?} → 202 和运行 ID |
| GET /sessions/{id}/events?after_id=&run_id= | events,cursor,has_more,active_run；每页最多 100 条 |
| POST /sessions/{id}/runs/{run_id}/cancel | 创建者/发起者停止运行 |
| GET /sessions/{id}/audit | 创建者查看邀请/撤权/取消记录 |
| GET /skill-library；PUT/DELETE /skill-library/{skill_id} | 发布目录、个人加入/更新/移除 |
| GET /skills；POST /sessions/{id}/messages/stream | 兼容单人目录/SSE；共享会话用 runs/events |

事件：message_start / step / tool / delta / citations / message_end / error；协作增加 discussion / members_changed / run_end。持久事件带 id、run_id；message_end 的落库消息为权威正文，run_end.status 为最终运行状态。字段及调试见后端 /docs。

业务工作流用 app.assistant_client.AssistantClient(base_url, user_jwt) 的 create_session / ask / events / cancel；ask 的 client_message_id 使用业务请求唯一键。无需 HSBC key 或 runtime token，不绕过任务权限；自主后台服务身份需另外设计授权。

## 6. 拉取与部署

1. 团队授权渠道提供配置。后端按 .env.example 设置 runtime/RAG 地址及 token；runtime 按模板设置 AI_BASE_URL / AI_API_KEY / AI_MODEL。真实 key 不入仓库/浏览器。
2. code/backend：安装 requirements-assistant.txt（包含原 requirements），首次按主站流程初始化业务数据库，再执行下方 Alembic 命令。只增加助手表；旧库缺业务字段时先按业务模块要求升级，不删除/重建业务库。
3. code/assistant-runtime：bun install --frozen-lockfile，bun run start。后端：python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1。
4. code/frontend：npm ci、npm run dev。端口变化在忽略提交的 .env.local 设置 HBCN_API_TARGET；生产 npm run build，静态服务设 SPA 回退及 /api 代理，SSE 关闭缓冲。
5. **当前单 API 实例/单 worker**：数据库保存事件/唯一运行槽，执行与取消仍是进程内 asyncio 任务。多实例须先引入持久队列及跨进程取消验证。SQLite 用于本机演示；真实 PostgreSQL/ECS 另做环境验收。

没有汇丰授权配置的电脑不能直接请求模型；拉取可部署不等于把私密 key 随仓库分发。RAG/OCR/业务审核部署由对应模块负责。

## 7. 验证与文档维护

~~~text
code/backend:           python -m unittest tests.test_assistant_api tests.test_assistant_collaboration
code/frontend:          npm test && npm run build
code/assistant-runtime: bun test && bun run typecheck
code/backend:           python -m alembic -c assistant-alembic.ini upgrade head
~~~

测试覆盖权限、撤权、幂等、并发拒绝、取消/超时、作者、旧消息、技能和 React 邀请/轨迹/异常；mock 不代替真实链路。本机另用汇丰 qwen3.8-flash 完成真实问答（约 11.6 / 16 秒），以及隔离双 JWT 账号的真实模型协作验收（约 12.9 秒）。后端显式执行 python -m tests.live_assistant_acceptance --live 可重做后一项：仅用临时库与合成数据，直接调用真实 ASGI 路由，模型走真实 HTTP；不等于双浏览器/反向代理验收。结果与待办见[当前修改规划](持续优化实施规划.md)。

最新回归：后端 **35**、前端 **19**、runtime **3** 项通过，类型检查和前端构建通过；runtime 还覆盖无项目依赖目录的独立发布包。本机两个独立登录页面已通过真实 HTTP/汇丰模型的邀请、历史共享、具名讨论、共同问答及撤权清屏。可用 --browser-fixture 启动临时验收环境，步骤见当前修改规划；这仍不等于 Linux/ECS、PostgreSQL 或两台团队电脑验收。

维护三层：[本文](README.md)说当前是什么；[修改规划](持续优化实施规划.md)记录本轮实现和验证；[决策记录](决策记录.md)解释长期取舍。接口/行为落地时同步，不按日期复制。[早期调研](多人协作AI对话调研与优化方案.md)与[旧交接](开发记录与交接.md)是历史，遇冲突以当前代码和本文为准。
