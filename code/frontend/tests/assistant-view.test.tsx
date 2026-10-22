import { StrictMode } from 'react'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { App, ConfigProvider } from 'antd'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import AssistantView from '@/views/AssistantView'
import ProtectedRoute from '@/router/ProtectedRoute'
import { assistantApi } from '@/assistant/api'
import { collaborationApi, STOP_ASSISTANT_RUN } from '@/assistant/collaboration'
import { useAuthStore } from '@/stores/auth'
import type { AssistantMessage, AssistantStreamEvent } from '@/assistant/types'

vi.mock('@/assistant/api', () => ({ assistantApi: {
  sessions: vi.fn(), capabilities: vi.fn(), tasks: vi.fn(), skills: vi.fn(),
  createSession: vi.fn(), session: vi.fn(), deleteSession: vi.fn(), streamMessage: vi.fn(),
} }))
vi.mock('@/assistant/collaboration', async (original) => {
  const module = await original<typeof import('@/assistant/collaboration')>()
  return { ...module, collaborationApi: { ...module.collaborationApi, streamMessage: vi.fn(), library: vi.fn() } }
})

const session = { id: 7, title: '风险讨论', message_count: 2, updated_at: '2026-10-20T10:00:00Z', task_code: null }
const final: AssistantMessage = {
  id: 12, role: 'assistant', content: '**可以协助梳理材料。**\n审核结论必须由有权限人员确认。', status: 'completed',
  steps: [{ key: 'evidence', label: '读取授权证据', detail: '已检索 2 条证据', status: 'completed' }],
  citations: [{ id: 'E1', reference_id: 'E1', source_id: 'source-1', source: '任务材料', label: '授信函', page: 2, detail: '仅适用于人民币提款' }],
}

beforeEach(() => {
  vi.resetAllMocks()
  useAuthStore.getState().setAuth('test-jwt', 'reviewer', '测试审核人员')
  vi.mocked(assistantApi.sessions).mockResolvedValue([])
  vi.mocked(assistantApi.capabilities).mockResolvedValue({ sdk: 'opencode-sdk', configured: true, model: 'test-model', rag_available: true, supports_stream: true, message: '就绪' })
  vi.mocked(assistantApi.tasks).mockResolvedValue([{ id: 1, task_code: 'TASK-1', borrower: '测试企业', status: 'created' }])
  vi.mocked(assistantApi.skills).mockResolvedValue([{ id: 'risk-review', name: '风险梳理', desc: '梳理风险', version: '1.0', owner: '项目组', license: 'Internal', permissions: ['task:read'] }])
  vi.mocked(collaborationApi.library).mockResolvedValue([])
  vi.mocked(assistantApi.createSession).mockImplementation(async () => {
    // The real API directory includes committed creations. Keep the network
    // fixture consistent, otherwise polling correctly treats it as revoked.
    vi.mocked(assistantApi.sessions).mockResolvedValue([session])
    return session
  })
})

