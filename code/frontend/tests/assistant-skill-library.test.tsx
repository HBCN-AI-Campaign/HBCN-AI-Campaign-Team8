import { App, ConfigProvider } from 'antd'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { SkillLibraryDrawer } from '@/assistant/SkillLibraryDrawer'
import { CollaborationApiError, collaborationApi } from '@/assistant/collaboration'
import type { LibrarySkill } from '@/assistant/collaboration'
import type { AssistantSkill } from '@/assistant/types'

vi.mock('@/assistant/collaboration', async (original) => {
  const module = await original<typeof import('@/assistant/collaboration')>()
  return { ...module, collaborationApi: {
    ...module.collaborationApi,
    library: vi.fn(), installSkill: vi.fn(), uninstallSkill: vi.fn(), createCustomSkill: vi.fn(),
    customSkill: vi.fn(), updateCustomSkill: vi.fn(), deleteCustomSkill: vi.fn(),
  } }
})

const builtin: LibrarySkill = {
  id: 'risk-review', name: '风险梳理', desc: '按证据和规则梳理风险', version: '1.0.0', owner: '项目审核组',
  license: 'Internal', permissions: ['read_authorized_evidence'], source: '项目审核目录', installed: false,
  update_available: false, is_custom: false, editable: false,
}
const personal: LibrarySkill = {
  id: 'private-7-a1b2c3d4e5', name: '贸易背景复核', desc: '对照合同和付款材料', version: '1.0.1', owner: '个人创建',
  license: 'User-defined', permissions: [], source: '个人技能 · 仅自己可见', installed: true,
  update_available: false, is_custom: true, editable: true, revision: 1,
}

function mount(options: { selectedSkillId?: string; skills?: AssistantSkill[] } = {}) {
  const onChoose = vi.fn()
  const onRefreshSkills = vi.fn().mockResolvedValue(options.skills || [builtin, personal])
  render(<ConfigProvider theme={{ token: { motion: false } }}><App>
    <SkillLibraryDrawer open disabled={false} selectedSkillId={options.selectedSkillId}
      onClose={vi.fn()} onChoose={onChoose} onRefreshSkills={onRefreshSkills} />
  </App></ConfigProvider>)
  return { onChoose, onRefreshSkills }
}

beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(collaborationApi.library).mockResolvedValue([builtin, personal])
  vi.mocked(collaborationApi.installSkill).mockResolvedValue({ installed: true })
  vi.mocked(collaborationApi.uninstallSkill).mockResolvedValue({ installed: false })
  vi.mocked(collaborationApi.createCustomSkill).mockResolvedValue({ ...personal })
  vi.mocked(collaborationApi.customSkill).mockResolvedValue({ ...personal, instructions: '原有指引：逐项列出差异。' })
  vi.mocked(collaborationApi.updateCustomSkill).mockResolvedValue({ ...personal, revision: 2 })
  vi.mocked(collaborationApi.deleteCustomSkill).mockResolvedValue({ deleted: true })
})

