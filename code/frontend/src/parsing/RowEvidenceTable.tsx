import { Button, Space, Table, Tag, Typography } from 'antd'
import type { ParsedField, ParsedRowResult } from '@/types'
import { numericRowColumns, rowColumns, rowLabels } from './FieldRowsEditor'

const issueText: Record<string, string> = {
  INVALID_ROW_SCHEMA: '明细缺列或格式不完整', CELL_EVIDENCE_MISSING: '缺少原文位置',
  CELL_QUOTE_NOT_GROUNDED: '原文转录与文字识别不一致', CELL_VALUE_SOURCE_MISMATCH: '识别值与原文不一致',
  LOW_OCR_SCORE: '文字识别质量较低', ALLOCATION_ROW_ALIGNMENT_UNPROVEN: '借款人与金额的行对应待核实',
  CONFLICTING_ROW_VALUES: '同一主体或授信品种存在不同值',
  AMOUNT_CURRENCY_MISMATCH: '金额与币种的对应不一致',
  INVOICE_ROW_ALIGNMENT_UNPROVEN: '行号、数量、单价和金额的行对应待核实',
  INVOICE_ROW_SEQUENCE_INCOMPLETE: '商品行号不连续或重复，请核对是否漏行',
  TERMS_CLAUSE_NOT_COMPLETE: '完整条款或跨页限制条件尚未核实',
  TERMS_SCOPE_MISMATCH: '授信或条款标题的原文归属不一致',
  TERMS_CLAUSE_MISSING: '模型未完整返回此条款，当前仅有文字识别候选',
  TERMS_PAGE_INCOMPLETE: '原图与条款范围尚未完整核对',
  TERMS_CALL_BUDGET_EXCEEDED: '本轮条款识别已达限额，须继续核实',
  TERMS_MARGIN_REVIEW_REQUIRED: '附表底部有未归类标记，请对照原件核实是否影响条款',
  TERMS_UNEXPECTED_ROW: '模型返回了范围外条款，附表完整性须核实',
  TERMS_SCHEDULE_END_NOT_FOUND: '未找到附表结束边界，请核实原件是否完整',
  TERMS_NOT_FOUND: '未获得完整的授信附表条款',
}
type Location = NonNullable<ParsedField['source']>
const displayText = (value: unknown) => String(value).normalize('NFKC').replace(/\s+/gu, '')

export function RowEvidenceTable({ field, onLocate, onAdopt }: {
  field: ParsedField; onLocate?: (source: Location) => void
  onAdopt?: (rows: Record<string, unknown>[]) => void
}) {
  const rows = field.row_results ?? []
  const incomplete = rows.filter(r => !r.value).length
  const candidates = rows.map(r => r.value ?? Object.fromEntries(
    (rowColumns[field.key] ?? []).map(key => {
      const value = r.cells[key]?.value ?? null
      return [key, numericRowColumns.has(key) && !/^\d+(?:\.\d+)?$/.test(String(value)) ? null : value]
    })))
  const keys = field.key === 'line_items' && rows.some(r => r.cells.line_no)
    ? ['line_no', ...rowColumns[field.key]] : rowColumns[field.key] ?? []
  const columns = keys.map(key => ({
    title: rowLabels[key] ?? key, key, width: key === 'clause_text' ? 600 : key.includes('name') ? 260 : 180,
    render: (_: unknown, row: ParsedRowResult) => {
      const cell = row.cells[key]
      const value = row.value?.[key] ?? cell?.value
      const pages = new Map<number, number[]>()
      for (const source of cell?.sources ?? []) {
        const box = pages.get(source.page)
        pages.set(source.page, box ? [Math.min(box[0], source.bbox[0]), Math.min(box[1], source.bbox[1]),
          Math.max(box[2], source.bbox[2]), Math.max(box[3], source.bbox[3])] : [...source.bbox])
      }
      return <Space direction="vertical" size={0} style={{ maxWidth: key === 'clause_text' ? '100%' : 250, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>
        <Typography.Text>{value == null ? '未识别' : String(value)}</Typography.Text>
        {cell?.raw_value && displayText(cell.raw_value) !== displayText(value) && <Typography.Text type="secondary">原文：{cell.raw_value}</Typography.Text>}
        {[...pages].map(([page, bbox]) => <Button key={page} size="small" type="link"
          disabled={!onLocate} onClick={() => onLocate?.({ page, bbox })}
          aria-label={`${field.label}${rowLabels[key] ?? key}第${page}页原文`}>
          第 {page} 页原文
        </Button>)}
      </Space>
    },
  }))
  const terms = field.key === 'facility_terms'
  const body = columns.find(column => column.key === 'clause_text')
  return <Space direction="vertical" style={{ width: '100%' }}>
    <Typography.Text type="secondary">候选按单元格保留来源。原文不清或行归属不明时，请核实或补件后再确认。</Typography.Text>
    {field.key === 'facility_terms' && <>
      <Typography.Text type="secondary">条款按授信品种分别保留。利率、罚息、费用及生效条件须分别核实，不能据此直接认定本次提款适用。</Typography.Text>
      {[...new Set(field.issues ?? [])].map(code => <Typography.Text type="warning" key={code}>
        {issueText[code] ?? '本附表仍有未核实内容，请查看逐条证据或补正原件'}
      </Typography.Text>)}
      {field.margin_blocks?.map(block => <Button key={block.block_id} size="small" type="link" disabled={!onLocate}
        onClick={() => onLocate?.({ page: block.page, bbox: block.bbox })}>
        第 {block.page} 页底部标记原文
      </Button>)}
    </>}
    <Table<ParsedRowResult> size="small" rowKey="__evidenceRowKey" dataSource={rows.map((r, i) => ({ ...r, __evidenceRowKey: String(i) }))}
      pagination={rows.length > 10 ? { pageSize: 10, showSizeChanger: false } : false}
      expandable={terms ? { defaultExpandedRowKeys: ['0'], columnWidth: 40,
        expandedRowRender: row => <Space direction="vertical" style={{ width: '100%' }}>
          <Typography.Text strong>完整条款原文</Typography.Text>
          {body?.render(undefined, row)}
        </Space>,
      } : undefined}
      columns={[...columns.filter(column => !terms || column.key !== 'clause_text'), { title: '核实状态', key: 'status', width: 250,
        render: (_, row) => <Space direction="vertical" size={0}>
          <Tag color={row.status === 'accepted' ? 'success' : 'warning'}>
            {row.status === 'accepted' ? '证据已核对' : row.status === 'conflict' ? '候选冲突' : '待核实'}
          </Tag>
          {row.issues.map(code => <Typography.Text type="secondary" key={code}>{issueText[code] ?? '需对照原件核实'}</Typography.Text>)}
        </Space>,
      }]} scroll={terms ? { x: 750 } : { x: 'max-content' }} />
    {onAdopt && field.value == null && candidates.length > 0 && <>
      <Button onClick={() => onAdopt(candidates)}>载入候选明细，逐行核实</Button>
      <Typography.Text type="secondary">载入不代表确认。请更正冲突、补齐漏行并填写核实说明后提交。</Typography.Text>
      {incomplete > 0 && <Typography.Text type="warning">其中 {incomplete} 行格式不完整，无法识别的单元格留空；请核实或补正原件，不能直接确认。</Typography.Text>}
    </>}
  </Space>
}
