# 8组项目 Master｜智汇跨境贷途·慧眼识险无忧

> **项目名称**：境外贷款单据智能审核平台  
> **团队编号**：Team 8  
> **最后更新**：2026-10-20

---

## 📋 快速导航

- [项目概览](#项目概览)
- [团队信息](#团队信息)
- [系统架构](#系统架构)
- [模块分工](#模块分工)
- [开发规范](#开发规范)
- [基础设施资源](#基础设施资源)
- [项目计划](#项目计划)
- [重要链接](#重要链接)

---

## 项目概览

### 一句话介绍

境外贷款单据智能审核系统：经办人上传单据 → **解析 Agent** 识别字段 → **规则引擎**硬核检查 → **专项审核 Agent** 处理外部能力项 → 给出通过 / 不通过 / 需人工处置结论。

### 技术栈

**后端**
- FastAPI + SQLAlchemy 2.0 + Pydantic 2
- python-jose (JWT) + bcrypt
- SQLite（默认）/ PostgreSQL（可选）
- OpenAI Agents SDK 0.4.2

**前端**
- Vite 6 + Vue 3.5 + TypeScript
- Pinia + Vue Router 4
- Element Plus 2.9 + axios
- @copilotkit/vue 1.79.1（AI 助手 UI）

**AI 能力**
- 阿里云百炼 API（LLM: qwen3.8-flash, Embedding: qwen3.7-text-embedding-flash）
- RAG 服务（独立服务 `code/rag-service`，端口 8010）
- OCR 服务（队友提供，`code/ocr_demo`）

### 系统边界

**已实现**
- 用户认证与角色权限（业务经办人 / 审核人员）
- 多文件上传与批次管理
- PDF 字段解析（当前 Mock，接口已定义）
- 规则引擎（20 条硬性规则，注册表模式）
- 专项审核 Agent（节假日/汇率/提单验真/制裁名单/法规检索，当前 Mock）
- 定位原文（字段级 PDF 高亮，pdfjs-dist 渲染）
- AI 助手「慧眼助手」（对话式审核辅助，SSE 流式）
- RAG 知识库（业务规则 + 项目设计资料，本地引擎已跑通）

**待完成**
- 解析 Agent 真实实现（OCR/LLM 识别字段 + source 坐标）
- 专项审核 Agent 真实实现（接入外部 API / 法规检索）
- RAGFlow 正式底座部署
- OCR 服务部署与联调

---

## 团队信息

### 成员与分工

| 成员 | 邮箱 | 角色 | 主要负责 |
|------|------|------|----------|
| **刘范聪** | 26263050026@m.fudan.edu.cn | PMO / 项目管理 | 整体规划、进度管理、团队协调、对外沟通；具备 Python 与数据分析 Agent 开发基础 |
| **吴杨** | yangwu26@m.fudan.edu.cn | 交互开发 / 前端开发 | 对话交互、结果展示和系统演示；熟悉 Python、JavaScript，有智能客服 Agent 经验 |
| **罗检** | 26263050030@m.fudan.edu.cn | AI 开发 / RAG 工程 | 检索增强生成和智能体核心功能；熟悉 Python、JavaScript，有 RAG 数据分析助手经验 |
| **肖瑶** | 26263050060@m.fudan.edu.cn | 业务分析 / 合规分析 | 贷款用途审核、风险识别、法规依据梳理；有法审合规和金融合规经验 |
| **陈子业** | ziyechen26@m.fudan.edu.cn | 前端开发 / 桌面端开发 | 人机交互、桌面端、文档解析和部署；具备 C# 跨平台桌面应用经验 |
| **诸葛** | 26263050084@m.fudan.edu.cn | 后端开发 / 业务分析 | Java 后台、数据处理和业务逻辑；有消费贷、基金业务经验，担任答辩主讲 |

### 协作方式

- **代码仓库**：[GitHub - HBCN-AI-Campaign-Team8](https://github.com/HBCN-AI-Campaign/HBCN-AI-Campaign-Team8)
- **文件共享**：百度网盘 `https://pan.baidu.com/s/4pUSzh0`
- **会议记录**：共享文件夹 `03_会议记录/`
- **提交约定**：按模块提交，**不要 `git add .`**；提交信息格式 `模块: 说明`（例如 `review_agent: 实现提单验真`）

---

## 系统架构

### 目录结构

```
HBCN-AI-Campaign-Team8/
├── code/
│   ├── backend/              # 后端主项目（FastAPI）
│   │   ├── app/
│   │   │   ├── main.py       # 入口
│   │   │   ├── models.py     # SQLAlchemy 模型
│   │   │   ├── schemas.py    # Pydantic DTO
│   │   │   ├── security.py   # JWT 鉴权
│   │   │   ├── config.py     # 环境配置
│   │   │   ├── parse_agent.py    # 文件解析 Agent（Mock）
│   │   │   ├── review_agent.py   # 专项审核 Agent（Mock）
│   │   │   ├── rag_service.py    # RAG 适配层
│   │   │   ├── assistant_service.py  # AI 助手核心
│   │   │   ├── rule_engine/      # 规则引擎
│   │   │   ├── routers/          # API 路由
│   │   │   ├── sample_pdfs/      # 样本 PDF（8 个模板）
│   │   │   └── uploads/          # 运行时产物（gitignore）
│   │   ├── tests/
│   │   └── requirements.txt
│   ├── frontend/             # 前端（Vite + Vue 3）
│   │   ├── src/
│   │   │   ├── views/            # 页面组件
│   │   │   ├── components/       # 可复用组件
│   │   │   ├── stores/           # Pinia 状态
│   │   │   ├── router/           # Vue Router
│   │   │   ├── api.ts            # axios 封装
│   │   │   └── assistant/        # AI 助手专属
│   │   ├── package.json
│   │   └── vite.config.ts
│   ├── rag-service/          # RAG 独立服务（端口 8010）
│   │   ├── app/
│   │   │   ├── main.py           # FastAPI 入口
│   │   │   ├── engine.py         # 引擎工厂 + LocalEngine
│   │   │   ├── embedding.py      # 百炼 Embedding 客户端
│   │   │   ├── local_store.py    # SQLite 向量库
│   │   │   ├── ocr.py            # OCR 客户端
│   │   │   ├── ragflow.py        # RAGFlow 官方客户端
│   │   │   ├── schemas.py        # 契约 DTO
│   │   │   └── static/index.html # 试用 UI
│   │   └── tests/
│   └── ocr_demo/             # OCR 服务（队友，独立 FastAPI）
├── docs/                     # 项目文档
│   ├── README.md             # 文档索引
│   ├── RAG模块技术方案.md
│   ├── RAG实施规划.md
│   ├── RAG模块交接说明.md
│   ├── knowledge-base-manifest.md
│   └── ai-assistant/
│       ├── README.md
│       └── 开发记录与交接.md
├── mockup/                   # HTML 设计稿（按成员命名）
├── AGENTS.md                 # AI 编码助手专用说明
└── README.md                 # 人类可读项目文档
```

### 核心流程

```
用户上传单据 PDF
    ↓
[parse_agent] 解析字段 + 记录 source{page, bbox}
    ↓
创建 ReviewTask + Document 记录
    ↓
[rule_engine] 硬性规则检查（20 条）
    ↓  ✓ 全部通过
    ↓  ✗ 不通过 → 人工复核
    ↓  ⚠️ 专项项 → [review_agent]
    ↓
[review_agent] 节假日/汇率/提单验真/制裁名单/法规检索
    ↓
生成审核报告（通过/不通过/待人工处置）
    ↓
前端展示 + PDF 高亮定位原文
```

### 数据流

**多文件上传**
- 前端：`FormData` 同名字段 `files` 逐个 append
- 后端：FastAPI `list[UploadFile]` 自动收成数组
- 落盘：`uploads/<batch_id>/<文件名>`

**字段解析**
- `parse_agent.parse_files(files)` 返回
  ```python
  {
    "fields": [
      {
        "key": "borrower_name",
        "label": "借款人名称",
        "value": "某公司",
        "kind": "string",
        "confidence": 0.95,
        "source": {"page": 1, "bbox": [0.1, 0.2, 0.5, 0.3]}  # 归一化坐标
      }
    ]
  }
  ```

**定位原文**
- 规则引擎 `detail` 行附带 `source {pdf_file, page, bbox}`
- 前端 `PdfSourceViewer.vue` 用 `pdfjs-dist` 渲染 + 红框高亮

---

## 模块分工

### 1. 解析 Agent（`backend/app/parse_agent.py`）

**职责**：OCR/LLM 识别字段 + 定位原文位置

**当前状态**：Mock 桩，返回硬编码字段

**输入契约**
```python
def parse_files(files: list[UploadFile]) -> dict:
    """
    files: FastAPI UploadFile 列表
    返回: {
      "fields": [
        {
          "key": str,           # 字段标识符（如 borrower_name）
          "label": str,         # 中文名称
          "value": str | float, # 识别结果
          "kind": str,          # 类型（string/number/date）
          "confidence": float,  # 置信度 0~1
          "source": {
            "page": int,        # 页码（1-based）
            "bbox": [x0, y0, x1, y1]  # 归一化坐标 0~1
          }
        }
      ]
    }
    """
```

**替换要求**
- 保持接口契约不变
- `source` 必须精确，用于前端 PDF 高亮
- 置信度 < 0.7 的字段应标记为待人工确认

**负责人**：待分配（可能需要 OCR 队友协作）

---

### 2. 专项审核 Agent（`backend/app/review_agent.py`）

**职责**：承接 `[专项]` 项调用外部能力 / LLM

**当前状态**：Mock 桩，生成思考流和待处置项

**能力清单**
1. **节假日核查**：检查贷款起止日期是否覆盖法定节假日
2. **汇率合理性**：比对单据汇率与当日银行汇率
3. **提单验真**：调用外部 API 验证提单真实性
4. **制裁名单**：检查借款人/受益人是否在 OFAC/UN 制裁名单
5. **法规检索**：RAG 检索相关法规条款

**输入契约**
```python
def build_session(
    task_code: str,
    fields: dict,
    special_items: list[dict],  # 规则引擎标记的 [专项] 项
    user: User
) -> dict:
    """
    返回: {
      "session_id": str,
      "思考流": str,              # 执行步骤
      "待处置项": [
        {
          "规则名": str,
          "外部核验结果": str,
          "建议": str,
          "证据": [...]
        }
      ]
    }
    """
```

**替换要求**
- 保持接口契约不变
- 每个能力项需返回明确的"通过/不通过/待人工"结论
- 必须附带证据引用（API 响应 / RAG 检索结果 / 计算依据）

**负责人**：待分配（需协调外部 API 接入）

---

### 3. 规则引擎（`backend/app/rule_engine/`）

**职责**：20 条硬性规则检查

**当前状态**：✅ 已实现，注册表模式

**架构**
```python
# rule_engine/base.py
class BaseRule:
    def check(self, fields: dict) -> CheckResult:
        pass

# rule_engine/registry.py
rules = [
    Rule01_BorrowerName(),  # 借款人名称非空
    Rule02_LoanAmount(),    # 贷款金额 > 0
    # ... 共 20 条
]

def run_all(fields: dict) -> list[CheckResult]:
    return [rule.check(fields) for rule in rules]
```

**扩展方式**
1. 在 `rule_engine/rules/` 下新增 `rule_xx.py`
2. 继承 `BaseRule`，实现 `check()` 方法
3. 在 `registry.py` 中注册

**负责人**：已完成，后续维护由后端负责

---

### 4. AI 助手「慧眼助手」（`backend/app/assistant_service.py` + `frontend/src/assistant/`）

**职责**：对话式审核辅助，提供审核建议和风险摘要

**当前状态**：✅ 已实现，SSE 流式 + CopilotKit UI

**功能**
- 对话式查询任务材料、规则结果、RAG 证据
- 生成审核解释、风险摘要、人工复核草稿
- 右侧「审核技能」商店（6 个业务技能，点击发送结构化 prompt）

**权限边界**
- ✅ 可读任务材料、规则结果、RAG 证据
- ✅ 可生成解释和建议
- ❌ 不能写入任务状态、改写 CheckResult
- ❌ 不能直接给出贷款最终审批结论
- ⚠️ 低置信度/证据冲突时必须提示人工确认

**技术细节**
- Agent SDK：OpenAI Agents SDK Python 0.4.2（锁定 pydantic 2.10.3，openai 2.44.0）
- 模型：阿里云百炼 `qwen3.8-flash`（汇丰提供）
- RAG：通过 `rag_service.RAGClient` 调用
- UI：`@copilotkit/vue` 1.79.1 官方 renderer

**安全机制**
- 不转发 Agent SDK 原始 `raw_response_event`（防止思维内容泄漏）
- 只在运行结束后检查 `final_output`，再分片发送 `delta`
- 历史消息应用输出安全检查（命中标记返回「已隐藏」）

**负责人**：已完成，后续维护由 AI 开发负责

---

### 5. RAG 服务（`code/rag-service/`）

**职责**：知识库检索（业务规则 + 项目设计资料）

**当前状态**：✅ 本地引擎已跑通，RAGFlow 正式底座未部署

**架构**
```
主项目后端 ──> code/backend/app/rag_service.py（RAGClient 适配层）
                    │  HTTP + SERVICE_TOKEN
                    v
          code/rag-service（:8010，独立服务）
                    ├─ 引擎选择：RAGFlowClient ｜ LocalEngine
                    │     LocalEngine = 百炼 Embedding + SQLite 向量库 + OCR 客户端
                    └─ /ui 试用页（业务视角）
```

**知识库范围**
1. `business_rules`：贷款文件比对要求、贷款用途、业务规则和术语
2. `project_design`：需求文档、方案、会议结论、系统时序图和当前接口文档
3. `all`（默认）：同时检索上述两库并合并去重按相似度排序
4. `task_documents`（未开放）：任务上传脱敏单据，需 task_code 权限过滤
5. `law`（未开放）：法规内容，需法规 MCP 授权

**接口**
```
GET  /health                  # 健康检查（无鉴权）
GET  /ui                      # 试用页（服务端注入 Token）
GET  /api/v1/capabilities     # 能力探测
POST /api/v1/query            # 检索 {query, scope?, top_k?}
POST /api/v1/documents        # 导入文件（multipart）
GET  /api/v1/documents        # 已入库文档列表
```

**待完成**
1. OCR 服务部署（队友 `code/ocr_demo`）
2. RAGFlow 正式实例部署（ECS Docker）
3. AI 助手与 RAG 的运行时联通（backend `.env` 两行）
4. 真实业务资料入库与权限范围

**负责人**：罗检（RAG 工程）

---

## 开发规范

### 代码约定

**后端**
- 分层：`models / schemas / routers / rule_engine / security` 各司其职，不跨层混写
- Agent 接口契约见各自文件顶部 docstring
- **替换 Mock 实现时保持接口不变**

**前端**
- Vue 3 组合式 API + Pinia 状态
- axios 统一封装在 `src/api.ts`
- 组件按功能模块组织（`views/` 页面，`components/` 复用）

### 安全注意事项

**禁止提交**
- `.env`（含 JWT 密钥、DB 配置、API Key）
- `uploads/` 里的真实业务 PDF
- 任何敏感凭据（用 `.env.example` 模板 + 本地 `.env`）

**必须遵守**
- JWT 鉴权与角色权限在 `app/security.py`，不可绕过
- 所有密钥通过环境变量注入，不写入前端构建变量
- 共享文件夹 `04设备API等文件/` **禁止进入知识库**（含 API Key、数据库、ECS 登录信息）

### 测试要求

**后端**
```bash
cd code/backend
.venv\Scripts\python -m unittest discover -s tests
```

**前端**
```bash
cd code/frontend
npm run build  # vue-tsc 类型检查 + vite build，提交前必须通过
```

**RAG 服务**
```bash
cd code/rag-service
$env:HBCN_TEST_SOURCE_ROOT='E:\2026_AgentStudy\Python_code\HBCN_AI_Campaign_Team8_Clever\汇丰竞赛8组共享文件夹'
.venv\Scripts\python -m unittest discover -s tests
```

### Git 工作流

1. **按模块提交**，不要 `git add .`（避免卷入队友改动）
2. **提交信息格式**：`模块: 说明`（例如 `review_agent: 实现提单验真`）
3. **分支策略**：
   - `main`：稳定版本
   - `lfc`：当前开发分支（刘范聪）
   - 其他功能分支按需创建
4. **并行开发**：多人同时改动时，明确报告「改了什么、会不会冲突」

---

## 基础设施资源

### ECS 服务器

**实例信息**
- 实例 ID：`i-2zebcrgxyyrerxges5ec`
- 公网 IP：`101.201.232.81`
- 私网 IP：`10.0.0.229`
- 登录用户名：`root`
- SSH 端口：`22`
- root 初始密码：`#QtD5-0PBDinTUrLU7uB`
- 到期时间：2026-12-12 23:59:59 +08:00
- 计费方式：包年包月 2 个月；不自动续费
- 公网带宽：固定带宽 3Mbps

**SSH 登录**
```bash
ssh root@101.201.232.81
```

**当前状态**
- 只开 SSH 22 端口
- 未安装 Docker
- 未部署 OCR 服务
- 未部署 RAGFlow

---

### PostgreSQL 数据库

**连接信息**
- 主机地址：`pgm-2ze9t2uh39o1115k.rwlb.rds.aliyuncs.com`（建议从队内 ECS 内网连接）
- 端口：`5432`
- 数据库名：`team08`
- 用户名：`team08`
- 密码：`Aa9_tE4p6xiT-lLg7nSxHxjrRmwP`
- 版本：PostgreSQL 16
- 扩展：pgvector 0.8.0.2 已启用（不提供 pgmq）
- 账号连接上限：30
- 建议应用连接池：5–10
- 初始容量预算：8 GB/队（软配额，包含数据和索引）

**向量测试 SQL**
```sql
SELECT '[1,2,3]'::vector <-> '[1,2,4]'::vector; -- 预期结果为 1
```

---

### 阿里云百炼 API

**基本信息**
- API Key：`sk-ws-H.PPHHHPD.V1aq.MEUCIQDs7MD9d6A299V3VZsBcB9sKkI4qHPG4cVTTrgzhI0w6AIgVQPbAlzX_V1x40FpmyucEHV-MT2NT_H6OISGCTtKJpA`
- API Host：`llm-tlndh47wd9ustbss.cn-beijing.maas.aliyuncs.com`
- OpenAI Compatible 配置：`https://llm-tlndh47wd9ustbss.cn-beijing.maas.aliyuncs.com/compatible-mode/v1`
- DashScope 配置：`https://llm-tlndh47wd9ustbss.cn-beijing.maas.aliyuncs.com/api/v1`
- 工作空间名称：`genai-hsbc`
- 工作空间 ID：`llm-tlndh47wd9ustbss`

**可用模型**
- LLM：`qwen3.8-flash`
- Embedding：`qwen3.7-text-embedding-flash`
- 视觉 OCR 兜底：`qwen3.8-flash`（多模态）
- Web Search：`enable_search`（百炼原生 REST）

**配置示例（backend `.env`）**
```bash
AI_BASE_URL=https://llm-tlndh47wd9ustbss.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
AI_API_KEY=sk-ws-H.PPHHHPD.V1aq.MEUCIQDs7MD9d6A299V3VZsBcB9sKkI4qHPG4cVTTrgzhI0w6AIgVQPbAlzX_V1x40FpmyucEHV-MT2NT_H6OISGCTtKJpA
AI_MODEL=qwen3.8-flash
AI_REQUEST_TIMEOUT=60
```

**配置示例（rag-service `.env`）**
```bash
BAILIAN_BASE_URL=https://llm-tlndh47wd9ustbss.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
BAILIAN_API_KEY=sk-ws-H.PPHHHPD.V1aq.MEUCIQDs7MD9d6A299V3VZsBcB9sKkI4qHPG4cVTTrgzhI0w6AIgVQPbAlzX_V1x40FpmyucEHV-MT2NT_H6OISGCTtKJpA
EMBEDDING_MODEL=qwen3.7-text-embedding-flash
OCR_VISION_MODEL=qwen3.8-flash
```

**注意事项**
- API Key 已配置在本地 `.env`（gitignored）
- 短期测试用，到期后需重新获取
- 禁止在前端构建变量或 Git 中保存明文 API Key
- 生产部署时通过环境变量或 Secret 注入

---

## 项目计划

### 里程碑

| 阶段 | 时间 | 截止日期 | 本阶段交付 | 牵头 | 状态 |
|------|------|----------|-----------|------|------|
| **1. 需求 + Mock Demo** | 10月10日—10月16日 | 2026-10-16 | 定下需求边界、最终页面样式，跑通 Mock 主流程 | 刘范聪 | ✅ 已完成 |
| **2. 后端真实实现** | 10月17日—10月28日 | 2026-10-28 | 前后端和 AI 完整联调，跑通真实文件处理 | 刘范聪 | 🚧 进行中 |
| **3. 测试优化** | 10月29日—11月1日 | 2026-11-01 | 修 bug、减少漏检，覆盖主要业务场景 | 刘范聪 | ⏳ 未开始 |
| **4. 交付制作** | 11月2日—11月3日 | 2026-11-03 | 录演示视频，整理源码和答辩材料 | 刘范聪 | ⏳ 未开始 |
| **5. 最终提交** | 11月4日 | 2026-11-04 | 全量复核、打包并上传 | 刘范聪 | ⏳ 未开始 |

### 当前阻塞与下一步

**阻塞项**
1. OCR 服务未部署（等待队友 `code/ocr_demo` 启动）
2. RAGFlow 正式底座未部署（ECS 需安装 Docker）
3. 解析 Agent 和专项审核 Agent 仍为 Mock

**下一步行动**
1. **优先级 P0**：部署 OCR 服务到 ECS 或本机
2. **优先级 P1**：实现解析 Agent 真实逻辑（OCR/LLM 识别 + source 坐标）
3. **优先级 P1**：实现专项审核 Agent 真实逻辑（接入外部 API / RAG）
4. **优先级 P2**：部署 RAGFlow 正式底座（ECS Docker）
5. **优先级 P2**：真实业务资料入库与权限范围测试

---

## 重要链接

### 代码与文档

- **GitHub 仓库**：[https://github.com/HBCN-AI-Campaign/HBCN-AI-Campaign-Team8](https://github.com/HBCN-AI-Campaign/HBCN-AI-Campaign-Team8)
- **百度网盘共享**：[https://pan.baidu.com/s/4pUSzh0](https://pan.baidu.com/s/4pUSzh0)
- **项目文档索引**：[docs/README.md](docs/README.md)
- **AI 助手交接文档**：[docs/ai-assistant/开发记录与交接.md](docs/ai-assistant/开发记录与交接.md)
- **RAG 模块交接文档**：[docs/RAG模块交接说明.md](docs/RAG模块交接说明.md)

### 业务资料

| 文件名 | 用途 | 位置 |
|--------|------|------|
| 贷款文件比对要求.xlsx | 20 条贷款文件比对规则 | `01_汇丰业务文件/` |
| 测试版授信使用申请书 中文空白.pdf | 中文申请书空白模板 | `01_汇丰业务文件/` |
| 测试版授信使用申请书 英语空白.pdf | 英文申请书空白模板 | `01_汇丰业务文件/` |
| 测试版授信函 - 中文空白.pdf | 中文授信函空白模板 | `01_汇丰业务文件/` |

### 团队作品

| 文件名 | 用途 | 位置 |
|--------|------|------|
| 03_第8题Demo_贷款审核助手.html | 当前第 8 题 Demo | `02_团队方案与作品/` |
| 09_汇丰跨境业务竞赛_系统构思.docx | 系统方案底稿 | `02_团队方案与作品/` |
| 12_金融Campaign项目需求梳理及软件策划_改进版.md | 方案、MVP 和交付要求 | `02_团队方案与作品/` |

---

## 快速开始

### 环境要求

- Python ≥ 3.11
- Node.js ≥ 18

### 后端启动

```bash
cd code/backend
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m app.seed                                  # 初始化种子数据
.venv\Scripts\python -m uvicorn app.main:app --port 8000          # 启动，/docs 看 API
```

### 前端启动

```bash
cd code/frontend
npm install
npm run dev      # Vite 开发服务器，端口 5173，/api 代理到后端 8000
npm run build    # vue-tsc 类型检查 + vite build（提交前必须通过）
```

### RAG 服务启动

```bash
cd code/rag-service
.venv\Scripts\python -m uvicorn app.main:app --port 8010
# 试用页：http://127.0.0.1:8010/ui （无需填任何东西）
```

### 默认账号

| 用户名 | 密码 | 角色 | 权限 |
|--------|------|------|------|
| `operator` | `operator123` | 业务经办人张三 | 上传解析 + 创建任务 |
| `reviewer` | `reviewer123` | 审核人员李四 | 触发核对 + 查看结果 + 处置专项项 |

---

## 附录：Excel Master 索引

### Master 索引 Sheet

| 文件名 / 入口 | 分类 | 用途（人话） | 共享文件夹内位置 | 来源 | 状态 |
|---------------|------|-------------|-----------------|------|------|
| 01_汇丰业务文件（文件夹） | HSBC 原始业务文件 | HSBC 实际提供的业务资料 | `01_汇丰业务文件/` | HSBC 提供（原始） | 持续使用 |
| 贷款文件比对要求.xlsx | HSBC 原始业务文件 | 20 条贷款文件比对规则 | `01_汇丰业务文件/贷款文件比对要求.xlsx` | HSBC 提供（原始） | 已整理 |
| 测试版授信使用申请书 中文空白.pdf | HSBC 原始业务文件 | 中文申请书空白模板 | `01_汇丰业务文件/测试版授信使用申请书 中文空白.pdf` | HSBC 提供（原始） | 已整理 |
| 测试版授信使用申请书 英语空白.pdf | HSBC 原始业务文件 | 英文申请书空白模板 | `01_汇丰业务文件/测试版授信使用申请书 英语空白.pdf` | HSBC 提供（原始） | 已整理 |
| 测试版授信函 - 中文空白.pdf | HSBC 原始业务文件 | 中文授信函空白模板 | `01_汇丰业务文件/测试版授信函 - 中文空白.pdf` | HSBC 提供（原始） | 已整理 |
| 02_团队方案与作品（文件夹） | 团队方案与作品 | 方案、Demo 和作品集中放这里 | `02_团队方案与作品/` | 8 组 | 持续更新 |
| 03_第8题Demo_贷款审核助手.html | 团队方案与作品 | 当前第 8 题 Demo | `02_团队方案与作品/03_第8题Demo_贷款审核助手.html` | 8 组 | 当前版本 |
| 09_汇丰跨境业务竞赛_系统构思.docx | 团队方案与作品 | 系统方案底稿 | `02_团队方案与作品/09_汇丰跨境业务竞赛_系统构思.docx` | 8 组 | 持续更新 |
| 12_金融Campaign项目需求梳理及软件策划_改进版.md | 团队方案与作品 | 方案、MVP 和交付要求 | `02_团队方案与作品/12_金融Campaign项目需求梳理及软件策划_改进版.md` | 8 组 | 持续更新 |
| 03_会议记录（文件夹） | 会议记录 | 启动会材料、视频和提炼后的会议记录 | `03_会议记录/` | 8 组 | 持续补充 |
| Infra 资源（工作表） | Infra 资源 | ECS、PostgreSQL 和 API 配置与访问凭据 | `8组项目Master.xlsx → Infra资源` | 8 组共享文件夹 / 04infra 资源 | 已汇总 |

---

## 版本记录

- **2026-10-20**：从 Excel Master 迁移为 Markdown，补充最新模块进展和 API 明文配置
- **2026-10-19**：AI 助手与 RAG 模块交接完成
- **2026-10-16**：Mock Demo 完成，规则引擎与前端框架就绪

---

**维护说明**：本文档由 Excel `8组项目Master.xlsx` 迁移而来，后续维护直接编辑此 Markdown 文件，不再同步更新 Excel。重大架构变更、团队分工调整、基础设施变更时及时更新对应章节。
