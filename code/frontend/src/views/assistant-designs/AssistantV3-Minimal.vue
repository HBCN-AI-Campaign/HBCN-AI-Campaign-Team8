<!--
  AI 助手 V3：卡片极简版
  参考：Open WebUI + 移动优先设计
  特点：单栏布局、大卡片、Emoji 图标、极简优雅
-->
<template>
  <div class="assistant-minimal">
    <!-- 顶部栏 -->
    <header class="top-bar">
      <div class="logo-group">
        <div class="logo-circle">✨</div>
        <span class="logo-text">慧眼助手</span>
      </div>
      <el-button text @click="$router.push('/tasks')">
        <el-icon><Close /></el-icon>
      </el-button>
    </header>

    <!-- 工具栏 -->
    <div class="toolbar">
      <el-select v-model="taskCode" placeholder="关联任务" size="small" style="width: 180px">
        <el-option v-for="t in tasks" :key="t.code" :label="t.code" :value="t.code" />
      </el-select>
      <el-button text size="small" @click="skillDrawer = true">
        <el-icon><Grid /></el-icon>
        审核技能
      </el-button>
      <el-button text size="small" @click="sessionDrawer = true">
        <el-icon><ChatDotRound /></el-icon>
        会话列表
      </el-button>
    </div>

    <!-- 对话区 -->
    <div class="chat-container" ref="containerRef">
      <!-- 空态 -->
      <div v-if="!messages.length" class="empty-state">
        <div class="hero-card">
          <div class="hero-icon">🤖</div>
          <h2 class="hero-title">让审核工作更快一步</h2>
          <p class="hero-desc">解析单据、验证规则、检索证据</p>
          <div class="hero-actions">
            <el-button @click="sendQuick('梳理风险点')" round>📋 梳理风险</el-button>
            <el-button @click="sendQuick('为什么被驳回？')" round>🔍 解释驳回</el-button>
            <el-button @click="sendQuick('核对文件')" round>📄 核对文件</el-button>
          </div>
        </div>

        <div class="hint-text">或者直接输入你的问题...</div>
      </div>

      <!-- 消息卡片 -->
      <div v-else class="message-cards">
        <div v-for="m in messages" :key="m.id" :class="['card-item', `card-${m.role}`]">
          <!-- 用户消息 -->
          <div v-if="m.role === 'user'" class="user-card">
            <div class="user-avatar">你</div>
            <div class="user-text">{{ m.content }}</div>
          </div>

          <!-- 助手消息 -->
          <div v-else class="asst-card">
            <div class="asst-header">
              <div class="asst-avatar">🤖</div>
              <div class="asst-meta">
                <span class="asst-name">慧眼助手</span>
                <el-tag v-if="m.streaming" size="small" type="info">
                  <el-icon class="is-loading"><Loading /></el-icon>
                  思考中
                </el-tag>
              </div>
            </div>

            <!-- 步骤折叠 -->
            <el-collapse v-if="m.steps?.length" class="steps-collapse">
              <el-collapse-item name="1">
                <template #title>
                  <span class="steps-title">🔄 执行轨迹（{{ m.steps.length }} 步）</span>
                </template>
                <div class="steps-body">
                  <div v-for="(st, i) in m.steps" :key="i" class="step-line">
                    <span v-if="st.status === 'completed'" class="step-mark">✓</span>
                    <span v-else-if="st.status === 'running'" class="step-mark spin">⏳</span>
                    <span v-else class="step-mark">○</span>
                    <span class="step-label">{{ st.description }}</span>
                    <span v-if="st.result" class="step-val">{{ st.result }}</span>
                  </div>
                </div>
              </el-collapse-item>
            </el-collapse>

            <!-- 内容 -->
            <div class="asst-body" v-html="renderMarkdown(m.content)"></div>

            <!-- 证据 -->
            <div v-if="m.citations?.length" class="evidence-box">
              <div class="evidence-title">📎 证据来源</div>
              <div class="evidence-list">
                <div v-for="(c, i) in m.citations" :key="i" class="evidence-item" @click="previewEvidence(c)">
                  <div class="evidence-name">{{ c.docName }}</div>
                  <div class="evidence-detail">
                    第 {{ c.page }} 页 · 相关度 <span class="evidence-score">{{ Math.round(c.score * 100) }}%</span>
                  </div>
                </div>
              </div>
            </div>

            <!-- 操作 -->
            <div class="asst-actions">
              <el-button text size="small" @click="copy(m.content)">
                <el-icon><DocumentCopy /></el-icon>
                复制
              </el-button>
              <el-button text size="small" @click="regen(m.id)">
                <el-icon><RefreshRight /></el-icon>
                重新生成
              </el-button>
            </div>
          </div>
        </div>
      </div>

      <!-- 滚动按钮 -->
      <transition name="el-fade-in">
        <el-button v-show="!atBottom" class="float-scroll" circle @click="scrollDown">
          <el-icon><ArrowDown /></el-icon>
        </el-button>
      </transition>
    </div>

    <!-- 输入框 -->
    <div class="input-bar">
      <el-input
        v-model="input"
        type="textarea"
        :autosize="{ minRows: 1, maxRows: 4 }"
        placeholder="描述你想核对的规则..."
        @keydown.enter.exact.prevent="send"
        class="input-field"
      />
      <el-button
        type="primary"
        :loading="generating"
        :disabled="!input.trim()"
        @click="send"
        circle
        class="send-btn"
      >
        <el-icon v-if="!generating"><Promotion /></el-icon>
      </el-button>
    </div>

    <!-- 技能抽屉 -->
    <el-drawer v-model="skillDrawer" title="审核技能" size="360px">
      <div class="skill-cards">
        <div v-for="sk in skills" :key="sk.id" class="skill-item" @click="useSk(sk)">
          <div class="skill-top" :style="{ background: sk.grad }">
            <div class="skill-emoji-lg">{{ sk.emoji }}</div>
          </div>
          <div class="skill-content">
            <h4 class="skill-title">{{ sk.name }}</h4>
            <p class="skill-text">{{ sk.desc }}</p>
            <el-tag size="small" type="info">🔥 本周 {{ sk.use }} 次</el-tag>
          </div>
        </div>
      </div>
    </el-drawer>

    <!-- 会话抽屉 -->
    <el-drawer v-model="sessionDrawer" title="会话列表" size="320px">
      <el-button type="primary" @click="newChat" style="width: 100%; margin-bottom: 16px">
        <el-icon><Plus /></el-icon>
        新建会话
      </el-button>
      <div class="session-list">
        <div
          v-for="s in sessions"
          :key="s.id"
          :class="['session-row', { active: currentId === s.id }]"
          @click="selectSession(s.id)"
        >
          <div class="session-title">{{ s.title }}</div>
          <div class="session-time">{{ formatTime(s.updatedAt) }}</div>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import {
  Close, Grid, ChatDotRound, Loading, DocumentCopy,
  RefreshRight, ArrowDown, Promotion, Plus
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

interface Msg {
  id: number
  role: 'user' | 'assistant'
  content: string
  streaming?: boolean
  steps?: Array<{ description: string; status: string; result?: string }>
  citations?: Array<{ docName: string; page: number; score: number; content: string }>
}

const taskCode = ref('')
const tasks = ref([{ code: 'LN0823', borrower: '某公司' }])

const messages = ref<Msg[]>([])
const input = ref('')
const generating = ref(false)
const atBottom = ref(true)

const skillDrawer = ref(false)
const sessionDrawer = ref(false)

const currentId = ref(1)
const sessions = ref([
  { id: 1, title: 'LN0823 审核', updatedAt: '2026-10-20T10:30:00' },
  { id: 2, title: '制裁筛查', updatedAt: '2026-10-19T15:00:00' }
])

const skills = ref([
  { id: 'bill', name: '提单验真', desc: '核验海运提单真实性和有效性', emoji: '🚢', grad: 'linear-gradient(135deg, #3b82f6, #1e40af)', use: 67 },
  { id: 'sanc', name: '制裁筛查', desc: '检查借款人是否在制裁名单', emoji: '🔒', grad: 'linear-gradient(135deg, #f59e0b, #d97706)', use: 54 },
  { id: 'exch', name: '汇率换算', desc: '验证单据汇率是否合理', emoji: '💱', grad: 'linear-gradient(135deg, #10b981, #059669)', use: 43 },
  { id: 'holi', name: '节假日核查', desc: '检查贷款日期与法定节假日冲突', emoji: '📅', grad: 'linear-gradient(135deg, #8b5cf6, #6d28d9)', use: 31 }
])

const containerRef = ref<HTMLElement>()

function renderMarkdown(text: string): string {
  const html = marked.parse(text) as string
  return DOMPurify.sanitize(html, {
    ALLOWED_TAGS: ['p', 'strong', 'em', 'ul', 'ol', 'li', 'code', 'pre', 'br']
  })
}

function formatTime(iso: string): string {
  const date = new Date(iso)
  return `${date.getMonth() + 1}月${date.getDate()}日`
}

function send() {
  if (!input.value.trim() || generating.value) return

  messages.value.push({ id: Date.now(), role: 'user', content: input.value.trim() })
  input.value = ''

  nextTick(scrollDown)

  // 模拟回复
  generating.value = true
  const asst: Msg = {
    id: Date.now() + 1,
    role: 'assistant',
    content: '',
    streaming: true,
    steps: [
      { description: '读取材料', status: 'completed', result: '3份' },
      { description: '检索知识库', status: 'running' }
    ]
  }
  messages.value.push(asst)

  setTimeout(() => {
    asst.steps![1].status = 'completed'
    asst.steps![1].result = '2条'
    asst.streaming = false
    asst.content = '根据规则，驳回原因：\n\n1. **借款用途不明确**\n2. **授信函缺失**'
    asst.citations = [
      { docName: '贷款文件比对要求.xlsx', page: 1, score: 0.89, content: '借款用途必须详细说明' }
    ]
    generating.value = false
  }, 2000)
}

function sendQuick(text: string) {
  input.value = text
  send()
}

function copy(text: string) {
  navigator.clipboard.writeText(text)
  ElMessage.success('已复制')
}

function regen(msgId: number) {
  ElMessage.info('重新生成功能开发中...')
}

function previewEvidence(cite: any) {
  ElMessage.info(`证据预览：${cite.docName}`)
}

function useSk(sk: any) {
  input.value = `使用「${sk.name}」`
  skillDrawer.value = false
  send()
}

function newChat() {
  const newId = Math.max(...sessions.value.map(s => s.id)) + 1
  sessions.value.unshift({ id: newId, title: '新对话', updatedAt: new Date().toISOString() })
  currentId.value = newId
  messages.value = []
  sessionDrawer.value = false
}

function selectSession(id: number) {
  currentId.value = id
  messages.value = []
  sessionDrawer.value = false
}

function scrollDown() {
  nextTick(() => {
    if (containerRef.value) {
      containerRef.value.scrollTop = containerRef.value.scrollHeight
    }
  })
}
</script>

<style scoped>
/* 全局 */
.assistant-minimal {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: linear-gradient(180deg, #f8fafc 0%, #f1f5f9 100%);
}

/* 顶部栏 */
.top-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 20px;
  background: white;
  border-bottom: 1px solid #e2e8f0;
}

.logo-group {
  display: flex;
  align-items: center;
  gap: 10px;
}

.logo-circle {
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: linear-gradient(135deg, #10b981, #059669);
  font-size: 20px;
}

.logo-text {
  font-size: 17px;
  font-weight: 700;
  color: #0f172a;
}

/* 工具栏 */
.toolbar {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 12px;
  padding: 12px 20px;
  background: white;
  border-bottom: 1px solid #e2e8f0;
}

/* 对话容器 */
.chat-container {
  flex: 1;
  overflow-y: auto;
  padding: 24px 20px;
  position: relative;
}

/* 空态 */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 40px 16px;
}

.hero-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  max-width: 500px;
  padding: 40px 32px;
  border-radius: 20px;
  background: white;
  box-shadow: 0 4px 24px rgba(0, 0, 0, .08);
}

