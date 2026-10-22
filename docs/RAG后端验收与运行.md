# RAG 后端验收与运行交接

日期：2026-10-21（北京时间）。本次目标为真实跑通独立 RAG 后端与本机服务端口，不做新的 UI、不修改队友主前后端、不提交或推送 Git。

## 技术选型铁律

- 先按业务目标、可验证质量和安全合规选择成熟的最优方案，不把当前 ECS 配置、现有 API/模型或本机能力当作目标架构上限。
- 若方案缺算力、存储、模型或授权，明确登记资源缺口并提出申请或替代部署路径；不得因资源暂缺而静默降低目标。
- 同时透明评估成本、时延、可靠性与维护复杂度；最优不是盲目堆硬件或堆 Agent。

## 结论

**已跑通真实后端，不再只有证据检索：上传 → 原件持久化 → 解析 → 切片 → 百炼 Embedding → 汇丰 PostgreSQL/pgvector → 相关性核对/有限改写重检索 → OpenCode SDK 生成带引用回答 → 原件及全文片段定位。**

- 本机 RAG：`http://127.0.0.1:8011`，OpenAPI：`/docs`。
- 依赖已有 OpenCode SDK runtime：本机8090，本次实测可用，没有改它的代码或进程。
- 原有8010监听进程未停止、未覆盖；**不要把8010旧服务当作本次后端**。
- 仅本机端口可用；未开放公网、未验证其他同学电脑/云电脑主动访问本机、未完成 ECS 常驻应用部署。
- **现有 React RAG UI 仍有静态演示/模拟动态，没有自动接上这些接口。** 后端验收不能用这个 UI 的固定答案证明，也不能据此宣称全网站已联调。

## 资源实际使用

| 资源 | 当前结果 |
| --- | --- |
| ECS | SSH 登录及私网转发实测可用；2C8G，用作本机访问私网 RDS 的跳板，不在其上部署重型 RAGFlow |
| PostgreSQL | 真实连接，使用独立 `hbcn_rag` schema，不修改主项目任务/用户表 |
| pgvector | 已下发并可用，版本0.8.0.2；1024维向量表 `chunks_v1`，HNSW索引已创建 |
| 百炼 Embedding | 实际批量生成业务文档向量，模型 `qwen3.7-text-embedding-flash` |
| LLM / SDK | 实际调用已有 OpenCode SDK `/runs`；runtime 本机配置为汇丰百炼 `qwen3.8-flash`，模型地址与 RAG 百炼配置一致 |
| OCR | 合成图片已真实上传、视觉识别并生成向量；队友8001 OCR服务不可达时走已有百炼视觉兜底；不是所有扫描件准确率验收 |
| OSS | 没有验证可用的 Bucket/Endpoint/授权组合，不能据此推断未开通；本次原件存本机 `data/`，不依赖 OSS |
| 北大法宝 MCP/API | 未接入，不把网页账号当作商用API授权，不把公开PDF检索冒充法宝查询 |

连接信息只从本机 `.env` 和共享文件夹下发资源文件读取，未写入源码、交接文档或验收报告。资源来源见 `RAG资源连通性核验.md`；其中“未部署/未写表/仍为SQLite”是前一阶段只读核验记录，**本次独立建表入库结果以此文为准**。

当前 RDS 不支持数据库 TLS；本机到 ECS 使用 SSH 加密，ECS 到 RDS 为私网未启用数据库 TLS，需资源管理员确认正式运行策略。代码固定观察到的 SSH 指纹，但该指纹尚未由组织方独立确认。没有放开 RDS 公网或改防火墙。

## 真实资料与范围

已导入4份汇丰业务资料，合计59个片段：

1. `贷款文件比对要求- V2 20261013.xlsx`：18片段。
2. `贷款文件比对要求.xlsx`：12片段。
3. `贷款用途常见描述.xlsx`：18片段。
4. `FOL 贷款用途（流贷+固贷）.docx`：11片段。

已导入2份 `law` 通知，合计13片段，保留官方来源URL与CN管辖区：

