import { Input, Select, Space, Table, Typography } from 'antd'
import { memo } from 'react'
import type { DocumentTypeSelection } from '@/types'
import { TYPE_LABEL } from '@/utils'

export type TypeSelections = Map<File, DocumentTypeSelection>
export const typeSelectionsValid = (choices: TypeSelections) => [...choices.values()].every(
  choice => !choice.type_code || choice.reason.trim().length >= 2)
export const typeSelectionPayload = (files: File[], choices: TypeSelections) =>
  files.map(file => choices.get(file) ?? { type_code: null, reason: '' })

export const DocumentTypeChoices = memo(function DocumentTypeChoices({ files, choices, onChange, disabled }: {
  files: File[]; choices: TypeSelections; onChange: (choices: TypeSelections) => void; disabled?: boolean
}) {
  const update = (file: File, choice: DocumentTypeSelection) => {
    const next = new Map(choices)
    if (choice.type_code) next.set(file, choice)
    else next.delete(file)
    onChange(next)
  }
  return <Space direction="vertical" style={{ width: '100%' }}>
    <Table size="small" pagination={false} rowKey="index" dataSource={files.map((file, index) => ({ file, index }))}
      columns={[
        { title: '文件名', render: (_, row) => `${row.index + 1}. ${row.file.name}` },
        { title: '文件类别', render: (_, { file, index }) => {
          const choice = choices.get(file)
          const label = `第${index + 1}份文件类别`
          return <Space direction="vertical" style={{ width: '100%' }}>
            <Select aria-label={label} disabled={disabled} style={{ minWidth: 240 }} value={choice?.type_code ?? ''}
              options={[{ value: '', label: '按文件名建议类别' }, ...Object.entries(TYPE_LABEL).map(([value, text]) => ({ value, label: text }))]}
              onChange={value => update(file, { type_code: value || null, reason: '' })} />
            {choice?.type_code && <Input aria-label={`第${index + 1}份文件类别依据`} disabled={disabled} maxLength={500}
              placeholder="填写原件标题或其他分类依据" value={choice.reason}
              status={choice.reason.trim().length < 2 ? 'warning' : undefined}
              onChange={event => update(file, { ...choice, reason: event.target.value })} />}
          </Space>
        } },
        { title: '大小', render: (_, { file }) => `${(file.size / 1024).toFixed(0)} KB` },
      ]} />
    <Typography.Text type="secondary">文件名只用于建议。名称不明确或类别不符时，请按原件选择类别并填写依据；选择类别后仍需核实识别字段。系统不自动拆分一份文件中的多种单据。</Typography.Text>
  </Space>
})
