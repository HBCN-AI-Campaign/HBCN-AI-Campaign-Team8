# main 合入 lfc：冲突评审

> 本文保留执行前的冲突快照。实际交付范围已扩展至 main `9e56048` 与 lfc `b36fec1`，结果见 [合并验证记录](main合入lfc验证记录.md)。当前只交付 lfc，禁止写入 main。

> 2026-10-22 · main `5e4926c` → lfc `1b9f78e`，共同祖先 `f722291`。已刷新远端引用并用 `merge-tree` 预演，未实际合并、提交或推送。以下不包含本机尚未提交的修改。

**先把 main 合入 lfc，交付同事验证；当前暂不合回 main，最高优先级规则见根目录 AGENTS.md。不能直接接受 Git 的默认处理结果。**

- **52 个冲突文件：47 个“main 删除、lfc 修改”，5 个双方内容冲突。**
- **另有 109 个路径会被自动删除，不报冲突。** 有些是合理清理，有些会破坏助手/RAG 的完整性，不能只处理那 52 个文件。
- 冲突多的重要原因是 main 的回退记录，尤其 `e47c589`：标题是回退 RAG 发布，但实际也移除了助手、runtime 和相关配置。提交说明没有解释业务取舍，不能据此认定团队要永久取消这些模块。

## 1. 哪些合理，哪些必须拦住

这里评的是“能否作为本次合并结果”，不据此判断同事当时回退是否合理。以下建议以**继续保留 lfc 的助手和 RAG 功能**为目标。

| 项目 | 要紧程度 | 判断与建议 |
|---|---|---|
| main 新增客户管理、字段编辑后重新核对、单据关系图 | 要紧 | **合理增量，应该保留。** 包括 `routers/customers.py`、任务接口、`ObjectGraph.tsx` 等，不应为了保住助手而整包覆盖 main |
| main 的新任务状态与数据库字段 | 很要紧 | **方向可以接受，但必须统一。** 新状态为 `pending / ai_reviewing / to_recheck`，原来为 `created / reviewing / supplemented`；新增 `customer_id / needs_recheck`。保留新业务流程，同时检查助手上下文、接口消费者和旧数据迁移，不能机械映射状态 |
| 删除助手、RAG、runtime 的源码和入口 | 很要紧 | **若照搬到本轮保留功能的合并中，不合理。** 应保留这些模块及配套文件，再接上 main 的业务变化；先确认先前回退的原因和此次恢复范围 |
| 保留助手页面，却丢掉依赖、Markdown 渲染和测试支持 | 很要紧 | **明显不能接受这种组合。** 预演已出现文件残留但配套被删除的情况，不能只在冲突处点“保留 lfc” |
| `AGENTS.md` 自动变回 Vue/Pinia，并称没有自动化测试 | 要紧 | **与源码不符，不能接受。** main 自己仍是 React；应保留当前技术栈和测试约定 |
| Vite 代理自动变成固定 8000，失去 `HBCN_API_TARGET` | 一般 | **配置能力回退，不建议接受。** 默认 8000 可以保留，同时保留可配置地址 |
| 新增 `code/ocr_service`，清理旧 `ocr_demo` | 一般 | **迁移方向合理，接线要补。** RAG 仍按旧地址/路径调用，见下方；主业务 `parse_files` 也仍为桩，服务目录存在不等于主站已接入 |
| 样式、旧原型、演示仓库、缓存等 | 较轻 | 对运行主链路影响较小，通常可以按当前用途整理；但运行脚本、知识索引不能混作旧资料删除。TEAM_MASTER 仍应保留为协作入口 |

**数据库注意：** main 的启动仍使用 `create_all`，在其后端目录未看到对应旧表/旧状态迁移脚本。已有数据库不能仅以“新库能启动”作为验收；本轮尚未连接或修改任何数据库。

## 2. 五个真正的内容冲突

| 文件 | 实际分歧 | 建议 |
|---|---|---|
| `code/backend/.env.example` | main 删除助手/RAG 配置，lfc 调整配置 | 合并配置项，保留主业务、助手、RAG 所需变量，仅放模板值 |
| `code/backend/app/config.py` | main 移除 runtime/RAG 相关设置，lfc 继续维护它们 | 保留助手、runtime、RAG 配置，与最终环境模板对应 |
| `code/backend/app/models.py` | main 删除旧助手表定义并增加客户/任务变化；lfc 更新助手时间类型 | 同时保留助手表与时间处理、main 的客户/任务模型；配套处理旧数据 |
| `code/frontend/src/layouts/MainLayout.tsx` | main 移除助手按钮；lfc 增加审核员可见限制 | 保留助手入口与角色限制，兼容 main 布局。补齐按钮、图标、路径状态等导入和变量 |
| `code/frontend/src/router/index.tsx` | main 移除助手路由；lfc 增加审核员路由保护 | 保留受保护的助手路由及全部业务路由，补齐懒加载等导入 |

最后两项尤其不能只保留冲突块：预演结果已经在块外自动移除了 `Button / RobotOutlined / isAssistant`、`Suspense / Spin / AssistantView` 等依赖的导入或声明。只留下按钮/路由那一行仍不完整。

## 3. 没报冲突，但必须一起处理

这些是未解决冲突的预演树中的结构性问题，尚未实际运行候选代码。

