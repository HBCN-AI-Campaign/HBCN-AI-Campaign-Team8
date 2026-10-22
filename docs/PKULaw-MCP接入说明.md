# 北大法宝 MCP 接入说明

更新日期：2026-10-21（北京时间）

本文保留最初 MCP 交接语境；2026-10-22 当前状态以 [RAG 总览](../code/rag-service/README.md)及[第三轮验证](RAG优化第三轮验证记录.md)为准：RAG 已有官方 SDK 只读适配，search_article 与知识库/SDK 联合烟测通过，默认关闭；get_article 只有契约测试，尚未真实调用。以下“尚未集成”仅指最初交接时点。

## 已验证状态

- 本机提供的 Token 已对 9 个北大法宝 MCP HTTPS 地址完成 MCP `initialize` 请求，均返回 HTTP 200。
- `mcp-law-search-service` 已完成 `tools/list`，确认提供 `search_article`（语义检索法条）与 `get_article`（按法规标题和条号获取法条内容）。
- 已实际调用 `search_article` 查询“商业银行办理境外贷款业务应遵守哪些审慎经营和风险管理要求？”，返回 3 条结果，含法规名称、文号、时效性、效力位阶、制定机关、日期和链接；其中两条含有条文正文，第一条正文为空。
- 这证明当前 Token、网络和该查询工具可用。初始化成功不代表每条检索结果都有正文，也不代表法规适用性已完成法律核验。
- 当前验证是直接对北大法宝 MCP 服务发请求；RAG 后端代码尚未集成 MCP 客户端，Codex 本机 MCP 配置也不等于 RAG 服务自动获得调用能力。

测试结果示例：

| 法规 | 文号 | 返回情况 |
| --- | --- | --- |
| 中国人民银行、国家外汇管理局关于调整银行业金融机构境外贷款业务有关事宜的通知 | 银发〔2026〕72号 | 现行有效；搜索结果未返回正文；[北大法宝](https://pkulaw.com/chl/c7f677e5d8adb68fbdfb.html) |
| 中国银监会关于进一步加强银行业金融机构境外运营风险管理的通知 | 银监发〔2016〕5号 | 现行有效；返回贷款“三查”等正文；[北大法宝](https://pkulaw.com/chl/194ce7ac1937f297bdfb.html) |
| 中国银监会关于规范银行业服务企业走出去加强风险防控的指导意见 | 银监发〔2017〕1号 | 现行有效；返回尽调、授信及贷后管理等正文；[北大法宝](https://pkulaw.com/chl/c988a3c08599420bbdfb.html) |

## 9 个 MCP 服务

| Codex 服务名 | HTTPS URL | 用途（按服务名） |
| --- | --- | --- |
| `pkulaw-law-search` | `https://apim-gateway.pkulaw.com/mcp-law-search-service` | 已发现两工具；真实调用 search_article，get_article 仅契约验证 |
| `pkulaw-law-keyword` | `https://apim-gateway.pkulaw.com/mcp-law` | 法规关键词检索 |
| `pkulaw-case-semantic-search` | `https://apim-gateway.pkulaw.com/mcp-case-search-service` | 案例语义检索 |
| `pkulaw-case-keyword` | `https://apim-gateway.pkulaw.com/mcp-case` | 案例关键词检索 |
| `pkulaw-law-item-keyword` | `https://apim-gateway.pkulaw.com/mcp-fatiao` | 法条关键词检索 |
| `pkulaw-law-recognition` | `https://apim-gateway.pkulaw.com/law_recognition` | 法规识别 |
| `pkulaw-case-number-recognition` | `https://apim-gateway.pkulaw.com/case_number_recognition` | 案号识别 |
| `pkulaw-citation-validator` | `https://apim-gateway.pkulaw.com/pku_citation_validator` | 引文校验 |
| `pkulaw-doc-link` | `https://apim-gateway.pkulaw.com/add-doc-link` | 文档链接处理 |

本机 Codex 配置位于 `C:\Users\<用户名>\.codex\config.toml`，密钥通过 `Authorization: Bearer <token>` 传递。Token 属于凭证，不得写入仓库、日志、截图、验收报告或前端代码。若 Token 曾出现在聊天、工单等非密钥管理位置，应先撤销并重新签发，再更新运行环境中的密钥。

配置的是运行 Codex 的那个环境。当前本机 Codex 重启后可使用这些 MCP；ECS 上运行的 RAG 服务不会读取本机 `config.toml`，也不会因为 ECS 可以 SSH 跳转而自动拥有北大法宝调用能力。

## RAG 后端接入约定

后续由 RAG 模块负责人实现远端 MCP 客户端适配，不要让浏览器直接请求北大法宝，也不要把 Token 发到 React。建议边界如下：

1. 在 RAG 后端配置服务端密钥，例如 `PKULAW_MCP_TOKEN`；只通过部署环境的密钥管理/忽略的本地 `.env` 注入，`.env.example` 只放空值或变量名。
2. 配置 `PKULAW_MCP_LAW_SEARCH_URL=https://apim-gateway.pkulaw.com/mcp-law-search-service`。按 MCP Streamable HTTP 协议发送 `initialize`，协商协议版本，再调用 `tools/list` 和 `tools/call`；不要把 MCP JSON-RPC 当成普通 REST 查询端点。
3. 境外贷款法规问题优先调用 `search_article`，按需用 `get_article` 补齐正文。将服务返回的法规标题、条号、正文、文号、时效性、效力位阶、制定机关、日期和原始 URL 保留为结构化证据与引用来源。
4. 若搜索命中但 `article` 为空，按工具契约补查，仍无正文则明确标注“仅检索到元数据/正文未取得”，不要据标题生成法规要求。
5. RAG 回答应区分本地已导入语料与实时北大法宝证据，保留来源 URL 和查询时间；法规现行状态、适用范围、修订废止、附件完整性仍需按业务流程复核，不把 MCP 检索结果直接转成自动审批结论。
6. 加超时、错误与限流处理；未授权/过期 Token、网络不可达、工具错误或结果为空时明确返回外部检索不可用/证据不足，不静默降级为本地语料已覆盖。

当前只有 `pkulaw-law-search` 完成真实 `tools/list` 和查询调用。其余 8 个地址已完成初始化连通性检查，但尚未逐个核对工具 schema 或执行业务查询。服务配额、商业授权范围和允许的存储/缓存/展示方式，应以团队签署的北大法宝授权条款为准；Token 可用本身不能替代授权范围确认。

## 验收步骤

RAG 集成提交后至少验证：有效密钥能初始化并发现工具；`search_article` 返回结构化法条证据；无正文命中会被补查或安全标注；无效密钥/超时会产生可解释错误；前端及日志中不出现密钥；引用保留原始 URL、法规元数据和查询时间。
