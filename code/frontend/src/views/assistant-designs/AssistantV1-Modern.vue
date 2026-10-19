<!--
  AI 助手 V1：现代简洁版
  参考：Lobe Chat + Chatbot UI 设计模式
  特点：三栏布局、专业交互、Element Plus 深度定制
-->
<template>
  <div class="assistant-shell">
    <!-- 左侧边栏：会话列表 -->
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-icon">
          <el-icon :size="24"><ChatDotRound /></el-icon>
        </div>
        <div class="brand-text">
          <div class="brand-name">慧眼助手</div>
          <div class="brand-caption">贷款审核智能助理</div>
        </div>
      </div>

      <el-button type="primary" class="new-chat-btn" @click="handleNewChat">
        <el-icon><Plus /></el-icon>
        <span>新建对话</span>
      </el-button>

      <div class="session-list">
        <div class="section-label">最近对话</div>
        <div
          v-for="session in sessions"
          :key="session.id"
          :class="['session-item', { active: currentSessionId === session.id }]"
          @click="selectSession(session.id)"
        >
          <div class="session-header">
            <span class="session-title">{{ session.title }}</span>
            <el-dropdown trigger="click" @command="(cmd) => handleSessionAction(cmd, session.id)">
              <el-icon class="session-more"><MoreFilled /></el-icon>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="rename">重命名</el-dropdown-item>
                  <el-dropdown-item command="delete">删除</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
          <div class="session-preview">{{ session.lastMessage }}</div>
          <div class="session-time">{{ formatTime(session.updatedAt) }}</div>
        </div>
      </div>

      <div class="sidebar-footer">
        <el-dropdown trigger="click">
          <div class="user-profile">
            <el-avatar :size="32">{{ profile.name[0] }}</el-avatar>
            <span class="user-name">{{ profile.name }}</span>
          </div>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item>设置</el-dropdown-item>
              <el-dropdown-item divided @click="$router.push('/login')">退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </aside>

    <!-- 中间主区：对话区 -->
    <main class="chat-main">
      <header class="chat-header">
        <div class="chat-title-group">
          <h1 class="chat-title">{{ currentSession?.title || '新对话' }}</h1>
          <el-select
            v-model="selectedTaskCode"
            placeholder="关联任务"
            clearable
            class="task-selector"
            size="small"
          >
            <el-option
              v-for="task in availableTasks"
              :key="task.code"
              :label="`${task.code} - ${task.borrower}`"
              :value="task.code"
            />
          </el-select>
        </div>
        <div class="chat-actions">
          <el-button text @click="showSettings = true">
            <el-icon><Setting /></el-icon>
          </el-button>
        </div>
      </header>

      <div class="chat-body" ref="chatBodyRef" @scroll="handleScroll">
        <!-- 欢迎屏幕 -->
        <div v-if="messages.length === 0" class="welcome-screen">
          <div class="welcome-icon">
            <el-icon :size="64" color="#10b981"><Histogram /></el-icon>
          </div>
          <h2 class="welcome-title">让审核工作更快一步</h2>
          <p class="welcome-subtitle">解析单据、验证规则、检索证据，助您快速完成审核决策</p>
          <div class="prompt-suggestions">
            <div
              v-for="(prompt, idx) in promptSuggestions"
              :key="idx"
              class="prompt-card"
              @click="sendMessage(prompt.text)"
            >
              <div class="prompt-icon">{{ prompt.icon }}</div>
              <div class="prompt-label">{{ prompt.label }}</div>
            </div>
          </div>
        </div>

        <!-- 消息流 -->
        <div v-else class="message-list">
          <div
            v-for="msg in messages"
            :key="msg.id"
            :class="['message-wrap', `message-${msg.role}`]"
          >
            <div v-if="msg.role === 'user'" class="message-bubble user-bubble">
              {{ msg.content }}
            </div>

            <div v-else class="message-card assistant-card">
              <div class="message-header">
                <el-avatar :size="32" class="assistant-avatar">
                  <el-icon><ChatDotRound /></el-icon>
                </el-avatar>
                <span class="assistant-name">慧眼助手</span>
                <el-tag v-if="msg.streaming" size="small" type="info">
                  <el-icon class="is-loading"><Loading /></el-icon>
                  思考中
                </el-tag>
              </div>

              <!-- 执行步骤 -->
              <el-collapse v-if="msg.steps && msg.steps.length" v-model="activeSteps" class="execution-steps">
                <el-collapse-item name="steps">
                  <template #title>
                    <el-icon><Operation /></el-icon>
                    <span>执行轨迹（{{ msg.steps.length }} 步）</span>
                  </template>
                  <div class="step-list">
                    <div v-for="(step, idx) in msg.steps" :key="idx" :class="['step-item', `step-${step.status}`]">
                      <el-icon v-if="step.status === 'completed'" class="step-icon" color="#10b981"><CircleCheckFilled /></el-icon>
                      <el-icon v-else-if="step.status === 'running'" class="step-icon is-loading" color="#3b82f6"><Loading /></el-icon>
                      <el-icon v-else class="step-icon" color="#94a3b8"><CircleFilled /></el-icon>
                      <span class="step-text">{{ step.description }}</span>
                      <span v-if="step.result" class="step-result">{{ step.result }}</span>
                    </div>
                  </div>
                </el-collapse-item>
              </el-collapse>

              <!-- 消息内容 -->
              <div class="message-content" v-html="renderMarkdown(msg.content)"></div>

              <!-- 引用证据 -->
              <div v-if="msg.citations && msg.citations.length" class="message-citations">
                <div class="citation-label">证据来源</div>
                <div class="citation-list">
                  <el-popover
                    v-for="(cite, idx) in msg.citations"
                    :key="idx"
                    placement="top"
                    :width="320"
                    trigger="hover"
                  >
                    <template #reference>
                      <el-tag class="citation-tag" size="small">
                        {{ cite.docName }} · p.{{ cite.page }}
                        <span class="citation-score">{{ Math.round(cite.score * 100) }}%</span>
                      </el-tag>
                    </template>
                    <div class="citation-preview">
                      <div class="citation-preview-title">{{ cite.docName }}</div>
                      <div class="citation-preview-content">{{ cite.content.slice(0, 100) }}...</div>
                    </div>
                  </el-popover>
                </div>
              </div>

              <!-- 消息操作栏 -->
              <div class="message-actions">
                <el-button text size="small" @click="copyMessage(msg.content)">
                  <el-icon><DocumentCopy /></el-icon>
                  复制
                </el-button>
                <el-button text size="small" @click="regenerate(msg.id)">
                  <el-icon><RefreshRight /></el-icon>
                  重新生成
                </el-button>
              </div>
            </div>
          </div>
        </div>

        <!-- 滚动到底部按钮 -->
        <transition name="el-fade-in">
          <el-button
            v-show="!isAtBottom"
            class="scroll-to-bottom"
            circle
            @click="scrollToBottom"
          >
            <el-icon><ArrowDown /></el-icon>
          </el-button>
        </transition>
      </div>

      <!-- 输入区 -->
      <div class="chat-input-wrap">
        <div class="input-toolbar">
          <el-button text size="small">
            <el-icon><PaperClip /></el-icon>
            附件
          </el-button>
        </div>
        <el-input
          v-model="inputText"
          type="textarea"
          :autosize="{ minRows: 1, maxRows: 6 }"
          placeholder="描述你想核对的规则或询问审核建议..."
          @keydown.enter.exact.prevent="handleSend"
          class="message-input"
        />
        <el-button
          type="primary"
          :loading="isGenerating"
          :disabled="!inputText.trim()"
          @click="handleSend"
          class="send-btn"
        >
          <el-icon v-if="!isGenerating"><Promotion /></el-icon>
          发送
        </el-button>
      </div>
    </main>

    <!-- 右侧边栏：技能商店 -->
    <aside class="skills-sidebar">
      <div class="skills-header">
        <h3>审核技能</h3>
        <el-button text size="small" @click="showAllSkills = !showAllSkills">
          {{ showAllSkills ? '收起' : '查看全部' }}
        </el-button>
      </div>

      <div class="skills-grid">
        <div
          v-for="skill in (showAllSkills ? skills : skills.slice(0, 4))"
          :key="skill.id"
          class="skill-card"
          @click="useSkill(skill)"
        >
          <div class="skill-cover" :style="{ background: skill.gradient }">
            <div class="skill-icon">{{ skill.icon }}</div>
          </div>
          <div class="skill-body">
            <h4 class="skill-name">{{ skill.name }}</h4>
            <p class="skill-desc">{{ skill.description }}</p>
            <div class="skill-meta">
              <el-tag size="small" type="info">🔥 本周 {{ skill.usage }} 次</el-tag>
            </div>
          </div>
        </div>
      </div>
    </aside>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, nextTick, onMounted } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import {
  ChatDotRound, Plus, MoreFilled, Setting, Histogram, Loading,
  Operation, CircleCheckFilled, CircleFilled, DocumentCopy,
  RefreshRight, ArrowDown, PaperClip, Promotion
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

// 类型定义
interface Message {
  id: number
  role: 'user' | 'assistant'
  content: string
  streaming?: boolean
  steps?: Array<{
    description: string
    status: 'completed' | 'running' | 'pending'
    result?: string
  }>
  citations?: Array<{
    docName: string
    page: number
    score: number
    content: string
  }>
}

interface Session {
  id: number
  title: string
  lastMessage: string
  updatedAt: string
}

interface Skill {
  id: string
  name: string
  description: string
  icon: string
  gradient: string
  usage: number
}

// 状态管理
const profile = ref({ name: '李四' })
const sessions = ref<Session[]>([
  { id: 1, title: 'LN0823 审核', lastMessage: '为什么被驳回？', updatedAt: '2026-10-20T10:30:00' },
  { id: 2, title: '制裁名单筛查', lastMessage: '检查借款人', updatedAt: '2026-10-19T15:20:00' }
])
const currentSessionId = ref(1)
const currentSession = computed(() => sessions.value.find(s => s.id === currentSessionId.value))

const messages = ref<Message[]>([])
const inputText = ref('')
const isGenerating = ref(false)
const isAtBottom = ref(true)
const activeSteps = ref(['steps'])
const showSettings = ref(false)
const showAllSkills = ref(false)

const selectedTaskCode = ref('')
const availableTasks = ref([
  { code: 'LN0823', borrower: '某跨境公司' },
  { code: 'LN0824', borrower: '某进出口公司' }
])

const promptSuggestions = [
  { icon: '📋', label: '梳理风险点', text: '帮我梳理当前任务的主要风险点' },
  { icon: '🔍', label: '解释驳回原因', text: '为什么这份单据被驳回？' },
  { icon: '📄', label: '核对必备文件', text: '检查所有必备文件是否齐全' },
  { icon: '⚖️', label: '法规检索', text: '这种贷款用途符合哪些法规？' }
]

const skills = ref<Skill[]>([
  { id: 'bill-verify', name: '提单验真', description: '核验海运提单的真实性和有效性', icon: '🚢', gradient: 'linear-gradient(135deg, #3b82f6 0%, #1e40af 100%)', usage: 67 },
  { id: 'sanction', name: '制裁筛查', description: '检查借款人是否在制裁名单', icon: '🔒', gradient: 'linear-gradient(135deg, #f59e0b 0%, #d97706 100%)', usage: 54 },
  { id: 'exchange', name: '汇率换算', description: '验证单据汇率是否合理', icon: '💱', gradient: 'linear-gradient(135deg, #10b981 0%, #059669 100%)', usage: 43 },
  { id: 'holiday', name: '节假日核查', description: '检查贷款日期与法定节假日冲突', icon: '📅', gradient: 'linear-gradient(135deg, #8b5cf6 0%, #6d28d9 100%)', usage: 31 },
  { id: 'regulation', name: '法规检索', description: 'RAG 检索相关法规条款', icon: '⚖️', gradient: 'linear-gradient(135deg, #ec4899 0%, #be185d 100%)', usage: 28 },
  { id: 'purpose', name: '用途审查', description: '核对贷款用途是否符合规定', icon: '🎯', gradient: 'linear-gradient(135deg, #06b6d4 0%, #0891b2 100%)', usage: 22 }
])

const chatBodyRef = ref<HTMLElement>()

// 方法
function renderMarkdown(text: string): string {
  const html = marked.parse(text) as string
  return DOMPurify.sanitize(html, {
    ALLOWED_TAGS: ['p', 'strong', 'em', 'ul', 'ol', 'li', 'code', 'pre', 'br', 'h1', 'h2', 'h3']
  })
}

function formatTime(isoString: string): string {
  const date = new Date(isoString)
  const now = new Date()
  const diff = now.getTime() - date.getTime()
  if (diff < 60000) return '刚刚'
  if (diff < 3600000) return `${Math.floor(diff / 60000)} 分钟前`
  if (diff < 86400000) return `${Math.floor(diff / 3600000)} 小时前`
  return `${date.getMonth() + 1}/${date.getDate()}`
}

function handleNewChat() {
  const newId = Math.max(...sessions.value.map(s => s.id)) + 1
  sessions.value.unshift({
    id: newId,
    title: '新对话',
    lastMessage: '',
    updatedAt: new Date().toISOString()
  })
  currentSessionId.value = newId
  messages.value = []
  inputText.value = ''
}

function selectSession(id: number) {
  currentSessionId.value = id
  // 这里应该加载该会话的历史消息
  messages.value = []
}

function handleSessionAction(command: string, sessionId: number) {
  if (command === 'delete') {
    sessions.value = sessions.value.filter(s => s.id !== sessionId)
    if (currentSessionId.value === sessionId) {
      currentSessionId.value = sessions.value[0]?.id || 0
    }
  }
}

async function handleSend() {
  if (!inputText.value.trim() || isGenerating.value) return

  const userMsg: Message = {
    id: Date.now(),
    role: 'user',
    content: inputText.value.trim()
  }
  messages.value.push(userMsg)
  inputText.value = ''

  await nextTick()
  scrollToBottom()

  // 模拟助手回复
  isGenerating.value = true
  const assistantMsg: Message = {
    id: Date.now() + 1,
    role: 'assistant',
    content: '',
    streaming: true,
    steps: [
      { description: '正在读取任务材料', status: 'completed', result: '已读取 3 份文件' },
      { description: '正在检索知识库', status: 'running' },
      { description: '组织审核建议', status: 'pending' }
    ]
  }
  messages.value.push(assistantMsg)

  // 模拟流式响应
  setTimeout(() => {
    assistantMsg.steps![1].status = 'completed'
    assistantMsg.steps![1].result = '找到 3 条证据'
    assistantMsg.steps![2].status = 'running'
  }, 1000)

  setTimeout(() => {
    assistantMsg.steps![2].status = 'completed'
    assistantMsg.streaming = false
    assistantMsg.content = '根据贷款文件比对要求，这份单据被驳回的主要原因是：\n\n1. **借款用途不明确**：申请书中未详细说明具体用途\n2. **授信函缺失**：未提供银行授信函原件\n\n建议补充上述材料后重新提交。'
    assistantMsg.citations = [
      { docName: '贷款文件比对要求.xlsx', page: 1, score: 0.89, content: '借款用途必须在申请书中详细说明，不得含糊...' },
      { docName: '授信函要求说明.pdf', page: 3, score: 0.76, content: '授信函必须提供银行原件，复印件无效...' }
    ]
    isGenerating.value = false
  }, 3000)
}

function sendMessage(text: string) {
  inputText.value = text
  handleSend()
}

function copyMessage(content: string) {
  navigator.clipboard.writeText(content)
  ElMessage.success('已复制到剪贴板')
}

function regenerate(msgId: number) {
  ElMessage.info('重新生成功能开发中...')
}

function useSkill(skill: Skill) {
  inputText.value = `使用「${skill.name}」技能`
  handleSend()
}

function handleScroll() {
  if (!chatBodyRef.value) return
  const { scrollTop, scrollHeight, clientHeight } = chatBodyRef.value
  isAtBottom.value = scrollHeight - scrollTop - clientHeight < 50
}

function scrollToBottom() {
  nextTick(() => {
    if (chatBodyRef.value) {
      chatBodyRef.value.scrollTop = chatBodyRef.value.scrollHeight
    }
  })
}

onMounted(() => {
  // 模拟已有对话
  if (currentSessionId.value === 1) {
    messages.value = [
      { id: 1, role: 'user', content: '为什么这份单据被驳回？' },
      {
        id: 2,
        role: 'assistant',
        content: '根据贷款文件比对要求，驳回原因如下：\n\n1. 借款用途不明确\n2. 授信函缺失',
        steps: [
          { description: '读取任务材料', status: 'completed', result: '已读取 3 份文件' },
          { description: '检索知识库', status: 'completed', result: '找到 2 条证据' }
        ],
        citations: [
          { docName: '贷款文件比对要求.xlsx', page: 1, score: 0.89, content: '借款用途必须详细说明' }
        ]
      }
    ]
  }
})
</script>

<style scoped>
/* 全局布局 */
.assistant-shell {
  display: grid;
  grid-template-columns: 280px 1fr 320px;
  height: 100vh;
  background: #f8f9fa;
}

/* 左侧边栏 */
.sidebar {
  display: flex;
  flex-direction: column;
  border-right: 1px solid #e5e7eb;
  background: #fff;
  overflow: hidden;
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 20px 16px;
  border-bottom: 1px solid #f3f4f6;
}

.brand-icon {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  border-radius: 10px;
  background: linear-gradient(135deg, #10b981 0%, #059669 100%);
  color: white;
}

.brand-name {
  font-size: 16px;
  font-weight: 600;
  color: #111827;
}

.brand-caption {
  font-size: 12px;
  color: #6b7280;
}

.new-chat-btn {
  margin: 12px 16px;
  width: calc(100% - 32px);
}

.session-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.section-label {
  padding: 8px 12px 4px;
  color: #9ca3af;
  font-size: 12px;
  font-weight: 600;
}

.session-item {
  padding: 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: background .2s;
}

.session-item:hover {
  background: #f9fafb;
}

.session-item.active {
  background: #f0fdf4;
}

.session-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}

.session-title {
  font-size: 14px;
  font-weight: 600;
  color: #111827;
}

.session-more {
  opacity: 0;
  transition: opacity .2s;
  cursor: pointer;
}

.session-item:hover .session-more {
  opacity: 1;
}

.session-preview {
  font-size: 13px;
  color: #6b7280;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.session-time {
  margin-top: 4px;
  font-size: 12px;
  color: #9ca3af;
}

.sidebar-footer {
  padding: 12px 16px;
  border-top: 1px solid #f3f4f6;
}

.user-profile {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px;
  border-radius: 8px;
  cursor: pointer;
  transition: background .2s;
}

.user-profile:hover {
  background: #f9fafb;
}

.user-name {
  font-size: 14px;
  font-weight: 500;
}

/* 中间对话区 */
.chat-main {
  display: flex;
  flex-direction: column;
  background: #fff;
  overflow: hidden;
}

.chat-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 24px;
  border-bottom: 1px solid #f3f4f6;
}

