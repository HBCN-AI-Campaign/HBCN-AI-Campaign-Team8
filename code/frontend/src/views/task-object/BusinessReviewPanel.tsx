import { useCallback, useEffect, useState } from 'react'
import {
  App,
  Alert,
  Button,
  Collapse,
  Empty,
  Input,
  Modal,
  Space,
  Spin,
  Tag,
  Typography,
} from 'antd'
import { CheckOutlined, QuestionCircleOutlined, ReloadOutlined } from '@ant-design/icons'
import { api } from '@/api'
import type { BusinessReviewFinding, BusinessReviewRun, FieldSource } from '@/types'

const statusLabel: Record<BusinessReviewFinding['status'], string> = {
  pass: '通过',
  fail: '不一致',
  needs_review: '待人工核实',
  not_applicable: '不适用',
}

const statusColor: Record<BusinessReviewFinding['status'], string> = {
  pass: 'success',
  fail: 'error',
  needs_review: 'warning',
  not_applicable: 'default',
}

function evidenceRows(value: unknown): { text: string; source?: FieldSource | null }[] {
  if (!Array.isArray(value)) return value == null ? [] : [{ text: String(value) }]
  return value.map((row) => {
    if (Array.isArray(row)) {
      const text = row.slice(0, 3).map((cell) => typeof cell === 'object' ? '' : String(cell ?? '')).filter(Boolean).join('：')
      const source = row[3] && typeof row[3] === 'object' ? row[3] as FieldSource : null
      return { text, source }
    }
    if (row && typeof row === 'object') {
      const text = Object.entries(row as Record<string, unknown>)
        .filter(([, cell]) => cell == null || typeof cell !== 'object')
        .map(([key, cell]) => `${key}：${String(cell ?? '')}`).join('；')
      return { text }
    }
    return { text: String(row ?? '') }
  }).filter((row) => row.text)
}

interface Props {
  code: string
  canReview: boolean
  onLocate?: (source?: FieldSource | null) => void
}

