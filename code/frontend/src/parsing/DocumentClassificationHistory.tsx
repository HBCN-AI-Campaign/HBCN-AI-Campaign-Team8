import { Alert, Button, Space, Typography } from 'antd'
import type { DocumentOut, FieldSource, ParsedDocument } from '@/types'
import { typeLabel } from '@/utils'

export function ClassificationAudit({ classification }: { classification?: ParsedDocument['classification'] }) {
  if (classification?.method !== 'operator_selected') return null
  return <Alert type="info" showIcon message="文件类别由经办人选择"
    description={<Space direction="vertical" size={0}>
      <Typography.Text>类别：{typeLabel(classification.type_code)}</Typography.Text>
      <Typography.Text>依据：{String(classification.reason)}</Typography.Text>
      <Typography.Text type="secondary">用户 {String(classification.selected_by)} · {String(classification.selected_at)}</Typography.Text>
      <Typography.Text type="secondary">该记录用于追溯文件分类，不代表识别字段或业务审核已通过。</Typography.Text>
    </Space>} />
}

export function DocumentClassificationHistory({ documents, onLocate }: {
  documents: DocumentOut[]; onLocate: (source: FieldSource) => void
}) {
  const selected=documents.filter(doc => doc.fields._parsing?.classification?.method === 'operator_selected')
  if (!selected.length) return null
  return <Space direction="vertical" style={{ width: '100%', marginBottom: 16 }}>
    {selected.map(doc => <div key={doc.id} style={{ width: '100%' }}>
      <Typography.Text strong>{doc.doc_code}</Typography.Text>
      <ClassificationAudit classification={doc.fields._parsing.classification} />
      {doc.pdf_file && <Button size="small" onClick={() => onLocate({ doc_id: doc.id, doc_code: doc.doc_code,
        type_code: doc.type_code, pdf_file: doc.pdf_file, page: 1, bbox: [] })}>查看分类依据原件 · {doc.doc_code}</Button>}
    </div>)}
  </Space>
}
