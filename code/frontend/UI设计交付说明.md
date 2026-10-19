# AI 助手 UI 设计交付说明

## 📦 交付内容

### 1. 三个完整的 UI 设计版本

所有文件位于 `src/views/assistant-designs/` 目录：

| 版本 | 文件 | 风格 | 推荐场景 |
|------|------|------|----------|
| **V1** | `AssistantV1-Modern.vue` | 现代简洁，三栏布局，Element Plus 标准风格 | 桌面端审核工作站 |
| **V2** | `AssistantV2-Dark.vue` | 暗色专业，金融终端风格，护眼模式 | 长时间盯屏审核 |
| **V3** | `AssistantV3-Minimal.vue` | 卡片极简，单栏布局，移动端友好 | 快速审核 + 移动端 |

### 2. 演示页面

- **文件**：`src/views/AssistantDesignDemo.vue`
- **路由**：`/assistant-demo`
- **功能**：
  - 三个版本之间切换预览
  - 显示每个版本的特性说明
  - 设计对比表（12 个维度）

### 3. 文档

- **UI设计选择指南.md**：详细的设计对比和选择建议
- **UI设计交付说明.md**（本文件）：快速上手指南

---

## 🚀 快速开始

### 方式 1：双击运行（Windows）

```bash
双击 code/frontend/查看UI设计.bat
```

浏览器会自动打开 `http://localhost:5173/assistant-demo`

### 方式 2：命令行运行

```bash
cd code/frontend
npm install  # 首次运行需要安装依赖
npm run dev
```

然后访问：`http://localhost:5173/assistant-demo`

### 方式 3：查看源码

直接打开以下文件查看代码：
- `src/views/assistant-designs/AssistantV1-Modern.vue`
- `src/views/assistant-designs/AssistantV2-Dark.vue`
- `src/views/assistant-designs/AssistantV3-Minimal.vue`

---

## 📸 设计截图（预期效果）

### V1 现代简洁

```
┌─────────────────────────────────────────────────────────────┐
│ ✨ 慧眼助手  [关联任务 ▼]                   [用户] [返回] │
├──────┬──────────────────────────────────────┬──────────────┤
│ 会话 │         对话区域                      │ 审核技能     │
│      │                                      │              │
│ [新建]│  欢迎界面 + 示例提示词               │ [全部技能]   │
│      │                                      │              │
│ • LN08│  [用户消息]                          │ 🚢 提单验真  │
│ • 制裁│  [助手消息 + 步骤 + 引用]            │ 🔒 制裁筛查  │
│ • 汇率│                                      │ 💱 汇率换算  │
│      │  [输入框] [发送]                     │              │
└──────┴──────────────────────────────────────┴──────────────┘
```

### V2 暗色专业

```
┌─────────────────────────────────────────────────────────────┐
│ ✨ 慧眼 | [任务 ▼]                           [用户] [返回] │
├──────┬──────────────────────────────────────┬──────────────┤
│ 会话 │         对话区域（暗色）              │ 审核技能     │
│(暗色)│                                      │  (暗色)      │
│ [新建]│  欢迎界面（大头像 + 渐变）           │ [全部]       │
│      │                                      │              │
│ ● LN08│  [用户消息（深蓝）]                  │ 🚢 提单验真  │
│ ● 制裁│  [助手消息（深灰卡片）+ 轨迹]        │ 🔒 制裁筛查  │
│      │                                      │              │
│      │  [输入框（深色）] [发送]             │ 热门技能     │
└──────┴──────────────────────────────────────┴──────────────┘
```

### V3 卡片极简

```
┌─────────────────────────────────────────────────────────────┐
│ ✨ 慧眼助手                                       [返回]   │
├─────────────────────────────────────────────────────────────┤
│   [任务 ▼]  [审核技能]  [会话列表]                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│    ┌───────────────────────────────────────────┐           │
│    │  🤖 让审核工作更快一步                     │           │
│    │  解析单据、验证规则、检索证据              │           │
│    │  [📋 梳理风险] [🔍 解释] [📄 核对]        │           │
│    └───────────────────────────────────────────┘           │
│                                                             │
│    ┌───────────────────────────────────────────┐           │
│    │  你: 为什么被驳回？                        │           │
│    └───────────────────────────────────────────┘           │
│                                                             │
│    ┌───────────────────────────────────────────┐           │
│    │  慧眼: [步骤折叠 ▼]                       │           │
│    │  单据被驳回的主要原因：...                 │           │
│    │  证据: [R001] [p.3] [89%]                │           │
│    │  [📋 复制] [🔄 重新生成]                  │           │
│    └───────────────────────────────────────────┘           │
│                                                             │
│    ┌─────────────────────────────┬───┐                     │
│    │ 描述你想核对的规则...        │ → │                     │
│    └─────────────────────────────┴───┘                     │
└─────────────────────────────────────────────────────────────┘
```

