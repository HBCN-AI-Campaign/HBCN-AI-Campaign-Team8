<template>
  <div class="assistant-page">
    <section class="assistant-shell">
      <!-- 左：会话 -->
      <aside class="session-rail">
        <div class="rail-brand">
          <span class="brand-mark"><el-icon><MagicStick /></el-icon></span>
          <span class="brand-name">慧眼助手</span>
        </div>
        <el-button class="new-session" type="primary" :icon="Plus" :disabled="loading" @click="newSession">新建会话</el-button>
        <div class="session-list">
          <button v-for="item in sessions" :key="item.id" class="session-item"
            :class="{ active: item.id === activeSessionId }" :disabled="loading" @click="openSession(item.id)">
            <span class="session-dot"></span>
            <span class="session-title">{{ item.title }}</span>
            <span class="session-count">{{ item.message_count }}</span>
          </button>
          <div v-if="!sessions.length" class="empty-rail">暂无会话</div>
        </div>
        <div class="rail-foot">
          <span class="live-dot" :class="{ ready: capabilities?.configured }"></span>
          {{ capabilities?.configured ? '模型已连接' : '本地演示模式' }}
        </div>
      </aside>

      <!-- 中：对话 -->
      <main class="chat-column">
        <header class="chat-head">
          <div class="head-title">
            <h2>{{ activeSession?.title || '新会话' }}</h2>
            <el-select v-if="tasks.length" v-model="taskSelection" class="task-select" size="small" clearable
              placeholder="关联任务" :disabled="loading" @change="selectTaskContext">
              <el-option v-for="task in tasks" :key="task.id" :value="task.task_code"
                :label="`${task.task_code} · ${task.borrower}`" />
            </el-select>
            <span v-else class="task-hint">未关联任务</span>
          </div>
          <div class="head-actions">
            <el-button class="mobile-session-trigger" circle :icon="ChatDotRound" title="会话列表" aria-label="会话列表" @click="mobileSessionsVisible = true" />
            <el-button class="mobile-skill-trigger" text @click="mobileSkillsVisible = true">审核技能</el-button>
            <el-button text :icon="ArrowLeft" @click="router.push({ name: 'dashboard' })">返回</el-button>
          </div>
        </header>

        <div ref="messageList" class="message-list">
          <div v-if="!messages.length" class="welcome-block">
            <div class="welcome-icon"><el-icon><MagicStick /></el-icon></div>
            <h3>让审核工作更快一步</h3>
            <p>我可以读取授权任务材料与规则结果，检索证据、解释规则并整理人工复核意见。</p>
            <div class="prompt-grid">
              <button v-for="prompt in prompts" :key="prompt.title" class="prompt-card" @click="usePrompt(prompt.text)">
                <span class="prompt-icon"><el-icon><component :is="prompt.icon" /></el-icon></span>
                <span><strong>{{ prompt.title }}</strong><small>{{ prompt.text }}</small></span>
              </button>
            </div>
          </div>

          <article v-for="message in messages" :key="message.id" class="message-row" :class="message.role">
            <div class="avatar" :class="message.role">
              <el-icon v-if="message.role === 'assistant'"><MagicStick /></el-icon>
              <span v-else>{{ auth.displayName?.slice(0, 1) || '我' }}</span>
            </div>
            <div class="message-body">
              <div class="message-meta">
                <strong>{{ message.role === 'assistant' ? '慧眼助手' : '你' }}</strong>
                <span v-if="message.streaming" class="streaming-label">正在生成</span>
                <button v-if="message.role === 'assistant' && safeMessageContent(message) && !message.streaming" class="copy-btn"
                  title="复制回答" aria-label="复制回答" @click="copyMessage(message)"><el-icon><CopyDocument /></el-icon></button>
              </div>
              <div class="message-card">
                <div v-if="message.steps?.length || message.streaming" class="activity-panel" :class="{ running: message.streaming }">
                  <button class="activity-heading" :aria-expanded="activityExpanded(message)" @click="toggleActivity(message)">
                    <span class="activity-spark"><el-icon v-if="message.streaming" class="spin"><Loading /></el-icon><el-icon v-else><CircleCheck /></el-icon></span>
                    <span class="activity-heading-copy"><b>{{ activityTitle(message) }}</b><small>{{ activitySubtitle(message) }}</small></span>
                    <el-icon class="activity-chevron" :class="{ expanded: activityExpanded(message) }"><ArrowRight /></el-icon>
                  </button>
                  <div v-if="activityExpanded(message)" class="activity-feed">
                    <div v-for="step in message.steps" :key="step.key" class="activity-event" :class="step.status">
                      <span class="event-marker"><el-icon v-if="step.status === 'completed'"><Check /></el-icon><el-icon v-else-if="step.status === 'error'"><Close /></el-icon><span v-else class="event-pulse"></span></span>
                      <div class="event-copy"><b>{{ step.label }}</b><small v-if="step.detail">{{ step.detail }}</small></div>
                    </div>
                    <div v-for="(tool, index) in toolActivity" :key="`${tool.name}-${index}`" class="activity-event" :class="tool.status">
                      <span class="event-marker"><el-icon v-if="tool.status === 'completed'"><Check /></el-icon><span v-else class="event-pulse"></span></span>
                      <div class="event-copy"><b>{{ toolLabel(tool.name) }}</b><small>{{ tool.status === 'running' ? '正在检索授权材料与知识库' : `找到 ${tool.result_count ?? 0} 条相关证据` }}</small></div>
                    </div>
                    <div v-if="message.streaming" class="activity-event pending"><span class="event-marker"><span class="event-pulse"></span></span><div class="event-copy"><b>组织审核建议</b><small>正在整合材料、规则和知识库依据</small></div></div>
                  </div>
                </div>
                <div class="message-content">
                  <CopilotChatAssistantMessage
                    v-if="message.role === 'assistant'"
                    :message="toCopilotMessage(message)"
                    :is-running="Boolean(message.streaming)"
                    :toolbar-visible="false"
                    class="copilot-answer"
                  />
                  <div v-else class="user-content">{{ message.content }}</div>
                </div>
                <div v-if="message.citations?.length" class="citation-wrap">
                  <div class="citation-label">证据引用</div>
                  <div class="citation-list">
                    <span v-for="citation in message.citations" :key="citation.id" class="citation-chip"
                      :class="citation.status" :title="citation.detail">
                      <span v-if="citation.status" class="cite-dot"></span>{{ citation.label }}
                      <small v-if="citation.page"> · p.{{ citation.page }}</small>
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </article>
        </div>

        <footer class="composer-wrap">
          <div v-if="runningSkill" class="skill-running"><el-icon class="spin"><Loading /></el-icon>正在执行：{{ runningSkill }}</div>
          <form class="composer" @submit.prevent="sendMessage">
            <el-input v-model="draft" type="textarea" :rows="1" :maxlength="8000" resize="none" :disabled="loading"
              placeholder="描述你想核对的规则、材料或风险…" @keydown.enter.exact.prevent="sendMessage" />
            <el-button v-if="!loading" class="send-button" type="primary" circle :icon="Promotion"
              :disabled="!draft.trim()" native-type="submit" title="发送消息" aria-label="发送消息" />
            <el-button v-else class="send-button stop-button" circle :icon="VideoPause" title="停止生成" aria-label="停止生成" @click.prevent="stopGeneration" />
          </form>
          <div class="composer-foot">受控只读 · 结论由审核人员确认</div>
        </footer>
      </main>

      <!-- 右：审核技能 -->
      <aside class="skill-rail">
        <div class="skill-head">审核技能</div>
        <div class="skill-list">
          <button v-for="skill in skills" :key="skill.name" class="skill-item" :disabled="loading" @click="runSkill(skill)">
            <span class="skill-icon"><el-icon><component :is="skill.icon" /></el-icon></span>
            <span class="skill-copy"><b>{{ skill.name }}</b><small>{{ skill.desc }}</small></span>
          </button>
        </div>
        <div class="skill-foot">技能沉淀自审核专家经验，点击即可运行</div>
      </aside>
    </section>
    <el-drawer v-model="mobileSessionsVisible" title="会话" direction="ltr" size="min(88vw, 360px)">
      <el-button class="new-session" type="primary" :icon="Plus" :disabled="loading" @click="newSession">新建会话</el-button>
      <div class="mobile-session-list">
        <button v-for="item in sessions" :key="item.id" class="session-item"
          :class="{ active: item.id === activeSessionId }" :disabled="loading" @click="openSession(item.id)">
          <span class="session-dot"></span>
          <span class="session-title">{{ item.title }}</span>
          <span class="session-count">{{ item.message_count }}</span>
        </button>
      </div>
    </el-drawer>
    <el-drawer v-model="mobileSkillsVisible" title="审核技能" direction="rtl" size="min(88vw, 360px)">
      <div class="mobile-skill-list">
        <button v-for="skill in skills" :key="skill.name" class="skill-item" :disabled="loading" @click="runSkill(skill)">
          <span class="skill-icon"><el-icon><component :is="skill.icon" /></el-icon></span>
          <span class="skill-copy"><b>{{ skill.name }}</b><small>{{ skill.desc }}</small></span>
        </button>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, defineAsyncComponent, nextTick, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { ElMessage } from 'element-plus'
