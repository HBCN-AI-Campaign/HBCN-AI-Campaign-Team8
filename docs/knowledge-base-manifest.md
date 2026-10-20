# 汇丰业务知识库资料清单

> **外部法规/汇丰公开资料已单独归档**：境外与跨境贷款相关的中国及境外法律法规、汇丰银行公开网页，
> 已下载并存放在 `code/rag-service/knowledge-base/`（索引见 `catalog.json`，说明见其 `README.md`）。
> 本文档只管理**内部业务资料**的白名单与入库规则。

## 资料源

历史业务资料源目录：

`E:\2026_AgentStudy\Python_code\HBCN_AI_Campaign_Team8_Clever\汇丰竞赛8组共享文件夹`

当前新仓库只保存索引规则和接口，不自动复制旧目录中的全部文件。部署 RAGFlow 时按本清单选择安全资料，再由项目成员确认是否允许上传到外部模型服务。

## 允许进入业务知识库的资料

以下文件是当前自动入库脚本的实际白名单；脚本位置为 `code/rag-service/app/manifest.py`。

### `business-rules`

- `01_汇丰业务文件\贷款文件比对要求.xlsx`
- `01_汇丰业务文件\贷款文件比对要求- V2 20261013.xlsx`
- `01_汇丰业务文件\贷款用途常见描述.xlsx`
- `01_汇丰业务文件\FOL 贷款用途（流贷+固贷）.docx`
- `02_团队方案与作品\10_金融Campaign项目需求梳理及软件策划.md`
- `02_团队方案与作品\12_金融Campaign项目需求梳理及软件策划_改进版.md`

### `project-design`

- `01_汇丰业务文件\业务时序图\loan-review-sequence.mmd`
- `01_汇丰业务文件\业务时序图\loan-review-sequence.html`
- `02_团队方案与作品\09_汇丰跨境业务竞赛_系统构思.docx`
- `02_团队方案与作品\11_金融信息系统_业务点整理.docx`
- `03_会议记录\01_启动会材料_HBCN_AI_Agent_Kickoff.pptx`

### `task-documents`

- 已脱敏、获得授权的业务 PDF 和图片样例。
- 当前不自动上传贷款样本件；需要单独确认脱敏和授权后再加入清单。
- 每份材料必须带 `task_code`、文件版本、页码和来源权限元数据。

## 禁止进入知识库

整个目录 `04设备API等文件` 禁止索引，包括：

- `.eml` 邮件；
- API Key refresh CSV；
- RDS PostgreSQL 连接信息；
- ECS 登录信息；
- 任何密码、Token、私钥和真实服务地址。

同时禁止把真实客户上传件、未脱敏会议录音、聊天导出和含个人信息的文件上传到外部 Embedding/LLM 服务。

## 入库元数据

每个切片至少保留：

```json
{
  "collection": "business-rules",
  "source_path": "相对资料路径",
  "document_version": "文件修改日期或版本号",
  "language": "zh-CN",
  "page": 1,
  "task_code": null,
  "permission_scope": "team8"
}
```

法规 API 返回的内容另加 `provider`、`law_title`、`article`、`retrieved_at` 和授权范围，不与内部材料混淆。