| 预演结果 | 影响与建议 |
|---|---|
| `code/backend/app/main.py` 保留 customers/tasks，却没有挂载 assistant 路由 | 助手文件留下也没有 API 入口；应同时挂载业务与助手路由 |
| `code/frontend/package.json` / 锁文件移除 Ant Design X、marked、DOMPurify、测试工具及 `test` 脚本 | 助手页面仍依赖这些能力；重新整合依赖、脚本和锁文件，不能只恢复页面 |
| 自动删掉 runtime 的 `package.json`、`bun.lock`、`tsconfig.json`、Docker 配置及技能文件 | 源码留下，安装、构建或部署配套不完整；按最终 runtime 版本一起保留 |
| 自动删掉 `code/backend/app/assistant_skills.py`、前端 `assistant/markdown.ts`、`tests/setup.ts` | 仍有源码/测试引用；必须恢复配套，而不是删除调用来凑通过 |
| 自动删掉 RAG 的 `app/database.py`、`local_store.py`、`manifest.py`、知识库索引和 UI 入口等 | RAG 仍引用相关模块；应按实际模块依赖保留，不可把整个删除组当清理 |
| `AGENTS.md` 和 `code/frontend/vite.config.ts` 自动采用 main 的旧约定 | 前者会误导后续 AI 开发，后者会丢可配置代理；需要主动修正 |
| RAG 默认 `OCR_BASE_URL` 为 8001，并拼接 `/ocr/file`；新 OCR 文档为 7888、直接路由 `/file`，约定由反代剥 `/ocr` | 统一部署地址与反代契约，再做一次实际调用；不能直接换端口就认定兼容 |

109 个自动删除路径的分布：runtime 13、主后端 1、主前端 5、RAG 27、旧 OCR demo 30、文档 16、演示仓库 14、原型 3。**这不是 109 个都必须恢复**；运行依赖和合理清理要分别判断。

## 4. 其余 47 个删除/修改冲突：完整清单

以下全部是 main 删除、lfc 继续修改；与第 2 节的 5 个文件合计 52 个。

### runtime：3 个，模块完整性要紧

```text
code/assistant-runtime/.env.example
code/assistant-runtime/src/index.ts
code/assistant-runtime/src/runtime.integration.test.ts
```

### 后端助手/RAG 接线：6 个，功能与回归要紧

```text
code/backend/app/assistant_schemas.py
code/backend/app/assistant_service.py
code/backend/app/rag_service.py
code/backend/app/routers/assistant.py
code/backend/tests/test_assistant_api.py
code/backend/tests/test_rag_service.py
```

### 前端助手：7 个，接口/交互要紧，纯样式较轻

```text
code/frontend/src/assistant/api.ts
code/frontend/src/assistant/types.ts
code/frontend/src/assistant/useAssistant.ts
code/frontend/src/views/AssistantView.css
code/frontend/src/views/AssistantView.tsx
code/frontend/tests/assistant-view.test.tsx
code/frontend/vitest.config.ts
```

### RAG：23 个，源码/存储/依赖要紧，说明和纯样式较轻

```text
code/rag-service/.env.example
code/rag-service/README.md
code/rag-service/app/answer_graph.py
code/rag-service/app/backend_api.py
code/rag-service/app/config.py
code/rag-service/app/document_store.py
code/rag-service/app/embedding.py
code/rag-service/app/engine.py
code/rag-service/app/main.py
code/rag-service/app/ocr.py
code/rag-service/app/parsing.py
code/rag-service/app/postgres_engine.py
code/rag-service/app/runtime_client.py
code/rag-service/app/schemas.py
code/rag-service/requirements.txt
code/rag-service/tests/test_embedding.py
code/rag-service/tests/test_postgres_backend.py
code/rag-service/tests/test_ragflow.py
code/rag-service/ui/package-lock.json
code/rag-service/ui/package.json
code/rag-service/ui/src/App.tsx
code/rag-service/ui/src/api.ts
code/rag-service/ui/src/styles.css
```

### 总档、说明与原型：8 个，运行风险较低，协作入口仍要保留

```text
TEAM_MASTER.md
docs/RAG后端验收与运行.md
docs/README.md
docs/ai-assistant/OpenCode-升级选型与实施方案.md
docs/ai-assistant/README.md
docs/ai-assistant/决策记录.md
docs/ai-assistant/多人协作AI对话调研与优化方案.md
mockup/mockup_assistant_collab.html
```

## 5. 建议怎么处理这一轮

**保留 main 的业务增量，也保留 lfc 的助手/RAG；逐项撤销不符合本轮目标的删除，再适配接口和数据库。** 这不是整包保留任一分支。

先确认两件事：①此次助手/RAG 恢复的范围及先前回退原因；②任务状态采用哪套口径、旧数据库怎样迁移。然后在独立工作区生成候选，验证业务任务流程、助手→RAG→runtime 链路、OCR 接线以及前后端构建/回归。最后更新实际 lfc，供同事运行验证。暂不合回 main。

本机 TEAM_MASTER、助手服务/配置/测试和多份文档还有未提交修改，其他会话也在新增资料；这些不在上面的提交快照中，真正合并前需单独保存并确认交付范围。本轮只新增本评审 Markdown，不处理这些在途修改。