import { assistantApi } from '@/assistant/api'
import '@copilotkit/vue/styles.css'
import type { AssistantCapabilities, AssistantMessage, AssistantSession, AssistantSkill, AssistantStep, AssistantTaskOption, AssistantToolActivity } from '@/assistant/types'
import type { AssistantMessage as CopilotMessage } from '@ag-ui/core'
import { ArrowLeft, ArrowRight, Calendar, ChatDotRound, Check, CircleCheck, Close, Coin, CopyDocument, DataLine, DocumentChecked, FolderOpened, Loading, Lock, MagicStick, Plus, Promotion, Reading, Search, Ship, VideoPause } from '@element-plus/icons-vue'

const router = useRouter()
const auth = useAuthStore()
const CopilotChatAssistantMessage = defineAsyncComponent(() => import('@copilotkit/vue/v2').then((module) => module.CopilotChatAssistantMessage))
const sessions = ref<AssistantSession[]>([])
const tasks = ref<AssistantTaskOption[]>([])
const activeSessionId = ref<number | null>(null)
const taskSelection = ref('')
const messages = ref<AssistantMessage[]>([])
const capabilities = ref<AssistantCapabilities | null>(null)
const draft = ref('')
const loading = ref(false)
const messageList = ref<HTMLElement | null>(null)
const activeTrace = ref<AssistantStep[]>([])
const toolActivity = ref<AssistantToolActivity[]>([])
const runningSkill = ref('')
const mobileSkillsVisible = ref(false)
const mobileSessionsVisible = ref(false)
const expandedActivityIds = ref(new Set<number | string>())
const streamAbortController = ref<AbortController | null>(null)

