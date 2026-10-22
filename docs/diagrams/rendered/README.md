# RAG 优化规划图像

这些 SVG/PNG 是待评审目标方案的导出图，不代表已实现。可缩放 SVG 适合阅读细节，PNG 方便预览和讨论；可编辑图源在上级目录对应的 `.mmd` 文件。

| 图 | 源文件 | 预览 |
| --- | --- | --- |
| 总体架构 | [MMD](../rag-target-architecture.mmd) | [SVG](rag-target-architecture.svg) / [PNG](rag-target-architecture.png) |
| 检索与重排闭环 | [MMD](../rag-target-retrieval.mmd) | [SVG](rag-target-retrieval.svg) / [PNG](rag-target-retrieval.png) |
| 案例与记忆治理 | [MMD](../rag-case-memory-lifecycle.mmd) | [SVG](rag-case-memory-lifecycle.svg) / [PNG](rag-case-memory-lifecycle.png) |
| 北大法宝 MCP 接入 | [MMD](../rag-mcp-integration-sequence.mmd) | [SVG](rag-mcp-integration-sequence.svg) / [PNG](rag-mcp-integration-sequence.png) |

导出方式：Mermaid 11.12.0，在浏览器加载本地 Mermaid 包、执行 parse/render，再保存 SVG 并以浏览器截图导出 PNG；已检查四张图的语法与中文可读性。导出依赖安装在仓库外的临时文档环境，未修改业务依赖。

更新时依次修改图源、同步 [优化规划](../../Agentic-RAG优化规划.md) 与 [模块总览](../../../code/rag-service/README.md) 的 Mermaid 块、重新导出本目录图像，并检查三处一致。当前架构仍以总览的“当前 RAG 架构”一节为准。