.hero-icon {
  font-size: 56px;
  margin-bottom: 20px;
}

.hero-title {
  margin: 0 0 12px;
  font-size: 26px;
  font-weight: 700;
  color: #0f172a;
}

.hero-desc {
  margin: 0 0 28px;
  font-size: 16px;
  color: #64748b;
  text-align: center;
}

.hero-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 10px;
}

.hint-text {
  margin-top: 24px;
  font-size: 14px;
  color: #94a3b8;
}

/* 消息卡片 */
.message-cards {
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-width: 800px;
  margin: 0 auto;
}

.card-item {
  display: flex;
}

.card-user {
  justify-content: flex-end;
}

.card-assistant {
  justify-content: flex-start;
}

.user-card {
  display: flex;
  align-items: center;
  gap: 12px;
  max-width: 75%;
  padding: 14px 18px;
  border-radius: 18px;
  background: linear-gradient(135deg, #10b981, #059669);
  color: white;
  box-shadow: 0 2px 8px rgba(16, 185, 129, .25);
}

.user-avatar {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: rgba(255, 255, 255, .3);
  font-size: 13px;
  font-weight: 600;
}

.user-text {
  flex: 1;
  font-size: 15px;
  line-height: 1.6;
}

.asst-card {
  max-width: 90%;
  padding: 20px;
  border-radius: 16px;
  background: white;
  box-shadow: 0 2px 12px rgba(0, 0, 0, .08);
}

.asst-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}