- `cn-overseas-loan-banks-2022.pdf`：3页、9片段，对应银发〔2022〕27号通知。
- `cn-overseas-loan-banks-2026-72.pdf`：2页、4片段，对应银发〔2026〕72号调整通知。

它们是知识库现有的官方网页打印件，**不等于完整法规全集，也没有对所有附件与当前效力作法律核验**。输出始终要求效力、适用性和附件完整性复核。

没有无差别导入 catalog 的38条条目。检查发现：标为“境内企业境外放款管理办法”的 `cn-overseas-lending-2026-63.pdf` 实际只有一页“参数设置”附件；部分其他目录标题与PDF正文年代/文号不一致，个人消费贷款资料也不应混为企业境外贷款依据。这些均未作为本次业务法规底座导入。

共享目录只有 `01_汇丰业务文件` 的明确白名单进入本次业务导入；未把API Key、SSH/RDS资源文件、整个资源目录、会议视频或真实任务单据混入知识库。`project_design` 中另外保留了明确命名的上传/OCR/失败重试验收资料，不能作为业务规则或法律依据。

## 技术实现与边界

复用成熟组件，不自建通用RAG框架：

- `langchain-postgres`：PGEngine / PGVectorStore，真实向量检索与HNSW。
- `langchain-text-splitters`：带原文字符起点的中文友好递归切分。
- `LangGraph`：问题理解、检索、相关性检查、有限改写重检索、生成节点；检索最多两轮。
- `pypdf`：原生PDF文本；`pypdfium2`：扫描页渲染；`python-docx` / `openpyxl`：Office。没有把自行拼接的字符串当作PDF解析器。
- 已有 OpenCode SDK：问题指代理解、相关性判断、回答生成，未在此复制SDK Agent循环。

初期验证曾使用 PyMuPDF，最终运行依赖改为 pypdf + pypdfium2，避免把 PyMuPDF 的 AGPL/商业授权决策隐含带入交付。上述项目及传递依赖仍应在正式分发前做许可证清单复核；本次没有复制第三方项目源码。报告生成仅用 reportlab 构建测试PDF，放在开发依赖中。

仅当文档完整提交后才把向量标为 searchable；失败/处理中内容不参与检索。scope和embedding模型有明确过滤。相同scope/文件SHA256/模型去重，失败需显式retry，不伪装成功。元数据和处理阶段在PostgreSQL，原件在本机私有目录，**两者都要备份**。

本机单进程、单worker，后台2个入库线程，队列最多8份排队/处理中资料；问答最多4个并发。该实现适用于竞赛模块演示/联调，不是分布式任务队列或多租户生产平台。SDK每次调用默认90秒，完整Agentic问答可包含多次调用，客户端应设240秒级超时或消费SSE。

## 接口接入

除 `/health` 外业务接口要求服务Bearer Token；本机浏览器通过 `/ui/` 可拿到短时HttpOnly同源会话，无需让用户填服务Token。不要将服务Token写入前端、关闭鉴权或绕过主项目JWT/角色权限。

| 接口 | 调用方式与返回 |
| --- | --- |
| `GET /api/v1/ready` | 数据库、pgvector列与SDK健康；HTTP200才表示本次就绪检查通过，不产生模型费用 |
| `GET /api/v1/capabilities` | 配置能力和文件约束；不取代ready |
| `POST /api/v1/ingestions` | multipart file/scope，可选source_url/jurisdiction；202返回document与status_url |
| `GET /api/v1/documents/{id}` | 轮询 state/stage/events；UI按真实事件展示，不用计时器模拟 |
| `POST /api/v1/documents/{id}/retry` | 失败文档重试 |
| `POST /api/v1/answers` | JSON query/scope/top_k/conversation；返回answer/sources/warnings/grounding/retrieval_rounds |
| `POST /api/v1/answers/stream` | 同一问答过程，SSE step/result/error；step是操作摘要，不是思维链 |
| `GET /api/v1/documents/{id}/content?chunk_id=...` | 全文、页/工作表和命中focus；用start_index定位原文，前端仍负责高亮/上下滚动 |
| `GET /api/v1/documents/{id}/source` | 原始字节；PDF inline，非PDF attachment，不执行原始HTML |
| `POST /api/v1/query` | 保留旧纯证据协议，供已有主项目适配层复用 |

