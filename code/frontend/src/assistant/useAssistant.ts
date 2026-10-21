import { useCallback, useEffect, useRef, useState } from 'react'
import { useAuthStore } from '@/stores/auth'
import { assistantApi } from './api'
import { collaborationApi, restoreActiveReply } from './collaboration'
import type { Run } from './collaboration'
import type { AssistantCapabilities, AssistantMessage, AssistantSession, AssistantSkill, AssistantStep, AssistantTaskOption } from './types'

const errorText = (error: unknown) => error instanceof Error ? error.message : '助手请求失败，请稍后重试'

function upsertStep(steps: AssistantStep[], step: AssistantStep): AssistantStep[] {
  return steps.some((item) => item.key === step.key)
    ? steps.map((item) => item.key === step.key ? step : item)
    : [...steps, step]
}

// Older stored replies may contain both running and completed events for one key.
function restoredMessage(message: AssistantMessage): AssistantMessage {
  return { ...message, streaming: false, steps: message.steps.reduce(upsertStep, []) }
}

/** React lifecycle adapter for the existing authenticated JSON/SSE contract. */
export function useAssistant(initialTask = '') {
  const role = useAuthStore((state) => state.role)
  const [sessions, setSessions] = useState<AssistantSession[]>([])
  const [activeId, setActiveId] = useState<number | null>(null)
  const [messages, setMessages] = useState<AssistantMessage[]>([])
  const [capabilities, setCapabilities] = useState<AssistantCapabilities | null>(null)
  const [tasks, setTasks] = useState<AssistantTaskOption[]>([])
  const [skills, setSkills] = useState<AssistantSkill[]>([])
  const [taskCode, setTaskCode] = useState(initialTask)
  const [skillId, setSkillId] = useState<string>()
  const [loading, setLoading] = useState(true)
  const [switching, setSwitching] = useState(false)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [activeRun, setActiveRun] = useState<Run | null>(null)
  const stream = useRef<AbortController | null>(null)
  const discussionLock = useRef(false)
  const generation = useRef(0)
  const replay = useRef<{ runId: string; cursor: number; events: import('./collaboration').RoomEvent[] } | null>(null)
  const shared = sessions.some((item) => item.id === activeId && item.shared)

  const refreshSession = useCallback(async () => {
    if (activeId === null || stream.current) return
    const request = generation.current
    try {
      const detail = await assistantApi.session(activeId)
      let restored = detail.messages.map(restoredMessage)
      if (detail.active_run) {
        const cache = replay.current?.runId === detail.active_run.id ? replay.current : { runId: detail.active_run.id, cursor: 0, events: [] }
        // Full active-run reconstruction is bounded by the server run timeout.
        for (let page = 0; page < 50; page++) {
          const result = await collaborationApi.events(activeId, cache.cursor, detail.active_run.id)
          cache.events.push(...result.events)
          cache.cursor = result.cursor
          if (!result.has_more) break
        }
        replay.current = cache
        restored = restoreActiveReply(restored, cache.events, detail.active_run)
      } else replay.current = null
      if (request !== generation.current || stream.current) return
      setMessages(restored)
      setActiveRun(detail.active_run || null)
      setSessions((items) => items.map((item) => item.id === detail.id ? detail : item))
    } catch (cause) {
      if (request === generation.current) {
        setError(errorText(cause))
        // Revoke cached material immediately when the server denies access.
        setMessages([])
        setActiveRun(null)
      }
    }
  }, [activeId])

  useEffect(() => {
    if (!shared || activeId === null || sending) return
    let busy = false
    const timer = setInterval(() => {
      if (busy || document.visibilityState === 'hidden') return
      busy = true
      void refreshSession().finally(() => { busy = false })
    }, 1800)
    return () => clearInterval(timer)
  }, [shared, activeId, sending, refreshSession])

  useEffect(() => {
    let current = true
    const timer = setInterval(() => {
      if (document.visibilityState === 'hidden' || stream.current) return
      const request = generation.current
      void assistantApi.sessions().then((items) => {
        if (!current || request !== generation.current) return
        setSessions(items)
        // A directory response can arrive before the room refresh. Do not stop
        // polling a revoked room while leaving its cached material on screen.
        if (activeId !== null && !items.some((item) => item.id === activeId)) {
          generation.current += 1
          setMessages([])
          setActiveRun(null)
          replay.current = null
          setActiveId(null)
          setTaskCode('')
          setError('此会话的访问权限已变更，请重新选择会话。')
        }
      }).catch(() => undefined)
    }, 5000)
    return () => { current = false; clearInterval(timer) }
  }, [activeId])

  useEffect(() => {
    let current = true
    void Promise.allSettled([
      assistantApi.sessions(), assistantApi.capabilities(),
      assistantApi.tasks(role === 'operator'), assistantApi.skills(),
    ]).then(([history, capability, availableTasks, availableSkills]) => {
      if (!current) return
      if (history.status === 'fulfilled') setSessions(history.value)
      else setError(errorText(history.reason))
      if (capability.status === 'fulfilled') setCapabilities(capability.value)
      else setNotice(`服务状态读取失败：${errorText(capability.reason)}`)
      if (availableTasks.status === 'fulfilled') setTasks(availableTasks.value)
      if (availableSkills.status === 'fulfilled') setSkills(availableSkills.value)
      if (availableTasks.status === 'rejected' || availableSkills.status === 'rejected') {
        setNotice('任务或技能目录暂不可用；仍可发起普通问答。')
      }
      setLoading(false)
    })
    return () => { current = false }
  }, [role])

  useEffect(() => () => {
    generation.current += 1
    stream.current?.abort()
  }, [])

  const refreshCapabilities = useCallback(async () => {
    try {
      setCapabilities(await assistantApi.capabilities())
      setNotice('')
    } catch (cause) { setNotice(errorText(cause)) }
  }, [])

  const newConversation = useCallback((nextTask = '') => {
    if (stream.current) return
    generation.current += 1
    setSwitching(false)
    setActiveId(null)
    setMessages([])
    setActiveRun(null)
    replay.current = null
    setTaskCode(nextTask)
    setError('')
  }, [])

  const selectSession = useCallback(async (id: number) => {
    if (stream.current) return
    const request = ++generation.current
    setSwitching(true)
    setError('')
    try {
      const session = await assistantApi.session(id)
      if (request !== generation.current) return
      setSessions((items) => items.some((item) => item.id === id)
        ? items.map((item) => item.id === id ? session : item) : [session, ...items])
      setActiveId(id)
      setMessages(session.messages.map(restoredMessage))
      setActiveRun(session.active_run || null)
      setTaskCode(session.task_code || '')
    } catch (cause) {
      if (request === generation.current) setError(errorText(cause))
    } finally {
      if (request === generation.current) setSwitching(false)
    }
  }, [])

  const deleteSession = useCallback(async (id: number) => {
    if (stream.current) return
    try {
      await assistantApi.deleteSession(id)
      setSessions((items) => items.filter((item) => item.id !== id))
      if (activeId === id) newConversation()
    } catch (cause) { setError(errorText(cause)) }
  }, [activeId, newConversation])

  const send = useCallback(async (text: string, accepted?: () => void) => {
    const content = text.trim()
    if (!content || loading || switching || stream.current) return
    const controller = new AbortController()
    stream.current = controller
    setSending(true)
    setError('')
    const request = generation.current
    let localId: string | undefined
    let ended = false
    let acceptedDraft = false
    const update = (apply: (message: AssistantMessage) => AssistantMessage) => {
      if (request === generation.current) {
        setMessages((items) => items.map((item) => item.id === localId ? apply(item) : item))
      }
    }
    try {
      let id = activeId
      if (id === null) {
        const created = await assistantApi.createSession('新会话', taskCode)
        if (controller.signal.aborted) return
        id = created.id
        setActiveId(id)
        setSessions((items) => [created, ...items])
      }
      if (controller.signal.aborted) return
      localId = `reply:${crypto.randomUUID()}`
      const user: AssistantMessage = { id: `user:${localId}`, role: 'user', content, status: 'completed', steps: [], citations: [] }
      const reply: AssistantMessage = { id: localId, role: 'assistant', content: '', status: 'running', streaming: true, steps: [], citations: [] }
      setMessages((items) => [...items, user, reply])
      if (!shared) { accepted?.(); acceptedDraft = true }
      const adapter = shared ? collaborationApi : assistantApi
      for await (const event of adapter.streamMessage(id, content, taskCode, skillId, controller.signal)) {
        if (controller.signal.aborted) break
        if (!acceptedDraft) { accepted?.(); acceptedDraft = true }
        if (event.event === 'step' && event.step) {
          update((message) => ({ ...message, steps: upsertStep(message.steps, event.step!) }))
        } else if (event.event === 'tool' && event.tool) {
          const tool = event.tool
          const step: AssistantStep = {
            key: `tool:${tool.name}`, label: '读取授权证据', status: tool.status,
            detail: tool.status === 'completed' ? `已检索 ${tool.result_count ?? 0} 条证据` : tool.status === 'running' ? '正在读取本轮授权证据' : '证据读取失败',
          }
          update((message) => ({ ...message, steps: upsertStep(message.steps, step) }))
        } else if (event.event === 'delta') {
          update((message) => ({ ...message, content: message.content + (event.delta || '') }))
        } else if (event.event === 'citations' && event.citations) {
          update((message) => ({ ...message, citations: event.citations! }))
        } else if (event.event === 'message_end' && event.message) {
          ended = true
          update(() => restoredMessage(event.message!))
          break
        } else if (event.event === 'error') {
          throw new Error(event.error_message || '助手请求失败')
        }
        // Reasoning and unknown events are never appended to the final answer.
      }
      if (!ended && !controller.signal.aborted) throw new Error('连接提前中断，未收到完整答复，请重新发送问题。')
    } catch (cause) {
      if (!controller.signal.aborted) {
        setError(errorText(cause))
        update((message) => ({ ...message, status: 'error', streaming: false,
          steps: message.steps.map((step) => step.status === 'running' ? { ...step, status: 'error', detail: '本轮执行中断' } : step),
        }))
      }
    } finally {
      if (controller.signal.aborted) {
        update((message) => ({
          ...message, streaming: false, status: 'stopped',
          steps: message.steps.map((step) => step.status === 'running' ? { ...step, status: 'error', detail: '已停止接收' } : step),
        }))
      }
      if (request === generation.current) {
        setSending(false)
        void assistantApi.sessions().then((items) => {
          if (request === generation.current) setSessions(items)
        }).catch(() => undefined)
      }
      if (stream.current === controller) stream.current = null
      if (shared) void refreshSession()
    }
  }, [activeId, loading, switching, taskCode, skillId, shared, refreshSession])

  const discuss = useCallback(async (content: string, accepted?: () => void) => {
    if (!content.trim() || activeId === null || discussionLock.current) return
    discussionLock.current = true
    const request = generation.current
    try {
      await collaborationApi.discuss(activeId, content.trim())
      if (request !== generation.current) return
      accepted?.()
      await refreshSession()
    } catch (cause) { if (request === generation.current) setError(errorText(cause)) }
    finally { discussionLock.current = false }
  }, [activeId, refreshSession])

  return {
    sessions, activeId, messages, capabilities, tasks, skills, taskCode, skillId,
    loading, switching, sending, error, notice, setSkillId, setError,
    refreshCapabilities, newConversation, selectSession, deleteSession, send,
    shared, activeRun, refreshSession, discuss,
    stop: () => stream.current?.abort(),
  }
}
