# RAG 模块联调验收 · 2026-10-22

本轮目标：交付 AI 模块可以通过 HTTP 调用的独立知识库服务，并完成接入文档。工作基于 `lfc`；本轮只提交 RAG 模块文件，不提交主站助手、主业务后端、队友工作区改动或真实资料，不合入 main。

## 结论和实际环境

**本机真实链路已跑通，汇丰服务器常驻 RAG 尚未部署。** 本机入口 `http://127.0.0.1:8012`，API 页面 `/docs`，React 工作台 `/ui/`。同事跨机器调用需部署方提供实际私网/HTTPS 地址，不能使用这一本机回环地址。

| 部分 | 本轮实际使用 |
| --- | --- |
| RAG | 本机 Windows、Python 3.12、FastAPI，服务 0.5.0 / HTTP 契约 1.3.0 |
| 数据库 | 汇丰 PostgreSQL、pgvector 0.8.0.2，独立 schema `hbcn_rag_release_v050`，1024 维向量；当前服务 `search_mode=vector` |
| 模型 | 实际 Embedding `qwen3.7-text-embedding-flash`；已配置的 OpenCode SDK runtime / `qwen3.8-flash`，协议 2 |
| 网络 | 本机通过已有受控 SSH 连接访问数据库和汇丰服务器上的已运行 runtime；没有新增服务器 RAG 实例或改动其他服务 |
| 原件 | 本机 `data/release-v050/originals/`；旧 schema 与旧原件保留 |
| 可选能力 | 法宝、专用 reranker、网页快照、案例/经验接口本次未启用，不计作当前链路通过 |

源码修复：此前 RAG 调用 `/runs` 缺少 `assistant_protocol=2`，会被当前 runtime 拒绝；现已补齐。就绪检查改用带鉴权的 `/readyz` 并校验协议，避免仅凭存活接口把不兼容的运行时报告为就绪。没有更改主站业务逻辑。

## 验证结果

| 检查 | 结果与范围 |
| --- | --- |
| 全量 RAG 回归 | `python -m unittest discover -s tests -q`：202 项，189 通过、13 按配置跳过 |
| 真实 PostgreSQL 混合机制 | `HBCN_TEST_POSTGRES=1 python -m unittest tests.test_hybrid_retrieval -q`：3 项通过；使用随机合成测试 schema，验证 FTS/混合/生命周期后清理；不表示当前服务已切 hybrid |
| React UI | 17 项测试通过；TypeScript 检查及 Vite 生产构建通过；打包体积警告保留，未做额外细节优化 |
| OpenAPI | `python scripts/export-openapi.py --check` 通过，HTTP 契约未变 |
| Python 依赖 | `python -m pip check` 通过 |
| 隔离启动 | `python scripts/smoke-isolated-api.py` 通过，覆盖启动、health/docs/OpenAPI、鉴权与契约；此项使用合成依赖 |
| 真实 HTTP/模型链路 | 以下 16 项全部通过；总时长 235.49 秒，包含入库、多次检索和答复，不是单次查询延迟指标 |

真实 HTTP 验收通过项：

1. 存活接口。
2. 无 Token 请求被拒绝（401）。
3. 实际数据库/模型运行时就绪（200）。
4. 在线 OpenAPI 存在增强检索入口。
5. 合成文档上传（202）。
6. 实际解析、Embedding、索引后变为 ready。
7. 原件下载 SHA256 与上传内容相同。
8. 兼容 `/query` 能命中该原文。
9. `/retrievals` 调用成功。
10. 增强检索返回该原文证据，实际状态 sufficient、1 轮。
11. 证据接口不混入最终 answer。
12. reader 定位内容包含所选原文窗口。
13. `/answers` 实际模型答复成功。
14. 答复带该资料引用，grounding=cited、verification=supported_by_model。
15. 增强入口拒绝 task_documents 越界范围（422）。
16. 合成资料撤回后原件接口拒读（404）。