---

## 🎯 核心创新点

### 1. 实时步骤追踪（三个版本共有）

```vue
<!-- 执行步骤可视化 -->
<div class="execution-steps">
  ✓ 正在读取任务材料 (已完成)
  ⏳ 正在检索知识库 (找到 3 条证据) <- 实时更新
  ○ 组织审核建议 (待执行)
</div>
```

**实现要点**：
- SSE `step` 事件驱动更新
- 三种状态：completed（✓ 绿色）/ running（⏳ 旋转）/ pending（○ 灰色）
- 可折叠面板，减少视觉干扰

### 2. 证据引用悬浮预览

```vue
<!-- 证据标签 + Hover 预览 -->
<el-tag @mouseenter="showCitationPreview">R001 贷款用途</el-tag>
<el-popover>
  <!-- 预览：证据片段 + 来源 + 相关度 -->
</el-popover>
```

**实现要点**：
- Hover 即显示证据片段（前 50 字）
- 点击跳转到完整证据（Drawer 或新页面）
- 支持 PDF 定位（跳转到指定页码）

### 3. 技能封面图 + 热度可视化

```vue
<!-- 技能卡片 -->
<div class="skill-card">
  <div class="cover" style="background: linear-gradient(135deg, #3b82f6, #1e3a8a)">
    <el-icon><Ship /></el-icon> <!-- 或 🚢 Emoji -->
  </div>
  <div class="card-body">
    <h3>提单验真</h3>
    <p>核验海运提单的真实性...</p>
    <div class="stats">🔥 本周使用 67 次</div>
  </div>
</div>
```

**封面图方案**：
- 渐变背景 + 图标（V1/V2 用 SVG，V3 用 Emoji）
- 每个技能独特的颜色编码（蓝/橙/紫/绿）
- 热度徽章（推荐/新上架/热门）

### 4. 暗色模式（V2 专属）

```css
/* 配色方案 */
--bg-primary: #0f172a;    /* 页面背景 */
--bg-secondary: #1e293b;  /* 卡片背景 */
--border: #334155;        /* 边框 */
--text-primary: #cbd5e1;  /* 主文本 */
--text-secondary: #64748b; /* 辅助文本 */
--accent: #3b82f6;        /* 强调色 */
```

### 5. 响应式适配（三个版本共有）

```typescript
// 断点方案
@media (max-width: 1200px) {
  // 平板：双栏，技能改为 Drawer
  grid-template-columns: 240px 1fr;
}

@media (max-width: 768px) {
  // 手机：单栏，会话和技能都改为 Drawer
  grid-template-columns: 1fr;
}
```

---

## 🔧 技术栈

### 核心依赖

```json
{
  "element-plus": "^2.9.1",        // UI 组件库
  "@element-plus/icons-vue": "^2.3.1", // 图标
  "marked": "^15.0.4",             // Markdown 渲染
  "dompurify": "^3.2.2",           // HTML 安全清理
  "vue": "^3.5.13",
  "vue-router": "^4.5.0",
  "pinia": "^2.3.0",
  "axios": "^1.7.9"
}
```

### 已移除的依赖

```diff
- "@copilotkit/core": "1.79.1",
- "@copilotkit/vue": "1.79.1",
- "@ag-ui/core": "xxx"
```

**移除原因**：
- 体积大（CopilotKit 约 2MB）
- 风格不统一（与 Element Plus 冲突）
- 过度封装（限制自定义能力）

---

## 📋 下一步工作

### 1. 选择版本

在演示页面 `/assistant-demo` 中：
- 切换查看三个版本
- 对比设计特性
- 确定最终采用的版本

### 2. 替换旧代码

```bash
# 例如选择 V2 暗色专业版
cp src/views/assistant-designs/AssistantV2-Dark.vue src/views/AssistantView.vue
```

