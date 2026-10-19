<!--
  AI 助手 V2：暗色专业版
  参考：Lobe Chat 暗色主题 + 金融终端风格
  特点：深蓝配色、护眼设计、专业感强
-->
<template>
  <div class="assistant-dark">
    <!-- 左侧会话栏 -->
    <aside class="sidebar-dark">
      <div class="brand-dark">
        <div class="brand-mark-dark">
          <el-icon :size="26"><ChatDotRound /></el-icon>
        </div>
        <div class="brand-info">
          <div class="brand-title">慧眼</div>
          <div class="brand-badge">智能助理</div>
        </div>
      </div>

      <el-button type="primary" class="new-btn-dark" @click="handleNewChat">
        <el-icon><Plus /></el-icon>
        新建会话
      </el-button>

      <div class="sessions-dark">
        <div
          v-for="s in sessions"
          :key="s.id"
          :class="['session-dark', { active: currentId === s.id }]"
          @click="currentId = s.id"
        >
          <div class="session-dot"></div>
          <div class="session-info">
            <div class="session-name">{{ s.title }}</div>
            <div class="session-time">{{ formatTime(s.updatedAt) }}</div>
          </div>
        </div>
      </div>

      <div class="sidebar-foot">
        <div class="user-card-dark">
          <el-avatar :size="36">{{ profile.name[0] }}</el-avatar>
          <span class="user-label">{{ profile.name }}</span>
        </div>
      </div>
    </aside>

    <!-- 主对话区 -->
    <main class="main-dark">
      <header class="header-dark">
        <div class="header-left">
          <h1 class="chat-label">{{ currentSession?.title || '新对话' }}</h1>
          <el-select v-model="taskCode" placeholder="选择任务" size="small" class="task-select-dark">
            <el-option v-for="t in tasks" :key="t.code" :label="t.code" :value="t.code" />
          </el-select>
        </div>
        <div class="header-right">
          <el-button text @click="showSettings = true">
            <el-icon color="#94a3b8"><Setting /></el-icon>
          </el-button>
        </div>
      </header>

      <div class="chat-area-dark" ref="chatRef">
        <!-- 欢迎界面 -->
        <div v-if="!messages.length" class="welcome-dark">
          <div class="welcome-avatar">
            <el-icon :size="72" color="#3b82f6"><Histogram /></el-icon>
          </div>
          <h2 class="welcome-h2">让审核工作更快一步</h2>
          <p class="welcome-p">解析单据、验证规则、检索证据</p>
          <div class="quick-prompts">
            <div v-for="(p, i) in prompts" :key="i" class="quick-item" @click="sendQuick(p.text)">
              <span class="quick-emoji">{{ p.emoji }}</span>
              <span class="quick-label">{{ p.label }}</span>
            </div>
          </div>
        </div>

        <!-- 消息列表 -->
        <div v-else class="msg-list-dark">
          <div v-for="m in messages" :key="m.id" :class="['msg-row-dark', `msg-${m.role}`]">
            <div v-if="m.role === 'user'" class="user-msg-dark">
              {{ m.content }}
            </div>

            <div v-else class="asst-msg-dark">
              <div class="asst-head">
                <el-avatar :size="36" class="asst-avatar">
                  <el-icon><ChatDotRound /></el-icon>
                </el-avatar>
                <span class="asst-label">慧眼助手</span>
                <el-tag v-if="m.streaming" size="small" type="info" effect="dark">
                  <el-icon class="is-loading"><Loading /></el-icon>
                  思考中
                </el-tag>
              </div>

              <!-- 步骤轨迹 -->
              <el-collapse v-if="m.steps?.length" class="steps-dark">
                <el-collapse-item name="1">
                  <template #title>
                    <el-icon><Operation /></el-icon>
                    <span>执行轨迹（{{ m.steps.length }} 步）</span>
                  </template>
                  <div class="step-track">
                    <div v-for="(st, idx) in m.steps" :key="idx" :class="['step-row', `step-${st.status}`]">
                      <el-icon v-if="st.status === 'completed'" color="#10b981"><CircleCheckFilled /></el-icon>
                      <el-icon v-else-if="st.status === 'running'" class="is-loading" color="#3b82f6"><Loading /></el-icon>
                      <el-icon v-else color="#475569"><CircleFilled /></el-icon>
                      <span class="step-desc">{{ st.description }}</span>
                      <span v-if="st.result" class="step-res">{{ st.result }}</span>
                    </div>
                  </div>
                </el-collapse-item>
              </el-collapse>

              <!-- 内容 -->
              <div class="asst-content" v-html="renderMd(m.content)"></div>

              <!-- 证据 -->
              <div v-if="m.citations?.length" class="citations-dark">
                <div class="cite-label">证据来源</div>
                <div class="cite-tags">
                  <el-popover v-for="(c, i) in m.citations" :key="i" placement="top" :width="300">
                    <template #reference>
                      <el-tag size="small" class="cite-tag-dark">
                        {{ c.docName }} · p.{{ c.page }}
                        <span class="cite-score">{{ Math.round(c.score * 100) }}%</span>
                      </el-tag>
                    </template>
                    <div class="cite-preview-dark">
                      <div class="cite-preview-title">{{ c.docName }}</div>
                      <div class="cite-preview-text">{{ c.content.slice(0, 80) }}...</div>
                    </div>
                  </el-popover>
                </div>
              </div>

              <!-- 操作 -->
              <div class="asst-actions">
                <el-button text size="small" @click="copy(m.content)">
                  <el-icon><DocumentCopy /></el-icon>
                  复制
                </el-button>
                <el-button text size="small">
                  <el-icon><RefreshRight /></el-icon>
                  重新生成
                </el-button>
              </div>
            </div>
          </div>
        </div>

        <!-- 滚动按钮 -->
        <transition name="el-fade-in">
          <el-button v-show="!atBottom" class="scroll-btn-dark" circle @click="scrollDown">
            <el-icon><ArrowDown /></el-icon>
          </el-button>
        </transition>
      </div>

      <!-- 输入框 -->
      <div class="input-zone-dark">
        <el-input
          v-model="inputVal"
          type="textarea"
          :autosize="{ minRows: 1, maxRows: 5 }"
          placeholder="描述你想核对的规则..."
          @keydown.enter.exact.prevent="send"
          class="input-dark"
        />
        <el-button
          type="primary"
          :loading="generating"
          :disabled="!inputVal.trim()"
          @click="send"
          class="send-dark"
        >
          <el-icon v-if="!generating"><Promotion /></el-icon>
          发送
        </el-button>
      </div>
    </main>

    <!-- 右侧技能栏 -->
    <aside class="skills-dark">
      <div class="skills-head">
        <h3>审核技能</h3>
        <el-button text size="small" @click="showAll = !showAll">
          {{ showAll ? '收起' : '全部' }}
        </el-button>
      </div>

      <div class="skills-scroll">
        <div v-for="sk in (showAll ? skills : skills.slice(0, 3))" :key="sk.id" class="skill-dark" @click="useSk(sk)">
          <div class="skill-cover-dark" :style="{ background: sk.grad }">
            <div class="skill-emoji">{{ sk.emoji }}</div>
          </div>
          <div class="skill-detail">
            <h4 class="skill-h4">{{ sk.name }}</h4>
            <p class="skill-p">{{ sk.desc }}</p>
            <el-tag size="small" type="info" effect="dark">🔥 {{ sk.use }}次</el-tag>
          </div>
        </div>
      </div>

      <div class="skills-hot">
        <div class="hot-title">热门技能</div>
        <div class="hot-list">
          <div v-for="h in hotSkills" :key="h" class="hot-item" @click="useSkById(h)">
            {{ skills.find(s => s.id === h)?.emoji }} {{ skills.find(s => s.id === h)?.name }}
          </div>
        </div>
      </div>
    </aside>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, nextTick } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import {
  ChatDotRound, Plus, Setting, Histogram, Loading, Operation,
  CircleCheckFilled, CircleFilled, DocumentCopy, RefreshRight,
  ArrowDown, Promotion
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

const profile = ref({ name: '李四' })
const sessions = ref([
  { id: 1, title: 'LN0823', updatedAt: '2026-10-20T10:30:00' },
  { id: 2, title: '制裁筛查', updatedAt: '2026-10-19T15:00:00' }
])
const currentId = ref(1)
const currentSession = computed(() => sessions.value.find(s => s.id === currentId.value))

const messages = ref<Msg[]>([])
const inputVal = ref('')
const generating = ref(false)
const atBottom = ref(true)
const showSettings = ref(false)
const showAll = ref(false)

const taskCode = ref('')
const tasks = ref([{ code: 'LN0823', borrower: '某公司' }])

const prompts = [
  { emoji: '📋', label: '梳理风险', text: '梳理当前任务的主要风险点' },
  { emoji: '🔍', label: '驳回原因', text: '为什么被驳回？' },
  { emoji: '📄', label: '文件核对', text: '检查必备文件是否齐全' },
  { emoji: '⚖️', label: '法规检索', text: '这种用途符合哪些法规？' }
]

const skills = ref([
  { id: 'bill', name: '提单验真', desc: '核验海运提单真实性', emoji: '🚢', grad: 'linear-gradient(135deg, #3b82f6, #1e40af)', use: 67 },
  { id: 'sanc', name: '制裁筛查', desc: '检查制裁名单', emoji: '🔒', grad: 'linear-gradient(135deg, #f59e0b, #d97706)', use: 54 },
  { id: 'exch', name: '汇率换算', desc: '验证汇率合理性', emoji: '💱', grad: 'linear-gradient(135deg, #10b981, #059669)', use: 43 },
  { id: 'holi', name: '节假日核查', desc: '检查日期冲突', emoji: '📅', grad: 'linear-gradient(135deg, #8b5cf6, #6d28d9)', use: 31 }
])

const hotSkills = ref(['bill', 'sanc', 'exch'])

const chatRef = ref<HTMLElement>()

function renderMd(text: string): string {
  const html = marked.parse(text) as string
  return DOMPurify.sanitize(html, {
    ALLOWED_TAGS: ['p', 'strong', 'em', 'ul', 'ol', 'li', 'code', 'pre', 'br']
  })
}

function formatTime(iso: string): string {
  const date = new Date(iso)
  return `${date.getMonth() + 1}/${date.getDate()}`
}

function handleNewChat() {
  const newId = Math.max(...sessions.value.map(s => s.id)) + 1
  sessions.value.unshift({ id: newId, title: '新对话', updatedAt: new Date().toISOString() })
  currentId.value = newId
  messages.value = []
}

function send() {
  if (!inputVal.value.trim() || generating.value) return

  messages.value.push({ id: Date.now(), role: 'user', content: inputVal.value.trim() })
  inputVal.value = ''

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
    asst.content = '根据规则，驳回原因：\n\n1. 借款用途不明确\n2. 授信函缺失'
    asst.citations = [
      { docName: '比对要求.xlsx', page: 1, score: 0.89, content: '借款用途必须详细说明' }
    ]
    generating.value = false
  }, 2000)
}