.asst-avatar {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: linear-gradient(135deg, #3b82f6, #2563eb);
  font-size: 22px;
}

.asst-meta {
  flex: 1;
}

.asst-name {
  display: block;
  font-size: 15px;
  font-weight: 600;
  color: #0f172a;
  margin-bottom: 2px;
}

.steps-collapse {
  margin-bottom: 16px;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
}

.steps-title {
  font-size: 13px;
  font-weight: 600;
}

.steps-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 8px 0;
}

.step-line {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 4px 0;
}

.step-mark {
  width: 20px;
  text-align: center;
  font-size: 14px;
}

.step-mark.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.step-label {
  flex: 1;
  font-size: 13px;
  color: #334155;
}

.step-val {
  font-size: 12px;
  color: #10b981;
  font-weight: 600;
}

.asst-body {
  font-size: 15px;
  line-height: 1.7;
  color: #334155;
}

.asst-body :deep(p) {
  margin: 0 0 14px;
}

.asst-body :deep(strong) {
  color: #0f172a;
  font-weight: 600;
}

.asst-body :deep(code) {
  padding: 3px 8px;
  border-radius: 6px;
  background: #f1f5f9;
  color: #3b82f6;
  font-size: 14px;
}

.evidence-box {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid #f1f5f9;
}