.chat-title-group {
  display: flex;
  align-items: center;
  gap: 16px;
}

.chat-title {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
}

.task-selector {
  width: 200px;
}

.chat-body {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
  position: relative;
}

.welcome-screen {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 60px 24px;
}

.welcome-icon {
  margin-bottom: 20px;
}

.welcome-title {
  margin: 0 0 8px;
  font-size: 24px;
  font-weight: 600;
  color: #111827;
}

.welcome-subtitle {
  margin: 0 0 32px;
  color: #6b7280;
  font-size: 15px;
}

.prompt-suggestions {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
  max-width: 600px;
}

.prompt-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  background: #fff;
  cursor: pointer;
  transition: all .2s;
}

.prompt-card:hover {
  border-color: #10b981;
  box-shadow: 0 4px 12px rgba(16, 185, 129, .15);
  transform: translateY(-2px);
}

.prompt-icon {
  font-size: 24px;
}

.prompt-label {
  font-size: 14px;
  font-weight: 500;
}

.message-list {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.message-wrap {
  display: flex;
}

.message-user {
  justify-content: flex-end;
}

.message-assistant {
  justify-content: flex-start;
}

.user-bubble {
  max-width: 70%;
  padding: 12px 16px;
  border-radius: 16px;
  background: #10b981;
  color: white;
  font-size: 14px;
  line-height: 1.6;
  word-break: break-word;
}

.assistant-card {
  max-width: 85%;
  padding: 16px;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  background: #fff;
  box-shadow: 0 1px 2px rgba(0, 0, 0, .05);
}

.message-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}

