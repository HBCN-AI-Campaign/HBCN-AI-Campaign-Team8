import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { App } from 'antd'
import { FacilityContextPanel } from '@/parsing/FacilityContextPanel'
import { FacilityContextHistory } from '@/parsing/FacilityContextHistory'
import CreateTaskView from '@/views/CreateTaskView'
import { api } from '@/api'
import type { FacilityContext, FacilityRecord, ParseResult } from '@/types'

vi.mock('react-router-dom', async original => ({ ...await original<object>(), useNavigate: () => vi.fn() }))
vi.mock('@/api', () => ({ api: { resumeParsing: vi.fn(), checkFacilityContext: vi.fn(), searchCustomers: vi.fn() } }))
vi.mock('@/components/PdfSourceViewer', () => ({ default: () => null }))
afterEach(() => { cleanup(); vi.clearAllMocks() })

const legalId = 'a'.repeat(64), allocationId = 'b'.repeat(64)
const legal: FacilityRecord = { id: legalId, doc_code: 'FOL-01', field_key: 'borrowers', row_index: 0,
  status: 'accepted', issues: [], value: { name: 'Alpha Legal', short_name: 'ALPHA' }, cells: {} }
const allocation: FacilityRecord = { id: allocationId, doc_code: 'FOL-01', field_key: 'borrower_allocations', row_index: 0,
  status: 'accepted', issues: [], value: { borrower_name: 'ALPHA', facility_name: 'Revolving Loan', amount: '1000.01', currency: 'USD' },
  borrower_ids: [legalId], cells: { amount: { value: '1000.01', raw_value: 'USD 1,000.01', issues: [], sources: [{
    block_id: 'p8-b1', page: 8, bbox: [.2, .3, .5, .4], text: 'USD 1,000.01', method: 'synthetic', score: 1,
  }] } } }
const context: FacilityContext = { status: 'needs_review', issues: [{ code: 'CROSS_CURRENCY_COMPARISON', message: 'CNY与USD不同，暂不直接比较。' }],
  request: { borrower: { value: null, doc_code: 'DD-01' }, amount: { value: '1200.00', doc_code: 'DD-01', source: { page: 1, bbox: [.1, .2, .3, .4] } } },
  borrowers: [legal], allocations: [allocation], selected_borrower_id: null, selected_allocation_id: null,
  association_method: null, nominal_limit: { amount: '1000.01', currency: 'USD', facility_name: 'Revolving Loan', doc_code: 'FOL-01' }, comparison: null, available_balance: null }

