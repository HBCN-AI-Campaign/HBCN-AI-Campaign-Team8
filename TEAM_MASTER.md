# Team 8 项目 Master

> 最后更新：2026-10-22。本次更新基于源码 `f722291`＋当前工作区与既有验收记录；没有重新宣称 ECS 全链路上线。

## 1. 团队分工

| 序号 | 成员 | 模块 | 联系方式 |
|:----:|------|------|----------|
| 1 | **罗检** | 前端工作台 + 后端任务编排 | 26263050030@m.fudan.edu.cn |
| 2 | **刘范聪** | RAG 服务 + AI 助手（慧眼），辅助审核 Agent | 26263050026@m.fudan.edu.cn |
| 3 | **诸葛 + 吴杨** | 专项审核 Agent，**诸葛负责答辩** | 26263050084@m.fudan.edu.cn / yangwu26@m.fudan.edu.cn |
| 4 | **陈子业 + 肖瑶** | 文件解析 + OCR，**负责部署** | ziyechen26@m.fudan.edu.cn / 26263050060@m.fudan.edu.cn |

模块归属沿用原分工。个人具体任务、提供/消费接口、依赖与验收见[跨模块分工与验收](docs/integration/分工与验收.md)；组内主导人拆分是待成员确认的建议，不代表重新分配模块所有权。

## 2. 全组接线入口

- [一分钟总览与现状/目标架构](docs/integration/README.md)：业务 workflow 与独立慧眼助手如何共用 RAG、SDK，哪些已实现、哪些待接。
- [详细接口与时序](docs/integration/接口与时序.md)：C01–C05 已有接口，N01–N05 拟议能力/运行/证据/网关契约，业务与助手两条时序。
- [任务分工与联合验收](docs/integration/分工与验收.md)：I01–I14 backlog、G0–G4 里程碑、A01–A15 验收。
- [目标界面原型](mockup/mockup_integration_workbench.html)：审核页、助手与知识工作台如何体现能力；只有示例数据，未接真实API。

共同交付目标：一笔脱敏任务完成“上传与真实解析 → 确定性核对 → 专项取证/结构化建议 → 审核页内求助与原文定位 → 人工处置/补件重审 → 人工终审”。聊天答复、run完成与业务审批完成分别记录，业务状态权威属于主后端。

## 3. 当前模块状态与代码归属

| 模块 | 负责人 | 当前依据与边界 |
|---|---|---|
| React 主站 / 任务API / 规则 | 罗检 | React 18、Ant Design 5、FastAPI；27个注册规则。业务任务与规则接口已有实现；持久化review-run、统一任务ACL、原文鉴权与终审门禁需继续完成 |
| 解析与 OCR | 陈子业＋肖瑶 | 主站 parse_agent 仍Mock；ocr_demo有HTTP全文识别源码，但字段抽取与page/bbox须完成联合验收；源码存在不等于已部署 |
| 专项与汇总Agent | 诸葛＋吴杨 | review_agent当前为Mock会话构造；尚未连接真实专项工具/SDK。须按结构化契约接业务run，不依赖前端动画 |
| 慧眼助手 | 刘范聪 | React路由、JSON/SSE、授权上下文与runtime已有基线；并行新增成员/专家、聊天run、事件轮询/审计源码与路由，完成状态以模块执行规划和联合验收为准；业务review-run是另一契约 |
| RAG | 刘范聪 | PostgreSQL/pgvector、检索、LangGraph问答与SDK已有本机验收；并行新增查询规划/融合与增强retrievals接口，按执行台账复验；主站adapter仍需对接，law/task_documents未开放 |
| 北大法宝MCP | 刘范聪 | 9个地址初始化成功，法条检索工具曾实际查询；不等于RAG后端/ECS已集成。见MCP接入文档 |
| SDK runtime | 刘范聪 | code/assistant-runtime；OpenCode SDK固定2.0.32，汇丰模型凭证只在服务端，供助手和RAG调用；专项共享能力适配待实现 |
| 部署上线 | 陈子业＋肖瑶 | ECS曾发现主站前后端进程；不能据旧记录声称最新RAG/runtime/OCR/助手已统一上线，按部署方案复验 |
| 答辩 | 诸葛 | 按真实用例与证据展示，明确Mock、已实现、已联调、已部署和规划，避免把图当上线证明 |

### 源码所有权

| 路径 | 主维护方 | 协作边界 |
|---|---|---|
| code/backend/app/routers/tasks.py、models.py、schemas.py、rule_engine/ | 罗检 | 共享文件由罗检整合，其他模块提供DTO/适配补丁，不并行覆盖 |
| code/backend/app/parse_agent.py、code/ocr_demo/ | 陈子业＋肖瑶 | 保持解析输入输出契约；真实识别、质量与位置由解析组交付 |
| code/backend/app/review_agent.py | 诸葛＋吴杨 | 专项/汇总建议与工具适配，不自行写审批状态 |
| code/backend/app/assistant_*、routers/assistant.py、rag_service.py | 刘范聪 | 助手与共享AI适配；权限策略/共享表修改与罗检对齐 |
| code/frontend/ | 罗检主站架构；刘范聪助手页面 | React统一，业务API与助手SSE分层；共享组件和路由双方复核 |
| code/rag-service/、code/assistant-runtime/ | 刘范聪 | RAG、SDK为独立服务；只经接口供业务消费 |
| 部署配置与运行环境 | 陈子业＋肖瑶 | 各模块交运行说明、就绪/真实验收与回滚，不在仓库放凭证 |

### 版本与计划维护

跨模块任务的逐项状态只在[分工与验收](docs/integration/分工与验收.md)维护，本文保留总体状态和入口；模块细节归各自README。旧时序中“全体任务自动入RAG、混合检索已完成、专项Agent已真调用”的描述是目标，不是当前事实，已由接线总览中的现状/目标双图替代。RAGFlow是历史候选/兼容适配，不再固定视为必须补部署的底座；按最新RAG规划和质量/资源评测决策。

## 4. 基础设施

### 4.1 ECS 服务器
```
IP: [请通过汇丰授权的资源渠道获取]
用户: [请通过汇丰授权的资源渠道获取]
密码: [请通过安全渠道获取，不在文档保存]
SSH: 使用已授权的密钥与主机指纹配置连接
```

### 4.2 PostgreSQL
```
地址: [请通过汇丰授权的资源渠道获取]
库名: team08
用户: [请通过汇丰授权的资源渠道获取]
密码: [请通过安全渠道获取，不在文档保存]
```

### 4.3 百炼 API
```
Base URL: https://llm-tlndh47wd9ustbss.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
API Key: [请通过团队密钥管理渠道获取，不在文档保存]
LLM: qwen3.8-flash
Embedding: qwen3.7-text-embedding-flash
```

---

## 5. 重要链接

1. **GitHub**：https://github.com/HBCN-AI-Campaign/HBCN-AI-Campaign-Team8
2. **百度网盘**：https://pan.baidu.com/s/4pUSzh0
3. **技术文档**：[docs/README.md](docs/README.md)
