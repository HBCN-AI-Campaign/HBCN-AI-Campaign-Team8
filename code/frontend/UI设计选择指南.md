# AI 助手 UI 设计方案 - 选择指南

## 快速预览

已创建三个完整的 UI 设计版本，可通过以下方式访问：

### 访问方式

1. **本地开发环境**
   ```bash
   cd code/frontend
   npm install  # 如果还没安装依赖
   npm run dev
   ```
   然后访问：`http://localhost:5173/assistant-demo`

2. **直接查看源码**
   - V1 现代简洁：`src/views/assistant-designs/AssistantV1-Modern.vue`
   - V2 暗色专业：`src/views/assistant-designs/AssistantV2-Dark.vue`
   - V3 卡片极简：`src/views/assistant-designs/AssistantV3-Minimal.vue`
   - 演示页面：`src/views/AssistantDesignDemo.vue`

---

## 三个版本对比

### V1 - 现代简洁风格 🎨

**核心特点**
- **布局**：三栏布局（会话 232px + 对话 flex + 技能 300px）
- **配色**：亮色主题，蓝色系 `#3b82f6`
- **风格**：标准 Element Plus 风格，清晰的信息层级
- **技能商店**：右侧固定面板 + 全屏 Dialog

**适用场景**
- 桌面端审核工作站
- 需要同时查看会话、对话和技能的场景
- 标准企业应用风格

**优势**
- ✅ 信息密度高，三栏同时可见
- ✅ Element Plus 标准组件，开发效率高
- ✅ 响应式设计，平板/手机自动切换
- ✅ 视觉清晰，学习成本低

**劣势**
- ❌ 小屏幕需要切换面板
- ❌ 亮色主题长时间使用可能疲劳

---

### V2 - 暗色专业风格 🌙

**核心特点**
- **布局**：三栏布局（会话 240px + 对话 flex + 技能 280px）
- **配色**：暗色主题，深蓝黑 `#0f172a` + 渐变
- **风格**：金融终端风格，专业护眼
- **技能商店**：右侧固定面板 + 全屏 Dialog（暗色）

**适用场景**
- 专业审核终端（长时间盯屏）
- 金融/法律等需要专业感的场景
- 夜间或低光环境下使用

**优势**
- ✅ 暗色护眼，适合长时间使用
- ✅ 金融终端专业感强，提升信任度
- ✅ 深蓝 + 渐变配色，视觉冲击力强
- ✅ 执行步骤轨迹可视化清晰

**劣势**
- ❌ 暗色主题适配工作量大
- ❌ 不适合明亮环境
- ❌ 需要精细调整对比度

---

### V3 - 卡片极简风格 ✨

**核心特点**
- **布局**：单栏布局（最大 900px 居中）
- **配色**：中性灰主题，白色卡片
- **风格**：极简卡片式，Emoji 图标
- **技能商店**：Drawer 抽屉 + 全屏 Dialog

**适用场景**
- 快速审核 + 移动端场景
- 需要专注对话内容的场景
- 希望减少视觉干扰的用户

**优势**
- ✅ 天生移动端友好
- ✅ 单栏布局，专注对话内容
- ✅ Emoji 图标，减少 SVG 依赖
- ✅ 极简边框，视觉干扰最小
- ✅ 开发复杂度最低

**劣势**
- ❌ 信息密度低，需要切换查看技能
- ❌ 不适合需要多任务并行的场景

---

## 技术对比表

| 维度 | V1 现代简洁 | V2 暗色专业 | V3 卡片极简 |
|------|-------------|-------------|-------------|
| **布局方式** | 三栏 232+flex+300 | 三栏 240+flex+280 | 单栏 max-900 |
| **主题** | 亮色 | 暗色 | 亮色（极简） |
| **主色调** | #3b82f6 蓝 | #1e3a8a 深蓝 | #374151 灰 |
| **技能面板** | 右侧固定 | 右侧固定 | Drawer 抽屉 |
| **消息气泡** | 左右对齐 | 左右对齐 | 卡片式 |
| **步骤展示** | Collapse 面板 | details 折叠 | details 折叠 |
| **证据标签** | Element Tag | 自定义 Tag | 浅灰 Tag |
| **图标方案** | SVG (Element Icons) | SVG (Element Icons) | Emoji + SVG 混合 |
| **移动端** | 响应式 | 响应式 | 天生友好 |
| **开发复杂度** | 中等 | 中高 | 低 |

---

## 设计细节对比

### 1. 技能商店封面图

**所有版本共享的封面图方案：**

| 技能 | 封面渐变 | 图标/Emoji | Unsplash 关键词 |
|------|----------|------------|-----------------|
| 提单验真 | 蓝色 `#3b82f6 → #1e3a8a` | 🚢 / Ship | `shipping container port` |
| 制裁筛查 | 橙色 `#f59e0b → #dc2626` | 🔒 / Lock | （纯渐变，无照片） |
| 汇率换算 | 紫色 `#8b5cf6 → #6d28d9` | 💱 / Coin | `world currency` |
| 节假日核验 | 绿色 `#10b981 → #047857` | 📅 / Calendar | （纯渐变，无照片） |
| 法规检索 | 绿色 `#10b981 → #047857` | ⚖️ / Reading | `law library books` |
| 单据比对 | 蓝色 `#3b82f6 → #1e3a8a` | 📊 / DataLine | （纯渐变，无照片） |