.evidence-title {
  margin-bottom: 10px;
  font-size: 13px;
  font-weight: 600;
  color: #64748b;
}

.evidence-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.evidence-item {
  padding: 10px 12px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #f8fafc;
  cursor: pointer;
  transition: all .2s;
}

.evidence-item:hover {
  border-color: #10b981;
  background: #f0fdf4;
}

.evidence-name {
  font-size: 13px;
  font-weight: 600;
  color: #0f172a;
  margin-bottom: 4px;
}

.evidence-detail {
  font-size: 12px;
  color: #64748b;
}

.evidence-score {
  color: #10b981;
  font-weight: 600;
}

.asst-actions {
  display: flex;
  gap: 8px;
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid #f8fafc;
}

.float-scroll {
  position: absolute;
  right: 20px;
  bottom: 20px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, .2);
}

/* 输入框 */
.input-bar {
  display: flex;
  align-items: flex-end;
  gap: 10px;
  padding: 14px 20px;
  background: white;
  border-top: 1px solid #e2e8f0;
}

.input-field {
  flex: 1;
}

.input-field :deep(.el-textarea__inner) {
  border: 1px solid #e2e8f0;
  border-radius: 16px;
  padding: 12px 16px;
  font-size: 15px;
}

.send-btn {
  width: 44px;
  height: 44px;
}

/* 抽屉内容 */
.skill-cards {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.skill-item {
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  overflow: hidden;
  cursor: pointer;
  transition: all .2s;
}

.skill-item:hover {
  border-color: #10b981;
  box-shadow: 0 4px 12px rgba(16, 185, 129, .15);
  transform: translateY(-2px);
}

.skill-top {
  display: grid;
  place-items: center;
  height: 100px;
}

.skill-emoji-lg {
  font-size: 48px;
}

.skill-content {
  padding: 14px;
}

.skill-title {
  margin: 0 0 6px;
  font-size: 16px;
  font-weight: 600;
}

.skill-text {
  margin: 0 0 10px;
  font-size: 13px;
  color: #64748b;
  line-height: 1.5;
}

.session-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.session-row {
  padding: 12px;
  border-radius: 10px;
  border: 1px solid #e2e8f0;
  cursor: pointer;
  transition: all .2s;
}

.session-row:hover {
  background: #f8fafc;
}

.session-row.active {
  border-color: #10b981;
  background: #f0fdf4;
}

.session-title {
  font-size: 14px;
  font-weight: 600;
  color: #0f172a;
  margin-bottom: 4px;
}

.session-time {
  font-size: 12px;
  color: #94a3b8;
}

@media (max-width: 768px) {
  .toolbar {
    flex-wrap: wrap;
  }
  .chat-container {
    padding: 16px 12px;
  }
  .message-cards {
    padding: 0;
  }
}
</style>
