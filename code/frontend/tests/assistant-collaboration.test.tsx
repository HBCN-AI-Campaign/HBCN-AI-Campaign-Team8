import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { App, ConfigProvider } from 'antd'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { CollaborationPanel } from '@/assistant/CollaborationPanel'
import { collaborationApi, restoreActiveReply } from '@/assistant/collaboration'

vi.mock('@/assistant/collaboration', async (original) => {
  const module = await original<typeof import('@/assistant/collaboration')>()
  return { ...module, collaborationApi: { experts: vi.fn(), members: vi.fn(), invite: vi.fn(), revoke: vi.fn(), profile: vi.fn(), myProfile: vi.fn() } }
})
const expert = { user_id: 2, name: '单证专家', specialty: '国际结算', bio: '核验贸易材料', tags: ['提单'], joined: false, is_self: false, profile_source: '本人维护' }
const members = [{ user_id: 1, name: '审核人员', role: 'owner' as const, active: true, is_self: true }, { user_id: 2, name: '单证专家', role: 'contributor' as const, active: true, is_self: false }]
beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(collaborationApi.experts).mockImplementation(async (_id, q) => q === '不存在' ? [] : [expert])
  vi.mocked(collaborationApi.members).mockResolvedValue(members)
  vi.mocked(collaborationApi.invite).mockResolvedValue({})
  vi.mocked(collaborationApi.revoke).mockResolvedValue({})
  vi.mocked(collaborationApi.myProfile).mockResolvedValue({ specialty: '贸易融资', bio: '我的既有介绍', tags: ['信用证'] })
  vi.mocked(collaborationApi.profile).mockResolvedValue({ saved: true })
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
    expect(screen.getByRole('region', { name: '专家搜索结果' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '维护我的专业资料' })).toBeTruthy()
    expect(screen.getByText('与当前讨论匹配的专家')).toBeTruthy()
    fireEvent.change(screen.getByRole('searchbox', { name: '搜索专家' }), { target: { value: '不存在' } })
    await screen.findByText('暂无匹配专家；可请同事维护自己的专业资料')
    expect(collaborationApi.experts).toHaveBeenCalledWith(3, '不存在')
    fireEvent.change(screen.getByRole('searchbox', { name: '搜索专家' }), { target: { value: '提单' } })
    fireEvent.click(await screen.findByRole('button', { name: /邀请加入/ }))
    expect(collaborationApi.experts).toHaveBeenCalledWith(3, '提单')
    await screen.findByText(/对方将能阅读当前会话的完整历史/)
    expect(collaborationApi.invite).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: /确认共享并邀请/ }))
    await waitFor(() => expect(collaborationApi.invite).toHaveBeenCalledWith(3, 2))
    await waitFor(() => expect(changed).toHaveBeenCalled())
  })

  it('searches beyond the initial directory and ignores late results from an older query', async () => {
    let stale!: (value: typeof expert[]) => void
    vi.mocked(collaborationApi.experts).mockImplementation(async (_id, q) => {
      if (q === '旧搜索') return new Promise((resolve) => { stale = resolve })
      if (q === '新搜索') return [{ ...expert, name: '默认首屏之外专家', bio: '最新服务端搜索结果' }]
      return [expert]
    })
    mount()
    await screen.findByText('核验贸易材料')
    const search = screen.getByRole('searchbox', { name: '搜索专家' })
    fireEvent.change(search, { target: { value: '旧搜索' } })
    await waitFor(() => expect(collaborationApi.experts).toHaveBeenCalledWith(3, '旧搜索'))
    fireEvent.change(search, { target: { value: '新搜索' } })
    await screen.findByText('最新服务端搜索结果')
    await act(async () => { stale([{ ...expert, bio: '过期结果' }]) })
    expect(screen.queryByText('过期结果')).toBeNull()
    expect(screen.getByText('最新服务端搜索结果')).toBeTruthy()
  })

  it('loads my profile outside search results and retains edits when saving fails', async () => {
    mount()
    await screen.findByText('核验贸易材料')
    fireEvent.change(screen.getByRole('searchbox', { name: '搜索专家' }), { target: { value: '不存在' } })
    await screen.findByText('暂无匹配专家；可请同事维护自己的专业资料')
    fireEvent.click(screen.getByRole('button', { name: '维护我的专业资料' }))
    const bio = await screen.findByRole('textbox', { name: '个人介绍' })
    expect((bio as HTMLTextAreaElement).value).toBe('我的既有介绍')
    expect(collaborationApi.myProfile).toHaveBeenCalledTimes(1)
    fireEvent.change(bio, { target: { value: '尚未保存的新介绍' } })
    vi.mocked(collaborationApi.profile).mockRejectedValueOnce(new Error('保存暂不可用'))
    fireEvent.click(screen.getByRole('button', { name: '保存资料' }))
    await waitFor(() => expect(screen.getAllByText('保存暂不可用').length).toBeGreaterThan(0))
    expect((screen.getByRole('textbox', { name: '个人介绍' }) as HTMLTextAreaElement).value).toBe('尚未保存的新介绍')
    fireEvent.click(screen.getByRole('button', { name: '保存资料' }))
    await waitFor(() => expect(collaborationApi.profile).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(screen.queryByRole('textbox', { name: '个人介绍' })).toBeNull())
    expect(collaborationApi.profile).toHaveBeenLastCalledWith({ specialty: '贸易融资', bio: '尚未保存的新介绍', tags: ['信用证'] })
  })

  it('does not open an empty profile editor after a failed profile read', async () => {
    vi.mocked(collaborationApi.myProfile).mockRejectedValue(new Error('本人资料读取失败'))
    mount()
    await screen.findByText('核验贸易材料')
    fireEvent.click(screen.getByRole('button', { name: '维护我的专业资料' }))
    await screen.findByText('本人资料读取失败')
    expect(screen.queryByRole('textbox', { name: '个人介绍' })).toBeNull()
    expect(collaborationApi.profile).not.toHaveBeenCalled()
  })

  it('does not execute an old invitation confirmation after changing rooms', async () => {
    const panel = (id: number) => <ConfigProvider theme={{ token: { motion: false } }}><App><CollaborationPanel open onClose={() => undefined} onChanged={async () => undefined} context="提单"
      session={{ id, title: '会话', task_code: 'TASK-1', can_manage: true, message_count: 0, updated_at: '' }} /></App></ConfigProvider>
    const view = render(panel(3))
    await screen.findByText('核验贸易材料')
    fireEvent.click(screen.getByRole('button', { name: /邀请加入/ }))
    await screen.findByText(/对方将能阅读当前会话的完整历史/)
    view.rerender(panel(4))
    await waitFor(() => expect(collaborationApi.members).toHaveBeenCalledWith(4))
    fireEvent.click(screen.getByRole('button', { name: /确认共享并邀请/ }))
    await waitFor(() => expect(screen.queryByText(/对方将能阅读当前会话的完整历史/)).toBeNull())
    expect(collaborationApi.invite).not.toHaveBeenCalled()
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