.assistant-name {
  font-size: 14px;
  font-weight: 600;
}

.execution-steps {
  margin-bottom: 12px;
  border: 1px solid #f3f4f6;
  border-radius: 8px;
}

.step-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 8px 0;
}

.step-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
}

.step-text {
  flex: 1;
  font-size: 13px;
}

.step-result {
  font-size: 12px;
  color: #10b981;
}

.message-content {
  font-size: 14px;
  line-height: 1.7;
  color: #374151;
}

.message-content :deep(p) {
  margin: 0 0 12px;
}

.message-content :deep(code) {
  padding: 2px 6px;
  border-radius: 4px;
  background: #f3f4f6;
  font-size: 13px;
}

.message-citations {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid #f3f4f6;
}

.citation-label {
  margin-bottom: 8px;
  font-size: 12px;
  font-weight: 600;
  color: #6b7280;
}

.citation-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.citation-tag {
  cursor: pointer;
}

.citation-score {
  margin-left: 4px;
  color: #10b981;
  font-weight: 600;
}

.citation-preview-title {
  margin-bottom: 8px;
  font-size: 13px;
  font-weight: 600;
}

.citation-preview-content {
  font-size: 12px;
  color: #6b7280;
  line-height: 1.6;
}

.message-actions {
  display: flex;
  gap: 8px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid #f9fafb;
}