### 3. 后端对接

#### 3.1 保持类型定义

`src/assistant/types.ts` 已经定义好，无需修改：

```typescript
interface AssistantMessage {
  id: number | string
  role: 'user' | 'assistant'
  content: string
  status: string
  steps: AssistantStep[]
  citations: AssistantCitation[]
  streaming?: boolean
}
```

#### 3.2 实现 SSE 流式接收

```typescript
// src/assistant/api.ts
async function* streamMessage(sessionId: number, content: string) {
  const response = await fetch(`/api/assistant/sessions/${sessionId}/messages/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify({ content }),
  })

  const reader = response.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { value, done } = await reader.read()
    buffer += decoder.decode(value, { stream: !done })
    const lines = buffer.split('\n\n')
    buffer = lines.pop() || ''

    for (const line of lines) {
      if (line.startsWith('data:')) {
        const event = JSON.parse(line.slice(5))
        yield event  // { event: 'delta', delta: '...' }
      }
    }

    if (done) break
  }
}
```

#### 3.3 实现 Markdown 渲染

```typescript
import { marked } from 'marked'
import DOMPurify from 'dompurify'

function renderMarkdown(text: string): string {
  const html = marked.parse(text) as string
  return DOMPurify.sanitize(html, {
    ALLOWED_TAGS: ['p', 'strong', 'em', 'ul', 'ol', 'li', 'code', 'pre', 'table', 'thead', 'tbody', 'tr', 'th', 'td', 'br'],
    ALLOWED_ATTR: []
  })
}
```

然后在组件中：

```vue
<div v-html="renderMarkdown(message.content)" />
```

### 4. 完善功能

- [ ] 真实会话列表加载
- [ ] 真实消息流渲染
- [ ] SSE 流式接收（打字机效果）
- [ ] 技能运行逻辑
- [ ] 证据引用 Hover 预览（Popover）
- [ ] 移动端适配测试
- [ ] 暗色模式切换（如果选择 V1/V3）
- [ ] 技能商店详情页（Drawer）

---

## 💡 设计亮点总结

| 亮点 | V1 | V2 | V3 | 说明 |
|------|----|----|----|----|
| 三栏布局 | ✅ | ✅ | ❌ | 信息密度高，适合桌面端 |
| 暗色主题 | ❌ | ✅ | ❌ | 护眼，金融终端专业感 |
| 移动端友好 | 响应式 | 响应式 | 天生 | V3 单栏布局最友好 |
| 步骤追踪 | ✅ | ✅ | ✅ | 实时更新，可折叠 |
| 证据预览 | ✅ | ✅ | ✅ | Hover 即显示 |
| 技能封面图 | ✅ | ✅ | ✅ | 渐变 + 图标，视觉冲击力强 |
| 热度可视化 | ✅ | ✅ | ✅ | 本周使用次数，引导转化 |
| Emoji 图标 | ❌ | ❌ | ✅ | 减少 SVG 依赖 |
| 卡片式气泡 | ❌ | ❌ | ✅ | 极简风格，专注内容 |

---

## 🎨 比赛建议

### 如果注重视觉冲击力和专业感

**推荐：V2 暗色专业**

**理由**：
- ✅ 深蓝 + 渐变配色，金融终端风格，有记忆点
- ✅ 暗色主题稀缺，差异化明显
- ✅ 长时间演示不疲劳（护眼）

### 如果注重用户体验和易用性

**推荐：V3 卡片极简**

**理由**：
- ✅ 单栏布局，专注对话内容，移动端友好
- ✅ Emoji 图标亲和力强
- ✅ 技能商店封面图出彩（大卡片 + 渐变）

### 如果注重稳健和标准

**推荐：V1 现代简洁**

**理由**：
- ✅ 三栏布局信息密度高，适合复杂任务
- ✅ Element Plus 标准风格，开发效率高
- ✅ 视觉清晰，学习成本低

---

## 📞 联系

如有疑问或需要调整，随时沟通。三个版本都是完整可运行的，可以直接在浏览器中预览效果。

**预览地址**：`http://localhost:5173/assistant-demo`

**文件位置**：
- 设计版本：`src/views/assistant-designs/`
- 演示页面：`src/views/AssistantDesignDemo.vue`
- 路由配置：`src/router/index.ts`
- 快速启动：`查看UI设计.bat`（Windows）