const prompts = [
  { title: '梳理风险', text: '帮我总结当前任务的风险和人工核对点', icon: DocumentChecked },
  { title: '解释规则', text: '解释当前不通过项，给出材料定位建议', icon: Search },
  { title: '材料核对', text: '哪些单据字段需要优先复核？', icon: FolderOpened },
]

const skills: AssistantSkill[] = [
  {
    name: '提单验真', desc: '核验海运提单关键信息', icon: Ship,
    prompt: '请执行【提单验真】：对当前关联任务的提单类单据，核验提单号、装运港/目的港、承运人与发票/合同的一致性，用表格列出：核对项 | 单据字段 | 是否一致 | 说明。证据不足的项标注“需人工确认”。',
  },
  {
    name: '汇率换算', desc: '核对币种与汇率折算', icon: Coin,
    prompt: '请执行【汇率换算】：核对关联任务的提款/支付币种与金额，检查是否存在跨币种折算及其汇率依据，用表格列出：单据 | 原币种 | 金额 | 折算说明。',
  },
  {
    name: '节假日核验', desc: '检查提款/付款日是否节假日', icon: Calendar,
    prompt: '请执行【节假日核验】：对关联任务的提款/付款日期，核验目标市场节假日与工作日历，用表格列出：单据 | 日期 | 是否节假日 | 说明。不确定处标注“需人工确认”。',
  },
  {
    name: '制裁名单筛查', desc: '筛查制裁与黑名单命中', icon: Lock,
    prompt: '请执行【制裁名单筛查】：检查关联任务的借款人、汇款人、收款人是否涉及制裁名单，用表格列出：主体 | 类型 | 筛查结果 | 说明。',
  },
  {
    name: '法规检索', desc: '检索跨境贷款适用法规', icon: Reading,
    prompt: '请执行【法规检索】：针对关联任务的跨境贷款场景，检索适用的外汇/跨境融资法规要点，用表格列出：法规 | 要点 | 对当前任务的影响。',
  },
  {
    name: '单据比对', desc: '核对单据字段一致性', icon: DataLine,
    prompt: '请执行【单据比对】：对比关联任务各单据的金额、币种、主体、期限等字段一致性，用表格列出：字段 | 各单据取值 | 是否一致 | 说明。',
  },
]

