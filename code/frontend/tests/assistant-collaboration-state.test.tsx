import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AssistantApiError, assistantApi } from '@/assistant/api'
import { useAssistant } from '@/assistant/useAssistant'
import { useAuthStore } from '@/stores/auth'
import { collaborationApi } from '@/assistant/collaboration'
import type { AssistantSessionDetail } from '@/assistant/types'

vi.mock('@/assistant/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/assistant/api')>()
  return { ...actual, assistantApi: {
    sessions: vi.fn(), capabilities: vi.fn(), tasks: vi.fn(), skills: vi.fn(), session: vi.fn(),
  } }
})
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
  it('never carries a selected skill across a new or restored conversation', async () => {
    const { result } = renderHook(() => useAssistant())
    await act(async () => { await Promise.resolve() })
    act(() => result.current.setSkillId('review-skill'))
    act(() => result.current.newConversation('TASK-2'))
    expect(result.current.taskCode).toBe('TASK-2')
    expect(result.current.skillId).toBeUndefined()

    act(() => result.current.setSkillId('review-skill'))
    await act(async () => { await result.current.selectSession(7) })
    expect(result.current.skillId).toBeUndefined()
  })

  it('keeps the private active run through a transient error and restores its completed reply on retry', async () => {
    const run = { id: 'recover-run', status: 'running', user_id: 1, session_id: 7, client_message_id: 'request-recover' }
    const privateRoom = { ...detail, shared: false, can_manage: true, active_run: run }
    const completed = { ...privateRoom, active_run: null, messages: [...detail.messages, {
      id: 2, run_id: run.id, role: 'assistant' as const, status: 'completed', content: '已恢复并完成核对', steps: [], citations: [],
    }] }
    vi.mocked(assistantApi.sessions).mockResolvedValue([privateRoom])
    vi.mocked(assistantApi.session)
      .mockResolvedValueOnce(privateRoom)
      .mockResolvedValueOnce(privateRoom)
      .mockRejectedValueOnce(new AssistantApiError(503, '服务暂不可用'))
      .mockResolvedValueOnce(privateRoom)
      .mockResolvedValue(completed)
    const events = vi.spyOn(collaborationApi, 'events')
      .mockResolvedValueOnce({ cursor: 2, has_more: false, active_run: run, events: [
        { id: 1, run_id: run.id, event: 'step', step: { key: 'retrieve', label: '读取授权材料', status: 'completed' } },
      ] })
      .mockResolvedValueOnce({ cursor: 4, has_more: false, active_run: run, events: [
        { id: 3, run_id: run.id, event: 'delta', delta: '仍在核对' },
      ] })
    const start = vi.spyOn(collaborationApi, 'streamMessage')
    const { result } = renderHook(() => useAssistant())
    await act(async () => { await Promise.resolve() })
    await act(async () => { await result.current.selectSession(7) })
    await act(async () => { await Promise.resolve() })

    expect(result.current.activeRun).toMatchObject({ id: run.id })
    expect(result.current.messages.at(-1)).toMatchObject({ streaming: true, steps: [{ key: 'retrieve' }] })
    expect(events).toHaveBeenNthCalledWith(1, 7, 0, run.id)
    expect(start).not.toHaveBeenCalled()

    await act(async () => { await vi.advanceTimersByTimeAsync(1800) })
    expect(result.current.activeRun).toMatchObject({ id: run.id })
    expect(result.current.messages.at(-1)).toMatchObject({ streaming: true, steps: [{ key: 'retrieve' }] })
    expect(result.current.error).toContain('正在尝试恢复')

    await act(async () => { await vi.advanceTimersByTimeAsync(1800) })
    expect(events).toHaveBeenNthCalledWith(2, 7, 2, run.id)
    expect(result.current.messages.at(-1)).toMatchObject({ content: '仍在核对', streaming: true })
    expect(result.current.error).toBe('')

    await act(async () => { await vi.advanceTimersByTimeAsync(1800) })
    expect(result.current.activeRun).toBeNull()
    expect(result.current.messages.at(-1)).toMatchObject({ content: '已恢复并完成核对', streaming: false })
    expect(result.current.error).toBe('')
    expect(start).not.toHaveBeenCalled()
  })

  it('clears private material and leaves the room when access is explicitly revoked', async () => {
    const run = { id: 'revoked-run', status: 'running', user_id: 1, session_id: 7, client_message_id: 'request-revoked' }
    const privateRoom = { ...detail, shared: false, can_manage: true, active_run: run }
    vi.mocked(assistantApi.sessions).mockResolvedValue([privateRoom])
    vi.mocked(assistantApi.session)
      .mockResolvedValueOnce(privateRoom)
      .mockRejectedValueOnce(new AssistantApiError(403, '禁止访问'))
    const { result } = renderHook(() => useAssistant())
    await act(async () => { await Promise.resolve() })
    await act(async () => { await result.current.selectSession(7) })
    await act(async () => { await Promise.resolve() })

    expect(result.current.activeId).toBeNull()
    expect(result.current.activeRun).toBeNull()
    expect(result.current.messages).toEqual([])
    expect(result.current.sessions.some((item) => item.id === 7)).toBe(false)
    expect(result.current.error).toContain('访问权限已变更')
  })

  it('recovers a private active run after reopening without submitting another model request', async () => {
    const run = { id: 'private-run', status: 'running', user_id: 1, session_id: 7, client_message_id: 'request-1' }
    const privateRoom = { ...detail, shared: false, can_manage: true, active_run: run }
    vi.mocked(assistantApi.sessions).mockResolvedValue([privateRoom])
    vi.mocked(assistantApi.session).mockResolvedValue(privateRoom)
    const events = vi.spyOn(collaborationApi, 'events').mockResolvedValue({ cursor: 2, has_more: false, active_run: run, events: [
      { id: 2, run_id: run.id, event: 'step', step: { key: 'compose', label: '生成审核建议', status: 'running' } },
    ] })
    const start = vi.spyOn(collaborationApi, 'streamMessage')
    const { result } = renderHook(() => useAssistant())
    await act(async () => { await Promise.resolve() })
    await act(async () => { await result.current.selectSession(7) })
    expect(result.current.shared).toBe(false)
    expect(result.current.messages.at(-1)).toMatchObject({ run_id: run.id, streaming: true })
    expect(events).toHaveBeenCalledWith(7, 0, run.id)
    await act(async () => { await result.current.send('重复提问') })
    expect(start).not.toHaveBeenCalled()
    expect(result.current.error).toContain('AI 正在工作')

    const final = { id: 2, run_id: run.id, role: 'assistant' as const, status: 'completed', content: '已完成核对', steps: [], citations: [] }
    vi.mocked(assistantApi.session).mockResolvedValue({ ...privateRoom, active_run: null, messages: [...detail.messages, final] })
    await act(async () => { await vi.advanceTimersByTimeAsync(1800) })
    expect(result.current.activeRun).toBeNull()
    expect(result.current.messages.at(-1)).toMatchObject({ content: '已完成核对', streaming: false })
    expect(start).not.toHaveBeenCalled()
  })

  it('clears cached messages when the directory removes the current room before room polling', async () => {
    const { result } = renderHook(() => useAssistant())
    await act(async () => { await Promise.resolve() })
    await act(async () => { await result.current.selectSession(7) })
    act(() => result.current.setSkillId('review-skill'))
    expect(result.current.messages[0].content).toBe('已授权材料')
    vi.mocked(assistantApi.sessions).mockResolvedValue([])
    await act(async () => { await vi.advanceTimersByTimeAsync(5000) })
    expect(result.current.messages).toEqual([])
    expect(result.current.activeId).toBeNull()
    expect(result.current.skillId).toBeUndefined()
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
