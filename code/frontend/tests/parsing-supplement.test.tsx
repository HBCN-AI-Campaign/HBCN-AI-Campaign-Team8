import { App } from 'antd'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import SupplementDocuments from '@/business-review/SupplementDocuments'
import { api } from '@/api'
import type { ParseResult } from '@/types'

vi.mock('../src/api', () => ({ api: { parseFiles: vi.fn() } }))
afterEach(() => { cleanup(); vi.clearAllMocks() })

const clause = 'Interest agreed by the Lender. Next page continuation.'
const value = { facility_name: 'Import Facilities', clause_heading: 'Interest', clause_text: clause }
const source = { block_id: 'p31b0', page: 31, bbox: [.1, .1, .9, .2], text: clause, method: 'paddle_http', score: .99 }
const parsed: ParseResult = {
  suggested_task_code: '', suggested_borrower: '', suggested_currency: '', suggested_amount: null,
  parse_run_id: 'new-receipt', documents: [{ doc_code: 'FACILITY_LETTER-01', type_code: 'FACILITY_LETTER',
    type_label: '授信函', source_filename: '补充授信函.pdf', pdf_file: 'uploads/new/fol.pdf', fields: [{
      key: 'facility_terms', label: '逐授信附表条款', value: null, kind: 'json', status: 'needs_review', confidence: 0,
      row_results: [{ value, status: 'needs_review', issues: ['TERMS_PAGE_INCOMPLETE'], cells: {
        clause_text: { value: clause, raw_value: clause, issues: [], sources: [source] },
      } }],
    }] }],
}

async function chooseAndParse(container: HTMLElement) {
  const file = new File(['local synthetic PDF'], '补充授信函.pdf', { type: 'application/pdf' })
  fireEvent.change(container.querySelector('input[type="file"]')!, { target: { files: [file] } })
  await waitFor(() => expect((screen.getByRole('button', { name: '识别补充文件' }) as HTMLButtonElement).disabled).toBe(false))
  fireEvent.click(screen.getByRole('button', { name: '识别补充文件' }))
}

