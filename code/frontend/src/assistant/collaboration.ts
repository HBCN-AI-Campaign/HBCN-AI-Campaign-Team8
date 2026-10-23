/** Business adapter for the existing JWT API; UI comes from Ant Design / X. */
import { useAuthStore } from '@/stores/auth'
import type { AssistantMessage, AssistantSessionDetail, AssistantSkill, AssistantStreamEvent } from './types'

export interface Expert {
  user_id: number; name: string; specialty: string; bio: string; tags: string[]
  joined: boolean; is_self: boolean; profile_source: string
}
export interface Member { user_id: number; name: string; role: 'owner' | 'contributor'; active: boolean; is_self: boolean }
export interface Run { id: string; status: string; user_id: number; session_id: number; client_message_id: string }
export interface RoomEvent extends AssistantStreamEvent { id: number; run_id?: string; user_message?: AssistantMessage; status?: string }
export interface EventPage { events: RoomEvent[]; cursor: number; has_more: boolean; active_run: Run | null }
export interface LibrarySkill extends AssistantSkill { source: string; installed: boolean; update_available: boolean }
export interface CustomSkillInput { name: string; desc: string; instructions: string }
export interface CustomSkillDetail extends AssistantSkill { instructions: string; revision: number }
export interface ExpertProfile { specialty: string; bio: string; tags: string[] }

export class CollaborationApiError extends Error {
  constructor(readonly status: number, message: string) {
    super(message)
    this.name = 'CollaborationApiError'
  }
}

// Aborting a reader (navigation/unmount) must not cancel a durable model run.
export const STOP_ASSISTANT_RUN = 'stop-assistant-run'

async function request<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const token = useAuthStore.getState().token
  const response = await fetch(`/api/assistant/v1${path}`, {
    method, headers: { Authorization: `Bearer ${token}`, ...(body ? { 'Content-Type': 'application/json' } : {}) },
    ...(body ? { body: JSON.stringify(body) } : {}),
  })
  if (!response.ok) {
    if (response.status === 401 && useAuthStore.getState().token === token) useAuthStore.getState().logout()
    const result = await response.json().catch(() => ({})) as { detail?: string }
    throw new CollaborationApiError(response.status, result.detail || `协作请求失败（${response.status}）`)
  }
  return response.json() as Promise<T>
}

const pause = (ms: number, signal?: AbortSignal) => new Promise<void>((resolve) => {
  if (signal?.aborted) return resolve()
  const done = () => { clearTimeout(timer); signal?.removeEventListener('abort', done); resolve() }
  const timer = setTimeout(done, ms)
  signal?.addEventListener('abort', done, { once: true })
})

