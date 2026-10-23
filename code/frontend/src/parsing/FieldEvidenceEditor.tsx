import { useState } from 'react'
import { Button, Collapse, Input, InputNumber, Select, Space, Tag, Typography } from 'antd'
import type { ParsedField } from '@/types'
import { FieldRowsEditor, hasRowEditor } from './FieldRowsEditor'
import { RowEvidenceTable } from './RowEvidenceTable'
import { fieldReview } from './fieldReview'

export function FieldEvidenceEditor({ field, machineField, onChange, onConfirm, onLocate }: {
  field: ParsedField
  machineField?: ParsedField
  onChange: (value: ParsedField['value']) => void
  onConfirm: (reason: string) => void
  onLocate?: (source: NonNullable<ParsedField['source']>) => void
}) {
  const [jsonDraft, setJsonDraft] = useState<string | null>(null)
  const [jsonError, setJsonError] = useState(false)
  const review = fieldReview(field, machineField)
  const pixelCorrected = field.candidates?.some(c => c.verification === 'blind_region_pixels' &&
    !c.superseded && Array.isArray(c.issues) && c.issues.length === 0)
  const incompleteIdentifier = field.issues?.includes('IDENTIFIER_SOURCE_INCOMPLETE') || field.candidates?.some(c =>
    !c.superseded && Array.isArray(c.issues) && c.issues.includes('IDENTIFIER_SOURCE_INCOMPLETE'))
  return <Space direction="vertical" style={{ width: '100%' }}>
    {field.kind === 'json' && hasRowEditor(field.key) ? <FieldRowsEditor fieldKey={field.key} label={field.label}
      value={field.value as Record<string, unknown>[] | null} onChange={onChange} />
      : field.kind === 'json' ? <>
      <Input.TextArea aria-label={`${field.label}明细`} rows={3}
        status={jsonError ? 'error' : undefined}
        value={jsonDraft ?? JSON.stringify(field.value ?? [], null, 2)}
        onChange={e => {
          const text = e.target.value
          setJsonDraft(text)
          try {
            const rows: unknown = JSON.parse(text)
            if (!Array.isArray(rows) || !rows.every(r => typeof r === 'object' && r !== null && !Array.isArray(r))) throw Error()
            onChange(rows as Record<string, unknown>[])
            setJsonError(false)
          } catch { setJsonError(true); onChange(null) }
        }} />
      {jsonError && <Typography.Text type="danger">明细格式有误，请保留有效的行数组后再提交。</Typography.Text>}
    </> : field.choices?.length ? <Select aria-label={field.label} allowClear
      placeholder="对照原件选择有效选项" value={field.value == null ? undefined : String(field.value)}
      options={field.choices.map(value => ({ value, label: value }))}
      style={{ width: '100%' }} onChange={value => onChange(value ?? null)} />
      : field.kind === 'list' ? <Select mode="tags" aria-label={field.label}
      value={(field.value as string[]) ?? []} style={{ width: '100%' }} onChange={onChange} />
      : field.kind === 'currency' || field.kind === 'number' ? <InputNumber<string>
        stringMode controls={false} aria-label={field.label}
        value={field.value == null ? null : String(field.value)} style={{ width: '100%' }} onChange={onChange} />
        : <Input aria-label={field.label} value={field.value == null ? '' : String(field.value)} onChange={e => onChange(e.target.value)} />}
    <Space>
      <Tag color={review.color}>{review.label}</Tag>
      {review.edited && machineField && <Button size="small" aria-label={`恢复${field.label}识别值`} onClick={() => {
        setJsonDraft(null); setJsonError(false)
        onChange(machineField.value); onConfirm('')
      }}>恢复识别值</Button>}
      {field.required && <Typography.Text type="secondary">业务必需</Typography.Text>}
      {pixelCorrected && <Tag color="blue">局部图像纠错</Tag>}
    </Space>
    {incompleteIdentifier && <Typography.Text type="warning">
      当前候选缺少完整的{field.label}原文依据，请对照原件核实。
    </Typography.Text>}
    <Input aria-label={`${field.label}核实说明`} placeholder="核实或更正时填写依据；原件有误请补正原件"
      status={review.blocked ? 'warning' : undefined}
      value={field.confirmation_reason ?? ''} onChange={e => onConfirm(e.target.value)} />
    {review.blocked && <Typography.Text type="warning">
      {field.value == null || field.value === '' ? '更正后的值为空，请恢复原值或按原件填写有效值；原件缺失时请补正原件。' : '已更正识别值，请填写核实说明后再提交。'}
    </Typography.Text>}
    {!!field.row_results?.length && <Collapse size="small" items={[{
      key: 'rows', label: `逐格原文与候选明细（${field.row_results.length}行）`,
      children: <RowEvidenceTable field={field} onLocate={onLocate} onAdopt={onChange} />,
    }]} />}
    {!!field.candidates?.length && <Collapse size="small" items={[{
      key: 'evidence', label: `原始候选与依据（${field.candidates.length}）`,
      children: field.candidates.map((c, i) => <div key={i} style={{ marginBottom: 8 }}>
        <Typography.Text>{typeof c.raw_value === 'string' ? c.raw_value : '未读取到确定值'}</Typography.Text>
        {c.verification === 'blind_region_pixels' && c.pixel_evidence != null && typeof c.pixel_evidence === 'object' &&
          'anchor_text' in c.pixel_evidence && <div><Typography.Text type="secondary">
            OCR原文：{String(c.pixel_evidence.anchor_text)}；本候选来自局部原图转录。
          </Typography.Text></div>}
        <div><Typography.Text type="secondary">{typeof c.reason === 'string' ? c.reason : ''}</Typography.Text></div>
      </div>),
    }]} />}
  </Space>
}