function mount(url = '/assistant') {
  return render(<StrictMode><ConfigProvider theme={{ token: { motion: false } }}><App><MemoryRouter initialEntries={[url]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><Routes>
    <Route path="/assistant" element={<ProtectedRoute reviewerOnly><AssistantView /></ProtectedRoute>} />
    <Route path="/dashboard" element={<div>审核工作台</div>} />
    <Route path="/login" element={<div>请重新登录</div>} />
  </Routes></MemoryRouter></App></ConfigProvider></StrictMode>)
}

async function send(text = '你好') {
  const input = await screen.findByRole('textbox')
  await waitFor(() => expect((input as HTMLTextAreaElement).disabled).toBe(false))
  fireEvent.change(input, { target: { value: text } })
  fireEvent.click(screen.getByRole('button', { name: '发送消息' }))
}

describe('React assistant user flows with real Ant Design X components', () => {
  it('routes operators away from the reviewer assistant', async () => {
    useAuthStore.getState().setAuth('operator-jwt', 'operator', '业务经办人')
    mount()
    expect(await screen.findByText('审核工作台')).toBeTruthy()
    expect(screen.queryByRole('textbox')).toBeNull()
    expect(assistantApi.sessions).not.toHaveBeenCalled()
  })

  it('sends a first message, streams visible progress, then collapses progress and retains sources', async () => {
    let finish!: () => void
    const gate = new Promise<void>((resolve) => { finish = resolve })
    vi.mocked(collaborationApi.streamMessage).mockImplementation(async function* () {
      yield { event: 'step', step: { key: 'evidence', label: '读取授权证据', detail: '正在检索', status: 'running' } }
      yield { event: 'reasoning', delta: '内部推理不得出现' }
      yield { event: 'delta', delta: '可以协助梳理材料。' }
      await gate
      yield { event: 'message_end', message: final }
    })
    mount()
    expect(assistantApi.createSession).not.toHaveBeenCalled()
    await send('请说明能力')
    await screen.findByText('正在执行 · 1 项操作')
    expect(screen.getByText('正在检索')).toBeTruthy()
    expect(screen.queryByText('内部推理不得出现')).toBeNull()
    expect(assistantApi.createSession).toHaveBeenCalledTimes(1)
    expect(assistantApi.streamMessage).not.toHaveBeenCalled()
    expect(assistantApi.tasks).toHaveBeenCalledWith(false)
    await act(async () => { finish() })
    await screen.findByText('执行完成 · 1 项操作')
    const toggle = screen.getByRole('button', { name: /执行完成/ })
    expect(toggle.getAttribute('aria-expanded')).toBe('false')
    expect(screen.getByText('可以协助梳理材料。').tagName).toBe('STRONG')
    fireEvent.click(screen.getByRole('button', { name: /参考依据/ }))
    await screen.findByText('授信函')
    expect(screen.getByText('第 2 页')).toBeTruthy()
    expect(screen.getByText('[E1]')).toBeTruthy()
    expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('')
  })

  it('keeps persisted evidence limits visible when completed execution is collapsed', async () => {
    vi.mocked(assistantApi.sessions).mockResolvedValue([session])
    vi.mocked(assistantApi.session).mockResolvedValue({ ...session, messages: [{ ...final, steps: [
      ...final.steps,
      { key: 'retrieval-warning-0', label: '知识库检索提示', detail: '本轮仅提供部分材料，请人工核实遗漏项。', status: 'error' },
    ] }] })
    mount('/assistant?session_id=7')
    await screen.findByText('本轮依据存在限制')
    expect(screen.getByRole('alert').textContent).toContain('本轮仅提供部分材料，请人工核实遗漏项。')
    expect(screen.getByRole('button', { name: /执行完成/ }).getAttribute('aria-expanded')).toBe('false')
  })

  it('stops receiving and re-enables sending', async () => {
    let stoppedSignal: AbortSignal | undefined
    vi.mocked(collaborationApi.streamMessage).mockImplementation(async function* (_id, _text, _task, _skill, signal) {
      stoppedSignal = signal
      yield { event: 'delta', delta: '部分答复' }
      await new Promise<void>((resolve) => signal!.addEventListener('abort', () => resolve(), { once: true }))
    })
    mount()
    await send()
    await screen.findByText('部分答复')
    fireEvent.click(screen.getByRole('button', { name: '停止接收' }))
    await screen.findByText('已停止接收，此答复可能不完整。')
    expect(stoppedSignal?.reason).toBe(STOP_ASSISTANT_RUN)
    expect(screen.getByRole('button', { name: '发送消息' })).toBeTruthy()
  })

  it('does not get stuck when the stream ends without message_end', async () => {
    vi.mocked(collaborationApi.streamMessage).mockImplementation(async function* () { yield { event: 'delta', delta: '未完成' } })
    mount()
    await send()
    await screen.findByText('连接提前中断，未收到完整答复，请重新发送问题。')
    expect(screen.getByRole('button', { name: '发送消息' })).toBeTruthy()
  })

  it('keeps the draft on a session-creation error', async () => {
    vi.mocked(assistantApi.createSession).mockRejectedValue(new Error('创建失败'))
    mount()
    await send('保留这个问题')
    await screen.findByText('创建失败')
    expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('保留这个问题')
    expect(collaborationApi.streamMessage).not.toHaveBeenCalled()
  })

  it('keeps the question if the server refuses to admit the run', async () => {
    vi.mocked(collaborationApi.streamMessage).mockImplementation(async function* () {
      throw new Error('当前会话已有运行，请刷新后重试')
    })
    mount()
    await send('不要丢失我的问题')
    await screen.findByText('当前会话已有运行，请刷新后重试')
    expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('不要丢失我的问题')
    expect(screen.getByRole('button', { name: '发送消息' })).toBeTruthy()
  })

  it('opens persisted history and sends a selected skill with task context', async () => {
    vi.mocked(assistantApi.sessions).mockResolvedValue([session])
    vi.mocked(assistantApi.createSession).mockImplementation(async () => {
      const created = { ...session, id: 8, title: '新会话' }
      vi.mocked(assistantApi.sessions).mockResolvedValue([created, session])
      return created
    })
    vi.mocked(assistantApi.session).mockResolvedValue({ ...session, messages: [{ ...final, steps: [
      { ...final.steps[0], status: 'running' }, ...final.steps,
    ] }] })
    vi.mocked(collaborationApi.streamMessage).mockImplementation(async function* (): AsyncGenerator<AssistantStreamEvent> { yield { event: 'message_end', message: final } })
    mount('/assistant?task_code=TASK-1')
    await screen.findByText('模型服务就绪')
    fireEvent.click(screen.getByRole('button', { name: '业务技能' }))
    fireEvent.click(await screen.findByRole('button', { name: '使用此技能' }))
    await send('检查任务')
    await waitFor(() => expect(collaborationApi.streamMessage).toHaveBeenCalledWith(8, '检查任务', 'TASK-1', 'risk-review', expect.any(AbortSignal)))
    await screen.findByText('执行完成 · 1 项操作')
    fireEvent.click(screen.getByText('风险讨论'))
    await waitFor(() => expect(assistantApi.session).toHaveBeenCalledWith(7))
    await waitFor(() => expect(screen.getByText('可以协助梳理材料。').tagName).toBe('STRONG'))
    expect(screen.getByRole('button', { name: /执行完成/ }).getAttribute('aria-expanded')).toBe('false')
  })

  it('redirects to login when authentication expires', async () => {
    mount()
    await screen.findByText('模型服务就绪')
    act(() => useAuthStore.getState().logout())
    expect(await screen.findByText('请重新登录')).toBeTruthy()
    expect(screen.queryByRole('button', { name: '发送消息' })).toBeNull()
  })
})
