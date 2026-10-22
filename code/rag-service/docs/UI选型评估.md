# RAG 工作台 UI 选型评估

评估日期：2026-10-20

## 结论

当前保留 `code/rag-service/ui` 作为独立、轻量的业务工作台：负责资料导入、范围筛选、文档状态和检索证据验证；通过本服务稳定的 HTTP API 工作，不依赖主项目 `code/frontend`，也不让浏览器直接持有 RAGFlow 管理凭据。这个页面是本地引擎的资料管理/检索验证入口，不冒充完整问答或 Agent 控制台。

实现上优先复用现有 Vue 3、Element Plus 和图标库控件，不另造表格、上传器、表单控件或 Markdown 渲染器。参考成熟产品的信息架构，但不复制整套产品前端：它们的路由、登录、权限、数据模型和 API 都与各自后端耦合。若后续要求可视化切分调优、数据集配置、模型管理和完整运营控制台，应直接部署/使用 RAGFlow 原生工作台，而不是在本 UI 内重造这些能力。

## 开源方案比较

| 项目 | 官方能力与 UI 借鉴点 | 对本项目的适配判断 |
| --- | --- | --- |
| [RAGFlow](https://github.com/infiniflow/ragflow) | 原生数据集和文档管理、解析配置、分块结果查看与人工修订、检索测试及可追溯引用；本项目正式引擎也使用其 API。 | 最适合作为完整 RAG 运营控制台和交互参考。但它是完整服务，不是可直接嵌入本项目的 UI 组件；运行还需要 Docker 等配套服务，官方 Quickstart 推荐起步配置为 4 核、16 GB RAM。当前工作台保持轻量，复杂数据集操作交由其原生 UI。 |
| [FastGPT](https://github.com/labring/FastGPT) | 有知识库管理、分块编辑、单点检索测试、引用和工作流；支持通过 API/iframe 集成应用。 | 完整 Next.js 平台，适合直接采用其后端和运营界面；不是当前 FastAPI/RAGFlow 协议的可插拔 Vue 页面。仓库采用 FastGPT Open Source License，有商业使用和 SaaS 条款，集成前需单独审阅。 |
| [Dify](https://github.com/langgenius/dify) | 完整 LLM 应用平台，包含知识库/RAG 流程、模型管理、工作流、应用 API 和观测能力。 | 适合建设独立的 LLM 应用平台，不适合作为本服务的可嵌 UI；引入会扩大部署与权限边界，也与另行负责的 Agent SDK 模块重叠。项目采用带附加条件的 Dify Open Source License，需先评估分发/商用条款。 |
| [MaxKB](https://github.com/1Panel-dev/MaxKB) | Vue 前端的完整知识库与智能体产品，支持文档导入、工作流和问答。 | 产品形态接近，但 UI 与 Django、存储和工作流实现绑定；仓库为 GPLv3。换用会替代而非补充当前服务边界，并引入不同的许可证义务。 |
| [AnythingLLM](https://github.com/Mintplex-Labs/anything-llm) | MIT 全栈产品，提供工作区、文档导入、引用、开发者 API；官方 embed 项目提供网站聊天小组件。 | 可将聊天小组件嵌入网站，但它不提供可复用的知识库管理界面；embed 仍需要 AnythingLLM 后端、workspace/embed ID 和相应访问控制，无法直接管理本服务的文档或调用本服务检索 API。 |
| [Kotaemon](https://github.com/Cinnamon/kotaemon) | Apache-2.0、Gradio 构建的可定制文档问答 UI；示例有文件集合、聊天、PDF 预览、引用页码和命中高亮。 | 比一般全栈控制台更易改造，但其扩展点是 Python/Gradio 的 RAG pipeline，不是可嵌入 Vue 的 UI 包。改用它会引入另一套 UI 服务器、身份与 pipeline；本项目借鉴文件集合和引用预览信息架构，不接管 RAG 服务。 |

项目自身也有成熟的 UI 基线：[主项目样式](../../frontend/src/styles.css) 使用浅灰画布、蓝色主色与 Element Plus；[助手页](../../frontend/src/views/AssistantView.vue) 用分栏展示会话、回答和引用。RAG 子模块延续相同组件与主色，但保持独立构建和 HTTP API，不从主前端跨目录导入组件或修改队友页面。

## 交互决策

- 工作台默认进入“知识文档”；文档、知识范围、索引状态、检索测试是一级任务，避免先进入聊天页或平台配置页。
- 导入前清楚显示目标知识范围、后端允许的扩展名和单文件限制；提交状态与“已完成索引”严格区分。
- 检索测试展示来源文件、范围、原文和原始检索分值；不把向量/检索分数格式化成百分比，避免被误读为置信概率。明确声明证据不是审核结论，不生成当前 API 契约未提供的答案。
- 一级导航使用原生按钮语义，桌面和移动端都能用 Tab/Enter 切换；上传、范围和检索仍复用 Element Plus 控件。
- 移动端将文档表格收敛为单列摘要，导航固定在底部；避免页面横向滚动。
- 权限与认证不在前端模拟：本机 UI 使用服务端短期 HttpOnly 会话；其他调用方通过服务 API 认证。

## 当前实现与验收

当前 UI 使用 Vue 3 + Element Plus，与主项目 `code/frontend` 分离；接口只调用 RAG 服务公开的 capabilities、documents、query 等端点。已在 320、390、768 和 1280 px 宽度复核，无页面横向溢出；320 px 下底部导航与最后一条证据相隔 38 px。键盘 Tab 可到工作区导航、问题输入和提交按钮，Enter 可提交检索。浏览器实测中，临时隔离 SQLite 通过真实文件选择器导入合成 TXT，生成 2 个索引片段，查询命中同一来源；不支持的 EXE 显示明确错误且文档数不变；空知识范围返回 0 条并显示“不应据此生成确定性审核结论”的提示。证据卡折叠/展开和列表/检索切换也已实测。此前在另一个独立临时服务/SQLite 中，已导入仓库自动生成的 `demo_scan.pdf`、`demo.docx` 和 `demo.xlsx`：扫描 PDF 走本机 PaddleOCR，三种格式均调用百炼 `qwen3.7-text-embedding-flash` 并可检索到引用；Excel 查询命中对应工作表和营业收入行。OCR 期间并发刷新 API 在约 1.3 秒内完成。所有 E2E 测试使用临时服务与存储，完成后已清理；未写入现有 8011 业务库，单样例检索分数不用于评估召回质量。

继续试用时重点检查：

1. 新用户是否能不看说明就找到资料导入、范围选择和检索入口。
2. 上传、格式/大小拒绝、解析中、失败和可检索状态是否容易区分。
3. 检索证据是否足以回到原文件，且长表格/长文本不会破坏页面布局。
4. 继续人工检查屏幕阅读器公告、空数据、离线、引擎未就绪和小屏上的完整上传流程。
5. RAGFlow 引擎的真实上传/解析仍待验证；当前本机未配置 RAGFlow URL、API Key 或数据集 ID，且未安装 Docker。PDF/Office 的本地 OCR + Embedding 链路已用仓库生成样例验证。
6. 本次检索表单把范围与证据条数改成独立控件组；检索分显示两位小数，不再显示百分比。主色已对齐主项目的低饱和蓝，错误状态保留红色；一级导航用原生按钮保证 Tab 可达。RAGFlow 真实实例的上传/解析验收仍受缺少实例配置限制。

## 官方资料

- [RAGFlow GitHub](https://github.com/infiniflow/ragflow)
- [RAGFlow Quickstart](https://ragflow.io/docs/)
- [FastGPT GitHub](https://github.com/labring/FastGPT)
- [Dify GitHub](https://github.com/langgenius/dify)
- [MaxKB GitHub](https://github.com/1Panel-dev/MaxKB)
- [AnythingLLM GitHub](https://github.com/Mintplex-Labs/anything-llm)
- [AnythingLLM Embedded Chat Widget](https://github.com/Mintplex-Labs/anythingllm-embed)
- [AnythingLLM API](https://docs.anythingllm.com/features/api)
- [Kotaemon GitHub](https://github.com/Cinnamon/kotaemon)
