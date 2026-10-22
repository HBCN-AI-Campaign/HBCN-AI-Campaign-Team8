# RAG 独立模块接口 v1

服务版本 `0.5.0`，HTTP 契约版本 `1.3.0`。调用方只依赖本文和 [OpenAPI 快照](contracts/openapi-v1.json)，不导入 `app/`、不查 RAG 表、不读取模型凭证。部署方法见 [deploy/README.md](deploy/README.md)；完整现状与优化范围见 [README](README.md)。

## 接线约定

部署同事提供私网 `RAG_BASE_URL` 和独立 `RAG_SERVICE_TOKEN`，调用方在自己的后端设置环境变量；地址不固定为个人电脑或某个端口。请求头使用 `Authorization: Bearer ...`。浏览器只访问主站 JWT API，由主站校验用户/任务权限后调用本服务，不把此服务 Token 交给浏览器。

`GET /health` 检查进程并返回 service_version/api_contract_version；不能据此认为数据库、模型或知识已就绪。`GET /api/v1/capabilities` 查询当前能力开关；`GET /api/v1/ready` 检查数据库/向量列与 SDK 健康，仍不能代替真实提问验收。响应头提供 `X-RAG-Service-Version`、`X-RAG-Contract-Version`，调用方接受 v1 主版本并容忍新增可选字段。

v1 保持路径、已有字段含义/类型、scope 和鉴权约定。新增可选字段/能力可在 v1 内发布；删除、改名、收窄既有含义或改变授权语义需要新契约主版本及迁移。内部模型、检索引擎、多源路由、重排和云端/API 资源可以替换，但必须通过相同 HTTP 契约与质量门槛。OpenAPI 快照变化须评审兼容性；快照一致不等于已证明业务质量。

## 两种检索入口

| 入口 | 用途 | 返回 |
| --- | --- | --- |
| `POST /api/v1/query` | 保留已有主站适配器的单次检索，不调用规划/答复 LLM | `evidence[]`、`warnings[]` |
| `POST /api/v1/retrievals` | 新调用方的增强证据检索；问题规划、有限补查、证据覆盖与法规门禁，**不生成最终答复** | `sources[]`、充分性、缺口、停止原因和来源状态 |

助手或专项 Agent 已负责最终回答时，调用 `/retrievals` 并消费原文证据，避免 RAG 再生成一次答案。独立问答 UI 才使用 `/answers` 或 `/answers/stream`。现有主站 `code/backend/app/rag_service.py` 仍调用 `/query`，本版本保留兼容；升级增强入口由主站负责人按新响应映射接线，本模块不覆盖其适配层。

增强检索的最小 JSON：

```json
{
  "query": "支付指令这 5000 元金额不对，应该怎样核查？",
  "scope": "business_rules",
  "top_k": 5,
  "sources": ["knowledge_base"],
  "purpose": "reference"
}
```

这是调用示例，不是预置答案。`scope` 为 business_rules/project_design/law/all，不能传 task_documents；`top_k` 增强入口 1–8，旧 query 入口 1–20。query 最长 4,000 字符；可选 conversation 最多 12 条 user/assistant 消息，每条同时满足 4,000 字符和 SDK UTF-16 限制。conversation 是提问背景，不是已证实事实或规范依据。

增强响应中的 `sources[]` 每项有 citation、content、document_id、document_name、page、score、chunk_id、source_url、reader_url、metadata。content 是所选原文窗口；page/score 可以为空，不能伪造页码或将分数显示为置信概率。相对原文 URL 由主站在重新校验权限后代理；外部链接按来源处理，不让浏览器直接携带服务 Token。

`evidence_status` 为 sufficient/insufficient/clarification，联合查看 missing、stop_reason、clarification_question、warnings、source_status、rerank_status、context_coverage、legal_applicability。HTTP 200 只表示本轮得到业务结果，**不等于可以审批通过**；片段有来源不等于支持全部结论，来源失败不等于无相关法规。调用方保留这些限定，不仅取 content 后丢弃缺口。

法宝仅在 scope=law/all、sources 显式包含 pkulaw、服务端授权配置启用时调用；默认关闭。`purpose=case_assessment` 必须提供经授权的 legal_context，并满足服务端法规复核；条件或有效依据不够时阻断本案结论。`case_reference`/`experience_memory` 为独立默认关闭的治理接口，尚不属于本增强来源列表，详见 [治理契约](../../docs/RAG案例与经验治理契约.md)。

独立调用示例仅依赖 HTTP：

```bash
python examples/retrieve.py --query '支付指令金额有误如何核查？' --scope business_rules
```

运行前在调用方配置 RAG_BASE_URL/RAG_SERVICE_TOKEN，安装 httpx。脚本不会读取本模块内部配置或业务后端对象；本轮 `--help`/机制测试不表示已在云端真实调用。

## 入库、原文和 SSE

| 路径 | 契约 |
| --- | --- |
| `POST /api/v1/ingestions` | multipart file/scope，可选来源 URL/辖区；202 后按 document.id 查询状态 |
| `GET /api/v1/documents`、`GET /api/v1/documents/{id}` | 文档列表/实际阶段；仅 ready 才可检索 |
| `POST /api/v1/documents/{id}/retry` | 失败或中断后的显式重试，不能靠查询触发重复入库 |
| `POST /api/v1/documents/{id}/withdraw` | 可信管理调用方逻辑撤回；传 `expected_sha256` 和枚举 `reason`，返回 document；未知 404、hash 不匹配 409、重复同版本撤回幂等 |
| `GET /api/v1/documents/{id}/content?chunk_id=...` | 原文页/章节及焦点；chunk 必须属于该文档 |
| `GET /api/v1/documents/{id}/source` | 原件存在才返回；PDF inline，其他 attachment，禁止 HTML 脚本执行 |
| `POST /api/v1/answers` | 独立问答 JSON；grounding=cited 仍不等于审核通过 |
| `POST /api/v1/answers/stream` | POST + fetch SSE；与 answers 相同请求体 |

