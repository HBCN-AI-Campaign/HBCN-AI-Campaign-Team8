import { useState } from 'react'
import { Alert, Button, Card, Descriptions, Input, Select, Space, Tag } from 'antd'
import type { FacilityContext, FacilityRecord, FacilitySelection, FieldSource } from '@/types'
import { FacilityTermFacts } from './FacilityTermFacts'

const labels: Record<string, string> = { borrower: '提款借款人', facility: '拟使用授信', currency: '提款币种', amount: '提款金额' }
const eligible = (row: FacilityRecord) => !!row.value && ['accepted', 'confirmed'].includes(row.status)

export function FacilityContextPanel({ context, selection, dirty, checking, onSelect, onCheck, onLocate }: {
  context: FacilityContext
  selection: FacilitySelection | null
  dirty: boolean
  checking: boolean
  onSelect: (selection: FacilitySelection | null) => void
  onCheck: () => void
  onLocate: (docCode: string, source: Pick<FieldSource, 'page' | 'bbox'>) => void
}) {
  const [borrowerId, setBorrowerId] = useState(selection?.borrower_id ?? context.selected_borrower_id ?? '')
  const [allocationId, setAllocationId] = useState(selection?.allocation_id ?? context.selected_allocation_id ?? '')
  const [reason, setReason] = useState(selection?.reason ?? '')
  const [editing, setEditing] = useState(false)
  const borrower = context.borrowers.find(row => row.id === borrowerId)
  const allocations = context.allocations.filter(row => borrowerId && row.borrower_ids?.length === 1 && row.borrower_ids[0] === borrowerId)
  const allocation = allocations.find(row => row.id === allocationId)
  const update = (b: string, a: string, r: string) => {
    setEditing(true)
    onSelect(b && a ? { borrower_id: b, allocation_id: a, reason: r } : null)
  }
  const locateRecord = (row: FacilityRecord) => (
    <Space wrap>{Object.entries(row.cells).map(([key, cell]) => {
      const pages = [...new Set(cell.sources.map(source => source.page))]
      return pages.map(page => {
        const sources = cell.sources.filter(source => source.page === page)
        const boxes = sources.map(source => source.bbox)
        const bbox = [Math.min(...boxes.map(b => b[0])), Math.min(...boxes.map(b => b[1])),
          Math.max(...boxes.map(b => b[2])), Math.max(...boxes.map(b => b[3]))]
        return <Button key={`${key}-${page}`} size="small" type="link" onClick={() => onLocate(row.doc_code, { page, bbox })}>
          {key === 'amount' ? '分配金额' : key === 'borrower_name' || key === 'name' ? '借款主体' : key === 'facility_name' ? '授信品种' : key === 'currency' ? '计价币种' : '名称依据'} · 第{page}页
        </Button>
      })
    })}</Space>
  )
  const needsReview = dirty || context.status !== 'ready'
  return <Card title="本次提款与FOL授信关联" style={{ marginBottom: 16 }} extra={<Tag color={needsReview ? 'warning' : 'success'}>
    {needsReview ? '待核实' : '关联已核对'}</Tag>}>
    <Descriptions column={1} size="small">
      {Object.entries(labels).map(([key, label]) => {
        const fact = context.request[key]
        return <Descriptions.Item key={key} label={label}>{fact?.value ?? '待核实'}
          {fact?.source && <Button type="link" size="small" onClick={() => onLocate(fact.doc_code, fact.source!)}>
            第{fact.source.page}页原文</Button>}
        </Descriptions.Item>
      })}
    </Descriptions>
    <Alert type="info" showIcon message="FOL名义限额与实际可用余额分别核实；中英文授信名称的对应说明不会修改原件字段。" style={{ margin: '12px 0' }} />
    <Space direction="vertical" style={{ width: '100%' }}>
      <Select aria-label="FOL法定借款人关联" placeholder="选择原件中的法定借款人" style={{ width: '100%' }}
        showSearch optionFilterProp="label" allowClear value={borrowerId || undefined}
        onChange={value => { setBorrowerId(value ?? ''); setAllocationId(''); update(value ?? '', '', reason) }}
        options={context.borrowers.map(row => ({ value: row.id, disabled: !eligible(row),
          label: `${row.doc_code} · ${row.value?.name ?? '未决主体'}${row.value?.short_name ? `（${row.value.short_name}）` : ''}` }))} />
      {borrower && locateRecord(borrower)}
      <Select aria-label="FOL主体授信分配关联" placeholder="选择该主体的授信分配行" style={{ width: '100%' }}
        showSearch optionFilterProp="label" allowClear disabled={!borrowerId} value={allocationId || undefined}
        onChange={value => { setAllocationId(value ?? ''); update(borrowerId, value ?? '', reason) }}
        options={allocations.map(row => ({ value: row.id, disabled: !eligible(row),
          label: `${row.value?.facility_name ?? row.cells.facility_name?.value ?? '未决授信'} · ${row.value?.amount ?? '金额待核实'} ${row.value?.currency ?? row.cells.currency?.value ?? ''}` }))} />
      {allocation && locateRecord(allocation)}
      <Input.TextArea aria-label="授信关联核实依据" placeholder="对照提款指令与FOL，说明主体和中英文授信品种的对应依据；原件有误时应补正原件"
        value={reason} maxLength={4000} rows={2} onChange={event => { setReason(event.target.value); update(borrowerId, allocationId, event.target.value) }} />
      {editing && (!borrowerId || !allocationId || !reason.trim()) && <Alert type="warning" message="手动关联需选定主体、分配行并填写核实依据；部分选择不会作为已确认关系提交。" />}
      {dirty && <Alert type="warning" message="字段或关联已修改，请重新核对。提交任务时服务端还会再次检查原件凭据和关联依据。" />}
      <Button loading={checking} onClick={onCheck} disabled={editing && !!selection && !reason.trim()}>重新核对授信关联</Button>
      {context.issues.map(issue => <Alert key={issue.code} type="warning" showIcon message={issue.message} />)}
      {context.nominal_limit && <p>所选主体名义限额：{context.nominal_limit.amount} {context.nominal_limit.currency}。
        {context.comparison === 'exceeds_nominal_limit' ? '提款金额超过同币种名义限额。' : context.comparison === 'within_nominal_limit' ? '提款金额未超过同币种名义限额。' : '金额暂不直接比较。'}
        实际可用余额：待核实。</p>}
      <FacilityTermFacts application={context.term_application} dirty={dirty} onLocate={onLocate} />
    </Space>
  </Card>
}
