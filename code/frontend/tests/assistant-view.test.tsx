import { StrictMode } from 'react'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { App, ConfigProvider } from 'antd'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import AssistantView from '@/views/AssistantView'
import ProtectedRoute from '@/router/ProtectedRoute'
import { assistantApi } from '@/assistant/api'
import { collaborationApi, STOP_ASSISTANT_RUN } from '@/assistant/collaboration'
import { useAuthStore } from '@/stores/auth'
import type { AssistantMessage, AssistantSkill, AssistantStreamEvent } from '@/assistant/types'

vi.mock('@/assistant/api', () => ({ assistantApi: {
  sessions: vi.fn(), capabilities: vi.fn(), tasks: vi.fn(), skills: vi.fn(),
  createSession: vi.fn(), session: vi.fn(), deleteSession: vi.fn(), streamMessage: vi.fn(),
} }))
vi.mock('@/assistant/collaboration', async (original) => {
  const module = await original<typeof import('@/assistant/collaboration')>()
  return { ...module, collaborationApi: {
    ...module.collaborationApi, streamMessage: vi.fn(), discuss: vi.fn(), library: vi.fn(), installSkill: vi.fn(), uninstallSkill: vi.fn(),
    createCustomSkill: vi.fn(), customSkill: vi.fn(), updateCustomSkill: vi.fn(), deleteCustomSkill: vi.fn(),
  } }
})
vi.mock('@/assistant/SkillLibraryDrawer', () => ({
  SkillLibraryDrawer: ({ open, onChoose, onClose }: {
    open: boolean
    onChoose: (skill?: AssistantSkill) => void
    onClose: () => void
  }) => open ? <button onClick={() => {
    onChoose({ id: 'risk-review', name: '风险梳理', desc: '梳理风险', version: '1.0', owner: '项目组', license: 'Internal', permissions: ['task:read'] })
    onClose()
  }}>选择风险梳理</button> : null,
}))
vi.mock('@/components/PdfSourceViewer', () => ({
  default: ({ visible, source, title }: {
    visible: boolean
    source: { pdf_file?: string | null; page: number } | null
    title: string
  }) => visible ? <div role="dialog" aria-label={title}>{source?.pdf_file} · {source?.page}</div> : null,
}))

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
  vi.mocked(collaborationApi.installSkill).mockResolvedValue({ installed: true })
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
  const input = await screen.findByPlaceholderText(/输入问题|询问此任务/)
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

  it('shows the knowledge-base contract diagnosis when the model is available', async () => {
    const diagnosis = '助手可用；知识库 API 版本不兼容，需使用 RAG 契约 1.2.0 或更新的 1.x 版本'
    vi.mocked(assistantApi.capabilities).mockResolvedValue({
      sdk: 'opencode-sdk', configured: true, model: 'test-model', rag_available: false,
      supports_stream: true, message: diagnosis,
    })
    mount()
    await screen.findByText('模型服务就绪')
    expect(await screen.findByText(diagnosis)).toBeTruthy()
    expect(screen.getByText('知识库未就绪')).toBeTruthy()
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
    const area = document.querySelector<HTMLElement>('.hy-chat-scroll')!
    Object.defineProperties(area, {
      scrollHeight: { configurable: true, value: 1000 },
      clientHeight: { configurable: true, value: 100 },
      scrollTop: { configurable: true, writable: true, value: 400 },
    })
    fireEvent.scroll(area)
    const jump = await screen.findByRole('button', { name: '回到最新消息' })
    await act(async () => { finish() })
    await screen.findByText('执行完成 · 1 项操作')
    expect(area.scrollTop).toBe(400)
    expect(screen.getByRole('button', { name: '回到最新消息' })).toBeTruthy()
    const toggle = screen.getByRole('button', { name: /执行完成/ })
    expect(toggle.getAttribute('aria-expanded')).toBe('false')
    expect(screen.getByText('可以协助梳理材料。').tagName).toBe('STRONG')
    fireEvent.click(screen.getByRole('button', { name: /参考依据/ }))
    await screen.findByText('授信函')
    expect(screen.getByText('第 2 页')).toBeTruthy()
    expect(screen.getByText('[E1]')).toBeTruthy()
    expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('')
    fireEvent.click(jump)
    expect(area.scrollTop).toBe(1000)
    expect(screen.queryByRole('button', { name: '回到最新消息' })).toBeNull()
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

  it('jumps from a verified answer reference into a long evidence list', async () => {
    const citations = Array.from({ length: 18 }, (_, index) => ({
      id: `E${index + 1}`, reference_id: `E${index + 1}`, source_id: `doc-${index + 1}`,
      source: `授权来源-${index + 1}-${'文件名'.repeat(30)}`, label: `审核材料-${index + 1}-${'X'.repeat(80)}`,
      page: index + 1, detail: `仅用于组件验收的材料摘录 ${'核验内容'.repeat(24)}`,
    }))
    const message: AssistantMessage = {
      ...final,
      content: '检查授权依据 [E18]；未出现在依据清单的 [E99] 不应可点击。\n\n| 核对项 | 结果 | 长字段 | 依据 |\n| --- | --- | --- | --- |\n| 币种 | 待复核 | ' + '超长字段'.repeat(30) + ' | [E1] |',
      citations,
    }
    vi.mocked(assistantApi.sessions).mockResolvedValue([session])
    vi.mocked(assistantApi.session).mockResolvedValue({ ...session, messages: [message] })
    mount('/assistant?session_id=7')

    const citationLink = await screen.findByRole('link', { name: /^查看依据 E18：/ })
    expect(screen.getByRole('button', { name: /参考依据 · 18 条/ }).getAttribute('aria-expanded')).toBe('false')
    const firstLink = document.querySelector<HTMLAnchorElement>('.hy-markdown a[data-citation-reference="E1"]')
    expect(firstLink?.getAttribute('aria-label')).toMatch(/^查看依据 E1：/)
    expect(document.querySelector('.hy-markdown')?.textContent).toContain('[E99]')
    fireEvent.click(citationLink)

    await waitFor(() => expect(screen.getByRole('button', { name: /参考依据 · 18 条/ }).getAttribute('aria-expanded')).toBe('true'))
    expect(document.querySelectorAll('.hy-sources li')).toHaveLength(18)
    expect(screen.getByRole('list', { name: '本轮参考依据，共 18 条' })).toBeTruthy()
    const target = document.querySelector('.hy-sources li[data-reference-id="E18"]')
    expect(target).toBeTruthy()
    await waitFor(() => expect(document.activeElement).toBe(target))
    expect(target?.id).toBe('assistant-citation-12-E18')
    await waitFor(() => expect(document.querySelector('.hy-sr-only')?.textContent).toContain('已定位到依据 E18：审核材料-18'))
    expect(screen.getByRole('table')).toBeTruthy()

    fireEvent.click(firstLink!)
    const firstTarget = document.querySelector('.hy-sources li[data-reference-id="E1"]')
    await waitFor(() => expect(document.activeElement).toBe(firstTarget))
    fireEvent.keyDown(firstTarget!, { key: 'Escape' })
    await waitFor(() => expect(screen.getByRole('button', { name: /参考依据 · 18 条/ }).getAttribute('aria-expanded')).toBe('false'))
    await waitFor(() => expect(document.activeElement).toBe(firstLink))
  })

  it('opens an authorized task PDF from its citation and does not offer a PDF for knowledge sources', async () => {
    const taskCitation = {
      ...final.citations[0], doc_code: 'F1', pdf_file: 'facility_letter.pdf',
    }
    const knowledgeCitation = {
      id: 'E2', reference_id: 'E2', source_id: 'kb-1', source: '知识库规则', label: '知识库规则', page: 8,
    }
    const message: AssistantMessage = {
      ...final, content: '任务依据 [E1]；知识来源 [E2]。', citations: [taskCitation, knowledgeCitation],
    }
    vi.mocked(assistantApi.sessions).mockResolvedValue([session])
    vi.mocked(assistantApi.session).mockResolvedValue({ ...session, messages: [message] })
    mount('/assistant?session_id=7')

    fireEvent.click(await screen.findByRole('link', { name: /^查看依据 E1：/ }))
    const openOriginal = await screen.findByRole('button', { name: '打开F1原件' })
    expect(screen.getAllByRole('button', { name: /打开.*原件/ })).toHaveLength(1)
    fireEvent.click(openOriginal)

    const viewer = await screen.findByRole('dialog', { name: 'F1原件' })
    expect(viewer.textContent).toContain('facility_letter.pdf')
    expect(viewer.textContent).toContain('2')
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

  it('asks before clearing a draft when starting a new conversation', async () => {
    mount()
    const input = await screen.findByPlaceholderText(/输入问题|询问此任务/)
    await waitFor(() => expect((input as HTMLTextAreaElement).disabled).toBe(false))
    fireEvent.change(input, { target: { value: '尚未发送的核对问题' } })

    fireEvent.click(screen.getByText('新建会话', { exact: true }))
    await screen.findAllByText('当前草稿尚未发送', { exact: true })
    fireEvent.click(screen.getByText('继续编辑', { exact: true }))
    expect((input as HTMLTextAreaElement).value).toBe('尚未发送的核对问题')

    fireEvent.click(screen.getByText('新建会话', { exact: true }))
    await screen.findAllByText('当前草稿尚未发送', { exact: true })
    fireEvent.click(screen.getByText('清空并切换', { exact: true }))
    expect((input as HTMLTextAreaElement).value).toBe('')
    expect(collaborationApi.streamMessage).not.toHaveBeenCalled()
  })

  it('keeps an unsent question in its current task until the user confirms a task switch', async () => {
    vi.mocked(assistantApi.tasks).mockResolvedValue([
      { id: 1, task_code: 'TASK-1', borrower: '测试企业一', status: 'created' },
      { id: 2, task_code: 'TASK-2', borrower: '测试企业二', status: 'created' },
    ])
    mount('/assistant?task_code=TASK-1')
    const input = await screen.findByPlaceholderText(/输入问题|询问此任务/)
    await waitFor(() => expect((input as HTMLTextAreaElement).disabled).toBe(false))
    fireEvent.change(input, { target: { value: '只适用于任务一的复核问题' } })
    const selector = document.querySelector('.hy-task-select .ant-select-selector')!

    fireEvent.mouseDown(selector)
    fireEvent.click(await screen.findByText('TASK-2 · 测试企业二'))
    await screen.findAllByText('当前草稿尚未发送', { exact: true })
    fireEvent.click(screen.getByText('继续编辑', { exact: true }))
    expect((input as HTMLTextAreaElement).value).toBe('只适用于任务一的复核问题')
    expect(document.querySelector('.hy-task-select .ant-select-selection-item')?.textContent).toBe('TASK-1 · 测试企业一')

    fireEvent.mouseDown(selector)
    fireEvent.click(await screen.findByText('TASK-2 · 测试企业二'))
    await screen.findAllByText('当前草稿尚未发送', { exact: true })
    fireEvent.click(screen.getByText('清空并切换', { exact: true }))
    await waitFor(() => expect(document.querySelector('.hy-task-select .ant-select-selection-item')?.textContent).toBe('TASK-2 · 测试企业二'))
    expect((input as HTMLTextAreaElement).value).toBe('')
    expect(assistantApi.createSession).not.toHaveBeenCalled()
    expect(collaborationApi.streamMessage).not.toHaveBeenCalled()
  })

  it('does not carry an unsent question into another historical task session', async () => {
    const otherTaskSession = { ...session, id: 9, title: 'TASK-2 复核', task_code: 'TASK-2' }
    vi.mocked(assistantApi.sessions).mockResolvedValue([otherTaskSession])
    vi.mocked(assistantApi.session).mockResolvedValue({ ...otherTaskSession, messages: [] })
    vi.mocked(assistantApi.tasks).mockResolvedValue([
      { id: 1, task_code: 'TASK-1', borrower: '测试企业一', status: 'created' },
      { id: 2, task_code: 'TASK-2', borrower: '测试企业二', status: 'created' },
    ])
    mount('/assistant?task_code=TASK-1')
    const input = await screen.findByPlaceholderText(/输入问题|询问此任务/)
    await waitFor(() => expect((input as HTMLTextAreaElement).disabled).toBe(false))
    fireEvent.change(input, { target: { value: '只适用于任务一的复核问题' } })

    fireEvent.click((await screen.findByText('TASK-2 复核')).closest('li')!)
    await screen.findAllByText('当前草稿尚未发送', { exact: true })
    fireEvent.click(screen.getByText('继续编辑', { exact: true }))
    expect((input as HTMLTextAreaElement).value).toBe('只适用于任务一的复核问题')

    fireEvent.click((await screen.findByText('TASK-2 复核')).closest('li')!)
    await screen.findAllByText('当前草稿尚未发送', { exact: true })
    fireEvent.click(screen.getByText('清空并切换', { exact: true }))
    await waitFor(() => expect(assistantApi.session).toHaveBeenCalledWith(9))
    await waitFor(() => expect(document.querySelector('.hy-task-select .ant-select-selection-item')?.textContent).toBe('TASK-2 · 测试企业二'))
    expect((input as HTMLTextAreaElement).value).toBe('')
    expect(collaborationApi.streamMessage).not.toHaveBeenCalled()
  })

  it('preserves the draft and skill when canceling deletion, then clears them after deleting the active session', async () => {
    vi.mocked(assistantApi.sessions).mockResolvedValue([session])
    vi.mocked(assistantApi.session).mockResolvedValue({ ...session, messages: [final] })
    vi.mocked(assistantApi.deleteSession).mockResolvedValue({ deleted: true })
    mount('/assistant?session_id=7')
    await screen.findByText('模型服务就绪')

    fireEvent.click(screen.getByRole('button', { name: '业务技能' }))
    fireEvent.click(await screen.findByRole('button', { name: '选择风险梳理' }))
    const input = screen.getByRole('textbox') as HTMLTextAreaElement
    fireEvent.change(input, { target: { value: '只属于当前会话的未发送问题' } })
    await screen.findByText(/本轮技能/)

    const activeItem = document.querySelector('.ant-conversations-item-active')!
    const menuTrigger = within(activeItem).getByRole('button', { name: /会话操作：/ })
    expect(menuTrigger.tagName).toBe('BUTTON')
    expect((menuTrigger as HTMLButtonElement).tabIndex).toBeGreaterThanOrEqual(0)
    fireEvent.click(menuTrigger)
    fireEvent.click(await screen.findByText('删除会话', { exact: true }))
    await screen.findAllByText('删除这段会话？', { exact: true })
    const firstConfirmation = document.querySelector('.ant-modal-confirm')!
    fireEvent.click(within(firstConfirmation).getByRole('button', { name: /取\s*消/ }))
    expect(input.value).toBe('只属于当前会话的未发送问题')
    expect(screen.getByText(/本轮技能/)).toBeTruthy()

    vi.mocked(assistantApi.deleteSession).mockRejectedValueOnce(new Error('删除失败'))
    fireEvent.click(menuTrigger)
    fireEvent.click(await screen.findByText('删除会话', { exact: true }))
    await screen.findAllByText('删除这段会话？', { exact: true })
    const secondConfirmation = document.querySelector('.ant-modal-confirm')!
    fireEvent.click(within(secondConfirmation).getByRole('button', { name: /删\s*除/ }))
    await screen.findByText('删除失败')
    expect(input.value).toBe('只属于当前会话的未发送问题')
    expect(screen.getByText(/本轮技能/)).toBeTruthy()

    fireEvent.click(menuTrigger)
    fireEvent.click(await screen.findByText('删除会话', { exact: true }))
    await screen.findAllByText('删除这段会话？', { exact: true })
    const finalConfirmation = document.querySelector('.ant-modal-confirm')!
    fireEvent.click(within(finalConfirmation).getByRole('button', { name: /删\s*除/ }))
    await waitFor(() => expect(assistantApi.deleteSession).toHaveBeenCalledWith(7))
    await waitFor(() => expect(input.value).toBe(''))
    expect(screen.queryByText(/本轮技能/)).toBeNull()
    expect(assistantApi.createSession).not.toHaveBeenCalled()
    expect(collaborationApi.streamMessage).not.toHaveBeenCalled()
  })

  it('resets member-only mode when switching to another shared conversation', async () => {
    const first = { ...session, title: '旧共享会话', shared: true, task_code: 'TASK-1' }
    const second = { ...session, id: 8, title: '新共享会话', shared: true, task_code: 'TASK-1' }
    vi.mocked(assistantApi.sessions).mockResolvedValue([first, second])
    vi.mocked(assistantApi.session).mockImplementation(async (id) => ({
      ...(id === first.id ? first : second), messages: [],
    }))
    vi.mocked(collaborationApi.streamMessage).mockImplementation(async function* (): AsyncGenerator<AssistantStreamEvent> {
      yield { event: 'message_end', message: final }
    })
    mount(`/assistant?session_id=${first.id}`)
    await screen.findByText('模型服务就绪')
    fireEvent.click(await screen.findByText('发给成员', { exact: true }))
    expect(document.querySelector('.ant-segmented-item-selected')?.textContent?.trim()).toBe('发给成员')

    fireEvent.click(screen.getByRole('list').querySelectorAll('.ant-conversations-item')[1])
    await waitFor(() => expect(assistantApi.session).toHaveBeenCalledWith(second.id))
    await waitFor(() => expect(document.querySelector('.ant-segmented-item-selected')?.textContent?.trim()).toBe('问 AI'))
    await send('只应发送给 AI')
    await waitFor(() => expect(collaborationApi.streamMessage).toHaveBeenCalledWith(
      second.id, '只应发送给 AI', 'TASK-1', undefined, expect.any(AbortSignal),
    ))
    expect(collaborationApi.discuss).not.toHaveBeenCalled()
  })

  it('clears a protected conversation draft and skill when directory access is revoked', async () => {
    const intervals: Array<{ delay: number; callback: () => void }> = []
    const setIntervalSpy = vi.spyOn(globalThis, 'setInterval').mockImplementation(((callback: TimerHandler, delay = 0) => {
      intervals.push({ delay, callback: callback as () => void })
      return intervals.length as unknown as ReturnType<typeof setInterval>
    }) as typeof setInterval)
    const clearIntervalSpy = vi.spyOn(globalThis, 'clearInterval').mockImplementation(() => undefined)
    vi.mocked(assistantApi.sessions).mockResolvedValue([session])
    vi.mocked(assistantApi.session).mockResolvedValue({ ...session, messages: [] })
    mount('/assistant?session_id=7')
    await act(async () => { await Promise.resolve(); await Promise.resolve() })

    fireEvent.click(screen.getByRole('button', { name: '业务技能' }))
    fireEvent.click(screen.getByRole('button', { name: '选择风险梳理' }))
    const input = screen.getByRole('textbox') as HTMLTextAreaElement
    fireEvent.change(input, { target: { value: '仅适用于已撤权会话的未发送问题' } })
    expect(screen.getByText(/本轮技能/)).toBeTruthy()

    vi.mocked(assistantApi.sessions).mockResolvedValue([])
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' })
    expect(intervals.map((interval) => interval.delay)).toContain(5000)
    await act(async () => {
      intervals.filter((interval) => interval.delay === 5000).at(-1)?.callback()
      await Promise.resolve()
    })
    try {
      await waitFor(() => expect(screen.getByText(/访问权限已变更/)).toBeTruthy())
      expect(input.value).toBe('')
      expect(screen.queryByText(/本轮技能/)).toBeNull()
      expect(collaborationApi.streamMessage).not.toHaveBeenCalled()
    } finally {
      cleanup()
      setIntervalSpy.mockRestore()
      clearIntervalSpy.mockRestore()
    }
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
    fireEvent.click(await screen.findByRole('button', { name: '选择风险梳理' }))
    await send('检查任务')
    await waitFor(() => expect(collaborationApi.streamMessage).toHaveBeenCalledWith(8, '检查任务', 'TASK-1', 'risk-review', expect.any(AbortSignal)))
    expect(screen.queryByText(/本轮技能/)).toBeNull()
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
