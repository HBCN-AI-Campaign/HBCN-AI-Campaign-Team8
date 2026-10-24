import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/api'
import { DocumentRevisionHistory } from '@/parsing/DocumentRevisionHistory'
import type { ReviewAudit } from '@/business-review/types'

vi.mock('../src/api', () => ({ api: { businessReviewAudit: vi.fn() } }))
afterEach(() => { cleanup(); vi.clearAllMocks() })
const history: ReviewAudit = {
  id: 'old-material', user_id: 7, kind: 'supplement', reason: '仅为测试的原件重复提交', created_at: '2026-10-23T12:00:00Z',
  data: { changes: [{ doc_code: 'FOL-01', replaces: 'FOL-01', previous_pdf: 'uploads/old/fol.pdf', pdf_file: 'uploads/new/fol.pdf',
    previous_document: { doc_code: 'FOL-01', type_code: 'FACILITY_LETTER', pdf_file: 'uploads/old/fol.pdf', fields: {
      _parsing: { unresolved_required: ['borrower'], unresolved_fields: ['facility_terms'], fields: {
        amount: { machine: { key: 'amount', label: '名义限额', kind: 'currency', confidence: .99, value: '123.45' },
          final_value: '543.21', status: 'confirmed', confirmation_reason: '旧版对照原文核实说明', confirmed_by: 7, confirmed_at: '2026-10-22T10:00:00Z' },
        facility_terms: { machine: { key: 'facility_terms', label: '逐授信附表条款', kind: 'json', value: null, confidence: 0,
          row_results: [{ value: { facility_name: 'Import Facilities', clause_heading: 'Interest', clause_text: 'Full old clause.' },
            status: 'needs_review', issues: ['TERMS_PAGE_INCOMPLETE'], cells: { clause_text: {
              value: 'Full old clause.', issues: [], sources: [{ block_id: 'old-p31', page: 31, bbox: [.1, .2, .8, .3],
                text: 'Full old clause.', score: .99, method: 'paddle_http' }],
            } } }],
        }, status: 'needs_review', final_value: null },
      } },
    } },
  }] },
}

describe('补件原件历史只读追溯', () => {
  it('展示旧确认并定位旧文件，候选没有载入或编辑入口', async () => {
    vi.mocked(api.businessReviewAudit).mockResolvedValue([history])
    const locate = vi.fn()
    render(<DocumentRevisionHistory code="CASE" materialVersion="new" onLocate={locate} />)
    expect(api.businessReviewAudit).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: '查看补件与旧原件' }))
    fireEvent.click(await screen.findByText(/补件记录 ·/))
    expect(screen.getByText('旧版对照原文核实说明')).toBeTruthy()
    expect(screen.getByText('543.21')).toBeTruthy()
    expect(screen.getByText('2 项（旧版记录）')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '查看旧版原件 · FOL-01' }))
    expect(locate).toHaveBeenLastCalledWith(expect.objectContaining({ pdf_file: 'uploads/old/fol.pdf', page: 1 }))
    fireEvent.click(screen.getByText('旧版机器候选与原文 · 逐授信附表条款'))
    fireEvent.click(await screen.findByLabelText('逐授信附表条款完整条款原文第31页原文'))
    expect(locate).toHaveBeenLastCalledWith(expect.objectContaining({ pdf_file: 'uploads/old/fol.pdf', page: 31, bbox: [.1, .2, .8, .3] }))
    expect(screen.queryByRole('button', { name: '载入候选明细，逐行核实' })).toBeNull()
    expect(screen.queryByRole('textbox')).toBeNull()
  })

  it('历史请求失败时明确提示，不展示当前文件冒充旧版本', async () => {
    vi.mocked(api.businessReviewAudit).mockRejectedValue(new Error('unavailable'))
    const locate = vi.fn()
    render(<DocumentRevisionHistory code="CASE" materialVersion="new" onLocate={locate} />)
    fireEvent.click(screen.getByRole('button', { name: '查看补件与旧原件' }))
    expect(await screen.findByText('补件历史读取失败，请关闭后重试')).toBeTruthy()
    expect(screen.queryByRole('button', { name: /查看旧版原件/ })).toBeNull()
    expect(locate).not.toHaveBeenCalled()
  })
})