describe('reviewer skill-library journeys', () => {
  it('searches the project catalog, adds a skill, then applies it without sending immediately', async () => {
    const savedBuiltin = { ...builtin, installed: true }
    vi.mocked(collaborationApi.library).mockResolvedValueOnce([builtin, personal]).mockResolvedValue([savedBuiltin, personal])
    const { onChoose } = mount()
    await screen.findByText('贸易背景复核')
    fireEvent.click(screen.getByRole('tab', { name: /项目目录/ }))
    fireEvent.change(screen.getByPlaceholderText('搜索技能名称或说明'), { target: { value: '风险' } })
    expect(screen.getByText('风险梳理')).toBeTruthy()
    expect(screen.queryByText('贸易背景复核')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: '加入我的技能' }))
    await waitFor(() => expect(collaborationApi.installSkill).toHaveBeenCalledWith('risk-review'))
    fireEvent.change(screen.getByPlaceholderText('搜索技能名称或说明'), { target: { value: '' } })
    fireEvent.click(screen.getByRole('tab', { name: /我的技能/ }))
    fireEvent.click(screen.getAllByRole('button').find((button) => button.textContent?.includes('应用于下一问'))!)
    expect(onChoose).toHaveBeenCalledWith(expect.objectContaining({ id: 'risk-review' }))
  })

  it('creates and edits a personal instruction, loading existing text and revision first', async () => {
    mount()
    await screen.findByText('贸易背景复核')
    fireEvent.click(screen.getByRole('button', { name: /新建技能/ }))
    fireEvent.change(screen.getByLabelText('技能名称'), { target: { value: '付款主体核对' } })
    fireEvent.change(screen.getByLabelText('用途说明'), { target: { value: '比对收款主体' } })
    fireEvent.change(screen.getByLabelText('工作指引'), { target: { value: '比对合同、发票和收款账户。' } })
    fireEvent.click(screen.getByRole('button', { name: /保\s*存/ }))
    await waitFor(() => expect(collaborationApi.createCustomSkill).toHaveBeenCalledWith({
      name: '付款主体核对', desc: '比对收款主体', instructions: '比对合同、发票和收款账户。',
    }))

    fireEvent.click(await screen.findByRole('button', { name: /编辑/ }))
    const instruction = await screen.findByLabelText('工作指引') as HTMLTextAreaElement
    await waitFor(() => expect(instruction.value).toBe('原有指引：逐项列出差异。'))
    fireEvent.change(screen.getByLabelText('工作指引'), { target: { value: '先比对主体，再记录差异。' } })
    fireEvent.click(screen.getByRole('button', { name: /保\s*存/ }))
    await waitFor(() => expect(collaborationApi.updateCustomSkill).toHaveBeenCalledWith(
      personal.id, { name: personal.name, desc: personal.desc, instructions: '先比对主体，再记录差异。' }, 1,
    ))
  })

  it('closes an untouched edit without a discard warning', async () => {
    mount()
    await screen.findByText('贸易背景复核')
    fireEvent.click(await screen.findByRole('button', { name: /编辑/ }))
    await screen.findByLabelText('工作指引')
    fireEvent.click(screen.getByRole('button', { name: /^取\s*消$/ }))
    expect(screen.queryByText('放弃未保存的技能修改？')).toBeNull()
    await waitFor(() => expect(screen.queryByLabelText('工作指引')).toBeNull())
  })

  it('keeps a modified draft on continue and discards it only after confirmation', async () => {
    mount()
    await screen.findByText('贸易背景复核')
    fireEvent.click(await screen.findByRole('button', { name: /编辑/ }))
    const instruction = await screen.findByLabelText('工作指引') as HTMLTextAreaElement
    fireEvent.change(instruction, { target: { value: '保留这段尚未保存的指引。' } })
    fireEvent.click(screen.getByRole('button', { name: /^取\s*消$/ }))
    await screen.findAllByText('放弃未保存的技能修改？')
    fireEvent.click(screen.getByRole('button', { name: '继续编辑' }))
    expect(instruction.value).toBe('保留这段尚未保存的指引。')

    fireEvent.click(screen.getByRole('button', { name: /^取\s*消$/ }))
    await screen.findAllByText('放弃未保存的技能修改？')
    fireEvent.click(screen.getByRole('button', { name: '放弃修改' }))
    await waitFor(() => expect(screen.queryByLabelText('工作指引')).toBeNull())
  })

  it('prevents closing the editor while a save is still pending', async () => {
    let finishSave!: (skill: AssistantSkill) => void
    vi.mocked(collaborationApi.updateCustomSkill).mockReturnValueOnce(new Promise((resolve) => { finishSave = resolve }))
    mount()
    await screen.findByText('贸易背景复核')
    fireEvent.click(await screen.findByRole('button', { name: /编辑/ }))
    const instruction = await screen.findByLabelText('工作指引') as HTMLTextAreaElement
    fireEvent.change(instruction, { target: { value: '等待保存完成后再关闭。' } })

    const editor = screen.getByText('编辑个人技能').closest('.hy-skill-editor-modal') as HTMLElement
    const titleId = editor.getAttribute('aria-labelledby')
    expect(titleId && Array.from(editor.querySelectorAll('[id]')).some((element) => element.id === titleId && element.textContent === '编辑个人技能')).toBe(true)
    fireEvent.click(within(editor).getByRole('button', { name: /^保\s*存$/ }))
    await waitFor(() => expect(collaborationApi.updateCustomSkill).toHaveBeenCalled())
    expect((within(editor).getByRole('button', { name: /^取\s*消$/ }) as HTMLButtonElement).disabled).toBe(true)
    expect(within(editor).queryByRole('button', { name: 'Close' })).toBeNull()
    fireEvent.keyDown(document, { key: 'Escape', code: 'Escape', keyCode: 27 })
    fireEvent.click(document.querySelector('.ant-modal-wrap'))
    expect(screen.getByLabelText('工作指引')).toBeTruthy()

    finishSave({ ...personal, revision: 2 })
    await waitFor(() => expect(screen.queryByLabelText('工作指引')).toBeNull())
  })

  it('keeps the draft visible and advances the revision after an edit conflict', async () => {
    const original = { ...personal, instructions: '旧版指引。' }
    const latest = { ...personal, desc: '最新服务器说明', instructions: '最新服务器指引。', revision: 2 }
    vi.mocked(collaborationApi.customSkill).mockResolvedValueOnce({ ...original }).mockResolvedValueOnce({ ...latest })
    vi.mocked(collaborationApi.updateCustomSkill).mockRejectedValueOnce(new CollaborationApiError(409, 'revision conflict'))
    mount()

    await screen.findByText('贸易背景复核')
    fireEvent.click(await screen.findByRole('button', { name: /编辑/ }))
    const instruction = await screen.findByLabelText('工作指引') as HTMLTextAreaElement
    fireEvent.change(instruction, { target: { value: '本地修改，等待合并。' } })
    fireEvent.click(screen.getByRole('button', { name: /保\s*存/ }))

    await screen.findByText(/已被其他人更新/)
    expect(instruction.value).toBe('本地修改，等待合并。')
    expect(screen.getByText('最新服务器版本 · r2')).toBeTruthy()
    expect(screen.getByText('最新服务器指引。')).toBeTruthy()

    fireEvent.change(screen.getByLabelText('用途说明'), { target: { value: '最新服务器说明' } })
    fireEvent.change(instruction, { target: { value: '结合服务器最新版后的指引。' } })
    fireEvent.click(screen.getByRole('button', { name: /保\s*存/ }))
    await waitFor(() => expect(collaborationApi.updateCustomSkill).toHaveBeenLastCalledWith(
      personal.id,
      { name: personal.name, desc: '最新服务器说明', instructions: '结合服务器最新版后的指引。' },
      2,
    ))
  })

  it('requires delete confirmation and clears a deleted current skill', async () => {
    const { onChoose } = mount({ selectedSkillId: personal.id })
    await screen.findByText('贸易背景复核')
    fireEvent.click(screen.getByRole('button', { name: /删除/ }))
    expect(await screen.findByText('删除这项个人技能？')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /^取\s*消$/ }))
    expect(collaborationApi.deleteCustomSkill).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: /删除/ }))
    expect(await screen.findByText('删除这项个人技能？')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /^删\s*除$/ }))
    await waitFor(() => expect(collaborationApi.deleteCustomSkill).toHaveBeenCalledWith(personal.id))
    expect(onChoose).toHaveBeenCalledWith(undefined)
  })
})
