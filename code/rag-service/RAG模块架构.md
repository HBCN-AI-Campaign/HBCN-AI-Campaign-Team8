# RAG 模块架构｜现状、目标与修改入口

> 2026-10-22 · 模块边界与 AI 模块一致：独立服务、HTTP 契约、内部独立更新。本文看图理解；实现、场景与验收看 [RAG模块优化规划](RAG模块优化规划.md)。实线表示已有机制；虚线表示待联调或待实现，不能把目标图当作上线证明。

## 1. 总图：知识怎样进去，AI 怎样调用

```mermaid
flowchart TB
  subgraph CALL[调用层：不依赖 RAG 内部代码]
    AI[AI 模块 / 专项 Agent]
    UI[知识库工作台<br/>上传 / 状态 / 原文 / 问答]
  end
  subgraph RAG[RAG 独立模块]
    API[FastAPI HTTP / OpenAPI<br/>服务鉴权 / 参数 / 取消 / 能力声明]
    ING[入库管线<br/>原件版本 → 解析 / OCR → 质量处理]
    INDEX[索引发布<br/>切片 / Embedding / 词法 / 原文位置]
    GRAPH[Agentic 检索<br/>理解与改写 → 混合召回 → 归并与重排<br/>原文覆盖核对 → 有限补查 / 明确停止]
    OUT[证据接口 retrievals<br/>原文 / 引用位置 / 缺口 / 来源状态]
    ANSWER[独立问答 answers<br/>结构化草稿 / 短引 / 支持复核]
    LIFE[资料生命周期<br/>质量 / 版本 / 撤回 / 返回前复查]
    API --> ING --> INDEX
    API --> GRAPH --> OUT
    GRAPH --> ANSWER
    LIFE --> INDEX
    LIFE --> GRAPH
  end
  subgraph DEP[可替换的部署依赖]
    FILE[(原件文件存储)]
    PG[(PostgreSQL / pgvector<br/>文档 / 向量 / 词法)]
    EMB[Embedding 与 OCR 服务]
    RT[OpenCode runtime<br/>汇丰模型 API]
  end
  AI -->|服务端调用 retrievals| API
  UI -->|本机受控会话| API
  ING --> FILE
  ING --> EMB
  INDEX --> EMB
  INDEX --> PG
  GRAPH --> PG
  GRAPH --> RT
  ANSWER --> RT
  OUT --> AI
  AI -.独立工具，待联合验收.-> LAW[北大法宝 MCP]
```

**RAG 内部会使用模型判断是否需要补查，这就是这里的 Agentic RAG。** 外层 AI 决定何时调用知识库、法宝或其他工具；它与 RAG 的有限检索循环是两个层次。法宝可由 AI 独立调用，已有 RAG 内部法宝适配保留为显式可选项，不是必需依赖，避免双方重复检索。网页是调用方授权提供的文本快照，不能只凭 URL 假装读过网页。

## 2. 入库图：为什么 OCR 后还可能停住

```mermaid
flowchart LR
  U[上传 PDF / Office / 文本 / 图片] --> V[登记范围 / 原件 SHA256<br/>queued → parsing]
  V --> P{能提取原生文字？}
  P -->|能| T[按页 / 工作表 / 章节提取]
  P -->|扫描或图片| O[OCR 服务 / 视觉模型]
  T --> Q{解析质量检查}
  O --> Q
  Q -->|无此类风险| C[机械检查通过]
  Q -->|OCR / 空页 / 结构疑点| R[quality_review<br/>显示具体单元与原因]
  Q -->|乱码 / 无有效文本| X[quarantined / failed<br/>更正后授权重检]
  R --> H[授权复核：原件与解析对照<br/>逐单元确认 / 拒绝 / 重检]
  H -->|批准当前三个摘要对应版本| C
  H -->|不完整或错误| X
  C --> S[切片 → Embedding → 写入隐藏索引]
  S --> A[事务发布 ready<br/>此时才能检索]
  A --> W[撤回：停止检索与原件访问<br/>在途结果重新检查]
```

这道检查拦的是**可能识别错的文字**，不是检查向量是否生成成功。OCR 已存在；Embedding 不会纠正漏字、金额或否定词。当前策略把 OCR 一律列为待对照，这是保守的工程策略，并非 Embedding 技术要求，也没有据此认定监管强制逐页人工审核。后续自动放行必须用独立 OCR 质量样本验证，不能用“没有乱码”代替识别正确。

