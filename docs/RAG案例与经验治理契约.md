# RAG 案例与经验治理契约

> 2026-10-22；R11/R12/R15 部分实现，默认关闭。独立存储、复核和检索接口已实现；未导入真实案例，未接主站 JWT/任务 ACL，也未接问答图或经验自动写入。

## 范围与用途

`case_reference` 保存经授权脱敏的历史事实摘要、处理措施及依据版本；只能说明相似问题曾怎样处理，不能证明本案事实或代替现行规范。`experience_memory` 仅保存检查清单或查询策略，必须绑定至少两个不同历史案件的确定版本；不能成为系统指令、硬规则或审批标准。原始任务单据继续由业务系统保管，本接口没有文件批量导入入口。

两类记录使用独立 SQLAlchemy 表，不进入 `documents`、pgvector 或公共规则检索。当前检索先严格匹配 namespace、产品、辖区、差异类型和政策版本，再用 PostgreSQL 中文分词全文检索（FTS/GIN）；不宣称是向量/混合检索或已通过案例相关性评测。跨政策版本的比较、事实差异分析、多语言改写和模型/Agent 接线继续按规划验收。

## 可信主体与访问范围

私网接口同时要求既有 `Authorization: Bearer <SERVICE_TOKEN>` 和 `X-Reference-Key`。后者是受控治理服务/评审操作方的独立高熵凭证，服务端注册表映射 subject、精确 namespace、reader/author/reviewer 角色及有效期；请求不得指定身份或复核者。每次请求重读注册表，删除主体或到期后拒绝访问，配置错误关闭服务。服务 Token、本机工作台 Cookie 和请求里的 namespace 均不会自动赋予案例权限。

这不是主站用户/任务授权方案。当前 subject 表示治理主体，不能凭此宣称已完成跨用户记忆或任务资料 ACL。接入生产用户前由主站认证和任务授权生成可信范围，保留真实操作人、撤权版本及审计；不能让浏览器持有服务凭证，也不能将任意用户表单转换为可信范围。部署主体注册表需由授权管理员管理文件权限、独立人员凭证、期限和轮换，经过授权部署后才开启接口。

配置使用 `RAG_REFERENCES_ENABLED=false` 和 `RAG_REFERENCE_PRINCIPALS_FILE=`。注册表放在受控部署路径，例如已忽略的 `data/`，不要提交凭证或真实 subject/案例数据。格式如下，`key_sha256` 为独立随机凭证的 SHA-256（示意占位符不能直接运行）；有效期必须带时区：

```json
{
  "principals": [{
    "subject": "approved-curation-subject",
    "key_sha256": "<64 lowercase hex characters; hash of a separately delivered random key>",
    "namespaces": ["approved_namespace"],
    "roles": ["reader", "author"],
    "valid_until": "2026-11-01T00:00:00Z"
  }]
}
```

至少使用 32 字节密码学随机凭证，单个 subject 一个有效 key；示例中的角色不含复核。第二个独立 subject 负责 reviewer。两人真实身份和脱敏质量由业务审批流程确认，程序只能阻止同 subject 自批及未授权角色，不能识别两份凭证是否实际上由同一个人持有。

## 不可变版本与状态

每次提交创建新 UUID 和递增逻辑版本，正文不得原地编辑；状态变化使用 revision 和 content_sha256 共同绑定。内容包括业务日期、原审核日期、政策版本、脱敏摘要、正反证据 ID/版本/hash、处理措施、结论状态、共享授权、脱敏确认、泄漏组及保留期限。缺失/未知适用条件、争议/撤销结论、评测专用资料、未获共享授权或未确认脱敏的候选不能发布；这些标记是人工复核的输入，不是自动完成了脱敏或政策真实性校验。

发布顺序为 candidate → 独立 reviewer 检查正文/依据/授权 → approved。发布同逻辑 ID 新版本时，旧 approved 版本变为 superseded，旧来源的派生经验同步 withdrawn。更正/撤销/权限变化/政策变化可撤回 candidate 或 approved；撤回不能靠原版本再次发布来恢复，必须新建并重新复核。

