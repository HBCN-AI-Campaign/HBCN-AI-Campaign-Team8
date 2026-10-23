import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Alert, App, Button, Collapse, Select, Space, Typography, Upload, type UploadFile } from 'antd'
import { api } from '@/api'
import type { DocumentOut, FieldSource, ParseResult, ParsedField, SupplementDocumentInput } from '@/types'
import { FieldEvidenceEditor } from '@/parsing/FieldEvidenceEditor'
import { fieldReview } from '@/parsing/fieldReview'
import { DocumentTypeChoices, typeSelectionsValid, typeSelectionPayload, type TypeSelections } from '@/parsing/DocumentTypeChoices'
import { ClassificationAudit } from '@/parsing/DocumentClassificationHistory'

export default function SupplementDocuments({ code, existing, disabled, onChange, onBusy, onSource }: {
  code: string
  existing: DocumentOut[]
  disabled: boolean
  onChange: (docs: SupplementDocumentInput[]) => void
  onBusy: (busy: boolean) => void
  onSource: (source: FieldSource) => void
}) {
  const { message } = App.useApp()
  const [files, setFiles] = useState<UploadFile[]>([])
  const [typeSelections, setTypeSelections] = useState<TypeSelections>(new Map())
  const [parsed, setParsed] = useState<ParseResult | null>(null)
  const [machineParsed, setMachineParsed] = useState<ParseResult | null>(null)
  const [replacements, setReplacements] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState('')
  const [error, setError] = useState('')
  const generation = useRef(0)
  const realFiles=useMemo(() => files.map(f => f.originFileObj).filter((f): f is NonNullable<typeof f> => !!f), [files])
  const changeTypes=useCallback((choices: TypeSelections) => {
    generation.current++; setTypeSelections(choices); setParsed(null); setReplacements({}); setError('')
  }, [])
  const notify = useRef(onChange); notify.current = onChange
  useEffect(() => {
    generation.current++; setFiles([]); setTypeSelections(new Map()); setParsed(null); setReplacements({}); setBusy(false); setProgress(''); setError('')
    return () => { generation.current++ }
  }, [code])
  useEffect(() => {
    notify.current(parsed?.documents.map(d => ({
      doc_code: d.doc_code, type_code: d.type_code, pdf_file: d.pdf_file,
      parse_run_id: parsed.parse_run_id, replaces_doc_code: replacements[d.doc_code] || null,
      fields: Object.fromEntries(d.fields.map(f => [f.key, f.value])),
      field_confirmations: Object.fromEntries(d.fields.filter(f => f.confirmation_reason?.trim()).map(f => [f.key, f.confirmation_reason])),
      field_sources: Object.fromEntries(d.fields.filter(f => f.source).map(f => [f.key, f.source!])),
    })) ?? [])
  }, [parsed, replacements])
  const correctionCount = parsed?.documents.reduce((sum, doc, di) => sum + doc.fields.filter((field, fi) =>
    fieldReview(field, machineParsed?.documents[di]?.fields[fi]).blocked).length, 0) ?? 0
  useEffect(() => { onBusy(busy || files.length > 0 && !parsed || correctionCount > 0) }, [busy, files.length, parsed, correctionCount, onBusy])
  const parse = async () => {
    if (!typeSelectionsValid(typeSelections)) return
    const current = generation.current
    if (!realFiles.length) return
    setBusy(true); setParsed(null); setError('')
    try {
      const result = await api.parseFiles(realFiles, text => { if (current === generation.current) setProgress(text) }, undefined, typeSelectionPayload(realFiles, typeSelections))
      if (current !== generation.current) return
      if (!result.parse_run_id || !result.documents.length || result.documents.some(d => d.type_code === 'UNKNOWN' || !d.fields.length)) {
        setError('存在尚未完成识别的文件，请核实文件类别并重新识别。'); return
      }
      setParsed(result); setMachineParsed(result); setReplacements({}); message.success('已读取实际文件，请核对内容并选择新增或替换')
    } catch { if (current === generation.current) setError('文件识别未完成，请检查服务后重试；本次补件尚未提交。') }
    finally { if (current === generation.current) setBusy(false) }
  }
  const changeField = (doc: number, index: number, change: Partial<ParsedField>) => {
    setParsed(previous => previous && ({ ...previous, documents: previous.documents.map((d, di) => di !== doc ? d : ({
      ...d, fields: d.fields.map((f, fi) => fi === index ? { ...f, ...change } : f),
    })) }))
  }
  return <Space direction="vertical" style={{ width: '100%' }}>
    <Upload multiple accept=".pdf,.png,.jpg,.jpeg,.webp" beforeUpload={() => false} fileList={files} disabled={disabled || busy}
      onChange={info => { generation.current++; setFiles(info.fileList); setParsed(null); setReplacements({}); setError('')
        const next = info.fileList.map(f => f.originFileObj)
        setTypeSelections(previous => new Map([...previous].filter(([file]) => next.includes(file as NonNullable<typeof next[number]>))))
      }}>
      <Button disabled={disabled || busy}>选择实际补充文件</Button>
    </Upload>
    {!!files.length && <DocumentTypeChoices files={realFiles}
      choices={typeSelections} disabled={disabled || busy} onChange={changeTypes} />}
    <Button onClick={() => void parse()} loading={busy} disabled={disabled || !files.length || !typeSelectionsValid(typeSelections)}>识别补充文件</Button>
    {busy && <Typography.Text>{progress || '正在读取实际文件'}</Typography.Text>}
    {error && <Alert type="error" message={error} showIcon />}
    {correctionCount > 0 && <Alert type="warning" showIcon
      message={`有 ${correctionCount} 项更正尚未完成，请填写有效值和核实说明后提交补件。`} />}
    <Typography.Text type="secondary">先识别原件，再确认新增或替换。替换会保留旧版依据，并要求重新审核。</Typography.Text>
    {parsed && <Collapse key={parsed.parse_run_id} items={parsed.documents.map((d, di) => ({
      key: d.doc_code, label: `${d.source_filename} · ${d.type_label}`,
      children: <Space direction="vertical" style={{ width: '100%' }}>
        <ClassificationAudit classification={d.classification} />
        <Select aria-label={`${d.source_filename}补件方式`} value={replacements[d.doc_code] || ''} style={{ width: '100%' }} disabled={disabled}
          onChange={value => setReplacements(previous => ({ ...previous, [d.doc_code]: value }))}
          options={[{ value: '', label: '作为新增支持材料' }, ...existing.filter(old => old.type_code === d.type_code).map(old => ({ value: old.doc_code, label: `替换 ${old.doc_code}` }))]} />
        <Button onClick={() => onSource({ doc_code: d.doc_code, pdf_file: d.pdf_file, page: 1, bbox: [] })}>查看补充原件</Button>
        {d.fields.map((field, fi) => <div key={field.key} style={{ width: '100%' }}>
          <Typography.Text strong>{field.label}</Typography.Text>
          <fieldset disabled={disabled} style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}>
            <FieldEvidenceEditor field={field} onChange={value => changeField(di, fi, { value })}
              machineField={machineParsed?.documents[di]?.fields[fi]}
              onConfirm={reason => changeField(di, fi, { confirmation_reason: reason })}
              onLocate={source => onSource({ ...source, doc_code: d.doc_code, pdf_file: d.pdf_file })} />
          </fieldset>
          {field.source && <Button size="small" onClick={() => onSource({ ...field.source!, doc_code: d.doc_code, pdf_file: d.pdf_file })}>定位此字段</Button>}
        </div>)}
      </Space>,
    }))} />}
  </Space>
}
