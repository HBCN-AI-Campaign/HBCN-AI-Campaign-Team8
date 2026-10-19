# 项目设计文档

这里记录当前工作区对应的系统设计。`legacy/` 保留从旧项目迁移来的方案，作为历史参考；`diagrams/` 中的 Mermaid 文件按当前代码结构重建，可继续编辑。

## 当前版本

- [RAG 模块技术方案](RAG模块技术方案.md)：当前 POC 的真实边界、RAG 接入位置和后续实现路线。
- [RAG 实施规划](RAG实施规划.md)：独立 RAG 服务、资料范围、HTTP 契约和部署边界。
- [知识库资料清单](knowledge-base-manifest.md)：安全资料范围与敏感目录排除规则。
- [RAG 实施规划](RAG实施规划.md)：独立 RAG 服务、资料范围、HTTP 契约和部署边界。
- [知识库资料清单](knowledge-base-manifest.md)：安全资料范围与敏感目录排除规则。
- [当前系统架构图](diagrams/current-system-architecture.mmd)：前端、FastAPI、规则引擎、Agent、数据库和文件存储。
- [当前审核时序图](diagrams/current-loan-review-sequence.mmd)：从上传、解析、建任务到人工终审的现有 API 流程。
- [证据定位数据流图](diagrams/document-evidence-flow.mmd)：字段来源、规则结果与 PDF 高亮之间的数据关系。
- [受控 RAG 接入时序图](diagrams/rag-integration-sequence.mmd)：未来接入 Embedding、知识库和受控 Agentic Retrieval 的边界。
- [RAG 服务隔离图](diagrams/rag-service-boundary.mmd)：独立服务与现有项目、RAGFlow、SDK 的通信边界。
- [RAG 服务隔离图](diagrams/rag-service-boundary.mmd)：独立服务与现有项目、RAGFlow、SDK 的通信边界。

## 历史迁移

- [历史 RAG 技术方案](legacy/RAG模块技术方案-历史版本.md)
- [历史业务集成时序图](legacy/RAG-汇丰业务集成时序图-历史版本.mmd)

历史文件保留原内容；当前开发和同步以 `docs/` 根目录下的方案与图为准。
