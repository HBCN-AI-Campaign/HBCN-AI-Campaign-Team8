import { Button, Input, InputNumber, Space, Table, Typography } from 'antd'

export const rowLabels: Record<string, string> = {
  line_no: '原件行号',
  description: '货物描述', quantity: '数量', unit: '单位', unit_price: '单价', amount: '金额',
  currency: '币种', tax_basis: '含税口径', name: '名称', borrower: '借款人', borrower_name: '借款人名称',
  facility_amount: '授信额度', facility: '授信品种', purpose: '用途', term: '期限',
  interest_rate: '利率', payment_threshold: '受托支付门槛', role: '主体角色',
  short_name: '原文简称', name_local: '中文法定名称', facility_name: '授信品种或共享组',
  clause_heading: '条款标题', clause_text: '完整条款原文',
}
export const rowColumns: Record<string, string[]> = {
  line_items: ['description', 'quantity', 'unit', 'unit_price', 'amount', 'currency', 'tax_basis'],
  tranches: ['name', 'borrower_name', 'facility_amount', 'currency', 'purpose', 'term'],
  borrowers: ['name', 'short_name', 'name_local'],
  facility_limits: ['facility_name', 'amount', 'currency'],
  borrower_allocations: ['facility_name', 'borrower_name', 'amount', 'currency'],
  facility_terms: ['facility_name', 'clause_heading', 'clause_text'],
}
export const numericRowColumns = new Set(['quantity', 'unit_price', 'amount', 'facility_amount', 'payment_threshold'])
const provenance = new Set(['block_ids', 'raw_values', 'cell_sources', '__uiRowKey'])

export function hasRowEditor(key: string) { return key in rowColumns }

export function FieldRowsEditor({ fieldKey, label, value, onChange }: {
  fieldKey: string; label: string; value: Record<string, unknown>[] | null
  onChange: (value: Record<string, unknown>[]) => void
}) {
  const rows = value ?? []
  const keys = [...new Set([...rowColumns[fieldKey], ...rows.flatMap(row => Object.keys(row))])].filter(key => !provenance.has(key))
  const update = (index: number, key: string, cell: unknown) =>
    onChange(rows.map((row, i) => i === index ? { ...row, [key]: cell } : row))
  const columns = keys.map(key => ({
    title: rowLabels[key] ?? key, key, width: key === 'clause_text' ? 560 : numericRowColumns.has(key) ? 150 : 180,
    render: (_: unknown, row: Record<string, unknown>) => {
      const index = Number(row.__uiRowKey)
      const cell = row[key]
      const name = `${label}第${index + 1}行${rowLabels[key] ?? key}`
      return numericRowColumns.has(key)
        ? <InputNumber<string> stringMode controls={false} aria-label={name} style={{ width: '100%' }}
          value={cell == null ? null : String(cell)} onChange={v => update(index, key, v)} />
        : key === 'clause_text'
          ? <Input.TextArea aria-label={name} autoSize={{ minRows: 4, maxRows: 16 }}
            value={cell == null ? '' : String(cell)} onChange={e => update(index, key, e.target.value)} />
        : <Input aria-label={name} value={cell == null ? '' : typeof cell === 'object' ? JSON.stringify(cell) : String(cell)}
          onChange={e => update(index, key, e.target.value)} />
    },
  }))
  return <Space direction="vertical" style={{ width: '100%' }}>
    <Table size="small" pagination={rows.length > 10 ? { pageSize: 10, showSizeChanger: false } : false} rowKey="__uiRowKey"
      dataSource={rows.map((row, i) => ({ ...row, __uiRowKey: String(i) }))} columns={[...columns, {
        title: '操作', key: 'actions', width: 90,
        render: (_: unknown, row: Record<string, unknown>) =>
          <Button size="small" onClick={() => onChange(rows.filter((_, i) => i !== Number(row.__uiRowKey)))}>移除此行</Button>,
      }]} scroll={{ x: 'max-content' }} />
    <Button size="small" onClick={() => onChange([...rows, {}])}>增加一行</Button>
    <Typography.Text type="secondary">{fieldKey === 'facility_terms'
      ? '请核对每项授信的完整条款，包括跨页续文及限制条件。修改后填写核实说明；条款原文不能替代本次提款适用性核实。'
      : '请逐行核对名称、金额及币种；共享额度不能加总。修改后填写本字段核实说明，原始识别与来源会保留。'}</Typography.Text>
  </Space>
}
