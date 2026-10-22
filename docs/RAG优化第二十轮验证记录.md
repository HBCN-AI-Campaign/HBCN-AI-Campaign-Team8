# 第二十轮：带来源约束的问题事实槽位

2026-10-22；范围 R01/R07/R16。将意图规划中的槽位从提示词要求变为受限结构化契约，同时保留“用户陈述不等于业务事实”的证据边界。

## 实现

- `QueryPlan` 新增 document_type、field、discrepancy_type、amount、currency、subject、business_date、jurisdiction 八类槽位。每个已抽取陈述携带 `source`、`source_index` 和 `quote`；索引只针对 conversation 中按序过滤后的 user 消息，助手消息不可作来源。
- 服务端核验 quote 是当前 query 或指定 user 消息的原文子串，且 value 出现在 quote 中；不匹配的陈述丢弃并标记 partial。槽位多个不同值时保留陈述并标记 ambiguous/unknown，不自动选择或强行要求用户二选一。
- `/retrievals` 增加 `query_context` 响应字段；旧 planner 响应仍可工作，但明确标记 extraction_status=unavailable。该状态不证明提取语义正确、用户陈述真实或法规适用，不形成权限凭据或规范证据。
- 更新 API 契约、OpenAPI 快照、规划目标图源、规划/模块总览 Mermaid 与导出 PNG/SVG。

## 验证

| 检查 | 结果 |
| --- | --- |
| `tests.test_query_retrieval` 专项 | 19 项通过；验证逐字来源、错误来源丢弃、多值歧义保留、旧 planner unavailable 和 `/retrievals` HTTP 响应 |
| RAG 服务完整回归 | `python -m unittest discover -s tests`：196 项通过，13 项因显式 PostgreSQL schema/授权外部语料未配置而跳过 |
| 主站后端完整回归 | `python -m unittest discover -s tests`：32 项通过 |
| OpenAPI 快照 | `scripts/export-openapi.py --check` 通过 |
| 架构图 | Mermaid 11.12.0 CLI 解析并渲染 SVG/PNG；PNG 目视检查通过，临时浏览器配置已删除 |
| 差异格式检查 | `git diff --check` 通过 |

以上只验证结构、来源子串绑定和接口传输。真实汇丰模型的字段抽取准确率、否定/更正语义、业务题集质量、调用方 UI 展示和云端链路仍未验收；`provenance_checked` 不是语义正确率或用户事实真实性声明。
