<template>
  <div class="assistant-page">
    <section class="assistant-shell">
      <aside class="session-rail">
        <div class="rail-brand">
          <div class="brand-mark"><el-icon><MagicStick /></el-icon></div>
          <div>
            <div class="eyebrow">AGENT WORKSPACE</div>
            <h1>慧眼助手</h1>
          </div>
        </div>
        <el-button class="new-session" type="primary" :icon="Plus" :disabled="loading" @click="newSession">新建会话</el-button>
        <div class="rail-label">最近会话</div>
        <div class="session-list">
          <button v-for="item in sessions" :key="item.id" class="session-item"
            :class="{ active: item.id === activeSessionId }" :disabled="loading" @click="openSession(item.id)">
            <span class="session-dot"></span>
            <span class="session-copy">
              <strong>{{ item.title }}</strong>
              <small>{{ item.task_code || '通用业务咨询' }}</small>
            </span>
            <span class="session-count">{{ item.message_count }}</span>
          </button>
          <div v-if="!sessions.length" class="empty-rail">还没有会话</div>
        </div>
        <div class="rail-foot">
          <div class="connection-row"><span class="live-dot"></span>{{ capabilityText }}</div>
          <span class="muted">SDK · {{ ragLabel }} · Workflow ready</span>
        </div>
      </aside>

      <main class="chat-column">
        <header class="chat-head">
          <div>
            <div class="head-kicker">HBCN · CONTROLLED AGENT SERVICE</div>
            <h2>{{ activeSession?.title || '新会话' }}</h2>
            <p>{{ activeSession?.task_code ? `已连接任务 ${activeSession.task_code}` : '通用会话 · 选择任务可读取授权材料与规则证据' }}</p>
          </div>
          <div class="head-actions">
            <el-select v-model="taskSelection" class="task-select" size="small" clearable filterable
              placeholder="选择任务上下文" :disabled="loading" @change="selectTaskContext">
              <el-option v-for="task in tasks" :key="task.id" :value="task.task_code"
                :label="`${task.task_code} · ${task.borrower}`" />
            </el-select>
            <el-tag :type="capabilities?.configured ? 'success' : 'warning'" effect="plain">
              <span class="tag-dot"></span>{{ capabilities?.configured ? '模型已连接' : '本地演示模式' }}
            </el-tag>
            <el-button text :icon="ArrowLeft" @click="router.push({ name: 'dashboard' })">返回工作台</el-button>
          </div>
        </header>

        <div ref="messageList" class="message-list">
          <div v-if="!messages.length" class="welcome-block">
            <div class="welcome-icon"><el-icon><MagicStick /></el-icon></div>
            <div class="head-kicker">CONTROLLED INTELLIGENCE</div>
            <h3>让审核工作更快一步</h3>
            <p>我可以读取授权任务上下文，检索证据，解释规则结果，并整理人工复核意见。</p>
            <div class="prompt-grid">
              <button v-for="prompt in prompts" :key="prompt.title" class="prompt-card" @click="usePrompt(prompt.text)">
                <span class="prompt-icon"><el-icon><component :is="prompt.icon" /></el-icon></span>
                <span><strong>{{ prompt.title }}</strong><small>{{ prompt.text }}</small></span>
                <el-icon class="prompt-arrow"><ArrowRight /></el-icon>
              </button>
            </div>
          </div>
          <article v-for="message in messages" :key="message.id" class="message-row" :class="message.role">
            <div class="avatar" :class="message.role"><el-icon v-if="message.role === 'assistant'"><MagicStick /></el-icon><span v-else>{{ auth.displayName?.slice(0, 1) || '我' }}</span></div>
            <div class="message-body">
              <div class="message-meta">
                <strong>{{ message.role === 'assistant' ? '慧眼助手' : '你' }}</strong>
                <span v-if="message.streaming" class="streaming-label">正在处理</span>
                <button v-if="message.role === 'assistant' && message.content && !message.streaming" class="copy-btn" @click="copyMessage(message)">复制</button>
              </div>
              <div class="message-card">
                <div v-if="message.steps?.length" class="step-stack">
                  <div v-for="step in message.steps" :key="step.key" class="step-line" :class="step.status">
                    <span class="step-icon"><el-icon v-if="step.status === 'completed'"><Check /></el-icon><el-icon v-else class="spin"><Loading /></el-icon></span>
                    <span><b>{{ step.label }}</b><small>{{ step.detail }}</small></span>
                    <el-icon v-if="step.status === 'completed'" class="step-check"><Check /></el-icon>
                  </div>
                </div>
                <div class="message-content">
                  <div class="markdown-body" v-html="renderMarkdown(message.content)"></div>
                  <span v-if="message.streaming" class="cursor"></span>
                </div>
                <div v-if="message.citations?.length" class="citation-wrap">
                  <div class="citation-label"><el-icon><Link /></el-icon>证据引用</div>
                  <div class="citation-list"><span v-for="citation in message.citations" :key="citation.id" class="citation-chip">{{ citation.label }}<small v-if="citation.page"> · p.{{ citation.page }}</small></span></div>
                </div>
              </div>
            </div>
          </article>
          <div v-if="loading && !activeTrace.length" class="typing"><span></span><span></span><span></span> 正在准备执行步骤</div>
        </div>

        <footer class="composer-wrap">
          <div class="context-strip">
            <span><el-icon><Lock /></el-icon>受控只读助手</span>
            <span><el-icon><Search /></el-icon>{{ capabilities?.rag_available ? '知识库已连接' : '任务材料检索' }}</span>
            <span class="context-hint">不会直接决定贷款审核结论</span>
          </div>
          <form class="composer" @submit.prevent="sendMessage">
            <el-input v-model="draft" type="textarea" :rows="2" :maxlength="8000" resize="none" :disabled="loading" placeholder="询问规则、材料、风险或下一步人工动作…" @keydown.enter.exact.prevent="sendMessage" />
            <el-button class="send-button" type="primary" circle :icon="loading ? Loading : Promotion" :loading="false" :disabled="!draft.trim() || loading" native-type="submit" />
          </form>
          <div class="composer-foot"><span>Enter 发送 · Shift + Enter 换行</span><span>{{ draft.length }}/8000</span></div>
        </footer>
      </main>

      <aside class="insight-rail">
        <div class="insight-head"><span class="eyebrow">LIVE TRACE</span><el-icon><MoreFilled /></el-icon></div>
        <div class="trace-card">
          <div class="trace-orb"><el-icon><Connection /></el-icon></div>
          <strong>Agent 服务状态</strong>
          <span>{{ capabilities?.message || '正在检查服务能力' }}</span>
          <div class="health-bar"><i :class="{ ready: capabilities?.configured }"></i></div>
        </div>
        <div class="insight-section"><div class="section-title">本轮执行</div><div v-if="activeTrace.length || toolActivity.length" class="trace-list"><div v-for="step in activeTrace" :key="step.key" class="trace-item" :class="step.status"><span class="trace-dot"><el-icon v-if="step.status === 'completed'"><Check /></el-icon><el-icon v-else class="spin"><Loading /></el-icon></span><span><b>{{ step.label }}</b><small>{{ step.detail }}</small></span></div><div v-for="tool in toolActivity" :key="tool.name" class="trace-item" :class="tool.status"><span class="trace-dot"><el-icon v-if="tool.status === 'completed'"><Check /></el-icon><el-icon v-else class="spin"><Loading /></el-icon></span><span><b>检索知识库证据</b><small>{{ tool.status === 'running' ? '正在检索任务材料与规则证据…' : `已完成 · ${tool.result_count ?? 0} 条证据` }}</small></span></div></div><div v-else class="trace-empty">发送问题后查看每一步处理状态</div></div>
        <div class="insight-section"><div class="section-title">当前边界</div><div class="guard-list"><div><el-icon><DocumentChecked /></el-icon><span>证据优先</span></div><div><el-icon><UserFilled /></el-icon><span>人工最终确认</span></div><div><el-icon><Lock /></el-icon><span>不写入业务结论</span></div></div></div>
        <div class="insight-foot">OpenAI Agents SDK<br>FastAPI · SSE · {{ ragLabel }}</div>
      </aside>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { ElMessage } from 'element-plus'
