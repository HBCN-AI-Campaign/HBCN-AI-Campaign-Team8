import { App, ConfigProvider } from 'antd'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import BusinessReviewPanel from '@/views/task-object/BusinessReviewPanel'
import { api } from '@/api'
import type { BusinessReviewRun, FieldSource } from '@/types'

vi.mock('@/api', () => ({ api: {
  businessReview: vi.fn(),
  runBusinessReview: vi.fn(),
  resolveBusinessReview: vi.fn(),
  businessReviewAdvice: vi.fn(),
} }))

const base: BusinessReviewRun = {
  run_id: 1,
  task_code: 'TASK-1',
  status: 'needs_review',
  is_current: true,
  findings: [{
    finding_id: 'SUPPORTING__BUYER',
    tier: 'strong_rule',
    rule_id: 'SUPPORTING__BUYER',
    rule_name: '买方一致且等于借款人',
    dimension: 'C',
    status: 'needs_review',
    raw_status: 'warn',
    requires_resolution: true,
    why: 'V2 与字段梳理表口径存在冲突。',
    suggestion: '核对冲突原文并人工确认。',
    evidence: [
      ['FOL 借款人', '企业甲', ''],
      ['发票买方', '企业乙', 'bad', { doc_id: 8, doc_code: 'IV1', type_code: 'PROFORMA_INVOICE',
        field_key: 'buyer', pdf_file: 'uploads/test/invoice.pdf', page: 2, bbox: [0.1, 0.2, 0.4, 0.3] }],
    ],
    business_conflict: 'BUYER_BORROWER_RULE_CONFLICT',
  }],
  decision_model: { status: 'not_configured', threshold: 0.9 },
  advisories: {},
}

function mount(onLocate?: (source?: FieldSource | null) => void, canReview = true) {
  return render(<ConfigProvider><App><BusinessReviewPanel code="TASK-1" canReview={canReview} onLocate={onLocate} /></App></ConfigProvider>)
}

describe('business review panel', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(api.businessReview).mockResolvedValue(base)
    vi.mocked(api.resolveBusinessReview).mockImplementation(async (_code, _id, _action, reason) => ({
      ...base,
      status: 'ready_for_approval',
      findings: [{ ...base.findings[0], requires_resolution: false, resolution: {
        action: 'acknowledge', reason, actor_id: 2, actor_name: '审核人', recorded_at: '2026-10-23T00:00:00Z',
      } }],
    }))
  })

  it('shows source conflicts as human review and records the reviewer reason', async () => {
    const onLocate = vi.fn()
    mount(onLocate)
    expect(await screen.findByText('待人工核实')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /买方一致且等于借款人/ }))
    expect(screen.getByText('V2 与字段梳理表口径存在冲突。')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '定位原文' }))
    expect(onLocate).toHaveBeenCalledWith(expect.objectContaining({ field_key: 'buyer', page: 2 }))
    fireEvent.click(screen.getByRole('button', { name: /确认已核实/ }))
    fireEvent.change(screen.getByPlaceholderText('填写核实依据或例外审批理由'), { target: { value: '按原文核验完成' } })
    fireEvent.click(screen.getByRole('button', { name: '保存处置' }))
    await waitFor(() => expect(api.resolveBusinessReview).toHaveBeenCalledWith(
      'TASK-1', 'SUPPORTING__BUYER', 'acknowledge', '按原文核验完成',
    ))
    expect(await screen.findByText('审核人：按原文核验完成')).toBeTruthy()
  })

  it('keeps stale findings read-only while preserving the exact PDF locator', async () => {
    const onLocate = vi.fn()
    vi.mocked(api.businessReview).mockResolvedValue({ ...base, is_current: false })
    mount(onLocate)

    expect(await screen.findByText('材料已变更，结论失效')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /买方一致且等于借款人/ }))
    fireEvent.click(screen.getByRole('button', { name: '定位原文' }))

    expect(onLocate).toHaveBeenCalledWith({
      doc_id: 8,
      doc_code: 'IV1',
      type_code: 'PROFORMA_INVOICE',
      field_key: 'buyer',
      pdf_file: 'uploads/test/invoice.pdf',
      page: 2,
      bbox: [0.1, 0.2, 0.4, 0.3],
    })
    expect(screen.queryByRole('button', { name: '请求 AI 参考' })).toBeNull()
    expect(screen.queryByRole('button', { name: '确认已核实' })).toBeNull()
    expect(screen.queryByRole('button', { name: '登记人工例外' })).toBeNull()
  })

  it('keeps archived findings readable without review mutation controls', async () => {
    mount(undefined, false)

    expect(await screen.findByText('待人工核实')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /买方一致且等于借款人/ }))
    expect(screen.getByRole('button', { name: '定位原文' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: '重新运行审核' })).toBeNull()
    expect(screen.queryByRole('button', { name: '请求 AI 参考' })).toBeNull()
    expect(screen.queryByRole('button', { name: '确认已核实' })).toBeNull()
  })
})