const activeSession = computed(() => sessions.value.find((item) => item.id === activeSessionId.value))

async function loadSessions() {
  try {
    const [items, capability] = await Promise.all([assistantApi.sessions(), assistantApi.capabilities()])
    sessions.value = items
    capabilities.value = capability
    try {
      tasks.value = await assistantApi.tasks(auth.role !== 'operator')
    } catch {
      ElMessage.warning('任务列表暂不可用，仍可使用通用助手会话')
    }
    if (items.length) await openSession(items[0].id)
    else await newSession()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '助手服务暂不可用')
  }
}

async function newSession() {
  mobileSessionsVisible.value = false
  try {
    const created = await assistantApi.createSession()
    sessions.value = [created, ...sessions.value]
    activeSessionId.value = created.id
    taskSelection.value = ''
    messages.value = []
    activeTrace.value = []
    toolActivity.value = []
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '无法创建会话')
  }
}

async function openSession(id: number) {
  mobileSessionsVisible.value = false
  try {
    const detail = await assistantApi.session(id)
    activeSessionId.value = id
    taskSelection.value = detail.task_code || ''
    messages.value = detail.messages
    activeTrace.value = messages.value[messages.value.length - 1]?.steps || []
    toolActivity.value = []
    scrollToBottom()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '无法打开会话')
  }
}

async function selectTaskContext(taskCode: string | undefined) {
  try {
    if (!taskCode) {
      await newSession()
      return
    }
    const task = tasks.value.find((item) => item.task_code === taskCode)
    const created = await assistantApi.createSession(task ? `${task.task_code} · ${task.borrower}` : taskCode, taskCode)
    sessions.value = [created, ...sessions.value]
    activeSessionId.value = created.id
    taskSelection.value = taskCode
    messages.value = []
    activeTrace.value = []
  } catch (error) {
    taskSelection.value = activeSession.value?.task_code || ''
    ElMessage.error(error instanceof Error ? error.message : '无法连接该任务')
  }
}

function usePrompt(text: string) { draft.value = text; sendMessage() }

async function runSkill(skill: AssistantSkill) {
  if (loading.value) return
  mobileSkillsVisible.value = false
  if (!activeSessionId.value) await newSession()
  runningSkill.value = skill.name
  draft.value = skill.prompt
  try {
    await sendMessage()
  } finally {
    runningSkill.value = ''
  }
}

async function sendMessage() {
  if (!draft.value.trim() || !activeSessionId.value || loading.value) return
  const content = draft.value.trim()
  draft.value = ''
  messages.value.push({ id: `user-${Date.now()}`, role: 'user', content, status: 'completed', steps: [], citations: [] })
  const assistant: AssistantMessage = { id: `assistant-${Date.now()}`, role: 'assistant', content: '', status: 'running', steps: [], citations: [], streaming: true }
  messages.value.push(assistant)
  loading.value = true
  const controller = new AbortController()
  streamAbortController.value = controller
  expandedActivityIds.value.add(assistant.id)
  activeTrace.value = []
  toolActivity.value = []
  scrollToBottom()
  try {
    for await (const event of assistantApi.streamMessage(activeSessionId.value, content, activeSession.value?.task_code || undefined, controller.signal)) {
      if (event.event === 'step' && event.step) {
        const step = event.step
        const index = assistant.steps.findIndex((current) => current.key === step.key)
        if (index >= 0) assistant.steps[index] = step
        else assistant.steps.push(step)
        activeTrace.value = [...assistant.steps]
      } else if (event.event === 'delta') assistant.content += event.delta || ''
      else if (event.event === 'citations') assistant.citations = event.citations || []
      else if (event.event === 'tool' && event.tool) {
        const found = toolActivity.value.find((item) => item.name === event.tool!.name)
        if (found) Object.assign(found, event.tool)
        else toolActivity.value.push({ ...event.tool })
      }
      else if (event.event === 'message_end' && event.message) {
        assistant.id = event.message.id
        assistant.content = event.message.content
        assistant.steps = event.message.steps || assistant.steps
        assistant.citations = event.message.citations || assistant.citations
        assistant.status = 'completed'
        assistant.streaming = false
        expandedActivityIds.value.delete(assistant.id)
      } else if (event.event === 'error') throw new Error(event.error_message || '助手执行失败')
      await nextTick()
      scrollToBottom()
    }
    const current = sessions.value.find((item) => item.id === activeSessionId.value)
    if (current) current.message_count += 2
  } catch (error) {
    assistant.status = 'error'
    assistant.streaming = false
    assistant.content = controller.signal.aborted ? '本次生成已停止。你可以补充要求后重新发送。' : error instanceof Error ? error.message : '助手执行失败，请重试'
    expandedActivityIds.value.delete(assistant.id)
    ElMessage.error(assistant.content)
  } finally {
    streamAbortController.value = null
    loading.value = false
  }
}