**封面尺寸：**
- 高度：140px
- 宽高比：16:9
- 图标大小：48px × 48px（V1/V2），56px Emoji（V3）
- 渐变方向：`linear-gradient(135deg, ...)`

### 2. 执行步骤样式

**V1 现代简洁：**
- 使用 `<el-collapse>` 组件
- 步骤图标：✓ (绿色) / ⏳ (蓝色旋转) / ○ (灰色)
- 展开/折叠动画：Element Plus 内置 300ms

**V2 暗色专业：**
- 使用原生 `<details>` 元素
- 步骤图标：✓ (绿色) / ⏳ (蓝色旋转) / ○ (灰色虚线)
- 深色背景 `#0f172a`，边框 `#334155`

**V3 卡片极简：**
- 使用原生 `<details>` 元素
- 步骤图标：Emoji ✓ (绿色) / ⏳ (旋转) / ○ (灰色)
- 白色卡片，浅灰边框 `#e5e7eb`

### 3. 证据引用标签

**V1 现代简洁：**
```vue
<el-tag type="info" effect="plain">R001 贷款用途</el-tag>
<el-tag type="info" effect="plain">提款申请书 · p.3</el-tag>
<el-tag type="success" effect="plain">业务规则 · 89%</el-tag>
```

**V2 暗色专业：**
```html
<span class="ref-tag rule">R001 贷款用途</span>  <!-- 蓝色 -->
<span class="ref-tag doc">提款申请书 · p.3</span>  <!-- 灰色 -->
<span class="ref-tag kb">业务规则 · 89%</span>  <!-- 绿色 -->
```

**V3 卡片极简：**
```html
<span class="evidence-tag">R001 贷款用途</span>  <!-- 统一浅灰 -->
<span class="evidence-tag">提款申请书 · p.3</span>
<span class="evidence-tag">业务规则 · 89%</span>
```

---

## 推荐选择

### 场景 1：桌面端审核工作站
**推荐：V1 现代简洁**
- 理由：三栏布局信息密度高，会话/对话/技能同时可见，减少切换
- 适合：长时间审核，需要频繁使用技能的场景

### 场景 2：专业审核终端（长时间盯屏）
**推荐：V2 暗色专业**
- 理由：暗色护眼，金融终端专业感强，适合长时间使用
- 适合：夜间审核，需要专业感和信任度的场景

### 场景 3：快速审核 + 移动端
**推荐：V3 卡片极简**
- 理由：天生移动端友好，单栏布局专注对话内容
- 适合：移动端审核，快速浏览任务的场景

### 场景 4：比赛演示
**推荐：V2 暗色专业 或 V3 卡片极简**
- 理由：
  - V2 视觉冲击力强，金融终端风格有记忆点
  - V3 极简风格现代，技能商店封面图出彩
- 避免：V1 太标准，缺乏差异化

---

## 下一步

### 1. 确定版本
在演示页面 (`/assistant-demo`) 中选择一个版本

### 2. 集成到主应用
替换现有的 `src/views/AssistantView.vue`：
```bash
# 例如选择 V2
cp src/views/assistant-designs/AssistantV2-Dark.vue src/views/AssistantView.vue
```

### 3. 后端对接
- 保持类型定义 `src/assistant/types.ts` 不变
- 对接 SSE 流式接口 `src/assistant/api.ts`
- 实现 Markdown 渲染（已安装 `marked` 和 `dompurify`）

### 4. 完善功能
- [ ] 实现真实的会话列表加载
- [ ] 实现真实的消息流渲染
- [ ] 实现 SSE 流式接收
- [ ] 实现技能运行逻辑
- [ ] 实现证据引用 Hover 预览
- [ ] 实现移动端适配测试

---

## 技术说明

### 已移除的依赖
- ❌ `@copilotkit/core` (1.79.1)
- ❌ `@copilotkit/vue` (1.79.1)
- ❌ `@ag-ui/core`

### 新增的依赖
- ✅ `marked` (^15.0.4) - Markdown 渲染
- ✅ `dompurify` (^3.2.2) - HTML 安全清理

### 保留的依赖
- ✅ `element-plus` (^2.9.1)
- ✅ `@element-plus/icons-vue` (^2.3.1)
- ✅ `vue` (^3.5.13)
- ✅ `vue-router` (^4.5.0)
- ✅ `pinia` (^2.3.0)
- ✅ `axios` (^1.7.9)

### Markdown 渲染示例

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

---

## 联系与反馈

如有问题或需要调整，请随时提出。三个版本都是完整可运行的，可以直接在浏览器中预览效果。
