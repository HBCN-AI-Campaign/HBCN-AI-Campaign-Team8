# 汇丰业务知识库与受控 Agentic RAG 实施规划

> 目标：把业务资料、任务单据、法律法规查询和外部审核能力统一成一个可被前端、审核流程和其他 Agent 调用的查询服务。  
> 当前状态：已完成独立服务、官方 RAGFlow REST 映射、资料白名单和本地验证；没有改动现有前端或共享后端。本机尚未安装 Docker，外部 RAGFlow、Embedding、LLM 和北大法宝 MCP 尚未配置。

## 1. 最终形态

这个模块不是单一的“RAG 页面”，而是一个**业务知识与外部法规查询服务**：

```text
现有前端/审核流程 ──HTTP──> 独立 hbcn-rag-service ──REST──> RAGFlow
                                      │                       │
                                      │                       ├─ business-rules
                                      │                       └─ project-design
                                      │
                                      └─ 返回检索证据；SDK 编排、任务权限和法规 MCP 分别接入
```

RAGFlow 负责文档解析、切片、索引和检索；独立 `code/rag-service` 只负责鉴权、范围映射和通信契约，不重复实现 RAG 引擎。OpenCode SDK 由另一个会话负责底层智能编排，本模块只提供可调用的查询服务契约。现有主项目的前端和共享后端保持不变。

## 2. 技术选型

| 能力 | 选型 | 原因 |
| --- | --- | --- |
| 知识库和检索底座 | RAGFlow，自部署 GitHub 项目 | 官方仓库提供文档解析、RAG、Agent 能力、Docker 部署和 HTTP 接口，适合复杂 PDF 与引用场景 |
| 检索模式 | RAGFlow Hybrid Retrieval；Agentic 编排由 OpenCode SDK 负责 | RAG 服务只返回来源证据；复杂问题的拆解、补检索和综合由独立 SDK 模块完成 |
| 本项目 RAG 模块 | 独立 FastAPI 服务 `code/rag-service` | 统一服务鉴权、知识库范围和证据契约，不侵入主项目 |
| 向量模型 | RAGFlow 配置外部 Embedding API | 不在本项目本地运行大模型；模型和向量维度在 RAGFlow 模型配置中固定 |
| 生成模型 | OpenCode SDK 调用 OpenAI-compatible LLM API | 使用现有中转站的低成本模型，具体模型名由 SDK 模块按实测选择 |
| 法规能力 | MCP 工具适配层，优先调用授权的北大法宝 API | 法规查询与普通业务知识库分开记录来源、授权和工具轨迹 |
| SDK | OpenCode SDK 由另一个模块负责 | 通过独立服务的 `/api/v1/query` 调用，不重复实现 SDK |

RAGFlow 和 Dify 都是成熟候选；当前选 RAGFlow 是因为本项目首先要解决复杂 PDF、表格、原文页码和证据定位。若部署验证发现模型协议或资源不匹配，再保留 Dify 作为 Workflow/API 备选，不同时维护两套底座。

## 3. 当前工作区已经落地的独立服务

服务目录：`code/rag-service/`，端口 `8010`。它不挂载到 `code/backend`，不修改 `code/frontend`。

- `GET /api/v1/capabilities`：能力探测。
- `POST /api/v1/query`：业务规则和项目设计资料查询，返回证据片段和来源元数据。
- `POST /api/v1/documents`：接收已授权文件，映射到 RAGFlow dataset 上传和解析接口。

初始化和资料入库命令在 `code/rag-service/README.md`：先运行不带 `--execute` 的 dry-run，再显式执行上传。`app/manifest.py` 是唯一资料白名单。

除 `/health` 外，接口都要求独立服务 Token。RAGFlow 未配置或没有证据时返回明确错误/警告，不生成假回答。详细模型见 `code/rag-service/app/schemas.py`。

## 4. 查询契约

查询请求：

```json
{
  "query": "提款用途需要哪些材料证明？",
  "scope": "business_rules",
  "top_k": 8
}
```

查询响应必须包含：

- `evidence`：片段、文件名、页码、分数和原文元数据；
- `warnings`：证据不足、冲突、权限过滤或外部服务失败。