问答 sources 包含 citation/content/document_id/document_name/page/score/chunk_id/source_url/reader_url/metadata。PDF页码是物理页码；Office/文本为null，XLSX用section工作表，不能冒充印刷页码。引用编号校验只保证编号存在，不是逐条法律真实性证明。证据不足返回 `grounding=insufficient`，不作确定性审核结论。

支持 business_rules/project_design/law/all；`task_documents` 未开放，仍须主项目先做任务级授权过滤。主项目既有适配层仍有law禁用逻辑，本次没有越界修改它；需要由负责同学按产品权限策略接入。主项目调用方应将后端环境变量 `RAG_BASE_URL` 设置为实际8011地址、`RAG_SERVICE_TOKEN` 与模块配置一致，不要在React页面放密钥。

## 验收结果

- 自动化回归：**47项通过**，含旧接口兼容、同源会话、范围隔离、新接口鉴权、实际PDF/Office解析、扫描页渲染/OCR调用、格式/大小校验、有限改写图、证据不足、引用越界抑制、原件安全下载等。
- 虚拟环境 `pip check` 通过，Python编译检查通过。
- 真实 HTTP：上传202；阶段从received/parsing/splitting/embedding/indexing到ready；PDF原件SHA256一致；返回真实2页；同文件去重；无鉴权401；跨文档chunk请求404。
- 损坏PDF真实进入failed；retry仍失败，不冒充ready。
- 业务问题“固定资产投资类贷款的用途应如何填写”通过真实pgvector检索 + SDK回答，返回引用业务原文；SSE真实step和result齐全。
- 无关中奖号码问题保守返回证据不足。
- 法规问题“银发〔2022〕27号通知基本原则”返回2个真实页码来源及效力复核提示，实测约40秒；这不是正式法律适用结论。
- 多轮指代追问真实HTTP200并返回带引用结果。
- 已重启新RAG进程，重新验证业务/法规文档存在、向量检索、全文focus与跨文档片段隔离，证明并非只存内存。

本机报告在忽略目录：`code/rag-service/data/backend-acceptance.json`、`persistence-acceptance.json`、`law-and-followup-acceptance.json`、`corpus-import.json`。报告不含密钥、密码或业务原文；延时只是当前小规模单次测试，不代表吞吐/并发SLA。

## 启停、复测

在 `code/rag-service` 目录执行：

```powershell
.\scripts\start-backend.ps1 -Port 8011
.\scripts\stop-backend.ps1 -Port 8011
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python scripts/verify-backend.py
.venv\Scripts\python scripts/verify-backend.py --persistence-only
$env:HBCN_TEST_SOURCE_ROOT = 'E:\2026_AgentStudy\Python_code\HBCN_AI_Campaign_Team8_Clever\汇丰竞赛8组共享文件夹'
.venv\Scripts\python -m unittest discover -s tests -v
```

已有实例时start会拒绝重复启动；stop核对保存的PID、监听端口和uvicorn进程，不随意停止其他服务。日志在 `data/backend-8011.out.log` / `backend-8011.err.log`。重启会把未结束任务标为failed/interrupted，原件保留，可以显式retry。

不要重新申请已实测可用的PostgreSQL/pgvector。北大法宝 MCP 的 9 个地址已从本机完成 initialize 连通性检查，法规语义检索工具也已实际查询并返回法规证据；RAG 后端尚未接入该 MCP 客户端，授权范围与可存储/缓存/展示边界仍须按团队协议确认。接入流程见[北大法宝 MCP 接入说明](PKULaw-MCP接入说明.md)。其他待完善项包括 OSS 完整授权（若迁移原件存储）、跨电脑安全网络入口/部署方式，以及生产 TLS、备份、任务权限与运行稳定性方案。UI接线是下一步独立工作，不妨碍现在直接调用后端API验收。
