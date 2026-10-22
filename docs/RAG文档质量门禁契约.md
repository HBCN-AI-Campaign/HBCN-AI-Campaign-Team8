# RAG 文档质量门禁与复核契约

> 2026-10-22；服务 0.4.0 / HTTP 契约 1.2.0。R12/T12 部分实现，主交付后端为 PostgreSQL。此门禁检查解析风险，不提供 OCR 正确率、文档完整性或法律审批结论。

## 解析、隔离与放行

原件登记 SHA256 必须与处理时读到的文件一致。解析按页或章节记录 extraction.method；DOCX 保留正文段落/表格顺序，XLSX 保留工作表定位。文本识别 UTF-8/16/32 BOM，旧编码推断要求复核。PDF 优先提取原生文本，空页才转图 OCR；含图像或已有 OCR 层的页面保守要求核对。依据 [pypdf 官方说明](https://pypdf.readthedocs.io/en/stable/user/extract-text.html)，文本提取不能可靠重建所有排版，隐藏 OCR 文本也可能已有识别错误，不能一律栅格化原生 PDF 来保证质量。

`document-quality-v1` 对替换字符 U+FFFD、无效控制字符/孤立代理字符、无可索引文本等阻断，状态为 quarantined，不进入 Embedding。OCR 输出、空单元、私用字形/cid、解析来源缺失、推断编码、DOCX 未转录图片/页眉页脚、XLSX 缺公式缓存值等进入 quality_review。OCR 服务即使未报告低置信度也不能自动放行；视觉响应不是 finish_reason=stop 或不是字符串时按失败处理，截断不冒充完整正文。当前不是 OCR 评分器，也不会用猜测值补公式或金额。

机械通过记 mechanically_checked 后才能索引；它只说明这些检查没有发现问题。质量报告含策略版本、解析摘要、报告摘要和逐单元原因，不保存正文副本。quarantined 不向 PostgreSQL JSONB 写入无效正文；待复核解析保存在文档记录中。复核通过后复用已核对解析，避免再次 OCR 改变正文；原件变化仍会阻断。报告、复核凭证与审核主体不复制到检索片段 metadata。

## 可信复核接口

除服务 Bearer Token 外，三个接口都要求 `X-Document-Review-Key`。部署配置 `RAG_DOCUMENT_REVIEW_PRINCIPALS_FILE`，默认为空（接口 404）；与案例治理开关/凭证分开管理。注册表复用 [治理主体格式](RAG案例与经验治理契约.md)，namespace 必须精确为该文档 scope（business_rules/project_design/law），role 含 reviewer，凭证独立随机生成并仅存 SHA256，设置有效期与文件权限。每次请求重新读注册表，删除或到期后拒绝；服务 Token、本机 Cookie、客户端自报姓名均不构成复核授权。此流程没有上传人与审核人双人分离保证；主站真实用户/任务 ACL 仍未完成。

| 路径（`/api/v1/documents/{id}`） | 行为 |
| --- | --- |
| `GET /quality` | 返回质量报告、待核对解析与文档摘要，要求范围内 reviewer；不是普通问答正文接口 |
| `POST /quality-review` | 记录 approve/reject，事务锁定当前版本；通过后仅排队，返回 202 不代表 ready |
| `POST /quality-recheck` | 原件 hash 绑定，先隐藏旧片段并排队重解析；可处理旧 ready/failed/quarantined/quality_review，不能恢复 withdrawn |

复核 JSON 严格禁止额外字段：expected_sha256、expected_parsed_sha256、expected_report_sha256（均 64 位小写 hex）；decision=approve/reject；verified_units 为实际核对的从 0 开始单元序号；reason=source_compared/incomplete/incorrect/unreadable。approve 仅接受 source_compared，并要求全部单元恰好各一次；版本/报告/状态变化 409，未知记录 404，范围不符 403。队列已满可能先返回 503；失败后先重新查询状态，不自动重放审批。服务端绑定主体与时间。quarantined 不能用审批入口绕过，需更正并重新检查。

审核人必须检查**所需内容是否真的被提取**。页眉、图片、公式结果缺失时，不能仅勾选单元就放行；必要正文缺失应 reject，先更正原件/解析再重检。`verified_units` 是审核声明，程序不能证明人确实看了原件。批准仅涉及该次解析，不是业务审批或法规适用性复核。

运维/受控审核工作机使用 HTTP 客户端 `code/rag-service/scripts/review-document-quality.py`；设置 RAG_BASE_URL、RAG_SERVICE_TOKEN、RAG_DOCUMENT_REVIEW_KEY，凭证不放命令行或浏览器。默认 GET；`--recheck --source-sha256 ...` 为显式重检；决定必须明确提供三个 hash、--decision、--reason 和实际 --verified-unit，工具不自动生成“全部已看”。输出含待核对正文，应在受控终端处理，不能写公共日志。所有响应 no-store，不能当作调用方的永久有效缓存。

## 旧库升级与部署验收

本轮复用 documents.provenance JSONB，没有新增列/正式 DDL；**旧 ready 文档缺少当前质量报告时默认排除**，已有 API 的可用资料范围会因此改变。`GET /ready` 额外返回 quality_policy_version/unverified_ready_documents，旧 ready 缺口非零时 503/degraded。先读只读清点，再按下列步骤安排迁移窗口，不能把“服务能启动”当可发布。

1. 在旧版本仍提供服务时备份一致的数据库、原件和配置；部署同事在隔离副本预演，运行 `python scripts/audit-document-quality.py`。工具只读事务、10 秒语句限时，不建表、不改文档、不调模型。
2. 配置独立 reviewer 注册表和原件路径。逐份确认登记 SHA256，经 `/quality-recheck` 重解析；该操作会立即隐藏旧片段，可能调用 OCR/Embedding 并产生费用。当前入库仍是进程内队列，只运行单实例，不声称持久队列/多实例恢复已完成。
3. 检查质量状态及原件；需要复核的逐单元审核，缺失/错误拒绝并修正。机械通过也需业务抽查，不能批量给旧库盖合格章。重新建立向量及启用 hybrid 时的词法索引。
4. 再次清点、检查 ready 和实际目标文档检索、原文定位、金额/币种、多语言及撤回；与隔离基线比召回和排名。旧片段在候选召回后仍会被最终门禁排除，迁移未完可能占候选名额、减少合格召回；因此待迁移缺口非零不能按生产质量发布。
5. 准备保留质量与撤回门禁的修复/回滚版本及一致快照演练。不能直接退回忽略本版质量门禁的 0.3.x 并开放数据，也不能在恢复后重新公开已撤回资料；云端回滚仍待部署同事实际验证。

本机只读清点：10 份旧 ready 全部缺本版记录，另 1 份 failed。未执行重检/复核、未迁移或重启共享实例。这是升级影响证据，不是这些原件实际不合格的结论。

## 当前边界与后续验收

自动门禁不检测全部缺页、金额识别错误、跨页表格、页眉脚注/文本框和复杂版面。OCR 提供方真实质量、扫描件逐字符/金额准确率、人工复核有效性、结构化条款切分与来源授权仍待独立语料验收。LocalEngine 仅阻断本次不确定上传，不追溯旧 SQLite；外部 RAGFlow 与法宝内容需独立来源质量策略，本契约不扩大解释为全来源覆盖。

继续执行 T12：使用授权合成/脱敏样本补跨页表格、扫描金额/币种/符号、漏页与复杂版面金标；比较成熟解析组件及所需资源，记录准确率、漏项、时延/费用，再决定解析/审核工作流，不以现有硬件能力降低目标。
