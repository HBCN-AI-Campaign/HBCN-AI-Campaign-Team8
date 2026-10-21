# 慧眼助手 UI 调研笔记（React 重构参考）

> 历史调研记录：其中“主抄 assistant-ui / vercel chatbot”是 React 迁移前的候选方案，不是当前依赖决策。助手现已采用 Ant Design X；当前评估与多人协作方案见[接入说明](README.md)及[多人协作调研](多人协作AI对话调研与优化方案.md)。不要按本笔记安装 Vue 或整套替代后端。

> 目的：为「AI 助手模块独立 React 重构」做 UI 调研，记录值得吸收的特性与对应可抄代码的仓库/路径。
> 更新：2026-10-20

## 一、头部项目速览（2026-10-20 实测）

| 项目 | Stars | 技术栈 | 定位 | 对我们最有用处 |
|---|---|---|---|---|
| [assistant-ui](https://github.com/assistant-ui/assistant-ui) | 12.6k | React + TS（YC 背书） | 生产级 AI 聊天组件库（headless primitives + shadcn 风格） | **主抄对象**：聊天 UI 全套组件 |
| [CopilotKit](https://github.com/CopilotKit/CopilotKit) | 38.1k | React/Vue/Angular | Agent-native 应用：Generative UI、共享状态、HITL、AG-UI 协议 | 工具调用渲染、HITL、activity 事件 |
| [vercel/chatbot](https://github.com/vercel/chatbot) | 21k | Next.js + shadcn/ui + AI SDK | 官方完整可改的聊天模板（DB/鉴权/artifacts 齐全） | 整体工程骨架、Markdown/来源面板 |
| [lobehub/lobehub](https://github.com/lobehub/lobehub)（原 lobe-chat） | 83k | React + TS | Agent 运营平台，**插件/Agent 市场**、函数调用可视化 | **技能商店**交互参考 |
| [open-webui](https://github.com/open-webui/open-webui) | 156k | Python + Svelte | 自托管 AI 界面（RAG/工具/工作区/多模型） | 引用面板、工作区、会话管理 |
| [LibreChat](https://github.com/LibreChat-AI/LibreChat) | 46k | React + TS | 增强版 ChatGPT 克隆，**Agents / MCP / Skills** | **Skills 商店**、多用户、artifacts |
| [NextChat](https://github.com/ChatGPTNextWeb/NextChat) | 89k | React/Next | 零配置聊天 | 会话管理、流式、重新生成 |

> 结论：**聊天气泡/输入框/会话栏直接抄 assistant-ui；整体工程骨架参考 vercel/chatbot；技能商店参考 lobe-chat + LibreChat 的 Skills。**

## 二、值得吸收的特性（按我们需求映射）

### 1. 执行步骤「冒泡」活动流（核心需求）
- 现象：AI 回复时实时闪现「正在执行哪一步、在干什么」，完成后折叠。
- 参考：
  - assistant-ui `chainOfThought` / `reasoning` primitives（步骤展示）
  - CopilotKit 的 activity / tool-call 实时渲染
  - Cursor / Claude Code 的 step 闪现动效（非开源，抄交互观感）
- 落地：我们后端已有 `step` / `tool` SSE 事件，只需前端做成「执行中展开+跳动、完成后折叠成『执行记录 · N 步』」。对应代码路径：
  - `assistant-ui/packages/react/src/primitives/chainOfThought*`
  - `assistant-ui/packages/react/src/primitives/reasoning*`

### 2. 会话列表 + 存档（已做）
- 参考 assistant-ui `threadList` / `threadListItem` / `threadListItemMore`（列表 + 更多菜单），vercel/chatbot 的 chat 侧栏（历史 + 删除）。
- 路径：`assistant-ui/packages/react/src/primitives/threadList*`、`threadListItem*`

### 3. Markdown 流式 + 表格 + 代码高亮
- 参考 vercel/chatbot 的 markdown 组件（`react-markdown` + `remark-gfm` + `shiki` 高亮），assistant-ui `messagePart`。
- 路径：`vercel/chatbot/components/markdown.tsx`、`vercel/chatbot/components/chat/message.tsx`

### 4. 技能商店（丰富 + 自定义创建）
- 参考 lobe-chat 的 plugin/agent 市场（卡片式 + 分类 + 搜索），LibreChat 的 Skills 目录。
- 落地：右侧窄栏 → 卡片列表（图标/名称/说明），点击触发结构化 prompt；「+ 创建技能」走弹窗表单（本地暂存或后续落库）。
- 路径：`lobehub/lobehub` 中 marketplace/plugin 相关组件；`LibreChat-AI/LibreChat` 中 skills 相关组件。

### 5. 建议追问（suggestion pills）
- assistant-ui `suggestion` primitive、vercel/chatbot 的回答后追问按钮。
- 路径：`assistant-ui/packages/react/src/primitives/suggestion*`

### 6. 停止生成 / 重新生成 / 分支
- assistant-ui `actionBar` / `branchPicker`，NextChat 的 regenerate。
- 路径：`assistant-ui/packages/react/src/primitives/actionBar*`、`branchPicker*`

### 7. 附件上传（未来 OCR/文件）
- assistant-ui `attachment` primitive。
- 路径：`assistant-ui/packages/react/src/primitives/attachment*`

### 8. 引用/来源面板
- open-webui 的 RAG citations、vercel/chatbot 的 sources。
- 路径：`vercel/chatbot/components/chat/sources.tsx`

### 9. 人工确认卡（HITL，未来）
- assistant-ui 的 approval card、CopilotKit 的 HITL 工作流。
- 路径：CopilotKit 文档 HITL 示例。

## 三、落地时的抄代码清单

| 要做的事 | 抄哪个仓库 | 具体路径 | 抄什么 |
|---|---|---|---|
| 聊天组件整套 | assistant-ui | `packages/react/src/primitives/` | thread、threadList、composer、message、messagePart |
| 步骤/推理展示 | assistant-ui | `packages/react/src/primitives/chainOfThought*`、`reasoning*` | 执行步骤时间线 |
| 建议追问 | assistant-ui | `packages/react/src/primitives/suggestion*` | 追问按钮 |
| 消息操作 | assistant-ui | `packages/react/src/primitives/actionBar*`、`branchPicker*` | 复制/停止/重新生成 |
| Markdown + 高亮 | vercel/chatbot | `components/markdown.tsx` | react-markdown + gfm + shiki |
| 聊天侧栏 | vercel/chatbot | `components/chat/` | 历史 + 删除交互 |
| 工程骨架 | vercel/chatbot | 根目录 + `app/` | Next.js + shadcn + drizzle 结构 |
| 技能市场 | lobehub/lobehub | marketplace/plugin 组件 | 卡片式技能商店 |
| Skills 目录 | LibreChat | skills 相关组件 | 技能定义/触发 |

## 四、下一步建议

1. 先用 assistant-ui 的 CLI 脚手架起一个独立 React 工程：`npx assistant-ui@latest create`（或 `init` 到现有工程）。
2. 三栏布局用它的 `Thread` + `ThreadList` 组合；`Composer` 做输入；`Message` + 自定义 `messagePart` 渲染 Markdown/表格/引用。
3. 执行步骤用 `chainOfThought`/`reasoning` 风格渲染我们后端的 `step`/`tool` SSE 事件。
4. 技能商店照 lobe-chat 的卡片式市场做，自定义技能先走前端弹窗 + localStorage。
5. 落地前把 assistant-ui / vercel/chatbot 仓库 clone 到本地 `github-demos/` 下对照抄，不直接引入其完整后端。
