import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { App, ConfigProvider } from 'antd'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { CollaborationPanel } from '@/assistant/CollaborationPanel'
import { collaborationApi, restoreActiveReply } from '@/assistant/collaboration'

vi.mock('@/assistant/collaboration', async (original) => {
  const module = await original<typeof import('@/assistant/collaboration')>()
  return { ...module, collaborationApi: { experts: vi.fn(), members: vi.fn(), invite: vi.fn(), revoke: vi.fn(), profile: vi.fn() } }
})
const expert = { user_id: 2, name: '单证专家', specialty: '国际结算', bio: '核验贸易材料', tags: ['提单'], joined: false, is_self: false, profile_source: '本人维护' }
const members = [{ user_id: 1, name: '审核人员', role: 'owner' as const, active: true, is_self: true }, { user_id: 2, name: '单证专家', role: 'contributor' as const, active: true, is_self: false }]
beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(collaborationApi.experts).mockResolvedValue([expert])
  vi.mocked(collaborationApi.members).mockResolvedValue(members)
  vi.mocked(collaborationApi.invite).mockResolvedValue({})
  vi.mocked(collaborationApi.revoke).mockResolvedValue({})
})
const mount = (canManage = true) => {
  const changed = vi.fn().mockResolvedValue(undefined)
  render(<ConfigProvider theme={{ token: { motion: false } }}><App><CollaborationPanel open onClose={() => undefined} onChanged={changed} context="请协助核验提单" session={{ id: 3, title: '贸易核验', task_code: 'TASK-1', can_manage: canManage, message_count: 2, updated_at: '' }} /></App></ConfigProvider>)
  return changed
}

describe('reviewer collaboration with Ant Design components', () => {
  it('shows real expert descriptions, searches, confirms history sharing before inviting', async () => {
    const changed = mount()
    await screen.findByText('核验贸易材料')
    expect(screen.getByText('与当前讨论匹配的专家')).toBeTruthy()
    fireEvent.change(screen.getByRole('searchbox', { name: '搜索专家' }), { target: { value: '不存在' } })
    await screen.findByText('暂无匹配专家；可请同事维护自己的专业资料')
    fireEvent.change(screen.getByRole('searchbox', { name: '搜索专家' }), { target: { value: '提单' } })
    fireEvent.click(await screen.findByRole('button', { name: /邀请加入/ }))
    await screen.findByText(/对方将能阅读当前会话的完整历史/)
    expect(collaborationApi.invite).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: /确认共享并邀请/ }))
    await waitFor(() => expect(collaborationApi.invite).toHaveBeenCalledWith(3, 2))
    await waitFor(() => expect(changed).toHaveBeenCalled())
  })

  it('only lets the owner manage members', async () => {
    mount(false)
    await screen.findByText('核验贸易材料')
    expect((screen.getByRole('button', { name: /邀请加入/ }) as HTMLButtonElement).disabled).toBe(true)
    fireEvent.click(screen.getByRole('tab', { name: /会话成员/ }))
    await screen.findByText('参与审核讨论 · 可向 AI 提问')
    expect(screen.queryByRole('button', { name: /撤销访问/ })).toBeNull()
  })

  it('reconstructs public progress and excludes reasoning events', () => {
    const run = { id: 'run-1', status: 'running', session_id: 3, user_id: 1, client_message_id: 'request-1' }
    const restored = restoreActiveReply([], [
      { id: 1, run_id: 'run-1', event: 'reasoning', delta: '内部推理' },
      { id: 2, run_id: 'run-1', event: 'step', step: { key: 'evidence', label: '检索证据', status: 'running' } },
      { id: 3, run_id: 'run-1', event: 'step', step: { key: 'evidence', label: '检索证据', status: 'completed' } },
      { id: 4, run_id: 'other', event: 'delta', delta: '其他运行' },
      { id: 5, run_id: 'run-1', event: 'delta', delta: '公开回答' },
    ], run)
    expect(restored[0].content).toBe('公开回答')
    expect(restored[0].steps).toHaveLength(1)
    expect(restored[0].steps[0].status).toBe('completed')
  })

  it('uses the canonical final reply if the run completes while replaying its events', () => {
    const run = { id: 'run-race', status: 'running', session_id: 3, user_id: 1, client_message_id: 'request-race' }
    const final = { id: 12, run_id: run.id, role: 'assistant' as const, content: '已核对，需人工确认', status: 'completed', steps: [], citations: [] }
    const restored = restoreActiveReply([], [
      { id: 1, run_id: run.id, event: 'delta', delta: '不完整回显' },
      { id: 2, run_id: run.id, event: 'message_end', message: final },
    ], run)
    expect(restored).toEqual([{ ...final, streaming: false }])
  })
})
