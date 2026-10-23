import { fireEvent, render, screen, cleanup } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { FieldEvidenceEditor } from '@/parsing/FieldEvidenceEditor'
import { RowEvidenceTable } from '@/parsing/RowEvidenceTable'
import { FieldRowsEditor } from '@/parsing/FieldRowsEditor'
import type { ParsedField } from '@/types'

afterEach(cleanup)
const amount: ParsedField = { key: 'amount', label: '金额', value: '9007199254740993.01',
  kind: 'currency', confidence: 0, status: 'conflict', required: true,
  candidates: [{ raw_value: '123.45', reason: '与另一页金额不同' }] }

describe('字段核实', () => {
  it('恢复原识别值保留金额原串并清除未提交说明', () => {
    const change = vi.fn(), confirm = vi.fn()
    const machine: ParsedField = { ...amount, value: '90071992547409.90', status: 'accepted' }
    render(<FieldEvidenceEditor machineField={machine} field={{ ...machine, value: '90071992547409.91', confirmation_reason: '未提交更正' }}
      onChange={change} onConfirm={confirm} />)
    expect(screen.getByText('核实说明已填写')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '恢复金额识别值' }))
    expect(change).toHaveBeenCalledWith('90071992547409.90')
    expect(confirm).toHaveBeenCalledWith('')
    expect(machine.value).toBe('90071992547409.90')
  })

  it('编号依据不完整须核实，已完成局部复核的旧候选不继续显示警告', () => {
    const props = { onChange: vi.fn(), onConfirm: vi.fn() }
    const partial = { raw_value: 'PI-123', issues: ['IDENTIFIER_SOURCE_INCOMPLETE'] }
    const field: ParsedField = { ...amount, key: 'contract_no', label: '合同号', kind: 'text', value: null,
      candidates: [partial, { raw_value: 'PI-123-CONTRACT', issues: [] }] }
    const view = render(<FieldEvidenceEditor {...props} field={field} />)
    expect(screen.getByText('当前候选缺少完整的合同号原文依据，请对照原件核实。')).toBeTruthy()
    expect(screen.getByText('候选冲突')).toBeTruthy()
    expect(props.onConfirm).not.toHaveBeenCalled()
    view.rerender(<FieldEvidenceEditor {...props} field={{ ...field, value: 'PI-123', status: 'accepted',
      candidates: [{ ...partial, superseded: true }, { raw_value: 'PI-123', verification: 'blind_region_pixels',
        issues: [], pixel_evidence: { anchor_text: 'PI-123Currency: USD' } }] }} />)
    expect(screen.queryByText(/当前候选缺少完整的/)).toBeNull()
    expect(screen.getByText('局部图像纠错')).toBeTruthy()
  })
  it('多页发票显示原件行号与跨页描述，错行候选须核实', () => {
    const locate = vi.fn()
    const source = { block_id: 'p1b0', page: 1, bbox: [.1, .2, .2, .3], text: '13', method: 'paddle_http', score: .99 }
    const next = { ...source, block_id: 'p2b0', page: 2, text: '(Stil: W-DR-02)' }
    render(<RowEvidenceTable field={{ ...amount, key: 'line_items', label: '货物明细', kind: 'json', value: null,
      row_results: [{ value: { line_no: '13', description: 'Kleid (Stil: W-DR-02)' }, status: 'needs_review',
        issues: ['INVOICE_ROW_ALIGNMENT_UNPROVEN'], cells: {
          line_no: { value: '13', raw_value: '13', issues: [], sources: [source] },
          description: { value: 'Kleid (Stil: W-DR-02)', raw_value: 'Kleid (Stil: W-DR-02)', issues: [], sources: [source, next] },
        } }] }} onLocate={locate} />)
    expect(screen.getByRole('columnheader', { name: '原件行号' })).toBeTruthy()
    expect(screen.getByText('行号、数量、单价和金额的行对应待核实')).toBeTruthy()
    fireEvent.click(screen.getByLabelText('货物明细货物描述第2页原文'))
    expect(locate).toHaveBeenCalledWith({ page: 2, bbox: source.bbox })
  })
  it('逐授信完整条款使用多行文本，保留限制条件且不出现技术列', () => {
    const change = vi.fn()
    const row = { facility_name: 'Revolving Loan', clause_heading: 'Purpose',
      clause_text: 'Working capital; repayment only if agreed by the Lender.', block_ids: ['p28b5'] }
    render(<FieldRowsEditor fieldKey="facility_terms" label="逐授信附表条款" value={[row]} onChange={change} />)
    const input = screen.getByLabelText('逐授信附表条款第1行完整条款原文') as HTMLTextAreaElement
    expect(input.tagName).toBe('TEXTAREA')
    expect(input.value).toContain('only if agreed by the Lender')
    fireEvent.change(input, { target: { value: `${row.clause_text}\nNext page continuation.` } })
    expect(change.mock.lastCall?.[0][0].clause_text).toContain('\nNext page continuation.')
    expect(screen.queryByRole('columnheader', { name: 'block_ids' })).toBeNull()
  })
  it('条款详情完整显示条件和跨页来源，范围未核实仍展示警告', () => {
    const locate = vi.fn()
    const clause = 'Rate agreed by the Lender. Next page continuation.'
    const source = { block_id: 'p31b0', page: 31, bbox: [.1, .1, .9, .2], text: clause, method: 'paddle_http', score: .99 }
    render(<RowEvidenceTable field={{ ...amount, key: 'facility_terms', label: '逐授信附表条款', kind: 'json', value: null,
      issues: ['TERMS_MARGIN_REVIEW_REQUIRED'], margin_blocks: [{ ...source, text: '?' }],
      row_results: [{ value: { facility_name: 'Import Facilities', clause_heading: 'Interest', clause_text: clause },
        status: 'needs_review', issues: ['TERMS_PAGE_INCOMPLETE'], cells: {
          clause_text: { value: clause, raw_value: clause, issues: [], sources: [source] },
        } }] }} onAdopt={vi.fn()} onLocate={locate} />)
    expect(screen.getByText(clause)).toBeTruthy()
    expect(screen.getByText(/附表底部有未归类标记/)).toBeTruthy()
    expect(screen.getByText('原图与条款范围尚未完整核对')).toBeTruthy()
    fireEvent.click(screen.getByLabelText('逐授信附表条款完整条款原文第31页原文'))
    expect(locate).toHaveBeenCalledWith({ page: 31, bbox: source.bbox })
  })
  it('图像纠错显式区分保留的OCR原文与局部转录', () => {
    render(<FieldEvidenceEditor field={{ ...amount, status: 'accepted', candidates: [{
      verification: 'blind_region_pixels', raw_value: '440,593.46', issues: [],
      pixel_evidence: { anchor_text: '440,593.4b' },
    }] }} onChange={vi.fn()} onConfirm={vi.fn()} />)
    expect(screen.getByText('局部图像纠错')).toBeTruthy()
    fireEvent.click(screen.getByText('原始候选与依据（1）'))
    expect(screen.getByText(/OCR原文：440,593.4b/)).toBeTruthy()
    expect(screen.getByText('440,593.46')).toBeTruthy()
  })
  it('金额保持精确字符串，展示冲突和核实说明', () => {
    const confirm = vi.fn()
    render(<FieldEvidenceEditor field={amount} onChange={vi.fn()} onConfirm={confirm} />)
    expect((screen.getByLabelText('金额') as HTMLInputElement).value).toBe('9007199254740993.01')
    expect(screen.getByText('候选冲突')).toBeTruthy()
    fireEvent.change(screen.getByLabelText('金额核实说明'), { target: { value: '已核实原件第1页' } })
    expect(confirm).toHaveBeenCalledWith('已核实原件第1页')
  })

  it('表格输入损坏时清空提交值，不能沿用上一次有效结果', () => {
    const change = vi.fn()
    render(<FieldEvidenceEditor field={{ ...amount, kind: 'json', label: '货物明细', value: [{ amount: '123.45' }] }} onChange={change} onConfirm={vi.fn()} />)
    fireEvent.change(screen.getByLabelText('货物明细明细'), { target: { value: '[broken' } })
    expect(change).toHaveBeenLastCalledWith(null)
    expect(screen.getByText(/明细格式有误/)).toBeTruthy()
  })

  it('未识别金额保持空白', () => {
    render(<FieldEvidenceEditor field={{ ...amount, value: null, status: 'missing' }} onChange={vi.fn()} onConfirm={vi.fn()} />)
    expect((screen.getByLabelText('金额') as HTMLInputElement).value).toBe('')
    expect(screen.getByText('未识别到')).toBeTruthy()
  })

  it('货物表格按业务列编辑精确金额，保留机器行的证据', () => {
    const change = vi.fn()
    const row = { description: '钢卷', amount: '9007199254740993.01', block_ids: ['p1b0'] }
    render(<FieldEvidenceEditor field={{ ...amount, key: 'line_items', kind: 'json', label: '货物明细', value: [row] }} onChange={change} onConfirm={vi.fn()} />)
    const input = screen.getByLabelText('货物明细第1行金额')
    expect((input as HTMLInputElement).value).toBe('9007199254740993.01')
    fireEvent.change(input, { target: { value: '440593.46' } })
    expect(change).toHaveBeenLastCalledWith([{ ...row, amount: '440593.46' }])
    expect(screen.queryByRole('columnheader', { name: 'block_ids' })).toBeNull()
  })

  it('跨页候选逐格定位，载入不触发人工确认，也不把证据作为编辑列', () => {
    const change = vi.fn(), confirm = vi.fn(), locate = vi.fn()
    const value = { facility_name: 'Revolving Loan', borrower_name: 'Borrower A', amount: '1000000', currency: 'USD',
      cell_sources: { amount: { raw_value: 'USD1,000,000', block_ids: ['p8b3'] } } }
    const source = { block_id: 'p8b3', page: 8, bbox: [.7, .2, .9, .3], text: 'USD1,000,000', method: 'paddle_http', score: .99 }
    const field: ParsedField = { ...amount, key: 'borrower_allocations', label: '借款人授信分配', kind: 'json', value: null,
      row_results: [{ value, status: 'needs_review', issues: ['ALLOCATION_ROW_ALIGNMENT_UNPROVEN'],
        cells: { amount: { value: '1000000', raw_value: 'USD1,000,000', issues: [], sources: [source] } } }] }
    render(<FieldEvidenceEditor field={field} onChange={change} onConfirm={confirm} onLocate={locate} />)
    expect(change).not.toHaveBeenCalled()
    fireEvent.click(screen.getByText('逐格原文与候选明细（1行）'))
    expect(screen.getByText('借款人与金额的行对应待核实')).toBeTruthy()
    fireEvent.click(screen.getByLabelText('借款人授信分配金额第8页原文'))
    expect(locate).toHaveBeenCalledWith({ page: 8, bbox: source.bbox })
    fireEvent.click(screen.getByText('载入候选明细，逐行核实'))
    expect(change).toHaveBeenCalledWith([value])
    expect(confirm).not.toHaveBeenCalled()
    expect(screen.queryByRole('columnheader', { name: 'cell_sources' })).toBeNull()
  })

  it('法定借款人区分英文名称、简称和中文名称', () => {
    render(<FieldEvidenceEditor field={{ ...amount, key: 'borrowers', label: '法定借款人清单', kind: 'json',
      value: [{ name: 'Alpha China Ltd', short_name: 'Alpha China', name_local: '甲有限公司' }] }} onChange={vi.fn()} onConfirm={vi.fn()} />)
    expect((screen.getByLabelText('法定借款人清单第1行名称') as HTMLInputElement).value).toBe('Alpha China Ltd')
    expect((screen.getByLabelText('法定借款人清单第1行原文简称') as HTMLInputElement).value).toBe('Alpha China')
    expect((screen.getByLabelText('法定借款人清单第1行中文法定名称') as HTMLInputElement).value).toBe('甲有限公司')
  })

  it('格式异常行仍显示借款人和原文，载入时不丢失而将非法金额留空', () => {
    const change = vi.fn()
    render(<RowEvidenceTable field={{ ...amount, key: 'borrower_allocations', label: '借款人授信分配', kind: 'json', value: null,
      row_results: [{ value: null, status: 'needs_review', issues: ['INVALID_ROW_SCHEMA'], cells: {
        facility_name: { value: 'Import Facilities', issues: [], sources: [] },
        borrower_name: { value: 'POS-QD', issues: [], sources: [] },
        amount: { value: ']0,000,000', raw_value: 'USD]0,000,000', issues: ['CELL_VALUE_SOURCE_MISMATCH'], sources: [] },
        currency: { value: 'USD', issues: [], sources: [] },
      } }] }} onAdopt={change} />)
    expect(screen.getByText('POS-QD')).toBeTruthy()
    expect(screen.getByText('原文：USD]0,000,000')).toBeTruthy()
    fireEvent.click(screen.getByText('载入候选明细，逐行核实'))
    expect(change).toHaveBeenCalledWith([{ facility_name: 'Import Facilities', borrower_name: 'POS-QD', amount: null, currency: 'USD' }])
    expect(screen.getByText(/其中 1 行格式不完整/)).toBeTruthy()
  })

  it('明细分页编辑和删除针对全表行号，不能误改第一页', () => {
    const change = vi.fn()
    const rows = Array.from({ length: 11 }, (_, i) => ({ facility_name: 'Loan', borrower_name: `Borrower ${i + 1}`, amount: String(i + 1), currency: 'USD' }))
    render(<FieldRowsEditor fieldKey="borrower_allocations" label="分配" value={rows} onChange={change} />)
    fireEvent.click(screen.getByTitle('2'))
    fireEvent.change(screen.getByLabelText('分配第11行金额'), { target: { value: '123.45' } })
    expect(change.mock.lastCall?.[0][0].amount).toBe('1')
    expect(change.mock.lastCall?.[0][10].amount).toBe('123.45')
    fireEvent.click(screen.getByText('移除此行'))
    expect(change.mock.lastCall?.[0]).toEqual(rows.slice(0, 10))
  })
})
