import { App } from 'antd'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import CreateTaskView from '@/views/CreateTaskView'
import { api } from '@/api'
import type { ParseResult } from '@/types'

const { navigate } = vi.hoisted(() => ({ navigate: vi.fn() }))
vi.mock('react-router-dom', async importOriginal => ({ ...await importOriginal<object>(), useNavigate: () => navigate }))
vi.mock('@/api', () => ({ api: { resumeParsing: vi.fn(), parseFiles: vi.fn(), createTask: vi.fn(), searchCustomers: vi.fn() } }))
vi.mock('@/components/PdfSourceViewer', () => ({ default: () => null }))
afterEach(() => { cleanup(); vi.clearAllMocks() })

const runId = '4a1b94290edf4c82b1d5fd2cf030f2e8'
const result: ParseResult = {
  suggested_task_code: 'preview', suggested_borrower: '隔离测试主体', suggested_currency: 'CNY',
  suggested_amount: '12000000.00', suggested_customer_no: 'TEST-8', suggested_customer_name: '测试客户',
  parse_run_id: runId, status: 'needs_review', documents: [{
    doc_code: 'WAYBILL-01', type_code: 'WAYBILL', type_label: '运单', source_filename: '运单.pdf',
    pdf_file: 'uploads/test/test.pdf', status: 'needs_review', fields: [
      { key: 'net_weight', label: '净重', kind: 'number', confidence: 0, value: null, status: 'needs_review' },
      { key: 'weight_unit', label: '重量单位', kind: 'text', confidence: 0, value: null, status: 'needs_review' },
    ],
  }],
}

describe('解析结果恢复', () => {
  it('更正已识别字段时先提示填写说明，恢复原值可撤销更正，未完成不能进入提交', async () => {
    const accepted: ParseResult = { ...result, documents: [{ ...result.documents[0], fields: [
      { key: 'net_weight', label: '净重', kind: 'number', confidence: .99, value: '89.85', status: 'accepted' },
    ] }] }
    vi.mocked(api.resumeParsing).mockResolvedValue(accepted)
    vi.mocked(api.createTask).mockResolvedValue({ task_code: '2026-CORRECTED' } as Awaited<ReturnType<typeof api.createTask>>)
    render(<App><CreateTaskView /></App>)
    fireEvent.change(screen.getByLabelText('解析编号'), { target: { value: runId } })
    fireEvent.click(screen.getByRole('button', { name: '恢复解析结果' }))
    const input = await screen.findByLabelText('净重')
    const next = screen.getByRole('button', { name: 'check 下一步：确认' }) as HTMLButtonElement
    fireEvent.change(input, { target: { value: '89.86' } })
    expect(next.disabled).toBe(true)
    expect(screen.getAllByText('已更正，待填写说明').length).toBeGreaterThan(0)
    expect(screen.queryByText('已识别')).toBeNull()
    expect(api.createTask).not.toHaveBeenCalled()
    fireEvent.change(input, { target: { value: '89.85' } })
    expect(next.disabled).toBe(false)
    fireEvent.change(input, { target: { value: '89.86' } })
    fireEvent.change(screen.getByLabelText('净重核实说明'), { target: { value: '对照原件第1页更正净重末位' } })
    expect(next.disabled).toBe(false)
    fireEvent.click(next)
    fireEvent.click(await screen.findByRole('button', { name: 'check-circle 保存字段并创建任务' }))
    await waitFor(() => expect(api.createTask).toHaveBeenCalledWith(expect.objectContaining({ documents: [expect.objectContaining({
      fields: { net_weight: '89.86' }, field_confirmations: { net_weight: '对照原件第1页更正净重末位' },
    })] })))
    expect(accepted.documents[0].fields[0]).toMatchObject({ value: '89.85', status: 'accepted' })
  })

  it('用原凭据恢复并提交人工核实，其他未决字段明确保留', async () => {
    vi.mocked(api.resumeParsing).mockResolvedValue({ ...result, suggested_amount: '90071992547409.93' })
    vi.mocked(api.createTask).mockResolvedValue({ task_code: '2026-TEST' } as Awaited<ReturnType<typeof api.createTask>>)
    render(<App><CreateTaskView /></App>)
    const resume = screen.getByRole('button', { name: '恢复解析结果' })
    expect((resume as HTMLButtonElement).disabled).toBe(true)
    fireEvent.change(screen.getByLabelText('解析编号'), { target: { value: runId } })
    fireEvent.click(resume)
    await screen.findByLabelText('净重')
    expect((screen.getByLabelText('任务提款金额') as HTMLInputElement).value).toBe('90071992547409.93')
    fireEvent.change(screen.getByLabelText('任务提款金额'), { target: { value: '90071992547409.95' } })
    expect(api.resumeParsing).toHaveBeenCalledWith(runId, expect.any(Function))
    fireEvent.change(screen.getByLabelText('净重'), { target: { value: '89.860' } })
    fireEvent.change(screen.getByLabelText('净重核实说明'), { target: { value: '对照原件第1页净重，单位仍待核实' } })
    fireEvent.click(screen.getByRole('button', { name: 'check 下一步：确认' }))
    await screen.findByText('仍有 1 项字段待核实')
    expect(screen.getByText('CNY 90,071,992,547,409.95', { exact: false })).toBeTruthy()
    expect(screen.queryByText('确认识别结果无误？')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'check-circle 创建待核实任务' }))
    await waitFor(() => expect(api.createTask).toHaveBeenCalledWith(expect.objectContaining({
      drawdown_amount: '90071992547409.95',
      documents: [expect.objectContaining({ parse_run_id: runId,
        fields: { net_weight: '89.86', weight_unit: null },
        field_confirmations: { net_weight: '对照原件第1页净重，单位仍待核实' },
      })],
    })))
    expect(navigate).toHaveBeenCalledWith('/tasks/2026-TEST')
  })

  it.each(['ready', 'needs_review'] as const)('上传快捷入口在%s状态保持原金额字符串', async status => {
    vi.mocked(api.parseFiles).mockResolvedValue({ ...result, suggested_amount: '90071992547409.93', status })
    vi.mocked(api.createTask).mockResolvedValue({ task_code: '2026-TEST' } as Awaited<ReturnType<typeof api.createTask>>)
    const { container } = render(<App><CreateTaskView /></App>)
    const chooser = container.querySelector('input[type="file"]') as HTMLInputElement
    fireEvent.change(chooser, { target: { files: [new File(['synthetic'], 'synthetic.pdf', { type: 'application/pdf' })] } })
    const upload = screen.getByRole('button', { name: /上传并创建任务/ })
    await waitFor(() => expect((upload as HTMLButtonElement).disabled).toBe(false))
    fireEvent.click(upload)
    if (status === 'ready') {
      await waitFor(() => expect(api.createTask).toHaveBeenCalledWith(expect.objectContaining({ drawdown_amount: '90071992547409.93' })))
    } else {
      const input = await screen.findByLabelText('任务提款金额') as HTMLInputElement
      expect(input.value).toBe('90071992547409.93')
      expect(api.createTask).not.toHaveBeenCalled()
    }
  })
})
