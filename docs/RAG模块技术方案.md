# RAG 模块技术方案（早期规划）

> 项目：境外贷款单据智能审核平台  
> **状态：早期规划，已不代表当前实现。** 本文按 2026-10-20 前后的 POC 状态编写，其中“RAG 外部服务尚未接入”等结论已经过时。当前实现请看 [RAG 模块总览](../code/rag-service/README.md) 和 [真实后端验收记录](RAG后端验收与运行.md)；本文保留作设计沿革。

## 1. 当前结论

本轮模块采用独立服务方式：`code/rag-service/` 通过 HTTP 与现有前端、审核流程和 SDK 通信。不要把 RAG 路由、配置、依赖或页面并入 `code/backend`、`code/frontend`，以免和其他同学的改动互相干扰。详细实施边界见 [RAG 实施规划](RAG实施规划.md)。

当前项目已经打通了“上传单据 → Mock 解析 → 规则核对 → 专项审核会话 → 前端展示与人工处置”的 POC 链路。RAG 不应被写成当前已经运行的服务；它的接入点是解析完成后的文档证据索引，以及 `review_agent` 需要法规、外部能力或跨文件证据时的受控检索。

第一版建议采用“混合检索为底座、受控 Agent 编排复杂问题”的路线：

1. 文本层 PDF 直接提取文本；扫描 PDF 或图片进入 OCR/版面解析。
2. 解析结果保留字段值、置信度、页码和归一化坐标。
3. 文档按任务、文件和版本建立索引，向量检索与关键词检索结合。
4. 简单问题直接检索；跨文件、跨法规的问题才进入有限轮数的 Agentic Retrieval。
5. 检索结果必须带文件名、版本、页码和原文锚点；证据不足时输出待人工确认。
6. 硬性规则仍由 `rule_engine` 执行，RAG 或 LLM 不直接改写规则结论。

## 2. 当前代码边界

| 层 | 当前实现 | RAG 接入位置 |
| --- | --- | --- |
| 前端 | 现有仓库前端 | 本模块不改页面；由前端同学按独立 HTTP 契约接入 |
| API | 现有主项目 API | 本模块不挂载路由；由审核流程或 SDK 通过 HTTP 调用独立服务 |
| 文件解析 | `code/backend/app/parse_agent.py` 当前按文件名返回 Mock 字段和 source | 替换为 OCR/LLM 后仍保持 `fields` 与 `source` 契约 |
| 硬规则 | `code/backend/app/rule_engine/` 注册规则并落库 `CheckResult` | RAG 只提供证据，不替代确定性校验 |
| 专项审核 | `code/backend/app/review_agent.py` 当前生成思考流和待处置项 | 把 `[专项]` 项接到外部核验和知识库检索 |
| 持久化 | SQLAlchemy 模型、SQLite 默认数据库；上传件落在 `code/backend/uploads/` | 先保存索引元数据，向量库可作为独立服务 |

当前接口链路：

```text
POST /api/tasks/parse
  -> parse_agent.parse_files
POST /api/tasks
  -> 创建 ReviewTask、Document
POST /api/tasks/{task_code}/run
  -> rule_engine.run_all
POST /api/tasks/{task_code}/ai/start
  -> review_agent.build_session
POST /api/tasks/{task_code}/ai/resolve
  -> 人工处置专项项或不通过项
```

## 3. 文档与证据模型

解析 Agent 输出的每个字段继续使用现有契约：

```json
{
  "key": "bill_of_lading_no",
  "label": "提单号",
  "value": "MAEU-SE-77215",
  "kind": "text",
  "confidence": 0.66,
  "source": {
    "page": 1,
    "bbox": [0.55, 0.14, 0.88, 0.18]
  }
}
```

RAG 入库时应在切片元数据中保留：

- `task_code`、`document_id`、原始文件名和文件版本；
- 文档类型、语言、页码、段落或表格位置；
- `bbox` 或 OCR 返回的原文坐标；
- 解析方式和置信度；
- embedding 模型版本和索引时间。

查询返回的证据包应能回到现有前端的 `FieldSource` / PDF 预览结构。低置信度字段、缺页、冲突版本和没有原文定位的结论进入人工处置队列。

## 4. 推荐实现顺序

### P0：先稳定现有 POC

- 保持 `parse_agent.py`、`review_agent.py` 的输入输出接口不变。
- 用当前样本 PDF 验证文本提取、扫描件识别和 `source` 坐标。
- 为规则结果和专项结果统一补充证据引用字段。

### P1：接入独立 RAG 服务

- 部署 RAGFlow 或同类文档检索服务，固定版本；独立服务代码放在 `code/rag-service/`，不混进当前 FastAPI POC。
- 由后端任务流程在解析成功后上传标准化文本和原文元数据。
- 由 `review_agent` 通过服务适配层调用检索；限制工具、轮数、超时和返回条数。
- 先做法规检索、跨文件一致性和提单/贸易背景核查，保留完整检索轨迹。

### P2：用真实样例验收

- 文本 PDF、扫描 PDF、表格和中英文混排各准备脱敏样例。
- 每类问题准备带期望文件和页码的检索题。
- 记录命中率、引用准确率、低置信度转人工率和平均延迟。

## 5. 部署判断

当前代码可以在本地运行；RAGFlow、OCR 和向量库是否本机部署，要根据机器资源和材料合规边界决定。embedding、LLM、OCR 的地址、模型名、向量维度和密钥通过环境变量注入，不能写入文档或提交到 Git。

成熟平台可以减少切片、索引、检索和 Agent 编排工作，但仍要针对本项目样例验证模型协议、扫描件解析、页码定位、权限隔离和数据出境规则。当前工作区只记录接入边界，不代表已经完成外部服务部署。

## 6. 图纸索引

- [当前系统架构图](diagrams/current-system-architecture.mmd)
- [当前审核时序图](diagrams/current-loan-review-sequence.mmd)
- [证据定位数据流图](diagrams/document-evidence-flow.mmd)
- [受控 RAG 接入时序图](diagrams/rag-integration-sequence.mmd)
- [RAG 服务隔离图](diagrams/rag-service-boundary.mmd)
