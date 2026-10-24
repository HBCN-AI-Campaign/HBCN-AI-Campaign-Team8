import { describe, expect, it } from 'vitest'
import { fieldReview } from '@/parsing/fieldReview'
import type { ParsedField } from '@/types'

const machine: ParsedField = { key: 'amount', label: '金额', kind: 'currency', value: '12000000.00', status: 'accepted', confidence: .99 }

describe('字段更正提交提示', () => {
  it('已接纳字段更正也必须填写说明，恢复原值即恢复机器状态', () => {
    const changed = { ...machine, value: '12000000.01' }
    expect(fieldReview(changed, machine)).toMatchObject({ edited: true, blocked: true, pending: true, label: '已更正，待填写说明' })
    expect(fieldReview({ ...changed, confirmation_reason: '  ' }, machine).blocked).toBe(true)
    expect(fieldReview({ ...changed, confirmation_reason: '对照原件更正末位' }, machine)).toMatchObject({ blocked: false, pending: false, label: '核实说明已填写' })
    expect(fieldReview(machine, machine)).toMatchObject({ edited: false, blocked: false, pending: false, label: '已识别' })
    expect(machine.value).toBe('12000000.00')
  })

  it('清空更正值不能凭说明提交，零值可核实', () => {
    for (const value of [null, '']) expect(fieldReview({ ...machine, value, confirmation_reason: '已核对' }, machine).blocked).toBe(true)
    expect(fieldReview({ ...machine, value: '0', confirmation_reason: '已核对零值' }, machine).blocked).toBe(false)
  })

  it('保留未决空值而未更正时可保存待核实，候选载入不自动确认', () => {
    const missing: ParsedField = { ...machine, value: null, status: 'needs_review' }
    expect(fieldReview(missing, missing)).toMatchObject({ blocked: false, pending: true })
    expect(fieldReview({ ...missing, value: '123.00' }, missing)).toMatchObject({ blocked: true, pending: true })
  })

  it('逐行明细按值比较，金额精度与行顺序改变需要说明', () => {
    const rows: ParsedField = { ...machine, kind: 'json', value: [{ description: '货品', amount: '90071992547409.93' }] }
    expect(fieldReview({ ...rows, value: [{ amount: '90071992547409.93', description: '货品' }] }, rows).edited).toBe(false)
    expect(fieldReview({ ...rows, value: [{ description: '货品', amount: '90071992547409.94' }] }, rows).blocked).toBe(true)
    const list: ParsedField = { ...machine, kind: 'list', value: ['01', '02'] }
    expect(fieldReview({ ...list, value: ['02', '01'] }, list).blocked).toBe(true)
    expect(fieldReview({ ...machine, value: 12000000 }, machine).edited).toBe(true)
  })
})
