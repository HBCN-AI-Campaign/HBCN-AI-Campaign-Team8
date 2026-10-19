# RAG 工作台 UI 改版交接

> 面向下一位 AI 实施者。本文记录 UI 调研结论、确定的设计方向、当前接口边界和验收要求。此文档本身不代表 UI 改版已经实施。

## 目标

改造 `code/rag-service` 内的独立 RAG 工作台，让业务人员能够导入并管理审核资料、检查索引状态、验证检索结果及其证据来源。工作台是 RAG 服务的管理与检索测试工具，不是主产品前端，也不负责生成审核结论。

## 已确定的设计方向

采用 **Dify 式知识库管理 + Kotaemon 式证据核查**：

- 文档管理作为默认入口，以清晰、可筛选的资料列表为主，不采用聊天首页。
- 检索测试单独成页，展示问题、知识范围、召回片段、来源文件和相关度；证据应容易核查。
- 参考 RAGFlow 的解析状态与分段质量检查思路，但控制配置密度，不复刻完整运维控制台。
- 视觉采用柔和、明亮、专业的浅色工作台；以白/浅灰为底，汇丰红少量点缀。避免大面积红色、营销型首屏和无业务意义的装饰卡片。
- 侧栏或顶部导航保持简短；使用表格、筛选、状态标识和清晰的空/加载/失败状态支撑重复性操作。

这是基于模块职责作出的实施基线；除非发现实现约束实质冲突，不需要重新发起同一轮方向选择。

## 参考产品

- **Dify**：文档列表、状态/范围管理、分段管理与独立检索测试。适合作为资料管理主视图参考。[官方知识内容管理文档](https://docs.dify.ai/en/self-host/use-dify/knowledge/manage-knowledge/maintain-knowledge-documents) · [GitHub](https://github.com/langgenius/dify)
- **Kotaemon**：问答工作区将来源证据、相关度和文档预览纳入核查流程。只借鉴证据呈现，不照搬聊天产品定位。[GitHub 与界面预览](https://github.com/Cinnamon/kotaemon) · [用户指南](https://github.com/Cinnamon/kotaemon/blob/main/docs/usage.md)
- **RAGFlow**：可视化分段、文件解析与检索测试的思路。用于参考知识库调试能力，不照搬其复杂的工程配置台。[GitHub](https://github.com/infiniflow/ragflow)
- **Open WebUI**：知识集合、文件浏览和检索模式可作为补充参考。[知识库文档](https://docs.openwebui.com/features/workspace/knowledge/)

上述项目的实际界面预览已在此前调研中查看。若需要替换外部参考，优先查看对应官方文档/仓库，不以第三方 UI 汇总文章作为唯一依据。

## 当前模块边界

- RAG 服务目录：`code/rag-service/`。后端使用 FastAPI，独立于主项目 backend/frontend。
- 当前 UI 入口：`GET /ui`、`GET /ui/`，由 `code/rag-service/app/main.py` 提供，实际页面文件为 `code/rag-service/app/static/workbench.html`。
- 已有页面能力：业务规则/项目设计范围筛选、文件导入、文档列表、检索测试与证据片段展示。改版应保留这些业务能力，不要只做静态视觉稿。
- 可用 API：
  - `GET /api/v1/capabilities`：服务能力与引擎状态。
  - `GET /api/v1/documents`：已索引文档列表。
  - `POST /api/v1/documents`：单文件 multipart 上传，`scope` 支持 `business_rules` / `project_design`。
  - `POST /api/v1/query`：检索，返回 evidence、来源、相关度及 warnings。
- 本地 UI 通过同源请求访问 API。服务端仅对 loopback UI 签发短期 HttpOnly Cookie；页面不应读取、展示或要求用户粘贴 `SERVICE_TOKEN`。远程 API 的 Bearer 鉴权仍由后端处理。
- 当前接口未完整提供文档解析进度、原文件预览、独立 chunk 管理、删除/重命名等操作。不要在 UI 中假造这些数据或按钮；需要新增能力时先说明接口缺口，并将 API 增量限定在 `rag-service`，不得侵入主项目同学负责的代码。

## 改版实施边界

- 主要改动限定在 `code/rag-service/app/static/workbench.html`；如确有必要新增静态资源，也放在 `code/rag-service/app/static/`。
- 不要改 `code/backend/`、`code/frontend/`、队友的 mockup 或主项目流程；不要把 RAG 页面嵌入/覆盖其他同学的前端。
- 保持 RAG 服务的 HTTP 契约和本地 UI 会话行为稳定。不要把密钥、Token 写入 HTML、JavaScript、URL、截图或文档。
- 当前目录已有其他未提交改动。开始前检查 `git status --short`，只编辑本次 UI 必需文件，不清理、不覆盖、不提交队友的改动。
- `code/rag-service/README.md` 中仍有旧的“用户粘贴 SERVICE_TOKEN”说明；运行时 `/ui` 已采用本机自动会话。若改版时更新文档，只修正这处与现状冲突的说明，避免误导用户。

## 页面结构建议

### 1. 知识文档

- 页面标题和资料总数；提供“导入资料”主操作，范围选择清楚可见。
- 支持按文件名搜索和按 `全部 / 业务规则 / 项目设计` 筛选。
- 表格至少展示文件名、知识范围、索引片段数、可检索状态/引擎来源（以 API 实际返回字段为准）。
- 展示服务连接、加载中、空列表、导入中、导入失败、检索不可用等状态；多文件选择应逐项反馈。
- 避免将内部引擎配置和 Token 暴露给普通使用者。

### 2. 检索测试

- 提供问题输入、知识范围和 Top-K 控件。
- 结果区按相关度顺序展示证据；每条清楚标出来源文件、范围、页码（若 API 有值）、相关度和可读片段。
- 无结果时展示 API warnings/可操作提示，不生成或暗示审核结论。
- 原始材料可能包含 HTML、代码或长文本；展示前应安全转义并限制预览长度，完整内容可通过展开阅读，不能让证据卡片被超长片段撑坏。

## 视觉与交互验收

- 首屏直接进入可用工作台，不出现登录/token 输入口。
- 桌面视口信息密度适合持续管理文件；窄屏下导航、上传控件、表格和证据文本不重叠、不横向挤坏。
- 按钮、筛选、上传、加载、成功/失败、空数据状态均可交互且有明确反馈；不留下仅供展示的死控件。
- 颜色不过度依赖单一绿色或红色；汇丰红作为强调色，不以品牌色大面积铺满页面。
- 至少在桌面和窄屏浏览器中实测主流程：打开页面、筛选列表、上传一份资料、执行检索、查看来源证据。
- 不应在检索结果中渲染原始 HTML 标签、脚本内容或隐藏页面控件文本；不要因此改变用户原始文件。

## 建议验证

- 后端回归：在 `code/rag-service` 中运行 `python -m unittest discover -s tests`（如测试需要，按仓库现有交接说明设置 `HBCN_TEST_SOURCE_ROOT`）。
- 确认 `/ui/`、capabilities、documents、query 均使用当前本机会话正常请求；HTML 中没有 Token。
- 浏览器实际验证宽屏和移动/窄屏布局；用真实索引资料检查证据可读性和溢出。
- 改完汇报实际改动文件、验证结果及任何因 API 不足而暂未实现的交互。不要提交或推送，除非项目负责人之后明确要求。