import { assistantApi } from '@/assistant/api'
import { renderMarkdown } from '@/assistant/markdown'
import type { AssistantCapabilities, AssistantMessage, AssistantSession, AssistantStep, AssistantTaskOption, AssistantToolActivity } from '@/assistant/types'
import { ArrowLeft, ArrowRight, Check, Connection, DocumentChecked, FolderOpened, Link, Loading, Lock, MagicStick, MoreFilled, Plus, Promotion, Search, UserFilled } from '@element-plus/icons-vue'

const router = useRouter()
const auth = useAuthStore()
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

const prompts = [
  { title: '梳理风险', text: '帮我总结当前任务的风险和人工核对点', icon: DocumentChecked },
  { title: '解释规则', text: '解释当前不通过项，给出材料定位建议', icon: Search },
  { title: '材料核对', text: '哪些单据字段需要优先复核？', icon: FolderOpened },
]

const activeSession = computed(() => sessions.value.find((item) => item.id === activeSessionId.value))
const capabilityText = computed(() => capabilities.value?.configured ? 'MODEL CONNECTED' : 'LOCAL DEMO READY')
const ragLabel = computed(() => (capabilities.value?.rag_available ? '知识库已连接' : '本地证据检索'))

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
  try {
    const created = await assistantApi.createSession()
    sessions.value = [created, ...sessions.value]
    activeSessionId.value = created.id
    taskSelection.value = ''
    messages.value = []
    activeTrace.value = []
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '无法创建会话')
  }
}