SSE 事件为 `step`（key/label/status 的简要动作）、`result`（完整 AnswerResponse）或 `error`（message）；仅收到 step 或连接结束不能算完成。没有正文 token 增量承诺、没有事件回放或自动续跑。客户端断开触发本地取消及连接清理，但不能据此宣称供应商已停费；反向代理须关闭缓冲并保留足够超时。

入库/列表/原文当前是可信服务级能力；不是主站用户/任务 ACL。主站不得把这些管理接口作为任意用户公共上传下载网关。真正任务资料、敏感历史数据和公网知识管理仍需主站权限及生命周期验收。

v1.1 新增文档 `sha256`、状态 `withdrawn` 及撤回入口；调用方需容忍新增状态，不能把未知状态当 ready。`reason` 为 superseded/incorrect/authorization_revoked/quality_issue/other，不能传自报 actor/用户权限。调用前读取状态核对版本；模块只记可信服务身份，最终操作者与授权需在主站管理接口审计，不开放给任意用户。撤回不可通过 retry 或同内容重复上传恢复，版本重新批准/替换仍需后续治理流程。

撤回在事务中使文档和所有向量片段不可检索；词法 JOIN 同一 searchable 标记。原文/content 返回 404，状态元数据仍可供管理读取。Agent 跨轮候选、后续模型调用前与返回结果前重新检查本库片段；已失效则停止使用并隐藏生成答复，返回 source_withdrawn/依据缺口。所有 `/api/v1` 响应使用 `Cache-Control: no-store`。这不能召回已交付给调用方的正文、强停正在外部供应商处理的请求或消除复核之后到网络发送之间的竞态；调用方不能继续复用过期答复。外部法宝生命周期、案例/经验引用绑定、物理删除/备份擦除及跨系统缓存通知仍需分别实现。

## 错误、时限与版本验证

非 2xx 保留 FastAPI 格式 `{"detail": "..."}`；422 的 detail 可以是校验数组。常见 401 鉴权、404 原文/参考不存在或不可用、409 治理版本冲突、413 超限、415 不支持格式、422 参数、429 并发忙、502/503 依赖失败。task_documents 的旧 query 明确返回 501；不静默扩权或退回另一份资料。SSE 建连后失败用 error 事件。错误文本可修订，调用方不要匹配中文文本决定业务状态。

默认增强请求总预算 240 秒，调用方/网关超时至少 300 秒；如果部署方调整预算，必须同步调用方。上传处理与问答预算分开，入库用 202 + 轮询。超时后不自动重复有费用的模型/MCP 调用；429/503 是否重试由调用方按只读性、预算和退避策略决定。时延和吞吐指标尚待真实云端测量，不能据配置推断达标。

发布时运行 `python scripts/export-openapi.py --check`，并执行后端、UI、隔离 API 回归。发生有意接口变化时先评审兼容性/版本与本文，再显式重新导出快照。未知可选字段允许扩展，旧客户端读取原证据结构仍受契约测试保护。

## 解析质量门禁（1.2，升级需处理旧库）

文档新增可选 quality 报告与 quality_review/quarantined 状态；消费者必须按 state 判断可用性，不能将未知状态或 202 视为完成。run 是历史粗粒度兼容标记，待复核也可能为 FAILED；具体流程看 state/stage/quality。报告不等于 OCR 正确率/完整性或业务审批。

新增 GET `/documents/{id}/quality`、POST `/documents/{id}/quality-review` 和 POST `/documents/{id}/quality-recheck`，除服务鉴权外要求独立 X-Document-Review-Key。默认未配置注册表时关闭，不把凭证暴露浏览器。三份 hash、单元核对、响应/错误与运维工具见[质量契约](../../docs/RAG文档质量门禁契约.md)。

这是有意收紧知识可用性的质量升级：旧 ready 缺当前策略报告将不再召回，ready 增加 quality_policy_version/unverified_ready_documents 并可返回 503/degraded。需先备份/隔离预演、授权重检/必要复核、真实召回回归，不能直接覆盖版本后认为升级完成。现有 query/retrievals 请求结构保持兼容；云端迁移和主站接线另行验收。

## 网页上下文（1.3，默认关闭）

retrievals / answers / answers/stream 新增可选 web_context 快照数组，sources 显式支持 web_context；接口同时要求服务 Bearer 与独立 X-Web-Context-Key。仅 URL 不可，实际文本/采集时间/精确 scope/处理授权必填，严格大小与域名/时效门禁。旧请求不受影响，query 不接快照。配置、字段、状态码和调用示例见[网页上下文契约](../../docs/RAG网页上下文接入契约.md)。

响应沿用 sources，并标 source_type=web_context、verification=caller_supplied_unverified；page/score/reader_url 为空，原链接可能变化，不提供虚构的持久原文接口。source_status.web_context=provided_unverified 只表示已收到获授权快照，不表示本服务已抓取、确认全文或证明事实。调用方须保留这些局限，不把网页来源包装为法规已审核。增强接口仍不生成最终业务答复。
