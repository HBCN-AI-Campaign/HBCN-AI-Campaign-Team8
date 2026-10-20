# 境外贷款单据智能审核平台 · React 前端

自有页面统一为 React 18 + TypeScript + Vite，使用 Ant Design 5、React Router 6、Zustand。登录、工作台、创建任务、任务审核、PDF 定位和慧眼助手均为 `.tsx`，没有保留第二套页面入口。

## 运行

建议 Node.js 22 LTS，锁文件使用公开 npm registry：

```powershell
npm ci
npm run dev -- --host 127.0.0.1
npm test
npm run build
```

访问 `http://127.0.0.1:5173`，登录后从顶栏进入 `/assistant`。默认将 `/api`、`/pdf`、`/uploads` 转发至主业务后端 `http://127.0.0.1:8000`。

端口冲突时复制 `.env.example` 为 `.env.local` 并修改 `HBCN_API_TARGET`，随后重启 Vite。本机主后端在 8001 时设置 `HBCN_API_TARGET=http://127.0.0.1:8001`。RAG 默认端口 8010，不能作为主站代理地址。

前端不存储模型 key。主后端通过私网 OpenCode runtime 调用汇丰模型 API，配置和时序见 [助手文档](../../docs/ai-assistant/README.md)。同学拉取后仍须取得授权的服务端环境配置；仓库不分发凭证，不依赖个人 CC Switch。

## 页面与模块

| 路由/目录 | 职责 |
| --- | --- |
| `/login` | 登录并返回原访问地址 |
| `/dashboard`、`/create`、`/tasks/:code` | 工作台、发起任务、审核及 PDF 定位 |
| `/assistant?task_code=任务编号` | 助手问答，可选任务上下文 |
| `src/assistant/api.ts` | 带 JWT 的 JSON 请求和可取消 SSE |
| `src/assistant/useAssistant.ts` | 会话切换、并发保护、生成生命周期 |
| `src/views/AssistantView.tsx` | Ant Design X Sender / Bubble / Conversations / ThoughtChain 业务组合 |
| `src/assistant/markdown.ts` | marked + DOMPurify，清洗不可信输出 |
| `tests/` | 真实组件交互、分片 SSE、401 与 Markdown 安全回归 |

助手按路由懒加载。生成时显示业务执行进度，完成后自动折叠；只显示后端明确发布的业务事件，不展示模型内部推理。停止操作取消接收，不表示撤销服务端写入。会话按用户隔离，切换任务开启新会话。

## 部署

`npm run build` 输出 `dist/`。静态服务器对前端路径（包括 `/assistant`）回退至 `index.html`；`/api` 必须代理至 FastAPI，不能回退成 HTML。还需代理 `/pdf` 和 `/uploads`；SSE 关闭代理缓冲并设置足够的读超时。`HBCN_API_TARGET` 仅配置 Vite 开发代理，不配置生产 Web 服务器。

知识库工作台已由对应模块迁为 React，在 `../rag-service/ui` 独立构建，并由 RAG 服务提供 `/ui/`；本模块不改其业务实现。
