# AI 助手 UI 设计版本说明

## 三个版本概览

### V1 - 现代简洁（AssistantV1-Modern.vue）

**一句话总结**：标准企业应用风格，三栏布局，Element Plus 原生设计

**视觉关键词**：
- 🎨 亮色主题
- 📐 三栏布局
- 🔵 蓝色系 (#3b82f6)
- 📦 标准 Element UI 风格

**适用场景**：
- ✅ 桌面端审核工作站
- ✅ 需要同时查看会话/对话/技能
- ✅ 标准企业应用

**核心特点**：
1. 三栏布局（会话 232px + 对话 flex + 技能 300px）
2. Element Plus 原生组件（Tag、Collapse、Button）
3. 清晰的信息层级
4. 响应式设计（平板/手机自动切换）

---

### V2 - 暗色专业（AssistantV2-Dark.vue）

**一句话总结**：金融终端风格，暗色护眼，深蓝渐变

**视觉关键词**：
- 🌙 暗色主题
- 💼 金融终端风格
- 🔷 深蓝黑 (#0f172a)
- ✨ 渐变 + 阴影

**适用场景**：
- ✅ 长时间盯屏审核
- ✅ 夜间或低光环境
- ✅ 需要专业感和信任度

**核心特点**：
1. 暗色主题（护眼模式）
2. 深蓝 + 渐变配色，专业感强
3. 金融终端风格（Bloomberg / 彭博）
4. 执行轨迹可视化清晰

---

### V3 - 卡片极简（AssistantV3-Minimal.vue）

**一句话总结**：单栏卡片布局，移动端友好，Emoji 图标

**视觉关键词**：
- ✨ 极简风格
- 📱 移动端优先
- 🎴 卡片式气泡
- 😊 Emoji 图标

**适用场景**：
- ✅ 移动端审核
- ✅ 快速浏览任务
- ✅ 专注对话内容

**核心特点**：
1. 单栏布局（最大 900px 居中）
2. 卡片式消息气泡
3. Emoji 图标代替 SVG
4. 极简边框，弱化装饰

---

## 快速对比表

| 维度 | V1 现代简洁 | V2 暗色专业 | V3 卡片极简 |
|------|-------------|-------------|-------------|
| **主题** | 亮色 | 暗色 | 亮色（极简） |
| **布局** | 三栏 | 三栏 | 单栏 |
| **配色** | 蓝 #3b82f6 | 深蓝 #1e3a8a | 灰 #374151 |
| **风格** | 企业标准 | 金融终端 | 极简现代 |
| **图标** | SVG | SVG | Emoji + SVG |
| **适合** | 桌面端 | 长时间使用 | 移动端 |
| **信息密度** | 高 | 高 | 中 |
| **视觉冲击力** | 中 | 强 | 中 |
| **开发复杂度** | 中 | 高 | 低 |
| **学习成本** | 低 | 中 | 低 |

---

## 核心共性（三个版本都有）

### 1. 实时步骤追踪

```
✓ 正在读取任务材料 (已完成)
⏳ 正在检索知识库 (找到 3 条证据) <- 实时更新
○ 组织审核建议 (待执行)
```

**实现方式**：
- V1: Element Plus `<el-collapse>` 组件
- V2: 原生 `<details>` 元素 + 自定义样式
- V3: 原生 `<details>` 元素 + 极简样式

### 2. 证据引用标签

```
🏷️ 证据引用:
[R001 贷款用途] [提款申请书 · p.3] [业务规则 · 89%]
```

**交互**：
- Hover 显示证据片段预览（Popover）
- 点击查看完整证据（Drawer）

### 3. 技能商店封面图

```
┌─────────────────────┐
│  [渐变背景 + 图标]   │  <- 蓝色/橙色/紫色/绿色
│      🚢 / Ship       │
│    [推荐/新/热门]    │
├─────────────────────┤
│  提单验真            │
│  核验海运提单...     │
│  🔥 本周 67 次       │
│  [详情] [立即运行]   │
└─────────────────────┘
```

### 4. 响应式适配

```
桌面（≥1200px）: 三栏布局（V1/V2）或单栏（V3）
平板（768-1199px）: 双栏 + Drawer
手机（<768px）: 单栏 + Drawer
```

---

## 推荐选择流程

### 第 1 步：确定使用场景

- **桌面端为主** → V1 或 V2
- **移动端为主** → V3
- **混合场景** → V1 或 V3

### 第 2 步：确定使用时长

- **长时间盯屏（>4小时/天）** → V2（暗色护眼）
- **短时间快速审核（<1小时/天）** → V1 或 V3

### 第 3 步：确定风格偏好

- **标准企业应用** → V1
- **专业金融终端** → V2
- **现代极简风格** → V3

### 第 4 步：确定差异化需求

- **比赛需要视觉冲击力** → V2 或 V3
- **比赛需要稳健可靠** → V1
- **比赛需要易用性** → V3

---

## 实现细节差异

### 技能卡片

**V1 现代简洁**：
```vue
<el-card shadow="hover">
  <div class="skill-icon-wrap">
    <el-icon><Ship /></el-icon>
  </div>
  <div class="skill-name">提单验真</div>
  <el-button size="small" type="primary">立即使用</el-button>
</el-card>
```

**V2 暗色专业**：
```vue
<div class="skill-item">
  <div class="skill-badge">
    <el-icon><Ship /></el-icon>
  </div>
  <div class="skill-text">
    <div class="skill-name">提单验真</div>
    <div class="skill-hint">核验提单关键信息</div>
  </div>
  <el-button size="small" type="primary" round>运行</el-button>
</div>
```

**V3 卡片极简**：
```vue
<div class="skill-box">
  <div class="skill-emoji">🚢</div>
  <div class="skill-label">提单验真</div>
  <button class="skill-run-btn">运行</button>
</div>
```

### 消息气泡

**V1 现代简洁**：
```css
.message-bubble {
  padding: 16px;
  border-radius: 12px;
  border: 1px solid #e2e8f0;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
}
```

**V2 暗色专业**：
```css
.msg-content {
  padding: 16px;
  border-radius: 12px;
  background: #1e293b;
  border: 1px solid #334155;
}
```

**V3 卡片极简**：
```css
.message-card {
  padding: 20px;
  border-radius: 12px;
  background: white;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
}
```

---

## 后端对接说明

所有三个版本共享相同的：

### 类型定义（src/assistant/types.ts）

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

interface AssistantStep {
  key: string
  label: string
  detail?: string
  status: 'running' | 'completed' | 'error'
}

interface AssistantCitation {
  id: string
  label: string
  source: string
  detail?: string
  page?: number | null
  status?: 'pass' | 'fail' | 'warn'
}
```

### SSE 事件格式

```typescript
// 后端发送的 SSE 事件
{
  event: 'step',
  step: { key: 'read_materials', label: '正在读取任务材料', status: 'running' }
}

{
  event: 'delta',
  delta: '单据 LN-008 被驳回的主要原因：'
}

{
  event: 'citations',
  citations: [
    { id: 'R001', label: 'R001 贷款用途', source: 'rule' },
    { id: 'doc_p3', label: '提款申请书', page: 3, source: 'document' }
  ]
}

{
  event: 'message_end',
  message: { id: 123, role: 'assistant', content: '...', status: 'completed' }
}
```

---

## 文件结构

```
src/views/assistant-designs/
├── AssistantV1-Modern.vue      # V1 现代简洁版本（约 800 行）
├── AssistantV2-Dark.vue        # V2 暗色专业版本（约 900 行）
├── AssistantV3-Minimal.vue     # V3 卡片极简版本（约 700 行）
└── README.md                   # 本文件

src/views/
└── AssistantDesignDemo.vue     # 演示页面（约 200 行）

code/frontend/
├── UI设计选择指南.md            # 详细的设计对比和选择建议
├── UI设计交付说明.md            # 快速上手指南
└── 查看UI设计.bat               # Windows 快速启动脚本
```

---

## 快速测试

### 1. 启动演示

```bash
cd code/frontend
npm install  # 首次运行
npm run dev
```

访问：`http://localhost:5173/assistant-demo`

### 2. 切换版本

在演示页面点击顶部的版本按钮：
- 🎨 V1 现代简洁
- 🌙 V2 暗色专业
- ✨ V3 卡片极简

### 3. 查看对比

点击"查看设计对比表"按钮，查看 12 个维度的详细对比

### 4. 确认选择

点击"确定使用此版本"按钮，确认你的选择

---

## 常见问题

### Q: 三个版本的代码结构一样吗？

**A**: 结构相似但不完全一样：
- **相同**：组件结构、数据流、事件处理逻辑
- **不同**：布局方式、样式细节、组件选型（Element vs 原生）

### Q: 可以混合使用吗？

**A**: 可以，但不推荐。建议：
- 选定一个版本作为主版本
- 从其他版本中借鉴局部设计（如 V2 的暗色主题 + V1 的三栏布局）

### Q: 暗色主题（V2）需要额外适配吗？

**A**: 需要。V2 的暗色主题已经完整实现，但如果要在 V1/V3 中添加暗色模式，需要：
1. 定义暗色主题变量
2. 添加主题切换逻辑
3. 适配所有组件的颜色

### Q: 移动端适配需要额外工作吗？

**A**: 三个版本都已实现响应式设计：
- V1/V2：通过媒体查询自动切换布局
- V3：天生移动端友好，无需额外适配

### Q: 技能封面图需要自己设计吗？

**A**: 不需要。已提供两种方案：
- **方案 1**：渐变背景 + SVG/Emoji 图标（无需外部图片）
- **方案 2**：Unsplash 照片 + 渐变蒙版（提供了搜索关键词）

### Q: 后端接口需要调整吗？

**A**: 不需要。三个版本共享相同的类型定义和 API 接口：
- `src/assistant/types.ts` 定义了所有数据结构
- `src/assistant/api.ts` 提供了 API 调用方法

---

## 下一步

1. **选择版本**：在演示页面中切换预览
2. **替换代码**：将选定的版本复制到 `src/views/AssistantView.vue`
3. **对接后端**：实现 SSE 流式接收和 Markdown 渲染
4. **测试调优**：在真实数据下测试和调整

---

**Happy Coding! 🚀**
