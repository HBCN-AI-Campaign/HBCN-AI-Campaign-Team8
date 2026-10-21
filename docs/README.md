# 项目设计文档索引

本索引指向当前可作为现状依据的模块总览、验收记录和部署规划。详细设计请看对应模块文档；标注“历史”的材料只解释设计沿革，不代表当前代码或部署状态。

## 项目管理入口

- [Team 8 项目管理主档](../TEAM_MASTER.md)：目标、分工、模块状态、行动项和资源台账。
- [迁移到汇丰 ECS 实施方案](部署到汇丰ECS实施方案.md)：本机 RAG/runtime 迁移、主站接线、网络边界、验收和回滚。

## 当前模块总览

- [RAG 模块总览与运行说明](../code/rag-service/README.md)：当前架构图、入库时序、实际 PostgreSQL/pgvector 数据关系、接口和限制。
- [RAG 后端验收与运行](RAG后端验收与运行.md)：真实后端联调结果、已验证资料范围、测试证据和剩余部署工作。
- [慧眼助手总规划](ai-assistant/README.md)：当前架构、对话时序、实际会话 ER、接口、权限与运行方式。
- [慧眼助手多人协作规划](ai-assistant/多人协作AI对话调研与优化方案.md)：专家/团队会话方向和目标图表；以文内“当前/目标”标识区分已实现与规划。
- [知识库资料清单](knowledge-base-manifest.md)：安全资料范围、白名单及敏感目录排除规则。

## 系统图与历史规划

- [主站证据定位数据流图](diagrams/document-evidence-flow.mmd)：解析字段、规则结果和 PDF 原文定位。
- `diagrams/current-system-architecture.mmd` 与 `diagrams/current-loan-review-sequence.mmd`：较早版本的主站图，仍包含 Vue 描述，需按 React 现状重画后再用于答辩。
- `diagrams/rag-integration-sequence.mmd` 与 `diagrams/rag-service-boundary.mmd`：早期规划图，包含尚未落地的审核 Agent/RAGFlow 流程，不代表当前 RAG 实现。
- [早期 RAG 技术方案](RAG模块技术方案.md)、[早期 RAGFlow 实施规划](RAG实施规划.md)、[RAG 旧交接记录](RAG模块交接说明.md)：历史决策材料，现状以 RAG 总览和验收记录为准。
- [资源连通性阶段核验](RAG资源连通性核验.md)：阶段性审计记录；新旧结论应按日期和后续验收报告理解。
- [历史迁移方案](legacy/)：保留旧项目迁移背景。