async function openSession(id: number) {
  try {
    const detail = await assistantApi.session(id)
    activeSessionId.value = id
    taskSelection.value = detail.task_code || ''
    messages.value = detail.messages
    activeTrace.value = messages.value[messages.value.length - 1]?.steps || []
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

async function sendMessage() {
  if (!draft.value.trim() || !activeSessionId.value || loading.value) return
  const content = draft.value.trim()
  draft.value = ''
  messages.value.push({ id: `user-${Date.now()}`, role: 'user', content, status: 'completed', steps: [], citations: [] })
  const assistant: AssistantMessage = { id: `assistant-${Date.now()}`, role: 'assistant', content: '', status: 'running', steps: [], citations: [], streaming: true }
  messages.value.push(assistant)
  loading.value = true
  activeTrace.value = []
  toolActivity.value = []
  scrollToBottom()
  try {
    for await (const event of assistantApi.streamMessage(activeSessionId.value, content, activeSession.value?.task_code || undefined)) {
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
      } else if (event.event === 'error') throw new Error(event.error_message || '助手执行失败')
      await nextTick()
      scrollToBottom()
    }
    const current = sessions.value.find((item) => item.id === activeSessionId.value)
    if (current) current.message_count += 2
  } catch (error) {
    assistant.status = 'error'
    assistant.streaming = false
    assistant.content = error instanceof Error ? error.message : '助手执行失败，请重试'
    ElMessage.error(assistant.content)
  } finally {
    loading.value = false
  }
}

async function copyMessage(message: AssistantMessage) {
  try {
    await navigator.clipboard.writeText(message.content)
    ElMessage.success('已复制到剪贴板')
  } catch {
    ElMessage.error('复制失败，请手动选择文本')
  }
}

function scrollToBottom() { nextTick(() => { if (messageList.value) messageList.value.scrollTop = messageList.value.scrollHeight }) }
onMounted(loadSessions)
</script>

<style scoped>
.assistant-page { min-height: calc(100vh - 40px); margin: -20px; background: #f5f7fb; color: #17253f; }
.assistant-shell { min-height: calc(100vh - 40px); display: grid; grid-template-columns: 252px minmax(540px, 1fr) 248px; max-width: 1600px; margin: 0 auto; background: #fff; box-shadow: 0 10px 36px rgba(28, 46, 79, .07); }
.session-rail { display: flex; flex-direction: column; padding: 26px 18px 18px; background: #f8fafc; border-right: 1px solid #e7ecf3; }
.rail-brand { display: flex; align-items: center; gap: 11px; padding: 0 7px 25px; }
.brand-mark, .welcome-icon { display: grid; place-items: center; color: #fff; background: linear-gradient(145deg, #356ed3, #214b99); box-shadow: 0 8px 18px rgba(53, 110, 211, .2); }
.brand-mark { width: 35px; height: 35px; border-radius: 8px; font-size: 18px; }
.eyebrow, .head-kicker { color: #7890b1; font-size: 10px; font-weight: 700; letter-spacing: 0; }
.rail-brand h1 { margin: 3px 0 0; color: #162844; font-size: 18px; letter-spacing: 0; }
.new-session { width: 100%; height: 39px; margin-bottom: 25px; border-radius: 7px; font-weight: 600; }
.rail-label, .section-title { color: #7890b1; font-size: 11px; font-weight: 700; letter-spacing: 0; text-transform: uppercase; }
.rail-label { padding: 0 8px 9px; }
.session-list { overflow: auto; }
.session-item { display: flex; align-items: center; width: 100%; gap: 9px; padding: 11px 9px; margin-bottom: 3px; border: 0; border-radius: 7px; background: transparent; color: #435574; text-align: left; cursor: pointer; }
.session-item:hover:not(:disabled), .session-item.active { background: #eaf1fd; color: #204f9e; }
.session-item:disabled { cursor: wait; opacity: .72; }
.session-dot { width: 7px; height: 7px; border: 2px solid #b8c7dc; border-radius: 50%; flex: 0 0 auto; }
.active .session-dot { border-color: #4e82dc; background: #4e82dc; box-shadow: 0 0 0 3px #d9e7fb; }
.session-copy { min-width: 0; display: grid; gap: 3px; }
.session-copy strong { overflow: hidden; font-size: 12px; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.session-copy small, .message-meta, .composer-foot, .muted { color: #8a9ab1; font-size: 11px; }
.session-count { margin-left: auto; color: #9aa9be; font-size: 10px; }
.empty-rail, .trace-empty { padding: 17px 9px; color: #9aa9be; font-size: 12px; }
.rail-foot { margin-top: auto; display: grid; gap: 7px; padding: 18px 7px 0; border-top: 1px solid #e6ebf2; }
.connection-row { display: flex; align-items: center; gap: 7px; color: #4d6a8e; font-size: 10px; font-weight: 700; letter-spacing: 0; }
.live-dot, .tag-dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; background: #2cba87; box-shadow: 0 0 0 3px #d9f6ea; }
.chat-column { min-width: 0; display: flex; flex-direction: column; background: #fff; }
.chat-head { display: flex; align-items: center; justify-content: space-between; gap: 16px; min-height: 88px; padding: 21px 30px 18px; border-bottom: 1px solid #e7ecf3; }
.chat-head h2 { margin: 5px 0 4px; color: #172a4b; font-size: 19px; font-weight: 700; }
.chat-head p { margin: 0; color: #8493a9; font-size: 12px; }
.head-actions { display: flex; align-items: center; gap: 14px; }
.task-select { width: 190px; }
.head-actions :deep(.el-tag) { border: 0; background: #f0fbf6; color: #258a64; }
.head-actions :deep(.el-button) { color: #71829a; font-size: 12px; }
.tag-dot { width: 6px; height: 6px; margin-right: 6px; box-shadow: none; }
.message-list { flex: 1; overflow: auto; min-height: 0; padding: 32px clamp(24px, 5vw, 75px) 24px; }
.welcome-block { max-width: 680px; margin: 6vh auto 0; text-align: center; }
.welcome-icon { width: 50px; height: 50px; margin: 0 auto 17px; border-radius: 8px; font-size: 25px; }
.welcome-block h3 { margin: 10px 0 7px; color: #1a2e50; font-size: 25px; letter-spacing: 0; }
.welcome-block > p { margin: 0 auto 27px; max-width: 490px; color: #8493a9; font-size: 13px; line-height: 1.7; }
.prompt-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; text-align: left; }
.prompt-card { position: relative; display: flex; align-items: flex-start; gap: 9px; min-height: 102px; padding: 14px 12px; border: 1px solid #e5eaf2; border-radius: 8px; background: #fff; color: #405574; text-align: left; cursor: pointer; transition: .18s ease; }
.prompt-card:hover { border-color: #a8c4ed; box-shadow: 0 8px 18px rgba(45, 93, 167, .09); transform: translateY(-2px); }
.prompt-icon { display: grid; place-items: center; width: 25px; height: 25px; flex: 0 0 auto; border-radius: 7px; background: #edf4ff; color: #4a7bd1; }
.prompt-card strong, .prompt-card small { display: block; }
.prompt-card strong { margin: 1px 0 6px; color: #344b6c; font-size: 12px; }
.prompt-card small { max-width: 130px; color: #8c9bb0; font-size: 11px; line-height: 1.45; }
.prompt-arrow { position: absolute; right: 8px; bottom: 8px; color: #b1bfd2; font-size: 12px; }
.message-row { display: flex; align-items: flex-start; gap: 11px; max-width: 760px; margin: 0 auto 26px; }
.message-row.user { flex-direction: row-reverse; }
.avatar { display: grid; place-items: center; width: 29px; height: 29px; flex: 0 0 auto; border-radius: 8px; font-size: 11px; font-weight: 700; }
.avatar.assistant { background: #eaf2ff; color: #3e70cb; font-size: 16px; }
.avatar.user { background: #e9edf4; color: #63758e; }
.message-body { max-width: calc(100% - 42px); }
.message-row.user .message-body { text-align: right; }
.message-meta { display: flex; align-items: center; gap: 8px; margin: 1px 2px 6px; }
.message-row.user .message-meta { justify-content: flex-end; }
.message-meta strong { color: #6e829d; font-size: 11px; }
.streaming-label { color: #4c82db; }
.message-card { padding: 13px 15px; border: 1px solid #e4e9f1; border-radius: 4px 8px 8px 8px; background: #fff; box-shadow: 0 3px 12px rgba(35, 59, 91, .035); text-align: left; }
.user .message-card { border: 0; border-radius: 8px 4px 8px 8px; background: #edf3fd; box-shadow: none; }
.message-content { margin: 0; color: #435573; font-size: 13px; line-height: 1.75; }
.user .message-content { color: #31568d; }
.markdown-body p { margin: 0 0 8px; }.markdown-body p:last-child { margin-bottom: 0; }
.markdown-body ul, .markdown-body ol { margin: 4px 0 8px; padding-left: 20px; }.markdown-body li { margin: 3px 0; }
.markdown-body code { padding: 1px 5px; border-radius: 4px; background: #eef2f8; color: #c7254e; font-size: 12px; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }
.markdown-body pre { margin: 8px 0; padding: 12px; border-radius: 8px; background: #f6f8fb; overflow: auto; }.markdown-body pre code { padding: 0; background: transparent; color: #435573; }
.markdown-body a { color: #4a7bd1; text-decoration: none; }.markdown-body a:hover { text-decoration: underline; }
.markdown-body h1, .markdown-body h2, .markdown-body h3 { margin: 10px 0 6px; color: #1a2e50; }
.copy-btn { border: 0; background: transparent; padding: 0; color: #7b93b1; font-size: 10px; cursor: pointer; }.copy-btn:hover { color: #4a7bd1; }
.cursor { display: inline-block; width: 6px; height: 15px; margin-left: 3px; vertical-align: -2px; background: #4d82da; animation: blink 1s infinite; }
@keyframes blink { 50% { opacity: 0; } }
.step-stack { display: grid; gap: 7px; margin: 0 0 11px; padding-bottom: 10px; border-bottom: 1px solid #edf1f5; }
.step-line, .trace-item { display: flex; align-items: flex-start; gap: 8px; color: #60738d; }
.step-icon { display: grid; place-items: center; width: 17px; height: 17px; border-radius: 50%; background: #edf3fc; color: #4a7bd1; font-size: 10px; }
.step-line.completed .step-icon { background: #e8f7f1; color: #28a879; }
.step-line > span:nth-child(2), .trace-item > span:nth-child(2) { display: grid; gap: 1px; }
.step-line b, .trace-item b { font-size: 11px; font-weight: 600; }
.step-line small, .trace-item small { color: #95a3b6; font-size: 10px; }
.step-check { margin-left: auto; color: #2bb282; font-size: 13px; }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.citation-wrap { margin-top: 13px; padding-top: 10px; border-top: 1px solid #edf1f5; }
.citation-label { display: flex; align-items: center; gap: 4px; color: #7890ae; font-size: 10px; font-weight: 700; }
.citation-list { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 6px; }
.citation-chip { padding: 3px 7px; border-radius: 4px; background: #f2f6fb; color: #597292; font-size: 10px; }
.citation-chip small { color: #9aabc0; }
.typing { max-width: 760px; margin: 0 auto; color: #90a1b8; font-size: 11px; }
.typing span { display: inline-block; width: 5px; height: 5px; margin: 0 2px; border-radius: 50%; background: #78a0df; animation: bounce 1s infinite; }
.typing span:nth-child(2) { animation-delay: .15s; }.typing span:nth-child(3) { animation-delay: .3s; }
@keyframes bounce { 50% { transform: translateY(-3px); opacity: .5; } }
.composer-wrap { padding: 0 clamp(24px, 5vw, 75px) 18px; }
.context-strip { display: flex; align-items: center; gap: 15px; padding: 0 2px 8px; color: #8394aa; font-size: 10px; }
.context-strip span { display: flex; align-items: center; gap: 4px; }.context-hint { margin-left: auto; color: #b1bdcb; }
.composer { position: relative; }.composer :deep(.el-textarea__inner) { min-height: 58px !important; padding: 13px 51px 12px 14px; border: 1px solid #d9e2ee; border-radius: 8px; color: #354a69; box-shadow: 0 4px 15px rgba(42, 66, 100, .05); font-size: 13px; }.composer :deep(.el-textarea__inner:focus) { border-color: #83a9df; box-shadow: 0 0 0 3px #edf4ff; }.send-button { position: absolute; right: 10px; bottom: 10px; width: 31px; height: 31px; }.composer-foot { display: flex; justify-content: space-between; padding: 6px 2px 0; }
.insight-rail { padding: 27px 18px; background: #fbfcfe; border-left: 1px solid #e7ecf3; }.insight-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 21px; color: #a6b3c4; }.trace-card { display: grid; justify-items: center; gap: 7px; padding: 18px 13px; border: 1px solid #e6ebf2; border-radius: 8px; background: #fff; text-align: center; }.trace-orb { display: grid; place-items: center; width: 39px; height: 39px; border-radius: 50%; background: #e9f4f1; color: #338a78; font-size: 18px; }.trace-card strong { color: #405675; font-size: 12px; }.trace-card > span { color: #91a0b4; font-size: 10px; line-height: 1.5; }.health-bar { width: 100%; height: 4px; overflow: hidden; margin-top: 5px; border-radius: 2px; background: #edf0f5; }.health-bar i { display: block; width: 42%; height: 100%; background: #e9b65e; }.health-bar i.ready { width: 100%; background: #36b98b; }.insight-section { margin-top: 25px; }.section-title { padding-bottom: 11px; border-bottom: 1px solid #e9edf3; }.trace-list { display: grid; gap: 15px; padding-top: 15px; }.trace-item { gap: 8px; }.trace-dot { display: grid; place-items: center; width: 16px; height: 16px; flex: 0 0 auto; border: 1px solid #cfdae7; border-radius: 50%; color: #7e9bca; font-size: 9px; }.trace-item.completed .trace-dot { border-color: #7bcdad; background: #e8f7f1; color: #2caa7e; }.guard-list { display: grid; gap: 12px; padding-top: 14px; }.guard-list div { display: flex; align-items: center; gap: 8px; color: #6e809a; font-size: 11px; }.guard-list .el-icon { color: #438f80; }.insight-foot { margin-top: auto; padding-top: 55px; color: #b0bac8; font-size: 10px; line-height: 1.7; }
@media (max-width: 1100px) { .assistant-shell { grid-template-columns: 220px minmax(480px, 1fr); }.insight-rail { display: none; } }
@media (max-width: 760px) { .assistant-page { margin: -20px; }.assistant-shell { display: block; }.session-rail { display: none; }.chat-head { align-items: flex-start; flex-direction: column; padding: 18px; }.head-actions { width: 100%; flex-wrap: wrap; gap: 8px; }.task-select { width: min(100%, 220px); }.message-list { padding: 24px 15px; }.prompt-grid { grid-template-columns: 1fr; }.prompt-card { min-height: 75px; }.composer-wrap { padding: 0 15px 14px; }.context-hint { display: none !important; } }
</style>
