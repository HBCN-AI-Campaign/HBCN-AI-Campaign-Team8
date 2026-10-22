# RAG 优化第三轮：法宝多源接入与专用重排契约

> 对应 R05/R06/R07/R15/R17 部分实现。服务源码与真实烟测已有证据；共享服务尚未切换，专用重排模型未部署，整体质量验收未完成。

## 这轮改变了什么

北大法宝适配器复用官方 `mcp==2.3.0`，实测协商协议 `2025-11-25`。按实际 tools/list 保存去除描述性文字的输入/输出 schema，只调用 `search_article` 和 `get_article`；工具目录最多三页/100 个条目，重复游标、缺失或重复工具名、结构变化均拒绝继续。输入/输出均按复核后的 JSON Schema 校验，不把服务描述、资料文字或额外工具转成执行权限。

`search_article` 真实参数为 text、可选筛选字段和 size；本实现每次最多取 3 条，不默认过滤成“现行”以免误答历史时点问题。记录法规 ID、文号、时效性、机关、日期、来源链接、获取时间和契约 hash；这些是来源声明，适用性仍为未核验。

正文为空时不据标题生成规则。`get_article` 必须提供 title 和 number，不能按 gid 获取整部法规；仅当问题明确含条号时，最多补取 2 次，并核对 ID、标题、文号及日期/时效性无冲突。没有已知条号时记录正文缺口；不猜“第一条”，不声称已读全文或核对附件。每次连接/调用共享默认 30 秒预算，无无限重试；异常不回显提供方响应或凭证。

## 多源归并与调用边界

`/api/v1/retrievals`、`/answers`、`/answers/stream` 增加 sources，默认 `["knowledge_base"]`，需要法宝时显式传 `["knowledge_base","pkulaw"]` 或 `["pkulaw"]`；法宝仅允许 law/all 范围。除查询表达外，不向法宝转发会话、知识库原文或上传文件。服务端仍须先配置并启用法宝；普通请求不会因为机器有桌面 MCP 配置就自动外发。

每轮法宝最多一个查询，优先通用表达；默认整次最多两次外部查询。先各来源内部做查询族归并，再以来源排名做跨源 RRF，保留各层分数与来源信息。来源分数不直接相加为相似度，不按本地四个同义词对外部一条结果堆叠投票。实体级同法规跨源对齐、规范依据/历史案例配额和冲突消解尚未完成。

响应新增 source_status、rerank_status；法宝部分结果、不可用、超时或范围受限明确返回。请求了外部依据而正文未完整取得时，不允许模型单方面声称充分；纯证据接口可返回部分支持片段和 missing，供调用 Agent 决定补查或人工处理。

## 独立重排的实际状态

已接入文档化的 Cohere-compatible Rerank HTTP 契约，在跨源归并后、充分性判断前调用。校验全部候选索引一一对应、有限且在范围内的分数；保留 RRF/provenance，不把 rerank 分当法律适用性或审批概率。响应大小、时间与候选数有预算；连接/映射失败显式报告，不静默冒充重排完成。

当前没有已确认的专用模型服务，因此默认 `RAG_RERANK_PROVIDER=disabled`，真实联合烟测也明确为 disabled。远程数据流需服务端 `RAG_RERANK_ALLOW_EXTERNAL=true`；默认只允许本机端点。Cohere-compatible 指接口形状，不表示选用或已获准向 Cohere 发送业务资料。模型版本未知会标记 unverified；服务的 token 截断可能性仍标记 not_verified，必须通过真实模型与长文档验证，不能据此确认读过全部输入。

资源候选：比较获授权的托管重排、在汇丰资源部署多语言专用模型（如 BGE 系列）及本地部署。最终以独立金融题集的排序收益、长文档覆盖、时延、成本与数据流向选择，不能因现有设备或现有 API 暂无重排就宣布无需重排。目前完成的是接口/失败机制，不是模型质量验收。

## 实际证据

| 项目 | 结果 | 证明边界 |
| --- | --- | --- |
| 官方 SDK 真实发现 | 两个白名单工具及 schema 已核对；协议 2025-11-25 | 不代表其他八个服务已集成 |
| 实际 search_article 单适配器验证 | partial；1 条正文证据（121 字符），元数据命中无正文被隔离；来源 URL 合法；约 1.78 秒 | 服务返回会变化；未实测 get_article 补取，不代表法效/附件核验 |
| 实际知识库＋法宝＋SDK 联合烟测 | 两来源均参与；最终 5 片段，source_status 为知识库 ok/法宝 partial，evidence_status insufficient，missing 1，未生成答案 | 使用当前 vector 模式；独立重排 disabled；不代表 hybrid＋rerank 全链路通过 |
| 同次联合烟测时延 | 48.67 秒，1 轮 | 包含数据库、实际 Embedding/SDK 与 MCP 调用；单样本不是 P95 或费用验收 |
| 自动回归与启动 | 显式启用 HBCN_TEST_POSTGRES=1 后全回归 89 项：88 通过、1 外部语料测试跳过；pip check 通过；隔离 uvicorn 启动与鉴权通过 | Mock 契约不替代真实无效凭证、配额、长文和 UI 验收 |

验收临时从用户已配置的桌面服务读取凭证，仅在进程内注入并清空，不打印或持久化，不把这条验收路径做成 RAG 运行依赖。服务仍只认服务端环境配置。没有保存法宝正文缓存或导入外部结果；验收摘要存 ignored data 目录。真实 SDK/Embedding/MCP 调用已发生，具体费用待账单确认，不声称免费。

复现命令（在 `code/rag-service` 使用虚拟环境 Python）：`python -m unittest discover -s tests -q`；实际 PostgreSQL 测试需先显式设置 `HBCN_TEST_POSTGRES=1`，使用随机合成 schema 并清理。`python scripts/smoke-isolated-api.py` 可无模型费用核对启动、OpenAPI、来源/重排契约和鉴权，且不初始化共享数据库。

## 依赖、复审与下一步

- MCP SDK v2 需要 Pydantic≥2.12，本轮固定为 2.12.5，并固定 sse-starlette 3.0.3 保持现有 FastAPI/Starlette 兼容；实际依赖检查与全回归须通过。SDK 及 jieba 为 MIT，JSON Schema 验证复用 jsonschema。
- 复审发现 get_article 无整法 gid 获取能力、目录需要有界分页、不同法规版本不能拼正文，均已落实保护与测试。
- 仍未确认法规存储/缓存/展示的商业边界；目前仅按用户授权做实时查询，不自动创建长期外部正文库。
- 长片段在现有 SDK runtime 仍有 4000 字符截断，必须进一步做可追溯窗口与覆盖管理，不能用本轮短片段烟测宣称长文已解决。
- 下一轮继续专用模型部署/对比条件、可追溯原文窗口、法规适用性与引用支持检查；之后推进真实 UI、历史案例/记忆治理与独立保留题集。整体持续目标保持执行中。

依据：[官方 MCP SDK transport](https://py.sdk.modelcontextprotocol.io/client/transports/)、[Cohere Rerank 契约](https://docs.cohere.com/reference/rerank)、[BGE reranker 官方模型说明](https://huggingface.co/BAAI/bge-reranker-v2-m3)、[既有法宝交接](PKULaw-MCP接入说明.md)。
