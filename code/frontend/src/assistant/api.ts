import type {
  AssistantCapabilities,
  AssistantSession,
  AssistantSessionDetail,
  AssistantStreamEvent,
  AssistantSkill,
  AssistantTaskOption,
} from './types'
import { useAuthStore } from '@/stores/auth'
import router from '@/router'

const base = '/api/assistant'

function token(): string {
  return localStorage.getItem('token') || ''
}

function headers(json = false): HeadersInit {
  return {
    ...(json ? { 'Content-Type': 'application/json' } : {}),
    ...(token() ? { Authorization: `Bearer ${token()}` } : {}),
  }
}

function rejectExpiredSession(): Error {
  useAuthStore().logout()
  const current = router.currentRoute.value
  if (current.name !== 'login') {
    void router.replace({ name: 'login', query: { redirect: current.fullPath } })
  }
  return new Error('登录已过期，请重新登录')
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  if (!response.ok) {
    if (response.status === 401) throw rejectExpiredSession()
    const body = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(body.detail || `助手请求失败（${response.status}）`)
  }
  return response.json() as Promise<T>
}

export const assistantApi = {
  capabilities(): Promise<AssistantCapabilities> {
    return request(`${base}/capabilities`, { headers: headers() })
  },

  sessions(): Promise<AssistantSession[]> {
    return request(`${base}/sessions`, { headers: headers() })
  },

  tasks(mine: boolean): Promise<AssistantTaskOption[]> {
    return request(`/api/tasks?mine=${mine}`, { headers: headers() })
  },

  skills(): Promise<AssistantSkill[]> {
    return request(`${base}/skills`, { headers: headers() })
  },

  createSession(title = '新会话', taskCode?: string): Promise<AssistantSession> {
    return request(`${base}/sessions`, {
      method: 'POST',
      headers: headers(true),
      body: JSON.stringify({ title, task_code: taskCode || null }),
    })
  },

  session(id: number): Promise<AssistantSessionDetail> {
    return request(`${base}/sessions/${id}`, { headers: headers() })
  },

  deleteSession(id: number): Promise<{ deleted: boolean }> {
    return request(`${base}/sessions/${id}`, { method: 'DELETE', headers: headers() })
  },

  async *streamMessage(id: number, content: string, taskCode?: string, skillId?: string, signal?: AbortSignal): AsyncGenerator<AssistantStreamEvent> {
    const response = await fetch(`${base}/sessions/${id}/messages/stream`, {
      method: 'POST',
      headers: { ...headers(true), Accept: 'text/event-stream' },
      body: JSON.stringify({ content, task_code: taskCode || null, skill_id: skillId || null }),
      signal,
    })
    if (!response.ok || !response.body) {
      if (response.status === 401) throw rejectExpiredSession()
      const body = await response.json().catch(() => ({})) as { detail?: string }
      throw new Error(body.detail || `助手流式请求失败（${response.status}）`)
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    try {
      while (true) {
        const { value, done } = await reader.read()
        buffer += decoder.decode(value || new Uint8Array(), { stream: !done })
        const frames = buffer.split(/\r?\n\r?\n/)
        buffer = frames.pop() || ''
        if (done && buffer.trim()) frames.push(buffer)
        for (const frame of frames) {
          const data = frame.split(/\r?\n/).filter((line) => line.startsWith('data:')).map((line) => line.slice(5).trimStart()).join('\n')
          if (data) {
            const event = JSON.parse(data) as AssistantStreamEvent
            if (event.event === 'error') event.error_message = (event as AssistantStreamEvent & { message?: string }).message
            yield event
          }
        }
        if (done) break
      }
    } finally {
      reader.releaseLock()
    }
  },
}