.scroll-to-bottom {
  position: absolute;
  right: 24px;
  bottom: 24px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, .15);
}

.chat-input-wrap {
  display: flex;
  align-items: flex-end;
  gap: 12px;
  padding: 16px 24px;
  border-top: 1px solid #f3f4f6;
}

.input-toolbar {
  display: flex;
  align-items: center;
}

.message-input {
  flex: 1;
}

.message-input :deep(.el-textarea__inner) {
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  padding: 12px 16px;
}

.send-btn {
  flex-shrink: 0;
}

/* 右侧技能栏 */
.skills-sidebar {
  display: flex;
  flex-direction: column;
  border-left: 1px solid #e5e7eb;
  background: #fff;
  overflow-y: auto;
}

.skills-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 20px 16px 12px;
  border-bottom: 1px solid #f3f4f6;
}

.skills-header h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
}

.skills-grid {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px;
}

.skill-card {
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  overflow: hidden;
  cursor: pointer;
  transition: all .2s;
}

.skill-card:hover {
  border-color: #10b981;
  box-shadow: 0 4px 12px rgba(16, 185, 129, .15);
  transform: translateY(-2px);
}

.skill-cover {
  display: grid;
  place-items: center;
  height: 80px;
}

.skill-icon {
  font-size: 32px;
}

.skill-body {
  padding: 12px;
}

.skill-name {
  margin: 0 0 4px;
  font-size: 14px;
  font-weight: 600;
}

.skill-desc {
  margin: 0 0 8px;
  font-size: 12px;
  color: #6b7280;
  line-height: 1.5;
}

.skill-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

/* 响应式 */
@media (max-width: 1200px) {
  .assistant-shell {
    grid-template-columns: 240px 1fr;
  }
  .skills-sidebar {
    display: none;
  }
}

@media (max-width: 768px) {
  .assistant-shell {
    grid-template-columns: 1fr;
  }
  .sidebar {
    position: fixed;
    left: 0;
    top: 0;
    bottom: 0;
    z-index: 100;
    transform: translateX(-100%);
    transition: transform .3s;
  }
  .sidebar.show {
    transform: translateX(0);
  }
}
</style>