function stopGeneration() { streamAbortController.value?.abort() }

function activityExpanded(message: AssistantMessage) { return expandedActivityIds.value.has(message.id) }
function toggleActivity(message: AssistantMessage) {
  const next = new Set(expandedActivityIds.value)
  if (next.has(message.id)) next.delete(message.id)
  else next.add(message.id)
  expandedActivityIds.value = next
}
function activityTitle(message: AssistantMessage) {
  if (message.streaming) return '慧眼正在处理'
  if (message.status === 'error') return '本次处理未完成'
  return `完成 ${message.steps?.length ?? 0} 个执行步骤`
}
function activitySubtitle(message: AssistantMessage) {
  const toolCount = toolActivity.value.length
  return message.streaming ? `${toolCount ? `已调用 ${toolCount} 次证据检索` : '正在理解请求并准备检索'}` : '查看本轮执行轨迹'
}
function toolLabel(name: string) {
  if (name.includes('knowledge')) return '检索知识库'
  if (name.includes('task')) return '读取任务证据'
  return name.split('_').join(' ')
}
function safeMessageContent(message: AssistantMessage) {
  const markers = ['我们需要回答用户', '用户要求两句话', '需要引用任务材料或规则结果', '先调用 search_knowledge_base', 'let me think', 'we need to answer the user', 'analysis:', 'reasoning:']
  const content = message.content || ''
  if (markers.some((marker) => content.toLowerCase().includes(marker.toLowerCase()))) {
    return '这条历史答复包含不可展示的内部过程，已隐藏。请重新发送问题以获取审核辅助答复。'
  }
  return content
}

function toCopilotMessage(message: AssistantMessage): CopilotMessage {
  return { id: String(message.id), role: 'assistant', content: safeMessageContent(message) }
}

async function copyMessage(message: AssistantMessage) {
  try {
    await navigator.clipboard.writeText(safeMessageContent(message))
    ElMessage.success('已复制到剪贴板')
  } catch {
    ElMessage.error('复制失败，请手动选择文本')
  }
}

function scrollToBottom() { nextTick(() => { if (messageList.value) messageList.value.scrollTop = messageList.value.scrollHeight }) }
onMounted(loadSessions)
</script>