审核 Agent 通过服务 Token 调用；任务级材料和法律法规暂不开放，分别等待主项目权限过滤和商业 API 的 MCP 授权适配。服务 Token 只能由可信后端持有，不放进浏览器代码；前端应通过主项目后端代理通信。

## 4.1 试用 UI（业务人员视角）

`code/rag-service` 附带的 `/ui` 试用页面面向业务人员，不是技术控制台：

- 前端**不展示、不要求填写**：服务 Token、知识库范围（scope）、top_k —— 这些属于后端与内部配置。
  Token 由服务端渲染 `/ui` 时注入为页面内变量（不显示、不写入 localStorage），生产环境应由主项目后端代理，浏览器不接触 Token。
- 交互：顶部居中搜索框；文件导入为「拖拽或点击上传」区域；结果以卡片展示（正文 + 来源文件 + 相似度）；底部列出已入库文档。
- 上传与查询的默认范围由后端决定：上传默认 `business_rules`，查询默认 `all`（同时检索 `business_rules` + `project_design` 并合并去重、按相似度排序）。
- OCR 是外部 API：RAG 服务通过 `OCR_BASE_URL` 调用队友 `code/ocr_demo` 的 `/ocr/file`，本地不安装 OCR 模型；OCR 服务不可用且文件为图片时，回退到百炼视觉 OCR 兜底。

## 5. 业务资料知识库

旧资料源目录已盘点，但其中 `04设备API等文件` 含 API Key、数据库和 ECS 登录信息，**整个目录禁止进入知识库**。安全资料范围、排除规则和迁移建议见 [知识库资料清单](knowledge-base-manifest.md)。

当前建立两个 RAGFlow dataset，第三类资料暂不开放：

1. `business-rules`：贷款文件比对要求、贷款用途、业务规则和术语。
2. `project-design`：需求文档、方案、会议结论、系统时序图和当前接口文档。
3. `task-documents`：任务上传的脱敏单据，待主项目完成 `task_code` 权限过滤后再接入。

法规内容单独走 `law` scope，不和内部业务材料混在同一个集合，避免引用来源和权限边界不清。

## 6. 今天的完成边界

本轮可以在当前仓库完成：

- RAGFlow 选型和部署配置规划；
- 安全资料清单与知识库元数据规范；
- 独立 FastAPI 查询、文件导入、能力探测接口；
- 与主项目隔离的 HTTP 通信契约；
- Agent SDK/MCP 的调用边界和响应契约；
- 启动接口文档和本地静态验证。

需要外部条件才能完成的部分：

- RAGFlow Docker 服务实际启动和 dataset 初始化；
- Embedding/LLM 中转站地址、模型名、维度和密钥配置；
- 北大法宝商业 API 的授权协议、接口文档和 MCP 适配；
- 真实业务资料上传到外部服务前的脱敏与合规确认。

官方 RAGFlow 部署固定为 `v1.0.0-rc2`，脚本位于 `code/rag-service/scripts/deploy-ragflow.ps1`。当前机器未检测到 Docker，因此本轮已完成可执行部署脚本，但没有虚构“RAGFlow 已启动”。

北大法宝账号只可通过本机临时环境或密钥管理器注入，不能写入 `.env.example`、Markdown、日志、代码或 Git。当前不自动登录、不抓取网页、不绕过商业 API 授权。

## 7. 验收标准

- 上传一份脱敏业务 PDF 后，能提交索引并返回 RAGFlow document IDs。
- 查询结果至少返回一条可定位到来源文件的证据，并保留 RAGFlow 原始位置元数据。
- 复杂问题的 Agentic 编排由 SDK 模块负责，并继续使用本服务的证据契约。
- 证据不足、RAGFlow 不可用或法规 MCP 未配置时，前端显示明确状态，不生成肯定性结论。
- 审核 Agent 只能获得当前任务和授权知识库范围，不能越权检索其他任务材料。
- 规则引擎结论仍由确定性规则负责，RAG 只提供证据和解释。

## 8. 官方项目参考

- [RAGFlow](https://github.com/infiniflow/ragflow)
- [RAGFlow 本地 Docker 配置](https://github.com/infiniflow/ragflow/tree/main/docker)
- [Dify](https://github.com/langgenius/dify)
- [Model Context Protocol reference servers](https://github.com/modelcontextprotocol/servers)
- [OpenCode](https://github.com/anomalyco/opencode)