复现：`python scripts/verify-module.py --base-url http://127.0.0.1:8012 --write-fixture --report data/module-acceptance-20261022.json`。明确允许后才创建/撤回合成资料并调用付费模型；报告只记录检查/标识，不记录凭证和业务正文。合成资料明确声明不是银行业务规则，不进入业务范围。

`supported_by_model` 是本次模型复核结果，不是人工正确性金标或贷款审批结论。本轮未对扫描件准确率、法规适用性、真实审核任务准确率作通过声明。

## 旧库与业务资料

旧 `hbcn_rag` 中有 10 份 ready 缺新版本质量报告、另 1 份 failed。当前质量策略会排除这 10 份；旧库入口返回 503/degraded 属于真实迁移问题，不能通过关闭门禁来宣布跑通。

本轮将原有 4 份业务资料和 2 份法规 PDF 的原件按相同 SHA256 重新提交到独立 schema/目录，未复制旧质量批准。法规两份均进入 `quality_review`，原因是 PDF 图像或 OCR 层未经原文复核；当前不可检索，需独立 reviewer 流程后才能放开。

| 资料 | 实际状态 | 可检索片段 |
| --- | --- | ---: |
| FOL 贷款用途（流贷+固贷）.docx | ready | 11 |
| 贷款用途常见描述.xlsx | ready | 18 |
| 贷款文件比对要求.xlsx | ready | 12 |
| 贷款文件比对要求- V2 20261013.xlsx | ready | 18 |
| cn-overseas-loan-banks-2022.pdf | quality_review | 0 |
| cn-overseas-loan-banks-2026-72.pdf | quality_review | 0 |

真实英文问题 “What are the permitted uses of working capital loans and fixed asset loans?” 通过 `/query` 返回 5 条真实业务证据。中文“流动资金贷款和固定资产贷款的用途限制分别是什么？”通过 `/retrievals` 命中 FOL 与文件比对要求，但在 `top_k=5` 时返回 `insufficient/evidence_budget`：完整所选依据超过5条，不能将部分证据包装为充分。该边界必须由调用方保留；增强接口最大 top_k=8，不是旧 `/query` 的20。

**综合业务增强检索尚未验收通过。** 同题 `top_k=8` 的最后一次核对在116.28秒内返回 `insufficient/assessment_unavailable`，20个候选窗口未完成模型核对，0条已核对输出，不能当成“没有相关规则”。该次 runtime 返回空答复；只读核对其配置为单次45,000毫秒，而 RAG 单次允许90秒。预算不同是需要部署方协调的依赖条件，当前未取得上游失败原因证据，不能把本次失败直接归因为超时。没有改动共用助手 runtime，也没有自动重试或降低质量标准。部署交接需对齐 RAG 专用 runtime 的预算并复验这一明确失败题；本轮停止追加重复验证，不宣称全部业务题通过。

原始无正文报告在忽略目录 `data/module-acceptance-20261022.json`、`data/release-v050/business-retrieval*.json`、`data/release-v050/document-states.json`；导入映射保留新旧 document id 与原件 hash，均未提交 Git。本轮旧库临时检查进程已停止，保留新库8012实例供本机联调。

## 交接与未验收范围

AI 模块接入看 [INTEGRATION.md](INTEGRATION.md)，完整字段见 [API_CONTRACT.md](API_CONTRACT.md)，服务器部署见 [deploy/README.md](deploy/README.md)。调用方只需服务地址、Token 和 HTTP 契约；问题改写、模型、索引等更新留在 RAG 内部。

本轮未完成：汇丰服务器的 RAG/systemd 或容器实际部署、重启/备份恢复、目标网络/负载验收、主站真实 UI 和任务权限、业务金标评测、法规待复核资料、当前法宝/专用 reranker/网页多源联合链路。服务器已有 runtime 可达，不能由此推断 RAG 部署完成。

主站助手回归在本轮早期检查时有旧 mock 边界不匹配、同步/异步 httpx 测试适配问题；相关文件同时由其他工作修改，本轮没有改动或包含它们。独立 RAG 可调用不等于主站助手联调通过，主站应在对应版本稳定后单独复验。