function sendQuick(text: string) {
  inputVal.value = text
  send()
}

function copy(text: string) {
  navigator.clipboard.writeText(text)
  ElMessage.success('已复制')
}

function useSk(sk: any) {
  inputVal.value = `使用「${sk.name}」`
  send()
}

function useSkById(id: string) {
  const sk = skills.value.find(s => s.id === id)
  if (sk) useSk(sk)
}

function scrollDown() {
  nextTick(() => {
    if (chatRef.value) chatRef.value.scrollTop = chatRef.value.scrollHeight
  })
}
</script>

<style scoped>
/* 暗色全局 */
.assistant-dark {
  display: grid;
  grid-template-columns: 260px 1fr 300px;
  height: 100vh;
  background: #0f172a;
  color: #cbd5e1;
}

/* 左侧栏 */
.sidebar-dark {
  display: flex;
  flex-direction: column;
  border-right: 1px solid #1e293b;
  background: #0a0f1e;
}

.brand-dark {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 20px 16px;
  border-bottom: 1px solid #1e293b;
}

.brand-mark-dark {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  border-radius: 12px;
  background: linear-gradient(135deg, #3b82f6, #1e40af);
  color: white;
}

.brand-title {
  font-size: 18px;
  font-weight: 700;
  color: #f1f5f9;
}

.brand-badge {
  font-size: 11px;
  color: #64748b;
}

.new-btn-dark {
  margin: 16px;
  width: calc(100% - 32px);
  background: linear-gradient(135deg, #3b82f6, #2563eb);
  border: none;
}

.sessions-dark {
  flex: 1;
  overflow-y: auto;
  padding: 8px 12px;
}

.session-dark {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: background .2s;
}

.session-dark:hover {
  background: #1e293b;
}

.session-dark.active {
  background: #1e3a5f;
}

.session-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #3b82f6;
}

.session-name {
  font-size: 14px;
  font-weight: 600;
  color: #e2e8f0;
}

.session-time {
  font-size: 12px;
  color: #64748b;
  margin-top: 2px;
}

.sidebar-foot {
  padding: 16px;
  border-top: 1px solid #1e293b;
}

.user-card-dark {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px;
  border-radius: 8px;
  cursor: pointer;
}

.user-card-dark:hover {
  background: #1e293b;
}

.user-label {
  font-size: 14px;
  font-weight: 500;
}

/* 主区 */
.main-dark {
  display: flex;
  flex-direction: column;
  background: #0f172a;
}

.header-dark {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 24px;
  border-bottom: 1px solid #1e293b;
  background: #0a0f1e;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.chat-label {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: #f1f5f9;
}

.task-select-dark {
  width: 180px;
}

.chat-area-dark {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
  position: relative;
}

.welcome-dark {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 80px 24px;
}

.welcome-avatar {
  margin-bottom: 24px;
  padding: 20px;
  border-radius: 20px;
  background: linear-gradient(135deg, #1e3a8a 0%, #3b82f6 100%);
}

.welcome-h2 {
  margin: 0 0 12px;
  font-size: 28px;
  font-weight: 700;
  color: #f1f5f9;
}

.welcome-p {
  margin: 0 0 40px;
  font-size: 16px;
  color: #94a3b8;
}

.quick-prompts {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
  max-width: 600px;
}

.quick-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px;
  border: 1px solid #1e293b;
  border-radius: 12px;
  background: #0a0f1e;
  cursor: pointer;
  transition: all .2s;
}

.quick-item:hover {
  border-color: #3b82f6;
  background: #1e3a8a;
  transform: translateY(-2px);
}

.quick-emoji {
  font-size: 24px;
}

.quick-label {
  font-size: 14px;
  font-weight: 500;
  color: #e2e8f0;
}

.msg-list-dark {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.msg-row-dark {
  display: flex;
}

.msg-user {
  justify-content: flex-end;
}

.msg-assistant {
  justify-content: flex-start;
}

.user-msg-dark {
  max-width: 70%;
  padding: 12px 18px;
  border-radius: 18px;
  background: linear-gradient(135deg, #3b82f6, #2563eb);
  color: white;
  font-size: 14px;
  line-height: 1.6;
}

.asst-msg-dark {
  max-width: 85%;
  padding: 18px;
  border: 1px solid #1e293b;
  border-radius: 12px;
  background: #0a0f1e;
}

.asst-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
}

.asst-label {
  font-size: 14px;
  font-weight: 600;
  color: #e2e8f0;
}

.steps-dark {
  margin-bottom: 14px;
  border: 1px solid #1e293b;
  border-radius: 8px;
  background: #0f172a;
}

.step-track {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 10px;
}

.step-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.step-desc {
  flex: 1;
  font-size: 13px;
  color: #cbd5e1;
}

.step-res {
  font-size: 12px;
  color: #10b981;
}

.asst-content {
  font-size: 14px;
  line-height: 1.7;
  color: #cbd5e1;
}

.asst-content :deep(p) {
  margin: 0 0 12px;
}

.asst-content :deep(code) {
  padding: 3px 8px;
  border-radius: 4px;
  background: #1e293b;
  color: #3b82f6;
}

.citations-dark {
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px solid #1e293b;
}

.cite-label {
  margin-bottom: 8px;
  font-size: 12px;
  font-weight: 600;
  color: #64748b;
}

.cite-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.cite-tag-dark {
  cursor: pointer;
  background: #1e293b;
  border-color: #334155;
}

.cite-score {
  margin-left: 4px;
  color: #10b981;
  font-weight: 600;
}

.cite-preview-dark {
  padding: 12px;
  background: #0f172a;
  border-radius: 8px;
}

.cite-preview-title {
  margin-bottom: 8px;
  font-size: 13px;
  font-weight: 600;
  color: #e2e8f0;
}

.cite-preview-text {
  font-size: 12px;
  color: #94a3b8;
  line-height: 1.6;
}

.asst-actions {
  display: flex;
  gap: 10px;
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px solid #1e293b;
}

.scroll-btn-dark {
  position: absolute;
  right: 24px;
  bottom: 24px;
  background: #1e293b;
  border-color: #334155;
}

.input-zone-dark {
  display: flex;
  align-items: flex-end;
  gap: 12px;
  padding: 16px 24px;
  border-top: 1px solid #1e293b;
  background: #0a0f1e;
}

.input-dark {
  flex: 1;
}

.input-dark :deep(.el-textarea__inner) {
  border: 1px solid #1e293b;
  border-radius: 12px;
  padding: 14px 18px;
  background: #0f172a;
  color: #cbd5e1;
}

.send-dark {
  background: linear-gradient(135deg, #3b82f6, #2563eb);
  border: none;
}

/* 右侧栏 */
.skills-dark {
  display: flex;
  flex-direction: column;
  border-left: 1px solid #1e293b;
  background: #0a0f1e;
  overflow-y: auto;
}

.skills-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 20px 16px;
  border-bottom: 1px solid #1e293b;
}

.skills-head h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: #f1f5f9;
}

.skills-scroll {
  flex: 1;
  padding: 16px;
  overflow-y: auto;
}

.skill-dark {
  margin-bottom: 12px;
  border: 1px solid #1e293b;
  border-radius: 12px;
  overflow: hidden;
  cursor: pointer;
  transition: all .2s;
}

.skill-dark:hover {
  border-color: #3b82f6;
  transform: translateY(-2px);
}

.skill-cover-dark {
  display: grid;
  place-items: center;
  height: 90px;
}

.skill-emoji {
  font-size: 36px;
}

.skill-detail {
  padding: 14px;
}

.skill-h4 {
  margin: 0 0 6px;
  font-size: 15px;
  font-weight: 600;
  color: #e2e8f0;
}

.skill-p {
  margin: 0 0 10px;
  font-size: 12px;
  color: #94a3b8;
  line-height: 1.5;
}

.skills-hot {
  padding: 16px;
  border-top: 1px solid #1e293b;
}

.hot-title {
  margin-bottom: 12px;
  font-size: 13px;
  font-weight: 600;
  color: #64748b;
}

.hot-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.hot-item {
  padding: 10px 12px;
  border-radius: 8px;
  background: #1e293b;
  font-size: 13px;
  color: #cbd5e1;
  cursor: pointer;
  transition: background .2s;
}

.hot-item:hover {
  background: #334155;
}

@media (max-width: 1200px) {
  .assistant-dark {
    grid-template-columns: 240px 1fr;
  }
  .skills-dark {
    display: none;
  }
}
</style>
