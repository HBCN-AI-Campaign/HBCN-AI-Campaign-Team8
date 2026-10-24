import { useEffect, useState } from 'react'
import { Alert, Button, Collapse, Descriptions, Drawer, Empty, Space, Spin, Table, Tag, Typography } from 'antd'
import { api } from '@/api'
import type { ReviewAudit } from '@/business-review/types'
import type { FieldSource } from '@/types'
import { typeLabel } from '@/utils'
import { RowEvidenceTable } from './RowEvidenceTable'
import { ClassificationAudit } from './DocumentClassificationHistory'

export function DocumentRevisionHistory({ code, materialVersion, onLocate }: {
  code: string; materialVersion: string; onLocate: (source: FieldSource) => void
}) {
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [rows, setRows] = useState<ReviewAudit[]>([])
  const [error, setError] = useState('')
  useEffect(() => { setOpen(false); setRows([]); setError('') }, [code])
  useEffect(() => {
    if (!open) return
    let active = true
    setLoading(true); setRows([]); setError('')
    api.businessReviewAudit(code).then(data => {
      if (active) setRows(data.filter(row => row.kind === 'supplement').reverse())
    }).catch(() => { if (active) setError('补件历史读取失败，请关闭后重试') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [code, materialVersion, open])
  return <>
    <Button style={{ marginBottom: 16 }} onClick={() => setOpen(true)}>查看补件与旧原件</Button>
    <Drawer open={open} title="补件与旧原件" width={1000} onClose={() => setOpen(false)}>
      <Alert type="warning" showIcon message="旧版字段、人工核实及原件仅供追溯，不代表当前材料已通过。" style={{ marginBottom: 16 }} />
      {error ? <Alert type="error" message={error} /> : loading ? <Spin /> : !rows.length
        ? <Empty description="尚无补件历史" /> : <Collapse items={rows.map(row => ({
          key: row.id, label: `补件记录 · ${row.created_at} · 用户 ${row.user_id}`,
          children: <Space direction="vertical" style={{ width: '100%' }}>
            <Typography.Paragraph>补件说明：{row.reason}</Typography.Paragraph>
            {(row.data.changes ?? []).map((change, index) => {
              const previous = change.previous_document
              const audits = Object.entries(previous?.fields._parsing?.fields ?? {})
              const confirmations = audits.filter(([, audit]) => audit.confirmation_reason)
              const pending = new Set([...(previous?.fields._parsing?.unresolved_required ?? []),
                ...(previous?.fields._parsing?.unresolved_fields ?? [])])
              return <Space key={`${change.doc_code}-${index}`} direction="vertical" style={{ width: '100%', marginBottom: 16 }}>
                <Space><Typography.Text strong>{change.doc_code}{previous ? ` · ${typeLabel(previous.type_code)}` : ''}</Typography.Text>
                  <Tag color="warning">{change.replaces ? '原件替换' : change.pdf_file ? '新增材料' : '字段更正'}</Tag></Space>
                {change.previous_pdf && <Button onClick={() => onLocate({ doc_code: change.doc_code,
                  type_code: previous?.type_code, pdf_file: change.previous_pdf, page: 1, bbox: [] })}>查看旧版原件 · {change.doc_code}</Button>}
                {previous ? <>
                  <ClassificationAudit classification={previous.fields._parsing?.classification} />
                  <Descriptions size="small" column={1} items={[{ key: 'pending', label: '替换前未决字段', children: `${pending.size} 项（旧版记录）` }]} />
                  {!!confirmations.length && <Table rowKey="key" size="small" pagination={false} scroll={{ x: 750 }}
                    dataSource={confirmations.map(([key, audit]) => ({ key, ...audit }))} columns={[
                      { title: '旧版核实字段', render: (_, audit) => audit.machine.label },
                      { title: '旧值', render: (_, audit) => typeof audit.final_value === 'string' ? audit.final_value : JSON.stringify(audit.final_value) },
                      { title: '当时核实依据', dataIndex: 'confirmation_reason' },
                      { title: '记录人员与时间', render: (_, audit) => `用户 ${audit.confirmed_by ?? '未记录'} · ${audit.confirmed_at ?? '未记录'}` },
                    ]} />}
                  {!!audits.some(([, audit]) => audit.machine.row_results?.length) && <Collapse items={audits
                    .filter(([, audit]) => audit.machine.row_results?.length).map(([key, audit]) => ({
                      key, label: `旧版机器候选与原文 · ${audit.machine.label}`,
                      children: <RowEvidenceTable field={audit.machine} onLocate={source => onLocate({ ...source,
                        doc_code: previous.doc_code, type_code: previous.type_code, pdf_file: previous.pdf_file })} />,
                    }))} />}
                </> : change.previous_pdf && <Typography.Text type="secondary">此历史版本未记录完整字段快照，请对照旧原件与历史审核依据查阅。</Typography.Text>}
              </Space>
            })}
          </Space>,
        }))} />}
    </Drawer>
  </>
}