经验的所有父案例须来自同 namespace、不同案件，保持 approved、同产品/辖区/差异类型/政策版本；经验期限不能晚于任一父案例。创建与发布都重查父版本，检索与正文读取也核查当前来源状态。依赖只允许“案例→经验”，不存在无限递归或经验自我强化。

发布、撤销、替换、到期清理及审计事件在同一事务提交。当前低频治理写入用一个数据库行锁串行化，设置锁等待和 SQL 时限，防止“撤销来源”与“发布派生经验”并发留下有效经验；不是分布式队列或高吞吐写入方案。行锁行为依据 [PostgreSQL 官方文档](https://www.postgresql.org/docs/current/explicit-locking.html)，本轮已用实际隔离 PostgreSQL 并发测试验证该业务不变量。

过期记录立即拒绝正文和检索；清理接口清空过期版本正文/检索文本和派生经验，保留不含正文的版本/hash 审计墓碑。清理必须由部署运维按保留政策调度；尚无自动调度。此处不承诺数据库备份、WAL、存储介质、外部日志或第三方缓存中的物理擦除，部署验收需统一执行相关保留政策。

## 接口与部署

| 私有路径（`/api/v1/references`） | 所需角色 | 行为 |
| --- | --- | --- |
| `POST /candidates` | author | 提交不可变候选；kind 显式区分案例/经验 |
| `GET /versions/{id}?namespace=...&inspect_candidate=true` | reviewer | 复核候选/保留期内历史版本；不是指导性读取 |
| `POST /versions/{id}/approve?namespace=...` | reviewer | expected_revision + content_sha256，拒绝自批 |
| `POST /versions/{id}/withdraw?namespace=...` | reviewer | 同版本绑定及受限撤销原因，事务内撤销派生经验 |
| `POST /search` | reader | 条件过滤、词法检索、仅返回当前有效的历史参考/经验 |
| `GET /versions/{id}?namespace=...` | reader | 当前有效参考原文；来源失效/期限届满即不可见 |
| `POST /purge-expired?namespace=...` | reviewer | 清理本范围到期正文与派生内容，幂等保留审计墓碑 |
| `GET /audit?namespace=...&after=...` | reviewer | 每页最多 100 个事件；无查询/案例正文 |

内容响应设置 `Cache-Control: no-store`，当前无案例/记忆应用缓存。正文读取（包括检索返回）记录主体、版本 ID、hash 和动作，不记录查询或正文。审计为应用侧追加事件，尚未实现独立审计库、数据库防篡改权限或持久外部审计汇聚，不能称为完整生产审计。

部署前审查独立表、授权、主站接线与清理任务；`scripts/deploy-reference-schema.py` 默认只检查，`--apply` 才创建配置的既有 schema 内四张 `reference_*_v1` 表和索引。不创建 schema、不迁移公共知识表、不导入数据。服务启动不会自动建表；未部署返回未就绪。本轮只在随机隔离 schema 执行迁移，未在正式 schema 执行。

## 评测与后续接线

检索接受评测管理方给出的 excluded_leakage_groups，既排除案例，也排除源于被排除案例的经验；这只是防泄漏机制，不能自行证明调用方提交了完整排除集。真实 holdout 应使用独立物理/授权快照，题集/案例映射由评测管理者冻结，不向普通问答公开。

接入 Agent 前还需：主站身份/任务 ACL 与撤权链；审批/脱敏 UI；授权真实案例质量集与可比性/事实差异评估；历史参考专用输出区域和支持核验；跨语言/混合检索及 rerank 对照；经验仅影响计划、不能改写系统规则的提示注入测试；正式迁移/备份/清理/审计/回滚。当前 `/answers`、`/retrievals` 仍只接受既有知识库/法宝来源，不能用本轮治理接口代替完整 R11 验收。