describe('提款与FOL关联核实', () => {
  it('审核员可查看提交时依据并定位金额，旧记录明确为历史且不替代当前结论', async () => {
    const locate = vi.fn()
    render(<FacilityContextHistory documents={[{ id: 8, doc_code: 'FOL-01', type_code: 'FACILITY_LETTER', pdf_file: 'uploads/test.pdf', fields: {
      _parsing: { facility_context: { ...context, selected_borrower_id: legalId, selected_allocation_id: allocationId,
        association_method: 'human_confirmed', selection: { borrower_id: legalId, allocation_id: allocationId, reason: '核对两份原件中的授信对应关系' },
        confirmed_by: 7, confirmed_at: '2026-10-23T03:00:00Z' } },
    } }]} needsRecheck={true} onLocate={locate} />)
    fireEvent.click(screen.getByText('提交时授信关联核实记录 · FOL-01'))
    expect(await screen.findByText('核对两份原件中的授信对应关系')).toBeTruthy()
    expect(screen.getByText('任务字段已修改，旧关联不能作为本次结论，请重新核实。')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '分配金额 · 第8页原文' }))
    expect(locate).toHaveBeenCalledWith(expect.objectContaining({ doc_id: 8, page: 8, pdf_file: 'uploads/test.pdf' }))
  })
  it('保留原件字段缺失及跨币种未决，不把名义限额当作余额', () => {
    const locate = vi.fn()
    render(<FacilityContextPanel context={context} selection={null} dirty={false} checking={false}
      onSelect={vi.fn()} onCheck={vi.fn()} onLocate={locate} />)
    expect(screen.getByText('CNY与USD不同，暂不直接比较。')).toBeTruthy()
    expect(screen.getByText(/实际可用余额：待核实/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '第1页原文' }))
    expect(locate).toHaveBeenCalledWith('DD-01', { page: 1, bbox: [.1, .2, .3, .4] })
  })

  it('选择候选及依据仅形成待服务器核对的关联，不自动改原件字段或清除问题', async () => {
    const select = vi.fn(), check = vi.fn(), locate = vi.fn()
    render(<FacilityContextPanel context={context} selection={null} dirty={true} checking={false}
      onSelect={select} onCheck={check} onLocate={locate} />)
    fireEvent.mouseDown(screen.getByRole('combobox', { name: 'FOL法定借款人关联' }))
    fireEvent.click(await screen.findByText('FOL-01 · Alpha Legal（ALPHA）'))
    fireEvent.mouseDown(screen.getByRole('combobox', { name: 'FOL主体授信分配关联' }))
    fireEvent.click(await screen.findByText('Revolving Loan · 1000.01 USD'))
    fireEvent.change(screen.getByLabelText('授信关联核实依据'), { target: { value: '对照FOL第8页与提款指令，仍需核实币种' } })
    expect(select).toHaveBeenLastCalledWith({ borrower_id: legalId, allocation_id: allocationId, reason: '对照FOL第8页与提款指令，仍需核实币种' })
    fireEvent.click(screen.getByRole('button', { name: '分配金额 · 第8页' }))
    expect(locate).toHaveBeenCalledWith('FOL-01', { page: 8, bbox: [.2, .3, .5, .4] })
    expect(screen.getByText('CNY与USD不同，暂不直接比较。')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '重新核对授信关联' }))
    expect(check).toHaveBeenCalledTimes(1)
  })

  it('任务信息改变后保留脏状态，忽略修改前请求的迟到结果', async () => {
    let complete!: (result: FacilityContext) => void
    vi.mocked(api.checkFacilityContext).mockReturnValue(new Promise(resolve => { complete = resolve }))
    const ready = { ...context, status: 'ready' as const, issues: [] }
    const result: ParseResult = { suggested_task_code: 'preview', suggested_borrower: 'Alpha Legal', suggested_currency: 'USD', suggested_amount: '1000.00',
      parse_run_id: 'c'.repeat(32), facility_context: ready, documents: [{ doc_code: 'FOL-01', type_code: 'FACILITY_LETTER', type_label: 'FOL', source_filename: 'FOL.pdf', fields: [
        { key: 'date', label: '授信函日期', kind: 'text', value: '2026-01-01', status: 'accepted', confidence: .99 },
      ] }] }
    vi.mocked(api.resumeParsing).mockResolvedValue(result)
    render(<App><CreateTaskView /></App>)
    fireEvent.change(screen.getByLabelText('解析编号'), { target: { value: 'c'.repeat(32) } })
    fireEvent.click(screen.getByRole('button', { name: '恢复解析结果' }))
    await screen.findByLabelText('任务借款人')
    fireEvent.click(screen.getByRole('button', { name: '重新核对授信关联' }))
    await waitFor(() => expect(api.checkFacilityContext).toHaveBeenCalledTimes(1))
    fireEvent.change(screen.getByLabelText('任务借款人'), { target: { value: '不同主体' } })
    complete(ready)
    await waitFor(() => expect(screen.getByText(/字段或关联已修改/)).toBeTruthy())
    const next = screen.getByRole('button', { name: 'check 下一步：确认' }) as HTMLButtonElement
    expect(next.disabled).toBe(false)
    fireEvent.click(next)
    expect(await screen.findByText('授信关联仍待核实')).toBeTruthy()
  })
})