export default function BusinessReviewPanel({ code, canReview, onLocate }: Props) {
  const { message } = App.useApp()
  const [review, setReview] = useState<BusinessReviewRun | null>(null)
  const [loading, setLoading] = useState(true)
  const [acting, setActing] = useState(false)
  const [selected, setSelected] = useState<BusinessReviewFinding | null>(null)
  const [modalMode, setModalMode] = useState<'resolve' | 'advice' | null>(null)
  const [reason, setReason] = useState('')
  const [question, setQuestion] = useState('请依据本项规则原文和材料证据，区分可确定结论与待人工核实内容。')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setReview(await api.businessReview(code))
    } catch {
      setReview(null)
    } finally {
      setLoading(false)
    }
  }, [code])

  useEffect(() => { void load() }, [load])

  const runReview = async () => {
    setActing(true)
    try {
      setReview(await api.runBusinessReview(code))
      message.success('业务审核已重新运行')
    } catch {
      // The shared API interceptor displays the server error.
    } finally {
      setActing(false)
    }
  }

  const submit = async () => {
    if (!selected || !modalMode) return
    setActing(true)
    try {
      if (modalMode === 'resolve') {
        const action = selected.status === 'fail' ? 'approve_exception' : 'acknowledge'
        setReview(await api.resolveBusinessReview(code, selected.finding_id, action, reason.trim()))
        message.success('审核处置和理由已记录')
      } else {
        const result = await api.businessReviewAdvice(code, selected.finding_id, question.trim())
        setReview(await api.businessReview(code))
        message[result.status === 'available' ? 'success' : 'warning'](
          result.status === 'available' ? '已取得 AI 参考意见' : 'AI 参考服务当前不可用',
        )
      }
      setModalMode(null)
      setSelected(null)
    } catch {
      // The shared API interceptor displays the server error.
    } finally {
      setActing(false)
    }
  }

  if (loading) return <Spin />
  if (!review) return <Alert type="error" showIcon message="业务审核结果暂不可用" />

  const current = review.is_current
  const pending = review.findings.filter((finding) => finding.requires_resolution && !finding.resolution).length
  const items = review.findings.map((finding) => {
    const advisory = review.advisories[finding.finding_id]
    const evidence = evidenceRows(finding.evidence)
    return {
      key: finding.finding_id,
      label: <Space wrap>
        <Tag color={statusColor[finding.status]}>{statusLabel[finding.status]}</Tag>
        <Typography.Text strong>{finding.rule_name}</Typography.Text>
        <Typography.Text type="secondary">{finding.dimension}</Typography.Text>
        {finding.business_conflict && <Tag color="warning">规则原文存在口径冲突</Tag>}
        {finding.resolution && <Tag>已留痕</Tag>}
      </Space>,
      children: <Space direction="vertical" size={8} style={{ width: '100%' }}>
        <Typography.Paragraph style={{ margin: 0 }}>{finding.why}</Typography.Paragraph>
        {finding.suggestion && <Typography.Text type="secondary">处理建议：{finding.suggestion}</Typography.Text>}
        {evidence.length > 0 && <div>
          <Typography.Text strong>材料证据</Typography.Text>
          {evidence.map((line, index) => <Space key={index} wrap>
            <span>{line.text}</span>
            {line.source?.pdf_file && <Button
              type="link"
              size="small"
              onClick={() => onLocate?.(line.source)}
            >定位原文</Button>}
          </Space>)}
        </div>}
        {finding.resolution && <Alert
          type="info"
          showIcon
          message={`${finding.resolution.actor_name}：${finding.resolution.reason}`}
        />}
        {advisory && <Alert
          type={advisory.status === 'available' ? 'info' : 'warning'}
          showIcon
          message={advisory.status === 'available' ? 'AI 参考意见，不构成审批结论' : 'AI 参考服务不可用'}
          description={<>
            {advisory.answer && <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', marginBottom: 8 }}>{advisory.answer}</Typography.Paragraph>}
            {advisory.citations?.map((citation, index) => <div key={`${citation.id ?? 'cite'}-${index}`}>
              [{citation.id ?? `E${index + 1}`}] {citation.label ?? citation.source ?? '材料证据'}
              {citation.page ? ` · 第 ${citation.page} 页` : ''}
              {citation.detail ? ` · ${citation.detail}` : ''}
            </div>)}
          </>}
        />}
        {canReview && current && ((finding.requires_resolution && !finding.resolution) || finding.business_conflict) && <Space wrap>
          {((finding.requires_resolution && !finding.resolution) || finding.business_conflict) && <Button
            icon={<QuestionCircleOutlined />}
            onClick={() => { setSelected(finding); setModalMode('advice') }}
          >请求 AI 参考</Button>}
          {finding.requires_resolution && !finding.resolution && <Button
            type={finding.status === 'fail' ? 'default' : 'primary'}
            danger={finding.status === 'fail'}
            icon={<CheckOutlined />}
            onClick={() => { setSelected(finding); setReason(''); setModalMode('resolve') }}
          >{finding.status === 'fail' ? '登记人工例外' : '确认已核实'}</Button>}
        </Space>}
      </Space>,
    }
  })

  return <div>
    <Space wrap style={{ marginBottom: 12 }}>
      <Tag color={current ? (pending ? 'warning' : 'success') : 'error'}>
        {current ? (pending ? `${pending} 项待处置` : '审核项已处理') : '材料已变更，结论失效'}
      </Tag>
      <Tag color={review.decision_model.status === 'configured' ? 'blue' : 'default'}>
        决策模型：{review.decision_model.status === 'configured' ? '已配置' : '未配置'}
      </Tag>
      {canReview && <Button icon={<ReloadOutlined />} loading={acting} onClick={() => void runReview()}>
        重新运行审核
      </Button>}
    </Space>
    {review.decision_model.status !== 'configured' && <Alert
      type="warning"
      showIcon
      style={{ marginBottom: 12 }}
      message="第二层决策模型尚未配置；本轮没有模型置信度结论。AI 参考意见不会自动改变审核结果。"
    />}
    {!current && <Alert
      type="error"
      showIcon
      style={{ marginBottom: 12 }}
      message="任务材料字段已变化，请重新运行审核后再处置或归档。"
    />}
    {review.findings.length ? <Collapse items={items} /> : <Empty description="暂无业务审核项" />}
    <Modal
      title={modalMode === 'advice' ? '请求 AI 参考意见' : selected?.status === 'fail' ? '登记人工例外' : '确认人工核实'}
      open={!!modalMode}
      onCancel={() => { setModalMode(null); setSelected(null) }}
      onOk={() => void submit()}
      okButtonProps={{ disabled: modalMode === 'resolve' ? !reason.trim() : !question.trim() }}
      confirmLoading={acting}
      okText={modalMode === 'advice' ? '获取参考' : '保存处置'}
      cancelText="取消"
      destroyOnHidden
    >
      {selected && <Typography.Paragraph>{selected.rule_name}：{selected.why}</Typography.Paragraph>}
      {modalMode === 'advice' ? <Input.TextArea
        value={question}
        rows={4}
        maxLength={2000}
        onChange={(event) => setQuestion(event.target.value)}
      /> : <Input.TextArea
        value={reason}
        rows={4}
        maxLength={2000}
        placeholder="填写核实依据或例外审批理由"
        onChange={(event) => setReason(event.target.value)}
      />}
    </Modal>
  </div>
}
