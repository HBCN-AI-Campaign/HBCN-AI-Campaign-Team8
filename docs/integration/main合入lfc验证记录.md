# main → lfc 合并验证

> 2026-10-22。本轮只交付 `lfc`，不提交、推送或合入 `main`。根目录 `AGENTS.md` 对所有会话适用。

## 合入范围

- 原 `lfc`：`b36fec1`，保留助手、OpenCode SDK runtime、RAG、SDK、React 入口、依赖、测试、团队总档与最新 RAG 架构文档。
- `main`：先接入 `5e4926c`，再接入执行期间新到达的 `9e56048`。保留客户关联、任务状态、字段修改后重新核对、单据关系图、OCR 服务与真实解析接线、种子规则结果。
- 处理了首轮 52 个冲突路径及未报冲突的配套删除；第二轮合并保留 OCR 配置、助手/RAG 配置模板与 PyYAML 依赖。
- 保留 main 对旧 OCR 演示目录、演示仓库引用和旧原型的清理。
- 补齐原 lfc 已存在但接线不完整的助手知识检索：使用 `business_rules` 适配器、独立超时、契约与范围校验；测试改为检查这个真实边界，不修改 RAG 适配器实现。

## 验证范围

| 项目 | 结果 |
|---|---|
| 主前端 | TypeScript + Vite 构建通过；30 项测试通过 |
| RAG 后端 | 202 项测试完成：189 通过，13 项外部 PostgreSQL 条件测试跳过 |
| RAG 前端 | 类型检查、构建通过；17 项测试通过。并发负载下首次出现一项 30 秒超时，单 worker 完整重测通过 |
| OpenCode runtime | 类型检查、打包通过；3 项测试通过，包含源码与独立构建包的 SDK 工具调用/鉴权集成测试 |
| Python 调用 SDK | 8 项测试通过 |
| 主后端 | 106 项回归测试全部通过；包含主应用启动、客户/任务/助手共存、字段修改、OCR HTTP 契约、种子数据重复执行 |

后端业务测试使用独立内存数据库，OCR 和模型响应使用测试服务；这些结果不等于真实 OCR 识别准确率、汇丰模型可用性或生产 PostgreSQL 已验收。

## 同事怎么验证

先拉取 `lfc`，使用它自己的依赖和配置模板。不要用旧 main 的依赖文件覆盖它。

后端在 `code/backend` 中运行（PowerShell；已有 Python 虚拟环境后）：

```powershell
.venv\Scripts\python -m pip install -r requirements.txt
# 使用新的测试库，不覆盖现有 loan_review.db。
$env:DATABASE_URL = 'sqlite:///./lfc-main-preview.db'
$env:OCR_BASE_URL = 'http://127.0.0.1:7888'  # 按实际 OCR 服务地址调整
.venv\Scripts\python -m app.seed
.venv\Scripts\python -m uvicorn app.main:app --port 8000
```

前端在 `code/frontend` 运行 `npm ci`、`npm run dev`。若后端不是 8000，在 `.env.local` 设置 `HBCN_API_TARGET`。助手/RAG 还需依照各模块 README 启动独立服务并在服务端配置凭证。

重点点验：客户搜索与建任务 → 上传材料与字段定位 → 修改字段后规则重算 → 启动审核/待复核/补件 → 单据关系图 → 审核员助手与知识引用。

## 尚需联调的边界

1. **旧数据库迁移**：main 新增 `customer_id / needs_recheck` 并更改任务状态；`create_all` 不会升级旧表。新测试库可验证本轮代码，已有业务库需另行备份并评审迁移，不能把旧 `reviewing` 自动当成“已完成”。`reset_db.sh` 是清库脚本，不是迁移工具，本轮未执行。
2. **真实 OCR**：主业务已经调用 `/file/detailed`、按需调用 `/extract`；需在同事实际环境检查服务可达性、字段准确率与定位坐标。OCR 异常时仍沿用 main 的空字段降级行为。
3. **RAG 的 OCR 地址**：RAG 现有配置可能经 `/ocr` 反向代理，不能因新服务目录出现便直接改掉路径；部署联调时确认代理与服务端口。
4. **在途工作**：原工作区其他会话未提交的技能/协作功能与文档继续保留；本轮不把这些新增功能混入合并交付，除上述已验证的检索接线修复。