describe('补件复用解析证据与新回执', () => {
  it('补件中已识别值更正后须填写说明，原值恢复和新回执不沿用更正状态', async () => {
    const accepted: ParseResult = { ...parsed, documents: [{ ...parsed.documents[0], fields: [
      { key: 'amount', label: '金额', value: '12000000.00', kind: 'currency', status: 'accepted', confidence: .99 },
    ] }] }
    vi.mocked(api.parseFiles).mockResolvedValue(accepted)
    const onChange = vi.fn(), onBusy = vi.fn()
    const view = render(<App><SupplementDocuments code="CASE" existing={[]} disabled={false}
      onChange={onChange} onBusy={onBusy} onSource={vi.fn()} /></App>)
    await chooseAndParse(view.container)
    fireEvent.click(await screen.findByText('补充授信函.pdf · 授信函'))
    const input = screen.getByLabelText('金额')
    fireEvent.change(input, { target: { value: '12000000.01' } })
    await waitFor(() => expect(onBusy).toHaveBeenLastCalledWith(true))
    expect(screen.getByText('已更正，待填写说明')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '恢复金额识别值' }))
    await waitFor(() => expect(onBusy).toHaveBeenLastCalledWith(false))
    expect(onChange.mock.lastCall?.[0][0].fields.amount).toBe('12000000.00')
    fireEvent.change(input, { target: { value: '12000000.01' } })
    fireEvent.change(screen.getByLabelText('金额核实说明'), { target: { value: '对照新原件更正末位' } })
    await waitFor(() => expect(onBusy).toHaveBeenLastCalledWith(false))
    expect(onChange.mock.lastCall?.[0][0]).toMatchObject({ fields: { amount: '12000000.01' }, field_confirmations: { amount: '对照新原件更正末位' } })
    expect(accepted.documents[0].fields[0]).toMatchObject({ value: '12000000.00', status: 'accepted' })
    vi.mocked(api.parseFiles).mockResolvedValue({ ...accepted, parse_run_id: 'next-receipt' })
    fireEvent.click(screen.getByRole('button', { name: '识别补充文件' }))
    await waitFor(() => expect(onChange.mock.lastCall?.[0][0]?.parse_run_id).toBe('next-receipt'))
    expect(onChange.mock.lastCall?.[0][0].field_confirmations).toEqual({})
    expect(onChange.mock.lastCall?.[0][0].fields).toEqual({ amount: '12000000.00' })
    expect(onBusy).toHaveBeenLastCalledWith(false)
  })

  it('显示完整授信条款和跨页来源，载入候选后仍需单独核实', async () => {
    vi.mocked(api.parseFiles).mockResolvedValue(parsed)
    const onChange = vi.fn(), onSource = vi.fn()
    const view = render(<App><SupplementDocuments code="CASE" existing={[]} disabled={false}
      onChange={onChange} onBusy={vi.fn()} onSource={onSource} /></App>)
    await chooseAndParse(view.container)
    fireEvent.click(await screen.findByText('补充授信函.pdf · 授信函'))
    fireEvent.click(await screen.findByText('逐格原文与候选明细（1行）'))
    expect(screen.getByText(clause)).toBeTruthy()
    expect(screen.getByText('原图与条款范围尚未完整核对')).toBeTruthy()
    expect(screen.queryByRole('columnheader', { name: '货品' })).toBeNull()
    fireEvent.click(screen.getByLabelText('逐授信附表条款完整条款原文第31页原文'))
    expect(onSource).toHaveBeenCalledWith({ page: 31, bbox: source.bbox, doc_code: 'FACILITY_LETTER-01', pdf_file: 'uploads/new/fol.pdf' })
    fireEvent.click(screen.getByText('载入候选明细，逐行核实'))
    await waitFor(() => expect(onChange.mock.lastCall?.[0][0].fields.facility_terms).toEqual([value]))
    expect(onChange.mock.lastCall?.[0][0].field_confirmations).toEqual({})
    const body = screen.getByLabelText('逐授信附表条款第1行完整条款原文') as HTMLTextAreaElement
    expect(body.value).toBe(clause)
    fireEvent.change(screen.getByLabelText('逐授信附表条款核实说明'), { target: { value: '仅为隔离测试：本轮对照新原件确认条款' } })
    await waitFor(() => expect(onChange.mock.lastCall?.[0][0].field_confirmations.facility_terms).toContain('本轮'))

    // Same document code and field key under a new receipt must start clean.
    vi.mocked(api.parseFiles).mockResolvedValue({ ...parsed, parse_run_id: 'next-receipt',
      documents: parsed.documents.map(d => ({ ...d, pdf_file: 'uploads/next/fol.pdf' })) })
    fireEvent.click(screen.getByRole('button', { name: '识别补充文件' }))
    await waitFor(() => expect(onChange.mock.lastCall?.[0][0]?.parse_run_id).toBe('next-receipt'))
    expect(onChange.mock.lastCall?.[0][0].fields.facility_terms).toBeNull()
    expect(onChange.mock.lastCall?.[0][0].field_confirmations).toEqual({})
    fireEvent.click(screen.getByText('补充授信函.pdf · 授信函'))
    expect((screen.getByLabelText('逐授信附表条款核实说明') as HTMLInputElement).value).toBe('')
    expect(screen.queryByLabelText('逐授信附表条款第1行完整条款原文')).toBeNull()
  }) // Use the project's shared 60s jsdom/Ant Design budget.

  it('换选文件后忽略旧文件迟到的解析结果', async () => {
    let finish!: (r: ParseResult) => void
    vi.mocked(api.parseFiles).mockReturnValue(new Promise(resolve => { finish = resolve }))
    const onChange = vi.fn(), onBusy = vi.fn()
    const view = render(<App><SupplementDocuments code="CASE" existing={[]} disabled={false}
      onChange={onChange} onBusy={onBusy} onSource={vi.fn()} /></App>)
    await chooseAndParse(view.container)
    await waitFor(() => expect(api.parseFiles).toHaveBeenCalledOnce())
    fireEvent.change(view.container.querySelector('input[type="file"]')!, {
      target: { files: [new File(['different PDF'], '另一份授信函.pdf', { type: 'application/pdf' })] },
    })
    await act(async () => finish(parsed))
    expect(onChange).toHaveBeenLastCalledWith([])
    expect(onBusy).toHaveBeenLastCalledWith(true)
    expect(screen.queryByText('补充授信函.pdf · 授信函')).toBeNull()
  })
})
