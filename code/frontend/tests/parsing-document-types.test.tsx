import { useState } from 'react'
import { App } from 'antd'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { DocumentTypeChoices, typeSelectionPayload, typeSelectionsValid, type TypeSelections } from '@/parsing/DocumentTypeChoices'
import CreateTaskView from '@/views/CreateTaskView'
import { DocumentClassificationHistory } from '@/parsing/DocumentClassificationHistory'
import { api } from '@/api'
import type { ParseResult } from '@/types'

vi.mock('react-router-dom', async original => ({ ...await original<object>(), useNavigate: () => vi.fn() }))
vi.mock('@/api', () => ({ api: { parseFiles: vi.fn(), resumeParsing: vi.fn(), createTask: vi.fn(), searchCustomers: vi.fn() } }))
vi.mock('@/components/PdfSourceViewer', () => ({ default: () => null }))
afterEach(() => { cleanup(); vi.clearAllMocks() })

const result: ParseResult = { suggested_task_code: 'test', suggested_borrower: 'test', suggested_currency: 'USD', suggested_amount: '100.01',
  status: 'needs_review', parse_run_id: 'a'.repeat(32), documents: [{ doc_code: 'UNKNOWN-01', type_code: 'UNKNOWN',
    type_label: '未识别类型', source_filename: '合同.pdf', fields: [], status: 'needs_review', issues: ['UNKNOWN_DOCUMENT_TYPE'] }] }

async function select(label: string, option: string) {
  fireEvent.mouseDown(screen.getByRole('combobox', { name: label }))
  // Ant retains the closed previous popup during its exit animation.
  const options = await screen.findAllByText(option, { selector: '.ant-select-item-option-content' })
  fireEvent.click(options[options.length - 1])
}

describe('文件类别选择与未知类型回退', () => {
  it('任务页可追溯经办人类别依据和原件，不把类别选择展示为通过', () => {
    const locate=vi.fn()
    render(<DocumentClassificationHistory documents={[{ id: 8, doc_code: 'INVOICE-01', type_code: 'PROFORMA_INVOICE', pdf_file: 'uploads/invoice.pdf',
      fields: { _parsing: { classification: { method: 'operator_selected', type_code: 'PROFORMA_INVOICE', reason: '原件标题PROFORMA RECHNUNG',
        selected_by: 7, selected_at: '2026-10-23T07:00:00+08:00' } } } }]} onLocate={locate} />)
    expect(screen.getByText('文件类别由经办人选择')).toBeTruthy()
    expect(screen.getByText('依据：原件标题PROFORMA RECHNUNG')).toBeTruthy()
    expect(screen.getByText('用户 7 · 2026-10-23T07:00:00+08:00')).toBeTruthy()
    expect(screen.getByText('该记录用于追溯文件分类，不代表识别字段或业务审核已通过。')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '查看分类依据原件 · INVOICE-01' }))
    expect(locate).toHaveBeenCalledWith(expect.objectContaining({ doc_id: 8, pdf_file: 'uploads/invoice.pdf', page: 1 }))
  })
  it('同名文件分别选类，删除前一份后不将依据套到剩余文件', async () => {
    const first = new File(['first'], 'same.pdf'), second = new File(['second'], 'same.pdf')
    const changed = vi.fn()
    function Harness() {
      const [files, setFiles] = useState([first, second])
      const [choices, setChoices] = useState<TypeSelections>(new Map())
      changed(typeSelectionPayload(files, choices))
      return <><DocumentTypeChoices files={files} choices={choices} onChange={setChoices} />
        <button onClick={() => setFiles([second])}>移除前份</button>
        <span>{typeSelectionsValid(choices) ? '依据已齐' : '依据未齐'}</span></>
    }
    render(<Harness />)
    await select('第1份文件类别', '提款指令')
    expect(screen.getByText('依据未齐')).toBeTruthy()
    fireEvent.change(screen.getByLabelText('第1份文件类别依据'), { target: { value: '提款申请标题' } })
    await select('第2份文件类别', '商业合同')
    fireEvent.change(screen.getByLabelText('第2份文件类别依据'), { target: { value: '销售合同标题' } })
    expect(changed.mock.lastCall?.[0]).toEqual([
      { type_code: 'DRAWDOWN_INSTRUCTION', reason: '提款申请标题' }, { type_code: 'COMMERCIAL_CONTRACT', reason: '销售合同标题' },
    ])
    fireEvent.click(screen.getByText('移除前份'))
    expect(changed.mock.lastCall?.[0]).toEqual([{ type_code: 'COMMERCIAL_CONTRACT', reason: '销售合同标题' }])
    expect((screen.getByLabelText('第1份文件类别依据') as HTMLInputElement).value).toBe('销售合同标题')
  })

  it('上传前必须填写类别依据，未知结果不能继续创建，可返回重新识别', async () => {
    vi.mocked(api.parseFiles).mockResolvedValue(result)
    const { container } = render(<App><CreateTaskView /></App>)
    const file = new File(['synthetic bytes'], '合同.pdf', { type: 'application/pdf' })
    fireEvent.change(container.querySelector('input[type="file"]')!, { target: { files: [file] } })
    await screen.findByRole('combobox', { name: '第1份文件类别' })
    await select('第1份文件类别', '商业合同')
    const parse = screen.getByRole('button', { name: /先逐项复核再创建/ }) as HTMLButtonElement
    expect(parse.disabled).toBe(true)
    fireEvent.change(screen.getByLabelText('第1份文件类别依据'), { target: { value: '原件Sales Contract标题' } })
    expect(parse.disabled).toBe(false)
    fireEvent.click(parse)
    await screen.findByRole('button', { name: '返回选择文件类别' })
    expect(api.parseFiles).toHaveBeenCalledWith([file], expect.any(Function), expect.any(Function),
      [{ type_code: 'COMMERCIAL_CONTRACT', reason: '原件Sales Contract标题' }])
    expect((screen.getByRole('button', { name: /下一步：确认/ }) as HTMLButtonElement).disabled).toBe(true)
    expect(api.createTask).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: '返回选择文件类别' }))
    expect((await screen.findByLabelText('第1份文件类别依据') as HTMLInputElement).value).toBe('原件Sales Contract标题')
    expect(screen.queryByText('未识别(可在下一步调整)')).toBeNull()
  })
})
