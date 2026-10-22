# RAG 网页上下文接入契约

> 2026-10-22；服务 0.5.0 / HTTP 契约 1.3.0。R05/R06/R08/R09/R15/R17 部分实现，默认关闭。复用现有 LangGraph、联合重排、原文窗口和支持核验，不新增通用 Agent 框架。

## 接入边界

调用方在已获授权的页面采集**实际文本**，经自己的后端授权后提交请求内快照。仅提供 URL、声称“已读取”、或把网页标题当全文均不可接受。本模块不代抓任意 URL，不操作浏览器，不下载页面附件，不把快照自动写入知识库/案例/长期记忆；真实浏览器采集与主站用户/任务权限仍需对应模块接线。现有 query 接口不接快照，新增消费者用 retrievals；独立问答可使用 answers 和 answers/stream。

网页是调用方声称的页面文本，不因 URL、时间或内容 hash 齐全就证明采集真实、全文完整或法规有效。服务端标 verification=caller_supplied_unverified、evidence_role=unverified_web_context，原始 URL 可能已变化。所选网页快照只供背景或网页内容参考；本案法规判断不会靠网页上下文变成充分依据。当前若 case_assessment 的所选证据含网页，会阻断确定性结论，保留参考片段和缺口；未来区分事实/规范的精细声明需另外评测，不能移除本门禁来追求通过率。

## 授权与配置

除既有服务 Bearer Token，还要求独立 `X-Web-Context-Key`。服务端配置如下（均默认未启用，不提交真实凭证/注册表）：

| 配置 | 要求 |
| --- | --- |
| RAG_WEB_CONTEXT_ENABLED | 默认 false；由部署负责人按数据授权启用 |
| RAG_WEB_CONTEXT_PRINCIPALS_FILE | 受控主体注册表；复用[主体格式](RAG案例与经验治理契约.md)，独立高熵 key 的 SHA256、精确 scope、reader 角色和有效期 |
| RAG_WEB_CONTEXT_ALLOWED_HOSTS | 逗号分隔精确 DNS 域名；无通配符/子域继承，不能把用户传来的域名直接加白名单 |
| RAG_WEB_CONTEXT_MAX_AGE_SECONDS | 默认 900，允许 60–3600；过期或未来快照要求重新采集 |

快照 scope 只能 business_rules/project_design/law，须被 reader 主体逐项授权；请求 all 不扩大权限。来源 URL 只接 HTTPS、默认 443，无用户名/密码或 query，拒绝 IP 字面量、本地域名和控制字符。需 query 才能定位的页面目前不能直接接入，应评审受控采集/定位方案；不静默剥离 query 导致引用指向另一页。没有网络抓取，因此不存在本适配器通过页面 URL 访问云元数据的路径；这也不等于已核实页面是否公开。

真实采集方负责验证最终页面/重定向来源、当前用户访问权、敏感信息筛除、允许发送模型/外部重排的范围以及授权撤销。processing_authorized=true 是调用方明确的处理授权声明，不能替代主站 ACL 或证明网页真实性。RAG_WEB_CONTEXT_KEY 只在受控调用后端使用，禁止下发浏览器；普通工作台没有采集/提交凭证入口。注册表、开关、域名和快照时效在模型使用证据及返回前重新核对；凭证不进入图 state、证据 metadata 或响应。

## HTTP 请求与证据

三个增强入口共用请求模型，显式 sources 含 web_context 且提交非空 web_context 数组，两者缺一则 422。每次最多 4 页，每页 text ≤40000 字符，合计 ≤160000 UTF-8 字节；超限拒绝，不截断。每份快照严格禁止额外字段，包含：

| 字段 | 语义 |
| --- | --- |
| url、title | 实际采集页面的允许地址和标题；不能由模型补造 |
| text | 实际选区或页面纯文本，不能传模型总结冒充原文；无效字符/空白/未映射字形拒绝 |
| captured_at | 带时区的实际采集时间，服务端归一 UTC；不自动用请求时间假装已采集 |
| scope | 经过调用方和服务端授权的知识范围 |
| completeness | selection 或 page_text；后者只是采集方声明页面文本，不保证附件/动态区域完整 |
| processing_authorized | 必须显式布尔 true，表示已确认本次模型/重排处理授权；false/缺失/数值 1 均拒绝 |
| language | 可选实际已知语言标签；未知留空，不让模型编造 |