<style scoped>
.assistant-page { height: calc(100vh - 60px); margin: -20px; background: #f5f7fb; overflow: hidden; color: #17253f; }
.assistant-shell { height: 100%; display: grid; grid-template-columns: 232px minmax(0, 1fr) 252px; background: #fff; }

/* 左：会话 */
.session-rail { display: flex; flex-direction: column; min-height: 0; padding: 20px 14px 14px; background: #f8fafc; border-right: 1px solid #e7ecf3; }
.rail-brand { display: flex; align-items: center; gap: 10px; padding: 0 8px 20px; }
.brand-mark { display: grid; place-items: center; width: 34px; height: 34px; border-radius: 8px; background: linear-gradient(145deg, #356ed3, #214b99); color: #fff; font-size: 17px; }
.brand-name { color: #172844; font-size: 16px; font-weight: 700; }
.new-session { width: 100%; height: 38px; margin-bottom: 14px; border-radius: 7px; font-weight: 600; }
.session-list { flex: 1; overflow-y: auto; min-height: 0; }
.session-item { display: flex; align-items: center; width: 100%; gap: 9px; padding: 10px 9px; margin-bottom: 3px; border: 0; border-radius: 7px; background: transparent; color: #435574; text-align: left; cursor: pointer; }
.session-item:hover:not(:disabled), .session-item.active { background: #eaf1fd; color: #204f9e; }
.session-item:disabled { cursor: wait; opacity: .72; }
.session-dot { width: 7px; height: 7px; border: 2px solid #b8c7dc; border-radius: 50%; flex: 0 0 auto; }
.active .session-dot { border-color: #4e82dc; background: #4e82dc; }
.session-title { min-width: 0; flex: 1; overflow: hidden; font-size: 12px; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.session-count { color: #9aa9be; font-size: 10px; }
.empty-rail { padding: 16px 9px; color: #9aa9be; font-size: 12px; }
.rail-foot { display: flex; align-items: center; gap: 7px; padding: 12px 8px 0; border-top: 1px solid #edf1f5; color: #6b7f99; font-size: 11px; }
.live-dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; background: #e9b65e; }
.live-dot.ready { background: #2cba87; box-shadow: 0 0 0 3px #d9f6ea; }

/* 中：对话 */
.chat-column { min-width: 0; min-height: 0; display: flex; flex-direction: column; overflow: hidden; background: #fff; }
.chat-head { display: flex; align-items: center; justify-content: space-between; gap: 14px; flex: 0 0 auto; padding: 16px 24px; border-bottom: 1px solid #e7ecf3; }
.head-title { display: flex; align-items: center; gap: 12px; min-width: 0; }
.chat-head h2 { margin: 0; overflow: hidden; color: #172a4b; font-size: 17px; font-weight: 700; text-overflow: ellipsis; white-space: nowrap; }
.task-select { width: 200px; }
.task-hint { color: #9aa9be; font-size: 12px; }
.chat-head :deep(.el-button) { color: #71829a; font-size: 12px; }
.message-list { flex: 1; overflow-y: auto; min-height: 0; padding: 24px clamp(20px, 4vw, 60px) 16px; }
.welcome-block { max-width: 680px; margin: 4vh auto 0; text-align: center; }
.welcome-icon { display: grid; place-items: center; width: 50px; height: 50px; margin: 0 auto 16px; border-radius: 8px; background: linear-gradient(145deg, #356ed3, #214b99); color: #fff; font-size: 25px; }
.welcome-block h3 { margin: 10px 0 7px; color: #1a2e50; font-size: 24px; }
.welcome-block > p { margin: 0 auto 26px; max-width: 490px; color: #8493a9; font-size: 13px; line-height: 1.7; }
.prompt-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; text-align: left; }
.prompt-card { display: flex; align-items: flex-start; gap: 9px; min-height: 92px; padding: 14px 12px; border: 1px solid #e5eaf2; border-radius: 8px; background: #fff; color: #405574; text-align: left; cursor: pointer; transition: .18s ease; }
.prompt-card:hover { border-color: #a8c4ed; box-shadow: 0 8px 18px rgba(45, 93, 167, .09); transform: translateY(-2px); }
.prompt-icon { display: grid; place-items: center; width: 25px; height: 25px; flex: 0 0 auto; border-radius: 7px; background: #edf4ff; color: #4a7bd1; }
.prompt-card strong, .prompt-card small { display: block; }
.prompt-card strong { margin: 1px 0 5px; color: #344b6c; font-size: 12px; }
.prompt-card small { max-width: 130px; color: #8c9bb0; font-size: 11px; line-height: 1.45; }
.message-row { display: flex; align-items: flex-start; gap: 11px; max-width: 760px; margin: 0 auto 24px; }
.message-row.user { flex-direction: row-reverse; }
.avatar { display: grid; place-items: center; width: 29px; height: 29px; flex: 0 0 auto; border-radius: 8px; font-size: 11px; font-weight: 700; }
.avatar.assistant { background: #eaf2ff; color: #3e70cb; font-size: 16px; }
.avatar.user { background: #e9edf4; color: #63758e; }
.message-body { max-width: calc(100% - 42px); }
.message-row.user .message-body { text-align: right; }
.message-meta { display: flex; align-items: center; gap: 8px; margin: 1px 2px 6px; }
.message-row.user .message-meta { justify-content: flex-end; }
.message-meta strong { color: #6e829d; font-size: 11px; }
.streaming-label { color: #4c82db; font-size: 11px; }
.copy-btn { border: 0; background: transparent; padding: 0; color: #7b93b1; font-size: 10px; cursor: pointer; }
.copy-btn:hover { color: #4a7bd1; }
.message-card { padding: 13px 15px; border: 1px solid #e4e9f1; border-radius: 4px 8px 8px 8px; background: #fff; box-shadow: 0 3px 12px rgba(35, 59, 91, .035); text-align: left; }
.user .message-card { border: 0; border-radius: 8px 4px 8px 8px; background: #edf3fd; box-shadow: none; }
.message-content { margin: 0; color: #435573; font-size: 14px; line-height: 1.8; }
.user-content { color: #31568d; white-space: pre-wrap; overflow-wrap: anywhere; }
.copilot-answer :deep([data-copilotkit]) { margin: 0; color: inherit; font-size: inherit; line-height: inherit; }
.copilot-answer :deep(.copilot-chat-assistant-markdown) { color: #354761; font-size: 14px; line-height: 1.8; }
.copilot-answer :deep(.copilot-chat-assistant-markdown p) { margin: 0 0 10px; }
.copilot-answer :deep(.copilot-chat-assistant-markdown p:last-child) { margin-bottom: 0; }
.copilot-answer :deep(.copilot-chat-assistant-markdown table) { width: 100%; display: block; overflow-x: auto; border-collapse: collapse; }
.copilot-answer :deep(.copilot-chat-assistant-markdown th), .copilot-answer :deep(.copilot-chat-assistant-markdown td) { padding: 7px 9px; border: 1px solid #e4e9f1; text-align: left; }
.copilot-answer :deep(.copilot-chat-assistant-markdown th) { background: #f2f6fb; font-weight: 600; }
.copilot-answer :deep(.copilot-chat-assistant-markdown pre) { max-width: 100%; overflow: auto; }
.copilot-user :deep([data-copilotkit]) { color: #31568d; font-size: 13px; line-height: 1.7; }
.activity-panel { margin: 0 0 12px; overflow: hidden; border: 1px solid #e2eaf4; border-radius: 8px; background: #f8fafd; }
.activity-panel.running { border-color: #c8d9f2; background: #f7faff; }
.activity-heading { display: flex; align-items: center; width: 100%; gap: 10px; padding: 10px 11px; border: 0; background: transparent; color: #344761; text-align: left; cursor: pointer; }
.activity-spark { display: grid; place-items: center; width: 26px; height: 26px; flex: 0 0 auto; border-radius: 7px; background: #e8f0fc; color: #4875bd; }
.activity-panel.running .activity-spark { background: #e5efff; color: #3979d6; }
.activity-heading-copy { display: grid; flex: 1; gap: 2px; min-width: 0; }
.activity-heading-copy b { color: #344761; font-size: 12px; font-weight: 650; }
.activity-heading-copy small { color: #8292a8; font-size: 10px; }
.activity-chevron { color: #8b9ab0; transition: transform .18s ease; }
.activity-chevron.expanded { transform: rotate(90deg); }
.activity-feed { display: grid; gap: 0; padding: 0 14px 10px 23px; }
.activity-event { position: relative; display: grid; grid-template-columns: 17px minmax(0, 1fr); gap: 9px; min-height: 36px; }
.activity-event:not(:last-child)::before { position: absolute; top: 17px; bottom: -2px; left: 7px; width: 1px; background: #dce5f1; content: ''; }
.event-marker { z-index: 1; display: grid; place-items: center; width: 15px; height: 15px; border: 1px solid #cbd8e9; border-radius: 50%; background: #fff; color: #318e72; font-size: 9px; }
.activity-event.running .event-marker { border-color: #8fb1e2; color: #4b81ce; }
.event-pulse { width: 5px; height: 5px; border-radius: 50%; background: #5d8ed6; animation: pulse 1.2s ease-in-out infinite; }
.event-copy { display: grid; align-content: start; gap: 2px; padding: 1px 0 9px; }
.event-copy b { color: #526681; font-size: 11px; font-weight: 600; }
.event-copy small { color: #8998ad; font-size: 10px; line-height: 1.4; }
.activity-event.pending .event-marker { border-style: dashed; }
@keyframes pulse { 50% { opacity: .4; transform: scale(.8); } }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.citation-wrap { margin-top: 13px; padding-top: 10px; border-top: 1px solid #edf1f5; }
.citation-label { color: #7890ae; font-size: 10px; font-weight: 700; }
.citation-list { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 6px; }
.citation-chip { display: inline-flex; align-items: center; gap: 5px; padding: 3px 8px; border-radius: 4px; background: #f2f6fb; color: #597292; font-size: 10px; }
.citation-chip small { color: #9aabc0; }
.citation-chip.pass { background: #e8f7f1; color: #23825f; }
.citation-chip.fail { background: #fdecec; color: #c04b4b; }
.citation-chip.warn { background: #fdf5e6; color: #b07d22; }
.cite-dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.typing { max-width: 760px; margin: 0 auto; color: #90a1b8; font-size: 11px; }
.typing span { display: inline-block; width: 5px; height: 5px; margin: 0 2px; border-radius: 50%; background: #78a0df; animation: bounce 1s infinite; }
.typing span:nth-child(2) { animation-delay: .15s; }.typing span:nth-child(3) { animation-delay: .3s; }
@keyframes bounce { 50% { transform: translateY(-3px); opacity: .5; } }
.composer-wrap { flex: 0 0 auto; padding: 0 clamp(20px, 4vw, 60px) 14px; }
.skill-running { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; color: #4a7bd1; font-size: 11px; }
.composer { position: relative; }
.composer :deep(.el-textarea__inner) { min-height: 44px !important; padding: 12px 46px 12px 14px; border: 1px solid #d9e2ee; border-radius: 8px; color: #354a69; box-shadow: 0 4px 15px rgba(42, 66, 100, .05); font-size: 13px; }
.composer :deep(.el-textarea__inner:focus) { border-color: #83a9df; box-shadow: 0 0 0 3px #edf4ff; }
.send-button { position: absolute; right: 9px; bottom: 8px; width: 30px; height: 30px; }
.composer-foot { padding: 6px 2px 0; color: #a5b2c4; font-size: 10px; }

/* 右：审核技能 */
.skill-rail { display: flex; flex-direction: column; min-height: 0; padding: 20px 14px 14px; background: #fbfcfe; border-left: 1px solid #e7ecf3; }
.skill-head { padding: 0 8px 14px; color: #405675; font-size: 13px; font-weight: 700; }
.skill-list { flex: 1; overflow-y: auto; min-height: 0; display: grid; gap: 8px; align-content: start; }
.skill-item { display: flex; align-items: center; gap: 10px; padding: 11px 10px; border: 1px solid #e6ebf2; border-radius: 8px; background: #fff; color: #405574; text-align: left; cursor: pointer; transition: .16s ease; }
.skill-item:hover:not(:disabled) { border-color: #a8c4ed; box-shadow: 0 6px 14px rgba(45, 93, 167, .08); }
.skill-item:disabled { cursor: wait; opacity: .72; }
.head-actions { display: flex; align-items: center; gap: 4px; flex: 0 0 auto; }
.mobile-session-trigger { display: none; }
.mobile-skill-trigger { display: none; }
.mobile-skill-list { display: grid; gap: 8px; }
.mobile-session-list { display: grid; gap: 4px; }
.skill-icon { display: grid; place-items: center; width: 30px; height: 30px; flex: 0 0 auto; border-radius: 7px; background: #edf4ff; color: #4a7bd1; font-size: 15px; }
.skill-copy { min-width: 0; display: grid; gap: 2px; }
.skill-copy b { color: #344b6c; font-size: 12px; font-weight: 600; }
.skill-copy small { color: #8c9bb0; font-size: 11px; line-height: 1.4; }
.skill-foot { padding: 12px 8px 0; border-top: 1px solid #edf1f5; color: #a5b2c4; font-size: 10px; line-height: 1.5; }

@media (max-width: 1100px) {
  .assistant-shell { grid-template-columns: 216px minmax(0, 1fr); }
  .skill-rail { display: none; }
  .mobile-session-trigger { display: inline-flex; }
  .mobile-skill-trigger { display: inline-flex; }
}
@media (max-width: 760px) {
  .assistant-shell { display: flex; flex-direction: column; }
  .session-rail { display: none; }
  .chat-head { padding: 14px 16px; }
  .message-list { padding: 20px 15px; }
  .prompt-grid { grid-template-columns: 1fr; }
  .composer-wrap { padding: 0 15px 12px; }
}
</style>
