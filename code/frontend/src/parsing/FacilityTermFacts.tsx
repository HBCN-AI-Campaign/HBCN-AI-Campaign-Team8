import { Alert, Button, Descriptions, Space, Tag, Typography } from 'antd'
import type { FacilityTermApplication, TermPeriod } from '@/types'

const period = (p: TermPeriod) => `${p.count}${p.unit === 'months' ? '个月' : '天'}`

export function FacilityTermFacts({ application, dirty = false, onLocate }: {
  application: FacilityTermApplication | null | undefined
  dirty?: boolean
  onLocate: (docCode: string, source: { page: number; bbox: number[] }) => void
}) {
  if (!application) return null
  const currencies = application.facts.permitted_currencies
  const tenor = application.facts.loan_tenor
  const scopeReady = application.status === 'accepted' && !dirty
  const locate = (key: 'permitted_currencies' | 'loan_tenor') => {
    const fact = application.facts[key]
    const pages = new Map<number, number[][]>()
    for (const source of fact?.evidence.clause_text?.sources ?? []) {
      pages.set(source.page, [...(pages.get(source.page) ?? []), source.bbox])
    }
    return [...pages].map(([page, boxes]) => <Button key={page} type="link" size="small"
      disabled={!application.doc_code} onClick={() => onLocate(application.doc_code!, { page,
        bbox: [Math.min(...boxes.map(b => b[0])), Math.min(...boxes.map(b => b[1])),
          Math.max(...boxes.map(b => b[2])), Math.max(...boxes.map(b => b[3]))] })}>
      {key === 'permitted_currencies' ? '币种条款' : '期限条款'} · 第{page}页
    </Button>)
  }
  const policy = tenor?.status === 'accepted' ? tenor.value : null
  return <Space direction="vertical" style={{ width: '100%' }}>
    <Typography.Text strong>所选授信条款事实 <Tag color={scopeReady ? 'success' : 'warning'}>
      {scopeReady ? '条款范围已核对' : '条款范围待核实'}</Tag></Typography.Text>
    <Typography.Text>{application.facility_name}</Typography.Text>
    {application.scope_method === 'explicit_named_subfacility' && <Typography.Text type="secondary">
      子品种由附表完整条款明确列名：{application.schedule_name}
    </Typography.Text>}
    {!scopeReady && <Alert type="warning" showIcon message="以下为已有原文支持的候选事实；附表完整性或关联仍待核实，不能直接用于通过结论。" />}
    <Descriptions size="small" column={1}>
      <Descriptions.Item label="允许提款币种">
        {currencies?.status === 'accepted' && currencies.value ? currencies.value.currencies.join(' / ') : '待核实'}
        {locate('permitted_currencies')}
      </Descriptions.Item>
      {currencies?.value?.aggregate_limit_currency && <Descriptions.Item label="总用信折算限制">
        按{currencies.value.aggregate_limit_currency}等值控制；折算汇率及实际占用仍须核实。
      </Descriptions.Item>}
      <Descriptions.Item label="贷款或用信期限">
        {!policy ? '待核实；不能从其他授信或利息期补入' : <Space direction="vertical" size={0}>
          {policy.standard_periods.length > 0 && <Typography.Text>标准期限：{policy.standard_periods.map(period).join(' / ')}</Typography.Text>}
          {policy.other_period_requires_lender_agreement === true && <Typography.Text>其他期限须贷款人同意，需核实本次同意依据。</Typography.Text>}
          {policy.absolute_maximum && <Typography.Text>
            {policy.maximum_includes_extensions_and_rollovers === true ? '包括延期和展期的绝对上限' : '每次用信上限'}：{period(policy.absolute_maximum)}
          </Typography.Text>}
          {Object.entries(policy.instrument_maxima).map(([kind, maximum]) => <Typography.Text key={kind}>
            {kind === 'paper' ? '纸质票据' : kind === 'electronic' ? '电子票据' : kind}上限：{period(maximum)}
          </Typography.Text>)}
        </Space>}
        {locate('loan_tenor')}
      </Descriptions.Item>
      {application.date_span?.elapsed_days != null && <Descriptions.Item label="原件日期差">
        {application.date_span.elapsed_days}天（日期相减观察值；不是利息期或已核实贷款期限）
      </Descriptions.Item>}
    </Descriptions>
    <Typography.Text type="secondary">普通利息、罚息、用途及支付条件保留各自完整原文；数值提取和范围核对不代表批准提款。</Typography.Text>
  </Space>
}
