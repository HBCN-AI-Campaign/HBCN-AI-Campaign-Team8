import { Alert, Button, Collapse, Descriptions, Space, Tag } from 'antd'
import type { DocumentOut, FacilityContext, FieldSource } from '@/types'
import { FacilityTermFacts } from './FacilityTermFacts'

export function FacilityContextHistory({ documents, needsRecheck, onLocate }: {
  documents: DocumentOut[]
  needsRecheck: boolean
  onLocate: (source: FieldSource) => void
}) {
  const snapshots = documents.filter(doc => doc.type_code === 'FACILITY_LETTER' && doc.fields._parsing?.facility_context)
  if (!snapshots.length) return null
  return <Collapse style={{ marginBottom: 16 }} items={snapshots.map(doc => {
    const context = doc.fields._parsing.facility_context as FacilityContext
    const borrower = context.borrowers.find(row => row.id === context.selected_borrower_id)
    const allocation = context.allocations.find(row => row.id === context.selected_allocation_id)
    const source = allocation?.cells.amount?.sources?.[0]
    return {
      key: doc.doc_code,
      label: <Space><span>提交时授信关联核实记录 · {doc.doc_code}</span><Tag color="warning">历史记录</Tag></Space>,
      children: <Space direction="vertical" style={{ width: '100%' }}>
        <Alert showIcon type="warning" message={needsRecheck ? '任务字段已修改，旧关联不能作为本次结论，请重新核实。' : '以下为提交时的关联依据；当前是否可审核通过，应以重新核对的规则和业务结果为准。'} />
        <Descriptions size="small" column={1}>
          <Descriptions.Item label="法定借款人">{String(borrower?.value?.name ?? '待核实')}</Descriptions.Item>
          <Descriptions.Item label="授信品种">{String(allocation?.value?.facility_name ?? '待核实')}</Descriptions.Item>
          <Descriptions.Item label="名义限额">{context.nominal_limit ? `${context.nominal_limit.amount} ${context.nominal_limit.currency}` : '待核实'}</Descriptions.Item>
          <Descriptions.Item label="实际可用余额">待核实</Descriptions.Item>
          <Descriptions.Item label="关联方式">{context.association_method === 'human_confirmed' ? '人工确认名称对应关系' : context.association_method === 'exact_registered_name' ? '原文登记名称精确匹配' : '未确定'}</Descriptions.Item>
          <Descriptions.Item label="核实依据">{context.selection?.reason || '未提交人工关联依据'}</Descriptions.Item>
          {context.confirmed_by != null && <Descriptions.Item label="核实记录">用户 {context.confirmed_by} · {context.confirmed_at}</Descriptions.Item>}
        </Descriptions>
        {source && doc.pdf_file && <Button onClick={() => onLocate({ doc_id: doc.id, doc_code: doc.doc_code,
          type_code: doc.type_code, pdf_file: doc.pdf_file, page: source.page, bbox: source.bbox })}>分配金额 · 第{source.page}页原文</Button>}
        {context.issues.map(issue => <Alert key={issue.code} type="warning" message={issue.message} />)}
        <FacilityTermFacts application={context.term_application} dirty={needsRecheck} onLocate={(code, location) => {
          if (doc.pdf_file) onLocate({ doc_id: doc.id, doc_code: code, type_code: doc.type_code, pdf_file: doc.pdf_file, ...location })
        }} />
      </Space>,
    }
  })} />
}
