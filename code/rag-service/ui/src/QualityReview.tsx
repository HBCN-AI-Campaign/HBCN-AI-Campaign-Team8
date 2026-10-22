import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Checkbox, Popconfirm, Select, Space, Tag } from 'antd'
import { errorMessage, getQuality, originalPath, recheckQuality, reviewQuality } from './api'
import type { KnowledgeDocument, QualityContent } from './api'

const REASONS: Record<string, string> = {
  ocr_requires_source_comparison: '本单元经过 OCR，需要与原件对照', empty_unit: '未提取到文字，请确认是否为空白页',
  pdf_images_or_ocr_layer_unverified: '含图像或 OCR 层，可能有未提取内容', embedded_images_not_transcribed: '文档内图片未转录',
  header_footer_not_transcribed: '页眉页脚未转录', formula_values_missing: '公式缺少计算结果', unmapped_glyphs: '有未映射字形',
  extraction_provenance_missing: '缺少解析方式记录', lossy_or_invalid_text: '含乱码或无效字符', no_indexable_text: '没有可索引文字',
}
export function qualityReason(value: string) { return REASONS[value] || `解析风险：${value}` }

export default function QualityReview({ document, onChanged }: { document: KnowledgeDocument; onChanged: (document: KnowledgeDocument) => void }) {
  const [data, setData] = useState<QualityContent>()
  const [verified, setVerified] = useState<number[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [stale, setStale] = useState(false)
  const [reason, setReason] = useState('incomplete')
  const abort = useRef<AbortController>()
  async function load() {
    abort.current?.abort(); abort.current = new AbortController()
    const signal = abort.current.signal
    setData(undefined); setVerified([]); setError(''); setStale(false); setBusy(true)
    try { const value = await getQuality(document.id, signal); if (!signal.aborted) setData(value) }
    catch (error) { if (!signal.aborted) setError(errorMessage(error)) }
    finally { if (!signal.aborted) setBusy(false) }
  }
  useEffect(() => { void load(); return () => abort.current?.abort() }, [document.id])
  const current = data?.document || document
  const report = current.quality
  const readyToReview = current.state === 'quality_review' && report?.status === 'quality_review'
    && report.unit_count === data?.pages.length
    && Boolean(report.parsed_sha256 && report.report_sha256 && current.sha256)
  const allVerified = Boolean(readyToReview && current.source_available && data?.pages.length && verified.length === data.pages.length)
  async function act(decision: 'approve' | 'reject' | 'recheck') {
    if (busy || stale) return
    setBusy(true); setError('')
    try {
      const result = decision === 'recheck' ? await recheckQuality(current, abort.current?.signal)
        : await reviewQuality(current, decision === 'approve' ? verified : [], decision,
          decision === 'approve' ? 'source_compared' : reason, abort.current?.signal)
      if (!abort.current?.signal.aborted) onChanged(result.document)
    } catch (error) {
      if (!abort.current?.signal.aborted) { setError(`${errorMessage(error)} 请刷新状态后再决定下一步。`); setStale(true); setVerified([]) }
    } finally { if (!abort.current?.signal.aborted) setBusy(false) }
  }
  const original = current.source_available ? originalPath(current.id) : null
  return <>
    <h3>{current.name}</h3>
    <Alert type="info" message="这里复核的是文字是否与原件一致，不是贷款审批或法规适用性审批。" description="请核对金额、币种、否定词、日期、表格和缺页；缺少必要内容时请选择拒绝，不要直接放行。" />
    <Space wrap><Button disabled={busy} onClick={() => void load()}>刷新复核状态</Button>
      {original && <a href={original} target="_blank" rel="noopener noreferrer">打开原件对照</a>}
      <Tag>{current.state}</Tag></Space>
    {error && <Alert type="error" message={error} />}
    {busy && <p role="status">正在处理复核请求…</p>}
    {!original && data && <Alert type="warning" message="原件当前不可访问，不能批准解析。请先恢复原件或重新上传。" />}
    {data?.pages.map((page, index) => <section className="parsed-page" key={index}>
      <h4>{page.page == null ? `单元 ${index + 1}` : `第 ${page.page} 页`}{page.section ? ` · ${page.section}` : ''}</h4>
      <p>解析方式：{page.extraction?.method || '未记录'}</p>
      {(report?.units?.[index]?.review_reasons || report?.review_reasons || []).map(value => <p key={value}>{qualityReason(value)}</p>)}
      <pre className="original-text">{page.text || '（本单元未识别到文字，请对照原件确认）'}</pre>
      <Checkbox disabled={busy || stale || !readyToReview || !current.source_available} checked={verified.includes(index)} onChange={event => setVerified(previous => event.target.checked ? [...previous, index] : previous.filter(value => value !== index))}>已对照原件核对单元 {index + 1}</Checkbox>
    </section>)}
    {readyToReview && <><p>已核对 {verified.length} / {data?.pages.length} 个单元。批准后会继续 Embedding，状态达到 ready 才可检索。</p>
      <Space wrap><Popconfirm title="确认批准这版解析并继续入库？" description="仅提交你实际对照过的版本；不会自动批准其他文件。" okText="确认批准" cancelText="取消" onConfirm={() => act('approve')}>
        <Button type="primary" disabled={busy || stale || !allVerified}>批准解析并继续入库</Button></Popconfirm>
        <Select aria-label="拒绝原因" value={reason} disabled={busy || stale} onChange={setReason} options={[{ value: 'incomplete', label: '内容不完整' }, { value: 'incorrect', label: '识别错误' }, { value: 'unreadable', label: '原件不可辨认' }]} />
        <Popconfirm title="确认拒绝这版解析？" okText="确认拒绝" cancelText="取消" onConfirm={() => act('reject')}><Button danger disabled={busy || stale}>拒绝解析</Button></Popconfirm>
      </Space></>}
    {['quality_review', 'quarantined', 'failed', 'ready'].includes(current.state || '') && <p><Popconfirm title="重新解析并检查？" description="旧片段会立即停止检索，重新识别可能调用付费模型；完成后仍可能需要复核。" okText="确认重新解析" cancelText="取消" onConfirm={() => act('recheck')}>
      <Button disabled={busy || stale || !data}>重新解析并检查</Button></Popconfirm></p>}
  </>
}
