<template>
  <div class="design-demo">
    <div class="demo-header">
      <h1>AI 助手界面设计方案</h1>
      <p class="demo-subtitle">选择下方版本预览不同的设计风格</p>

      <div class="version-selector">
        <button
          v-for="version in versions"
          :key="version.id"
          class="version-btn"
          :class="{ active: activeVersion === version.id }"
          @click="activeVersion = version.id"
        >
          <div class="version-icon">{{ version.icon }}</div>
          <div class="version-info">
            <div class="version-name">{{ version.name }}</div>
            <div class="version-desc">{{ version.desc }}</div>
          </div>
        </button>
      </div>

      <div class="design-features">
        <div class="feature-badge" v-for="feature in currentFeatures" :key="feature">
          ✓ {{ feature }}
        </div>
      </div>
    </div>

    <div class="demo-preview">
      <component :is="currentComponent" />
    </div>

    <div class="demo-footer">
      <el-button @click="showComparison = true">查看设计对比表</el-button>
      <el-button type="primary" @click="confirmDesign">确定使用此版本</el-button>
    </div>

    <!-- 对比表 Dialog -->
    <el-dialog v-model="showComparison" title="设计方案对比" width="80%">
      <el-table :data="comparisonData" border>
        <el-table-column prop="aspect" label="对比维度" width="150" fixed />
        <el-table-column prop="v1" label="V1 现代简洁" />
        <el-table-column prop="v2" label="V2 暗色专业" />
        <el-table-column prop="v3" label="V3 卡片极简" />
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, defineAsyncComponent } from 'vue'
import { ElMessage } from 'element-plus'

const AssistantV1 = defineAsyncComponent(() => import('./assistant-designs/AssistantV1-Modern.vue'))
const AssistantV2 = defineAsyncComponent(() => import('./assistant-designs/AssistantV2-Dark.vue'))
const AssistantV3 = defineAsyncComponent(() => import('./assistant-designs/AssistantV3-Minimal.vue'))

const activeVersion = ref('v1')
const showComparison = ref(false)

const versions = [
  {
    id: 'v1',
    name: 'V1 现代简洁',
    icon: '🎨',
    desc: '三栏布局，Element Plus 标准风格',
    features: [
      '三栏布局（会话+对话+技能）',
      '亮色主题',
      '标准 Element Plus 组件',
      '清晰的信息层级',
      '适合桌面端长时间使用'
    ],
    component: AssistantV1
  },
  {
    id: 'v2',
    name: 'V2 暗色专业',
    icon: '🌙',
    desc: '金融终端风格，暗色护眼',
    features: [
      '暗色主题（护眼模式）',
      '金融终端专业感',
      '深蓝+渐变配色',
      '步骤轨迹可视化',
      '适合长时间盯屏审核'
    ],
    component: AssistantV2
  },
  {
    id: 'v3',
    name: 'V3 卡片极简',
    icon: '✨',
    desc: '单栏卡片，移动端友好',
    features: [
      '单栏布局，移动端友好',
      '卡片式消息气泡',
      'Emoji 图标代替 SVG',
      '极简边框，强调内容',
      '适合快速浏览'
    ],
    component: AssistantV3
  }
]

const currentComponent = computed(() => {
  return versions.find(v => v.id === activeVersion.value)?.component
})

const currentFeatures = computed(() => {
  return versions.find(v => v.id === activeVersion.value)?.features || []
})

