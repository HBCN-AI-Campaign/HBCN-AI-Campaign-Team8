import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { assistantApi } from '@/assistant/api'
import { useAssistant } from '@/assistant/useAssistant'
import { useAuthStore } from '@/stores/auth'
import type { AssistantSessionDetail } from '@/assistant/types'

vi.mock('@/assistant/api', () => ({ assistantApi: {
  sessions: vi.fn(), capabilities: vi.fn(), tasks: vi.fn(), skills: vi.fn(), session: vi.fn(),
} }))
const detail: AssistantSessionDetail = {
  id: 7, title: '协作会话', message_count: 1, updated_at: '', task_code: 'TASK-1',
  shared: true, can_manage: false, active_run: null,
  messages: [{ id: 1, role: 'user', content: '已授权材料', author_name: '审核同事', status: 'completed', steps: [], citations: [] }],
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.resetAllMocks()
  useAuthStore.getState().setAuth('test-jwt', 'reviewer', '审核人员')
  vi.mocked(assistantApi.sessions).mockResolvedValue([detail])
  vi.mocked(assistantApi.session).mockResolvedValue(detail)
  vi.mocked(assistantApi.tasks).mockResolvedValue([])
  vi.mocked(assistantApi.skills).mockResolvedValue([])
  vi.mocked(assistantApi.capabilities).mockResolvedValue({ sdk: 'opencode-sdk', configured: true, rag_available: true, supports_stream: true, message: '就绪' })
})
afterEach(() => vi.useRealTimers())

describe('shared room authority and directory races', () => {
  it('clears cached messages when the directory removes the current room before room polling', async () => {
    const { result } = renderHook(() => useAssistant())
    await act(async () => { await Promise.resolve() })
    await act(async () => { await result.current.selectSession(7) })
    expect(result.current.messages[0].content).toBe('已授权材料')
    vi.mocked(assistantApi.sessions).mockResolvedValue([])
    await act(async () => { await vi.advanceTimersByTimeAsync(5000) })
    expect(result.current.messages).toEqual([])
    expect(result.current.activeId).toBeNull()
    expect(result.current.error).toContain('访问权限已变更')
  })

  it('uses authoritative shared-room permissions even when initial directory metadata is stale', async () => {
    vi.mocked(assistantApi.sessions).mockResolvedValue([{ ...detail, shared: false, can_manage: true }])
    const { result } = renderHook(() => useAssistant())
    await act(async () => { await Promise.resolve() })
    await act(async () => { await result.current.selectSession(7) })
    expect(result.current.shared).toBe(true)
    expect(result.current.sessions.find((item) => item.id === 7)?.can_manage).toBe(false)
  })
})