export const collaborationApi = {
  library: () => request<LibrarySkill[]>('/skill-library'),
  installSkill: (skillId: string) => request(`/skill-library/${encodeURIComponent(skillId)}`, 'PUT'),
  uninstallSkill: (skillId: string) => request(`/skill-library/${encodeURIComponent(skillId)}`, 'DELETE'),
  createCustomSkill: (skill: CustomSkillInput) => request<AssistantSkill>('/skill-library/custom', 'POST', skill),
  customSkill: (skillId: string) => request<CustomSkillDetail>(`/skill-library/custom/${encodeURIComponent(skillId)}`),
  updateCustomSkill: (skillId: string, skill: CustomSkillInput, expectedRevision: number) => request<AssistantSkill>(
    `/skill-library/custom/${encodeURIComponent(skillId)}`, 'PUT', { ...skill, expected_revision: expectedRevision },
  ),
  deleteCustomSkill: (skillId: string) => request<{ deleted: boolean }>(`/skill-library/custom/${encodeURIComponent(skillId)}`, 'DELETE'),
  experts: (id: number, q = '') => request<Expert[]>(`/experts?session_id=${id}&q=${encodeURIComponent(q)}`),
  members: (id: number) => request<Member[]>(`/sessions/${id}/members`),
  invite: (id: number, userId: number) => request(`/sessions/${id}/members`, 'POST', { user_id: userId }),
  revoke: (id: number, userId: number) => request(`/sessions/${id}/members/${userId}`, 'DELETE'),
  myProfile: () => request<ExpertProfile>('/experts/me'),
  profile: (profile: ExpertProfile) => request('/experts/me', 'PUT', profile),
  discuss: (id: number, content: string) => request<AssistantMessage>(`/sessions/${id}/messages`, 'POST', { content }),
  events: (id: number, cursor: number, runId?: string) => request<EventPage>(`/sessions/${id}/events?after_id=${cursor}${runId ? `&run_id=${encodeURIComponent(runId)}` : ''}`),
  cancel: (id: number, runId: string) => request(`/sessions/${id}/runs/${runId}/cancel`, 'POST'),
  async *streamMessage(id: number, content: string, taskCode?: string, skillId?: string, signal?: AbortSignal): AsyncGenerator<AssistantStreamEvent> {
    if (signal?.aborted) return
    // Snapshot cursor precedes admission: a fast model cannot finish in the gap.
    const room = await request<AssistantSessionDetail>(`/sessions/${id}`)
    if (signal?.aborted) return
    let cursor = room.event_cursor || 0
    const run = await request<Run>(`/sessions/${id}/runs`, 'POST', {
      content, task_code: taskCode || null, skill_id: skillId || null, client_message_id: crypto.randomUUID(),
    })
    let ended = false
    // RAG's documented enhanced-retrieval budget is 240s, then the model has
    // its own request budget; leave margin for persistence and polling.
    const deadline = Date.now() + 400_000
    try {
      yield { event: 'run_started', run }
      while (!signal?.aborted && Date.now() < deadline) {
        const page = await collaborationApi.events(id, cursor, run.id)
        cursor = page.cursor
        for (const event of page.events) {
          if (event.run_id !== run.id) continue
          if (event.event === 'error') event.error_message = typeof event.message === 'string' ? event.message : '助手运行未完成'
          yield event
          if (event.event === 'message_end') { ended = true; return }
          if (event.event === 'run_end') {
            ended = true
            throw new Error(event.status === 'cancelled' ? '本轮运行已停止' : '本轮未获得完整答复，请重试')
          }
        }
        if (!page.has_more) await pause(700, signal)
      }
      if (!signal?.aborted) throw new Error('运行超时，请刷新查看结果')
    } finally {
      if (signal?.aborted && signal.reason === STOP_ASSISTANT_RUN && !ended) {
        await collaborationApi.cancel(id, run.id).catch(() => undefined)
      }
    }
  },
}

/** Reconstruct only public events for the active run after a refresh. */
export function restoreActiveReply(messages: AssistantMessage[], events: RoomEvent[], active: Run | null): AssistantMessage[] {
  if (!active || messages.some((message) => message.role === 'assistant' && message.run_id === active.id && message.status === 'completed')) return messages
  const reply: AssistantMessage = { id: `run:${active.id}`, run_id: active.id, role: 'assistant', author_name: '慧眼助手', content: '',
    status: 'running', streaming: true, steps: [], citations: [] }
  for (const event of events) {
    if (event.run_id !== active.id) continue
    if (event.event === 'step' && event.step) {
      const index = reply.steps.findIndex((step) => step.key === event.step!.key)
      if (index < 0) reply.steps.push(event.step); else reply.steps[index] = event.step
    } else if (event.event === 'tool' && event.tool) {
      const step = { key: `tool:${event.tool.name}`, label: '读取授权证据', status: event.tool.status }
      reply.steps = [...reply.steps.filter((item) => item.key !== step.key), step]
    } else if (event.event === 'delta') reply.content += event.delta || ''
    else if (event.event === 'citations' && event.citations) reply.citations = event.citations
    else if (event.event === 'message_end' && event.message) return [...messages, { ...event.message, streaming: false }]
    else if (event.event === 'error' || event.event === 'run_end') {
      reply.streaming = false
      reply.status = event.status === 'cancelled' ? 'stopped' : 'error'
      reply.steps = reply.steps.map((step) => step.status === 'running' ? { ...step, status: 'error' } : step)
    }
  }
  return [...messages, reply]
}