请求示意（captured_at 必须替换为本次真实采集时间，示意时间不作为有效快照）：

```json
{
  "query": "页面怎样描述支付指令金额不一致的处理？",
  "scope": "business_rules",
  "sources": ["knowledge_base", "web_context"],
  "purpose": "reference",
  "web_context": [{
    "url": "https://approved.example.com/procedure#amount",
    "title": "实际页面标题",
    "text": "经授权采集的实际原文，不填入模型编写的示例规则。",
    "captured_at": "2026-10-22T12:00:00Z",
    "scope": "business_rules",
    "completeness": "selection",
    "processing_authorized": true,
    "language": "zh-CN"
  }]
}
```

独立 HTTP 示例 `code/rag-service/examples/retrieve.py` 新增 --web-context-file，读取上述快照数组 JSON；凭证从 RAG_BASE_URL、RAG_SERVICE_TOKEN、RAG_WEB_CONTEXT_KEY 环境获取，不导入内部 app、不自动采集时间、不跟重定向或重放超时请求。旧 query 模式拒绝快照，避免静默忽略。输入/输出可能含业务文本，只在受控终端处理，不能写公共日志。

未启用 404；未配授权/白名单 503；缺 key/到期 key 401；角色/精确范围/来源不符 403；快照过期或未来时间 409；输入格式/预算 422。处理期间授权变化时整个图以安全错误结束，不继续返回失效网页；SSE 可先收到步骤，不能据步骤当最终成功。响应 no-store，调用方使用结果前还需自己的权限/时效检查；无法收回已交付正文或供应商在途请求。

返回沿用 sources[]，document_id/chunk_id 由 URL+采集时间+正文 SHA256 绑定到 web: 版本，page=null、score=null、reader_url=null，source_url 为原页面。metadata 保留 captured_at/received_at、content_sha256、scope、language、capture_completeness 和未核实角色。长文窗口沿用父 hash 和字符区间，返回前校验内容确实对应请求快照，不伪造 PDF 页码/持久化原文接口。相同 URL 不同时间/正文保留为不同快照；完全重复提交拒绝。

## 多路归并与排序

知识库/法宝的有序列表继续查询族及跨源 RRF。网页快照是**无序上下文**，不塞进 RRF 冒充独立检索票数；原候选与最多 4 页网页共同组成最多 20 个父候选，再复用已配置的专用 reranker。原知识候选配额最多 min(3×top_k, 20−网页数)，随后所有候选一起进入原文分窗、联合覆盖与支持核验。是否出现在最终依据由核对决定，不为某来源强保最终席位。

专用重排模型未部署时仍报告 disabled；本轮没有真实排序收益结论。现有重排接口的长文 token 截断状态仍未验证，不能把排序完成当全文已读。原文窗口另有完整性预算和可见缺口。问题规划只用用户问题/用户会话，网页不会被伪装成已确认的用户事实；“这个 5000”缺业务背景时仍可要求澄清。

检索内容中的指令按不可信数据处理，仍需引用/短引和输出核验。[LangChain 官方 RAG 指南](https://docs.langchain.com/oss/python/deepagents/rag)明确说明提示词/分隔符不能可靠消除间接提示注入。本轮没有自动工具执行或网页发起的网络请求，也不宣称模型抗注入已全面达标；需要真实模型与对抗题集另验。

## 交付与剩余验收

本轮默认关闭，不创建表、不迁移旧库、不修改主站适配器或真实浏览器；部署方按本契约设置私网地址、独立主体、域名和模型数据流。对应[质量门禁升级](RAG文档质量门禁契约.md)与撤回回滚要求仍有效。

尚未完成：真实浏览器采集/页面主体证明、动态页面/附件完整性、主站用户/任务授权传递、生产撤权通知、网页关联法规版本、真实网页/KB/法宝联合重排质量、模型抗注入、云端时延/负载和回滚。按 T05/T06/T08/T09/T15/T17 继续验收，不能以合成接口测试替代。