## 3. 查询图：改写、混合检索、多源与有限补查

```mermaid
flowchart TB
  Q[用户问题 + 获准会话背景] --> PLAN[意图 / 指代 / 事实槽位<br/>原问题 + 通用表达 + 中英术语<br/>金额币种保真，不猜未知事实]
  PLAN --> V[向量召回]
  PLAN --> L[中文词法召回<br/>hybrid 配置启用]
  PLAN -.显式选择与授权.-> E[法宝适配 / 网页快照<br/>当前非基础链路必需]
  V --> F[RRF / 来源与查询族归并<br/>去重 / 保留版本与定位]
  L --> F
  E --> F
  F --> RR[可选专用 reranker<br/>未部署时明确标为 disabled]
  RR --> CTX[长文窗口 / 分批核对 / 联合覆盖<br/>法规条件 / 反例与冲突 / 缺口]
  CTX --> D{证据足够且运行完整？}
  D -->|有可修复缺口且未超预算| PLAN
  D -->|足够| RESULT[返回原文证据<br/>或生成并复核引用答复]
  D -->|模型失败 / 超时 / 缺依据| GAP[返回具体停止原因与缺口<br/>不把模型失败说成知识库没有资料]
```

默认上限为两轮、六次内部检索；跨语言分支和来源有各自预算。模型核对、生成、复核会增加时延，应分别量测。相关性重排只排列候选；覆盖核对决定是否还缺依据，二者不能互相替代。

## 4. 当前状态与部署边界

| 部分 | 当前事实 / 验收边界 |
|---|---|
| 解析、向量入库、检索、引用、撤回 | 本机已有真实 HTTP / PG / Embedding / 模型链路记录；不等于任意文件都已通过 |
| OCR 复核 | 页面原文对照、逐单元确认与版本绑定审批已补齐；两页合成扫描件经真实OCR/Embedding/Agentic检索通过，首次OCR失败与时延仍保留在[流程报告](RAG模块流程验收报告.md) |
| 混合召回、多源适配、专用重排接口 | 代码机制存在；当前实例为 vector，法宝与专用重排未启用，不宣称收益已验收 |
| 复杂业务题 | 已记录模型覆盖核对未完成的失败，不能以基础烟测替代 |
| 历史案例 / 经验记忆 | 独立治理机制存在；真实案例授权、用户权限和外层 AI 接线待做，不混进公共法规索引 |
| 汇丰服务器 / 主站联合 UI | 待同事部署和联合实测；本机运行不代表服务器已上线 |

```mermaid
flowchart LR
  CLIENT[业务系统 / AI 模块] --> GW[主站身份与任务授权<br/>服务端接入适配]
  GW --> R[RAG 单实例 / 单 worker]
  R --> D[(独立 schema + 原件卷<br/>一致备份与恢复)]
  R --> M[模型 / OCR / Embedding API]
  OPS[部署同事] -.配置 / ready 检查 / 场景验收.-> R
  OPS -.后续：持久队列 / 多实例设计.-> SCALE[扩容方案，未实现]
```

## 5. 修改入口

| 模块 | 源码与职责 |
|---|---|
| HTTP 与权限 | `app/main.py`、`app/backend_api.py`、`app/reference_security.py`：服务调用、受控工作台、复核范围授权 |
| 解析与质量 | `app/parsing.py`、`app/ocr.py`、`app/document_quality.py`：提取、OCR、风险报告 |
| 文档与索引 | `app/document_store.py`、`app/postgres_engine.py`、`app/lexical_index.py`：状态、批准、Embedding、索引发布与撤回 |
| 查询与归并 | `app/query_plan.py`、`app/retrieval_fusion.py`、`app/rerank.py`：保真改写、RRF、重排 |
| Agentic 与证据 | `app/answer_graph.py`、`app/evidence_context.py`、`app/evidence_assessment.py`：有界循环、长文覆盖、停止原因 |
| 法规与引用 | `app/legal_applicability.py`、`app/answer_draft.py`、`app/answer_verification.py`：用途门禁、结构化答复与短引复核 |
| 外部来源与 UI | `app/pkulaw.py`、`app/web_context.py`、`ui/src/`：可选来源、上传/对照/问答页面 |

接口字段只维护在 [API_CONTRACT](API_CONTRACT.md) 与 OpenAPI；部署只维护在 [deploy/README](deploy/README.md)，避免复制多份相互矛盾的规格。
