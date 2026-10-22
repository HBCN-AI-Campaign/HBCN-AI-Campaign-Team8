# RAG 法规复核台账契约

> 第七轮 R08/R12 的约束基础，尚未完成法规业务验收。台账不是审批系统，也不能代替法律人员判断。没有配置真实复核记录时，本案法规判断保持证据不足。

## 请求用途与业务条件

`/api/v1/answers`、`/answers/stream`、`/retrievals` 共用以下新增字段；旧调用默认 `purpose=reference`，仅作资料参考，不能解释为本案核验通过。调用方开展本案法规判断须显式使用 `case_assessment`。前端接线、主站用途传递与自动意图识别尚未验收，不能声称任意自然语言问句都会自动进入本案门禁。

```json
{
  "query": "这份合成贷款资料应核对哪些法规条件？",
  "scope": "law",
  "sources": ["knowledge_base", "pkulaw"],
  "purpose": "case_assessment",
  "legal_context": {
    "business_date": "2024-06-01",
    "jurisdiction": "CN",
    "subject_type": "commercial_bank",
    "business_type": "overseas_loan"
  }
}
```

示例仅说明契约，未证明该主体、业务或辖区的实际法规范围。日期要求真实存在的 YYYY-MM-DD；辖区和主体/业务分类由调用方明确提供，模型不能猜测。主体/业务目前按精确分类值匹配，跨系统分类表与 UI 选项待统一。结构化条件传入模型作为理解上下文，同时执行确定性门禁；它们不是法规证据，也不能自行批准。当前未将这些字段实现为数据库时间/辖区检索过滤器，因此不能宣称已具备完整时态检索。

## 服务端复核文件

服务端通过 `RAG_LEGAL_REVIEW_FILE` 指向由获授权复核人员管理的 UTF-8 JSON 文件；默认空、不生成批准记录、不接收上传资料中的自称批准字段。部署时须限制文件写权限并以完整文件原子替换，维护人员身份、修订审计与复核流程。没有新增可由客户端写台账的接口。

机器契约见 [JSON Schema](../code/rag-service/app/contracts/legal-review-registry.schema.json)，源码为 [legal_applicability.py](../code/rag-service/app/legal_applicability.py)。文件顶层 `version=1`、`reviews` 数组；单个文件最多 10 MB/10000 条。每条记录包括：

| 字段 | 含义 |
| --- | --- |
| review_id、reviewed_by、reviewed_at | 复核编号、责任人、已发生且带时区的复核时点；字符串身份不等于已实现身份认证/数字签名 |
| document_id、chunk_id、content_sha256 | 原始文档及片段、原文哈希；窗口绑定父片段，不能用片段摘要代替原文 |
| source_version | 必填；有来源版本则精确匹配，没有版本时显式 null。法宝状态等元数据变化会使旧版本记录失配 |
| state | approved 或 revoked；撤销记录不能通过 |
| review_expires_on | 复核记录到期日，按服务当前 UTC 日期检查；不是法规终止日 |
| valid_from、valid_to_exclusive | 法规已复核有效区间，左闭右开；终点必须显式提供，null 仅表示复核人员明确批准开放终点，缺字段拒绝 |
| jurisdictions、subject_types、business_types | 已复核范围，按明确值匹配；不推断跨辖区适用 |
| authority_url | 复核人员记录的 HTTPS 依据地址；程序不据此下载或证明权威性，须由复核流程核实 |

生效/失效、修订过渡条款与溯及适用需要真实材料和复核，不能从发布日期、抓取日期或“现行有效”字样推算。台账支持对明确历史业务时点检查版本范围；不能由此宣称已解析所有法律过渡规则。对同一绑定存在多条记录一律要求先解决冲突，不自动取“最新”以盖过撤销；撤销可更新同一记录，旧审计版本保存在服务外受控历史中。

每次检查重新读取台账，防止进程内缓存隐藏撤销。缺文件、格式异常、过期、哈希/版本改变、范围不匹配均不能确认充分。错误不返回文件路径、复核文件内容或解析异常。商用缓存/全文授权、法规变更订阅及分布式撤销传播仍待单独验收。

## 返回状态与边界

`legal_applicability` 与 `missing` 同时出现在问答和增强检索响应中。

| status | 含义 |
| --- | --- |
| not_checked | 本轮未进入适用性检查，例如澄清、时间预算耗尽 |
| not_required | 所选资料不含法规且本次没有显式法规判断需求；不是审批结果 |
| reference_only | 参考检索，法规原文尚未做本案适用核验 |
| legal_evidence_required | 本案法规判断未选出法规原文，不能仅选其他材料绕过门禁 |
| context_required | 本案条件缺失 |
| review_required | 台账未配置或不可用 |
| blocked | 原文/版本、复核状态或适用区间/范围未通过 |
| reviewed_constraints_match | 所选法规片段的已复核结构化约束匹配；仍不是法律、信贷或放款审批结论 |

门禁阻断时保留已选相关片段和缺口，返回 insufficient，跳过最终业务结论生成。默认参考用途通过模型指令禁止输出本案批准结论；这还不是独立的语义越界分类器，需在后续 UI/用途路由、独立保留题集和业务复核中补齐。旧 `/query` 不执行此增强图，调用方不能将它的相关性分数当成适用性通过。

该文件是当前可执行约束与交接契约。未来应比较受控文档管理/法规版本系统作为台账来源；不能为每一条检索片段临时造批准记录来提高通过率，也不能把手工台账当成最终高质量法规检索架构。