const comparisonData = [
  {
    aspect: '视觉风格',
    v1: '现代简洁，浅色调',
    v2: '专业终端，深色调',
    v3: '极简卡片，白色调'
  },
  {
    aspect: '布局方式',
    v1: '三栏布局（232px + flex + 280px）',
    v2: '三栏布局（240px + flex + 280px）',
    v3: '单栏布局（最大 900px 居中）'
  },
  {
    aspect: '配色方案',
    v1: '蓝色主题 #3b82f6',
    v2: '深蓝主题 #1e3a8a + 渐变',
    v3: '中性灰主题 #374151'
  },
  {
    aspect: '技能卡片',
    v1: '右侧固定面板 + Dialog 商店',
    v2: '右侧固定面板 + Dialog 商店',
    v3: 'Drawer 抽屉 + Dialog 商店'
  },
  {
    aspect: '消息气泡',
    v1: '左右对齐，浅色卡片',
    v2: '左右对齐，深色卡片',
    v3: '中心对齐，白色卡片'
  },
  {
    aspect: '执行步骤',
    v1: 'Element Collapse 折叠面板',
    v2: 'details 折叠面板',
    v3: 'details 折叠面板（极简）'
  },
  {
    aspect: '证据引用',
    v1: 'Element Tag 标签',
    v2: '自定义 Tag（带颜色编码）',
    v3: '浅灰背景 Tag'
  },
  {
    aspect: '移动端适配',
    v1: '响应式（<768px 单栏）',
    v2: '响应式（<768px 单栏）',
    v3: '天生移动端友好'
  },
  {
    aspect: '加载动画',
    v1: 'Element Icon 旋转',
    v2: 'CSS spin 动画',
    v3: 'Emoji 旋转'
  },
  {
    aspect: '适用场景',
    v1: '桌面端审核工作站',
    v2: '专业审核终端（长时间）',
    v3: '快速审核 + 移动端'
  },
  {
    aspect: '技术依赖',
    v1: 'Element Plus',
    v2: 'Element Plus',
    v3: 'Element Plus（最少）'
  },
  {
    aspect: '开发复杂度',
    v1: '中等',
    v2: '中高（暗色主题适配）',
    v3: '低（结构简单）'
  }
]

function confirmDesign() {
  const selected = versions.find(v => v.id === activeVersion.value)
  ElMessage.success(`已选择：${selected?.name}`)
  // 这里可以继续实现确认逻辑
}
</script>

<style scoped>
.design-demo {
  min-height: 100vh;
  background: #f5f7fb;
  display: flex;
  flex-direction: column;
}

.demo-header {
  background: white;
  padding: 32px 24px;
  border-bottom: 1px solid #e2e8f0;
}

.design-demo h1 {
  font-size: 32px;
  font-weight: 700;
  color: #1e293b;
  margin: 0 0 8px;
  text-align: center;
}

.demo-subtitle {
  font-size: 16px;
  color: #64748b;
  margin: 0 0 24px;
  text-align: center;
}

.version-selector {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  max-width: 1200px;
  margin: 0 auto 24px;
}

.version-btn {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 20px;
  border: 2px solid #e2e8f0;
  border-radius: 12px;
  background: white;
  cursor: pointer;
  transition: all 0.3s;
}

.version-btn:hover {
  border-color: #3b82f6;
  box-shadow: 0 4px 12px rgba(59, 130, 246, 0.1);
  transform: translateY(-2px);
}

.version-btn.active {
  border-color: #3b82f6;
  background: #eff6ff;
  box-shadow: 0 8px 20px rgba(59, 130, 246, 0.15);
}

.version-icon {
  font-size: 48px;
}

.version-info {
  flex: 1;
  text-align: left;
}

.version-name {
  font-size: 18px;
  font-weight: 700;
  color: #1e293b;
  margin-bottom: 4px;
}

.version-desc {
  font-size: 14px;
  color: #64748b;
}

.design-features {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  justify-content: center;
  max-width: 1000px;
  margin: 0 auto;
}

.feature-badge {
  padding: 8px 16px;
  border-radius: 20px;
  background: #f1f5f9;
  color: #475569;
  font-size: 13px;
  font-weight: 500;
}

.demo-preview {
  flex: 1;
  overflow: hidden;
  background: white;
}

.demo-footer {
  display: flex;
  justify-content: center;
  gap: 16px;
  padding: 24px;
  background: white;
  border-top: 1px solid #e2e8f0;
}

/* 响应式 */
@media (max-width: 1024px) {
  .version-selector {
    grid-template-columns: 1fr;
  }
}
</style>
