import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { FacilityTermFacts } from '@/parsing/FacilityTermFacts'
import type { FacilityTermApplication } from '@/types'

afterEach(cleanup)
const application: FacilityTermApplication = {
  status: 'accepted', facility_name: 'Revolver', schedule_name: 'Revolver', scope_method: 'exact_schedule_name',
  issues: [], doc_code: 'FOL-01', facts: {
    permitted_currencies: { status: 'accepted', issues: [], clause_heading: 'Utilization', value: { currencies: ['CNY', 'USD'], aggregate_limit_currency: 'USD', aggregate_limit_condition: 'USD equivalent cap' }, evidence: {} },
    loan_tenor: { status: 'accepted', issues: [], clause_heading: 'Utilization', value: { standard_periods: [{ count: 1, unit: 'months' }, { count: 3, unit: 'months' }, { count: 6, unit: 'months' }],
      other_period_requires_lender_agreement: true, absolute_maximum: { count: 12, unit: 'months' }, maximum_includes_extensions_and_rollovers: true,
      maximum_scope: 'each_loan', instrument_maxima: {} }, evidence: { clause_text: { value: 'Full clause', raw_value: 'Full clause', issues: [], sources: [
        { block_id: 'a', page: 28, bbox: [.1, .2, .4, .3], text: 'A', method: 'synthetic', score: 1 },
        { block_id: 'b', page: 28, bbox: [.2, .3, .8, .5], text: 'B', method: 'synthetic', score: 1 },
        { block_id: 'c', page: 29, bbox: [.1, .1, .7, .2], text: 'C', method: 'synthetic', score: 1 },
      ] } } },
  }, date_span: { elapsed_days: 30, status: 'needs_review', issue: 'TENOR_CONVENTION_UNVERIFIED' },
}

describe('所选授信的只读条款事实', () => {
  it('保留币种折算、其他期限须同意、展期上限，日期差不冒充月期限', () => {
    const locate = vi.fn()
    render(<FacilityTermFacts application={application} onLocate={locate} />)
    expect(screen.getByText('CNY / USD')).toBeTruthy()
    expect(screen.getByText(/按USD等值控制/)).toBeTruthy()
    expect(screen.getByText('标准期限：1个月 / 3个月 / 6个月')).toBeTruthy()
    expect(screen.getByText(/其他期限须贷款人同意/)).toBeTruthy()
    expect(screen.getByText('包括延期和展期的绝对上限：12个月')).toBeTruthy()
    expect(screen.getByText('30天（日期相减观察值；不是利息期或已核实贷款期限）')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '期限条款 · 第28页' }))
    expect(locate).toHaveBeenLastCalledWith('FOL-01', { page: 28, bbox: [.1, .2, .8, .5] })
    fireEvent.click(screen.getByRole('button', { name: '期限条款 · 第29页' }))
    expect(locate).toHaveBeenLastCalledWith('FOL-01', { page: 29, bbox: [.1, .1, .7, .2] })
  })
  it.each(['incomplete', 'changed'])('集合未决或字段已改时显示候选，保留单项原文支持：%s', reason => {
    render(<FacilityTermFacts application={{ ...application, status: reason === 'incomplete' ? 'needs_review' : 'accepted' }}
      dirty={reason === 'changed'} onLocate={vi.fn()} />)
    expect(screen.getByText('条款范围待核实')).toBeTruthy()
    expect(screen.getByText(/以下为已有原文支持的候选事实/)).toBeTruthy()
    expect(screen.queryByText('条款范围已核对')).toBeNull()
    expect(screen.getByText('CNY / USD')).toBeTruthy()
  })
  it('未验证的期限值不得展示为可用，未载入不显示伪造空事实', () => {
    const view = render(<FacilityTermFacts application={{ ...application, facts: { loan_tenor: { ...application.facts.loan_tenor!, status: 'needs_review' } } }} onLocate={vi.fn()} />)
    expect(screen.getByText('待核实；不能从其他授信或利息期补入')).toBeTruthy()
    expect(screen.queryByText(/标准期限：/)).toBeNull()
    view.rerender(<FacilityTermFacts application={null} onLocate={vi.fn()} />)
    expect(view.container.textContent).toBe('')
  })
})
