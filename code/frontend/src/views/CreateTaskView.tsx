import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Alert,
  App,
  Button,
  Card,
  Collapse,
  Descriptions,
  Form,
  Input,
  InputNumber,
  Result,
  Select,
  Space,
  Steps,
  Table,
  Tag,
  Tooltip,
  Upload,
  type TableColumnsType,
  type UploadFile,
} from 'antd'
import {
  ArrowLeftOutlined,
  CheckOutlined,
  CheckCircleOutlined,
  InboxOutlined,
  SendOutlined,
  ThunderboltOutlined,
  WarningFilled,
  EyeOutlined,
} from '@ant-design/icons'
import { api } from '@/api'
import type { ParseResult, ParsedDocument, ParsedField, FieldSource, Customer, FacilitySelection, FacilityContext, DocumentIn } from '@/types'
import { fmt } from '@/utils'
import PdfSourceViewer from '@/components/PdfSourceViewer'
import { FieldEvidenceEditor } from '@/parsing/FieldEvidenceEditor'
import { fieldReview } from '@/parsing/fieldReview'
import { FacilityContextPanel } from '@/parsing/FacilityContextPanel'
import { DocumentTypeChoices, typeSelectionsValid, typeSelectionPayload, type TypeSelections } from '@/parsing/DocumentTypeChoices'
import { ClassificationAudit } from '@/parsing/DocumentClassificationHistory'

// 快捷键：从 sample_pdfs 载入 8 个真实 PDF（走和真人上传完全一致的 multipart 流程）
// 每项 [前端呈现的模板名(决定解析类型), 服务器样本文件名(真实二进制来源)]
const TEMPLATE_FILES: [string, string][] = [
  ['贷款合同.pdf', 'facility_letter.pdf'],
  ['授信请求.pdf', 'drawdown_instruction_zn.pdf'],
  ['支付指令-01.pdf', 'payment_instruction.pdf'],
  ['支付指令-02.pdf', 'payment_instruction.pdf'],
  ['商务合同.pdf', 'commercial_contract.pdf'],
  ['形式发票.pdf', 'invoice.pdf'],
  ['报关单.pdf', 'customs_declaration.pdf'],
]

interface TaskForm {
  customer_no: string | null
  customer_name: string | null
  borrower: string
  drawdown_currency: string
  drawdown_amount: string | null
}

function lowConfCount(doc: ParsedDocument): number {
  return doc.fields.filter((f) => f.confidence < 0.8).length
}

function documentInputs(parsed: ParseResult): DocumentIn[] {
  return parsed.documents.map(d => ({
    parse_run_id: parsed.parse_run_id, doc_code: d.doc_code, type_code: d.type_code,
    pdf_file: d.pdf_file ?? null,
    fields: Object.fromEntries(d.fields.map(f => [f.key, f.value])),
    field_sources: Object.fromEntries(d.fields.filter(f => f.source).map(f => [f.key, { ...f.source, confidence: f.confidence }])),
    field_confirmations: Object.fromEntries(d.fields.filter(f => f.confirmation_reason?.trim()).map(f => [f.key, f.confirmation_reason])),
  }))
}

export default function CreateTaskView() {
  const navigate = useNavigate()
  const { message } = App.useApp()

  const [step, setStep] = useState(0)
  const [files, setFiles] = useState<File[]>([])
  const [fileList, setFileList] = useState<UploadFile[]>([])
  const [typeSelections, setTypeSelections] = useState<TypeSelections>(new Map())
  const [parsing, setParsing] = useState(false)
  const [parseProgress, setParseProgress] = useState('')
  const [parseRunId, setParseRunId] = useState('')
  const [creating, setCreating] = useState(false)
  const [loadingTpl, setLoadingTpl] = useState(false)
  const [parsed, setParsed] = useState<ParseResult | null>(null)
  const [machineParsed, setMachineParsed] = useState<ParseResult | null>(null)
  const [facilityContext, setFacilityContext] = useState<FacilityContext | null>(null)
  const [facilitySelection, setFacilitySelection] = useState<FacilitySelection | null>(null)
  const [facilityDirty, setFacilityDirty] = useState(false)
  const [facilityChecking, setFacilityChecking] = useState(false)
  const [facilityRevision, setFacilityRevision] = useState(0)
  const facilityRequestRevision = useRef(0)
  const [activeDocs, setActiveDocs] = useState<string[]>([])
  const [taskForm, setTaskForm] = useState<TaskForm>({
    customer_no: null,
    customer_name: null,
    borrower: '',
    drawdown_currency: '',
    drawdown_amount: null,
  })

  // 客户搜索下拉（识别后自动选中建议客户，可搜索改选）
  const [custOptions, setCustOptions] = useState<Customer[]>([])
  const [custSearching, setCustSearching] = useState(false)

  // 定位原文（PDF 预览 + 高亮）
  const [pdfVisible, setPdfVisible] = useState(false)
  const [pdfSource, setPdfSource] = useState<FieldSource | null>(null)
  const reviews = parsed?.documents.flatMap((doc, di) => doc.fields.map((field, fi) =>
    fieldReview(field, machineParsed?.documents[di]?.fields[fi]))) ?? []
  const pendingCount = reviews.filter(review => review.pending).length
  const correctionCount = reviews.filter(review => review.blocked).length
  const facilityPending = !!parsed?.documents.some(doc => doc.type_code === 'FACILITY_LETTER') &&
    (facilityDirty || facilityContext?.status !== 'ready')
  const hasPending = pendingCount > 0 || !!parsed?.documents.some(doc => doc.issues?.length) || facilityPending
  const unknownDocuments = parsed?.documents.some(doc => doc.type_code === 'UNKNOWN' || !doc.fields.length)
  const typesValid = typeSelectionsValid(typeSelections)

  const goBack = () => navigate('/dashboard')

  // 上传列表变化（阻止自动上传，手动收集 File）
  const onUploadChange = (info: { fileList: UploadFile[] }) => {
    setFileList(info.fileList)
    const next = info.fileList.map((f) => f.originFileObj as File).filter(Boolean)
    setFiles(next)
    setTypeSelections(previous => new Map([...previous].filter(([file]) => next.includes(file))))
  }

  // 一键载入 8 个真实样本 PDF
  const loadTemplate = async () => {
    setLoadingTpl(true)
    try {
      const made = await Promise.all(
        TEMPLATE_FILES.map(async ([tplName, sample]) => {
          const resp = await fetch(`/pdf/${encodeURIComponent(sample)}`)
          if (!resp.ok) throw new Error(`拉取样本 ${sample} 失败 (${resp.status})`)
          const blob = await resp.blob()
          return new File([blob], tplName, { type: 'application/pdf' })
        }),
      )
      setFiles(made)
      setTypeSelections(new Map())
      setFileList(
        made.map((f, i) => ({
          uid: String(Date.now() + i),
          name: f.name,
          status: 'done' as const,
          originFileObj: f as unknown as UploadFile['originFileObj'],
        })),
      )
      message.success(`已载入 ${made.length} 个真实样本 PDF，可直接点「开始智能识别」`)
    } catch (e) {
      message.error('载入模板失败：' + ((e as Error)?.message || e))
    } finally {
      setLoadingTpl(false)
    }
  }

  // 恢复使用同一份服务器凭据；不重新识别、不恢复未提交的人工编辑。
  const doParse = async (resume = false) => {
    if (!resume && !typesValid) return
    setParsing(true)
    try {
      const res = resume ? await api.resumeParsing(parseRunId.trim(), setParseProgress)
        : await api.parseFiles(files, setParseProgress, setParseRunId, typeSelectionPayload(files, typeSelections))
      setParsed(res)
      setMachineParsed(res)
      setFacilityContext(res.facility_context ?? null)
      setFacilitySelection(null)
      setFacilityDirty(false)
      setFacilityRevision(revision => revision + 1)
      setTaskForm({
        customer_no: res.suggested_customer_no ?? null,
        customer_name: res.suggested_customer_name ?? null,
        borrower: res.suggested_borrower,
        drawdown_currency: res.suggested_currency,
        drawdown_amount: res.suggested_amount == null ? null : String(res.suggested_amount),
      })
      // 预置下拉项：把识别到的客户放入候选，保证下拉能回显名称
      if (res.suggested_customer_no && res.suggested_customer_name) {
        setCustOptions([
          { id: -1, customer_no: res.suggested_customer_no, name: res.suggested_customer_name },
        ])
      } else {
        setCustOptions([])
      }
      setActiveDocs(res.documents.map((_, i) => String(i)))
      setStep(1)
      const custHint = res.suggested_customer_no
        ? `，已匹配客户 ${res.suggested_customer_no}`
        : '，未匹配到客户请手动选择'
      if (res.status === 'needs_review') message.warning(`材料已解析，存在待核实项${custHint}`)
      else message.success(`识别完成：共 ${res.documents.length} 份单据${custHint}`)
    } catch {
      /* 拦截器已提示 */
    } finally {
      setParsing(false)
    }
  }

  // 客户搜索（防抖交给 antd Select 的 filterOption=false + 手动触发）
  const searchCustomers = async (keyword: string) => {
    setCustSearching(true)
    try {
      const rows = await api.searchCustomers(keyword, 20)
      setCustOptions(rows)
    } catch {
      /* 拦截器已提示 */
    } finally {
      setCustSearching(false)
    }
  }

  // 选中某客户
  const onSelectCustomer = (customerNo: string | undefined) => {
    const hit = custOptions.find((c) => c.customer_no === customerNo)
    setTaskForm((s) => ({
      ...s,
      customer_no: customerNo ?? null,
      customer_name: hit?.name ?? null,
    }))
  }

  // 字段编辑：不可变更新 parsed
  const updateField = (docIdx: number, fieldIdx: number, value: ParsedField['value']) => {
    facilityRequestRevision.current += 1
    setFacilitySelection(null)
    setFacilityDirty(true)
    setFacilityRevision(revision => revision + 1)
    setParsed((prev) => {
      if (!prev) return prev
      const documents = prev.documents.map((d, di) => {
        if (di !== docIdx) return d
        const fields = d.fields.map((f, fi) => (fi === fieldIdx ? { ...f, value } : f))
        return { ...d, fields }
      })
      return { ...prev, documents }
    })
  }

  const confirmField = (docIdx: number, fieldIdx: number, reason: string) => {
    facilityRequestRevision.current += 1
    setFacilitySelection(null)
    setFacilityDirty(true)
    setFacilityRevision(revision => revision + 1)
    setParsed(prev => prev ? { ...prev, documents: prev.documents.map((d, di) => di !== docIdx ? d : {
      ...d, fields: d.fields.map((f, fi) => fi !== fieldIdx ? f : { ...f, confirmation_reason: reason }),
    }) } : prev)
  }

  const locateParsed = (doc: ParsedDocument, row: ParsedField) => {
    if (!doc.pdf_file || !row.source?.bbox) {
      message.info('该字段暂无原文定位信息')
      return
    }
    setPdfSource({
      doc_code: doc.doc_code,
      type_code: doc.type_code,
      pdf_file: doc.pdf_file,
      page: row.source.page,
      bbox: row.source.bbox,
    })
    setPdfVisible(true)
  }

  const checkFacilityContext = async () => {
    if (!parsed) return
    const revision = facilityRequestRevision.current
    setFacilityChecking(true)
    try {
      const context = await api.checkFacilityContext({ documents: documentInputs(parsed),
        facility_selection: facilitySelection, borrower: taskForm.borrower,
        drawdown_currency: taskForm.drawdown_currency, drawdown_amount: taskForm.drawdown_amount })
      if (revision !== facilityRequestRevision.current) return
      setFacilityContext(context)
      setFacilityDirty(false)
      setFacilityRevision(revision => revision + 1)
    } catch { /* interceptor reports the server validation error */ }
    finally { setFacilityChecking(false) }
  }

  const updateTaskFact = (patch: Partial<TaskForm>) => {
    facilityRequestRevision.current += 1
    setFacilityDirty(true)
    setTaskForm(current => ({ ...current, ...patch }))
  }

  // 一步到位：上传 → 后端解析 → 直接创建任务（创建时后端自动完成首次规则核对）
  // 有识别疑点时进入核实页；满足创建条件后进入规则审核结果页。
  const uploadAndCreate = async () => {
    if (!files.length || !typesValid) return
    setCreating(true)
    try {
      // 1) 解析（后端据此生成 documents，并建议关联客户）
      const res = await api.parseFiles(files, setParseProgress, setParseRunId, typeSelectionPayload(files, typeSelections))
      if (res.status !== 'ready' || res.documents.some(doc => doc.type_code === 'UNKNOWN' || !doc.fields.length)
        || res.suggested_amount == null || !res.suggested_borrower || !res.suggested_currency) {
        setParsed(res)
        setMachineParsed(res)
        setFacilityContext(res.facility_context ?? null)
        setFacilitySelection(null)
        setFacilityDirty(false)
        setFacilityRevision(revision => revision + 1)
        setTaskForm({ customer_no: res.suggested_customer_no ?? null, customer_name: res.suggested_customer_name ?? null,
          borrower: res.suggested_borrower, drawdown_currency: res.suggested_currency, drawdown_amount: res.suggested_amount == null ? null : String(res.suggested_amount) })
        setActiveDocs(res.documents.map((_, i) => String(i)))
        setStep(1)
        message.warning('材料中有识别疑点，请对照原件核实后继续')
        return
      }
      // 2) 组装 documents
      const documents = res.documents.map((d) => ({
        parse_run_id: res.parse_run_id,
        doc_code: d.doc_code,
        type_code: d.type_code,
        fields: Object.fromEntries(d.fields.map((f) => [f.key, f.value])),
        pdf_file: d.pdf_file ?? null,
        field_sources: Object.fromEntries(d.fields.filter((f) =>
          f.source || (f.value !== null && f.value !== undefined && f.value !== ''),
        ).map((f) => [
          f.key,
          { ...(f.source ?? {}), confidence: f.confidence },
        ])),
      }))
      // 3) 创建任务（后端自动跑首次规则核对，状态直接进入「审核中」）
      const created = await api.createTask({
        customer_no: res.suggested_customer_no ?? null,
        borrower: res.suggested_borrower,
        drawdown_currency: res.suggested_currency,
        drawdown_amount: String(res.suggested_amount),
        documents,
      })
      message.success(`任务 ${created.task_code} 已创建并完成首次核对`)
      // 4) 直达规则审核结果页
      navigate(`/tasks/${encodeURIComponent(created.task_code)}`)
    } catch {
      /* 拦截器已提示 */
    } finally {
      setCreating(false)
    }
  }

  // 核实后创建；仍有未决项时可保存待核实任务，由规则关口阻断自动通过。
  const confirmCreate = async () => {
    if (!parsed) return
    if (correctionCount) {
      message.warning('请为更正后的字段填写有效值和核实说明')
      setStep(1)
      return
    }
    if (!taskForm.borrower.trim() || !taskForm.drawdown_currency.trim() || taskForm.drawdown_amount == null) {
      message.warning('请核实并填写借款人、提款币种和金额；未识别值不能默认为零')
      setStep(1)
      return
    }
    if (!taskForm.customer_no) {
      message.warning('请先选择客户号')
      setStep(1)
      return
    }
    setCreating(true)
    try {
      const documents = documentInputs(parsed)
      const created = await api.createTask({
        customer_no: taskForm.customer_no,
        borrower: taskForm.borrower,
        drawdown_currency: taskForm.drawdown_currency,
        drawdown_amount: taskForm.drawdown_amount,
        documents,
        facility_selection: facilitySelection,
      })
      message.success(`任务 ${created.task_code} 已创建，可交审核人员核对`)
      navigate(`/tasks/${encodeURIComponent(created.task_code)}`)
    } catch {
      /* 拦截器已提示 */
    } finally {
      setCreating(false)
    }
  }

  // 单份单据的字段编辑表格列
  const fieldColumns = (doc: ParsedDocument, docIdx: number): TableColumnsType<ParsedField> => [
    {
      title: '字段',
      width: 160,
      render: (_, row) => (
        <span>
          {row.label}{' '}
          {row.confidence < 0.8 && (
            <Tooltip title="识别置信度较低，请复核">
              <WarningFilled style={{ color: 'var(--amber)' }} />
            </Tooltip>
          )}
        </span>
      ),
    },
    {
      title: '识别值（可编辑）',
      render: (_, row, fieldIdx) => {
        if (row.status) return <FieldEvidenceEditor field={row}
          machineField={machineParsed?.documents[docIdx]?.fields[fieldIdx]}
          onChange={value => updateField(docIdx, fieldIdx, value)}
          onLocate={source => locateParsed(doc, { ...row, source })}
          onConfirm={reason => confirmField(docIdx, fieldIdx, reason)} />
        const low = row.confidence < 0.8
        const lowStyle = low
          ? { background: '#fff8e6', boxShadow: '0 0 0 1px var(--amber) inset' }
          : undefined
        if (row.kind === 'list') {
          return (
            <Select
              mode="tags"
              value={(row.value as string[]) || []}
              style={{ width: '100%', ...lowStyle }}
              onChange={(v) => updateField(docIdx, fieldIdx, v)}
            />
          )
        }
        if (row.kind === 'currency' || row.kind === 'number') {
          return (
            <InputNumber<string>
              stringMode
              controls={false}
              value={row.value == null ? null : String(row.value)}
              style={{ width: '100%', ...lowStyle }}
              onChange={(v) => updateField(docIdx, fieldIdx, v)}
            />
          )
        }
        return (
          <Input
            value={row.value as string}
            style={lowStyle}
            onChange={(e) => updateField(docIdx, fieldIdx, e.target.value)}
          />
        )
      },
    },
    {
      title: '识别状态',
      width: 110,
      render: (_, row, fieldIdx) => {
        const review = fieldReview(row, machineParsed?.documents[docIdx]?.fields[fieldIdx])
        return <Tag color={review.color}>{review.label}</Tag>
      },
    },
    {
      title: '原文',
      width: 100,
      align: 'center',
      render: (_, row) =>
        row.source && doc.pdf_file ? (
          <Button type="link" size="small" onClick={() => locateParsed(doc, row)}>
            <EyeOutlined style={{ marginRight: 2 }} />
            查看
          </Button>
        ) : (
          <span style={{ color: 'var(--muted)' }}>—</span>
        ),
    },
  ]

  return (
    <div>
      <div
        className="page-head"
        style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}
      >
        <div>
          <h2>发起审核任务</h2>
          <p>上传材料 → 系统自动识别并完成首次规则核对 → 进入审核结果页核对</p>
        </div>
        <Button icon={<ArrowLeftOutlined />} onClick={goBack}>
          返回工作台
        </Button>
      </div>

      <Steps
        current={step}
        style={{ marginBottom: 20 }}
        items={[{ title: '上传材料' }, { title: '自动识别 + 规则核对' }, { title: '进入审核结果' }]}
      />

      {/* 步骤 1：上传 */}
      {step === 0 && (
        <Card
          title="📎 上传材料"
          extra={
            <Button
              color="green"
              variant="outlined"
              icon={<ThunderboltOutlined />}
              loading={loadingTpl}
              disabled={parsing || creating}
              onClick={loadTemplate}
            >
              载入示例模板（非第8套验收材料）
            </Button>
          }
        >
          <Upload.Dragger
            multiple
            disabled={parsing || creating}
            fileList={fileList}
            beforeUpload={() => false}
            onChange={onUploadChange}
          >
            <p className="ant-upload-drag-icon">
              <InboxOutlined />
            </p>
            <p className="ant-upload-text">点击或拖拽上传材料</p>
            <p className="ant-upload-hint">支持 PDF / 图片，可多选；其他文件请先转为 PDF</p>
          </Upload.Dragger>

          <p style={{ fontSize: 13, color: 'var(--muted)', marginTop: 10 }}>
            材料类型：贷款合同 · 授信请求 · 提款指令 · 支付指令 · 商务合同 · 形式发票 · 报关单 · 运单
          </p>

          {files.length > 0 && (
            <DocumentTypeChoices files={files} choices={typeSelections} onChange={setTypeSelections} disabled={parsing || creating} />
          )}

          <Alert
            type="info"
            showIcon
            style={{ marginTop: 14 }}
            message="上传后自动识别并整理业务字段；遇到识别不清、选项歧义或内容冲突时，会展示原件依据供核实。"
          />

          {(parsing || creating) && parseProgress && <p role="status">{parseProgress}</p>}

          <Space.Compact style={{ marginTop: 14, width: '100%', maxWidth: 560 }}>
            <Input aria-label="解析编号" placeholder="已有解析编号？可恢复服务器识别结果"
              value={parseRunId} onChange={e => setParseRunId(e.target.value)} disabled={parsing || creating} />
            <Button disabled={!/^[a-f0-9]{32}$/.test(parseRunId.trim()) || parsing || creating}
              onClick={() => doParse(true)}>恢复解析结果</Button>
          </Space.Compact>
          {parseRunId && <p style={{ color: 'var(--muted)', fontSize: 12 }}>解析编号：{parseRunId}。恢复仅限本人的原始识别结果，未提交编辑请另行保存。</p>}

          <div style={{ marginTop: 18, textAlign: 'right' }}>
            <Space>
              <Button
                icon={<ThunderboltOutlined />}
                loading={parsing}
                disabled={!files.length || creating || !typesValid}
                onClick={() => doParse()}
              >
                先逐项复核再创建
              </Button>
              <Button
                type="primary"
                icon={<SendOutlined />}
                loading={creating || parsing}
                disabled={!files.length || !typesValid}
                onClick={uploadAndCreate}
              >
                上传并创建任务（{files.length} 个文件）
              </Button>
            </Space>
          </div>
        </Card>
      )}

      {/* 步骤 2：复核编辑 */}
      {step === 1 && parsed && (
        <>
          <Card title="任务基本信息（可修改）" style={{ marginBottom: 16 }}>
            <Form layout="inline">
              <Form.Item label="任务编号">
                <Tooltip title="任务编号由系统在创建时自动生成（格式 年份-序号）">
                  <Tag color="default" style={{ height: 32, lineHeight: '30px', fontSize: 14 }}>
                    创建时自动生成
                  </Tag>
                </Tooltip>
              </Form.Item>
              <Form.Item
                label="客户"
                required
                validateStatus={taskForm.customer_no ? 'success' : 'warning'}
                help={taskForm.customer_no ? undefined : '识别未匹配到客户，请搜索选择'}
              >
                <Select
                  aria-label="任务客户"
                  showSearch
                  allowClear
                  placeholder="按客户号 / 名称搜索"
                  style={{ width: 300 }}
                  value={taskForm.customer_no ?? undefined}
                  filterOption={false}
                  loading={custSearching}
                  onSearch={searchCustomers}
                  onFocus={() => {
                    if (custOptions.length === 0) searchCustomers('')
                  }}
                  onChange={onSelectCustomer}
                  notFoundContent={custSearching ? '搜索中…' : '无匹配客户'}
                  options={custOptions.map((c) => ({
                    value: c.customer_no,
                    label: `${c.customer_no} · ${c.name}`,
                  }))}
                />
              </Form.Item>
              <Form.Item label="借款人">
                <Input
                  aria-label="任务借款人"
                  style={{ width: 240 }}
                  value={taskForm.borrower}
                  onChange={(e) => updateTaskFact({ borrower: e.target.value })}
                />
              </Form.Item>
              <Form.Item label="提款币种">
                <Input
                  aria-label="任务提款币种"
                  style={{ width: 110 }}
                  value={taskForm.drawdown_currency}
                  onChange={(e) =>
                    updateTaskFact({ drawdown_currency: e.target.value })
                  }
                />
              </Form.Item>
              <Form.Item label="提款金额">
                <InputNumber<string>
                  stringMode
                  aria-label="任务提款金额"
                  min="0"
                  max="9999999999999999.99"
                  step="100000"
                  changeOnBlur={false}
                  controls={false}
                  style={{ width: 180 }}
                  value={taskForm.drawdown_amount}
                  onInput={value => updateTaskFact({ drawdown_amount: value || null })}
                  onChange={(v) => updateTaskFact({ drawdown_amount: v })}
                />
              </Form.Item>
            </Form>
          </Card>

          {facilityContext && parsed.documents.some(doc => doc.type_code === 'FACILITY_LETTER') && <FacilityContextPanel
            key={`${parsed.parse_run_id}-${facilityRevision}`} context={facilityContext} selection={facilitySelection}
            dirty={facilityDirty} checking={facilityChecking}
            onSelect={selection => { facilityRequestRevision.current += 1; setFacilitySelection(selection); setFacilityDirty(true) }}
            onCheck={checkFacilityContext}
            onLocate={(docCode, source) => {
              const doc = parsed.documents.find(d => d.doc_code === docCode)
              if (doc) locateParsed(doc, { key: '', label: '', kind: 'text', confidence: 0, value: null, source })
            }} />}

          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 14 }}
            message="待核实字段请对照原件确认并填写依据。未识别到的值保持空白；原件本身有误时应补正原件。"
          />

          {unknownDocuments && <Alert type="error" showIcon style={{ marginBottom: 14 }}
            message="有文件类别尚未确定，暂不能创建任务。请返回上传步骤，选择类别并填写依据后重新识别；重新识别会清空本页未提交的核实。"
            action={<Button onClick={() => setStep(0)}>返回选择文件类别</Button>} />}

          {correctionCount > 0 && <Alert type="warning" showIcon style={{ marginBottom: 14 }}
            message={`有 ${correctionCount} 项更正尚未完成，请填写有效值和核实说明后继续。`} />}

          <Collapse
            key={parsed.parse_run_id}
            activeKey={activeDocs}
            onChange={(keys) => setActiveDocs(keys as string[])}
            items={parsed.documents.map((doc, di) => ({
              key: String(di),
              label: (
                <span>
                  <Tag style={{ marginRight: 8 }}>{doc.doc_code}</Tag>
                  <strong>{doc.type_label}</strong>
                  <span style={{ color: 'var(--muted)', fontSize: 12, marginLeft: 8 }}>
                    · {doc.source_filename}
                  </span>
                  {lowConfCount(doc) > 0 && (
                    <Tag color="warning" style={{ marginLeft: 10 }}>
                      {lowConfCount(doc)} 项待复核
                    </Tag>
                  )}
                </span>
              ),
              children: (
                <Space direction="vertical" style={{ width: '100%' }}>
                <ClassificationAudit classification={doc.classification} />
                {doc.pdf_file && <Button onClick={() => { setPdfSource({ doc_code: doc.doc_code, type_code: doc.type_code, pdf_file: doc.pdf_file, page: 1, bbox: [] }); setPdfVisible(true) }}>查看此份原件</Button>}
                <Table<ParsedField>
                  rowKey="key"
                  size="small"
                  tableLayout="fixed"
                  bordered
                  dataSource={doc.fields}
                  columns={fieldColumns(doc, di)}
                  pagination={false}
                />
                </Space>
              ),
            }))}
          />

          <div style={{ marginTop: 18, textAlign: 'right' }}>
            <Space>
              <Button onClick={() => setStep(0)}>上一步</Button>
              <Button type="primary" icon={<CheckOutlined />} disabled={unknownDocuments || correctionCount > 0} onClick={() => setStep(2)}>
                下一步：确认
              </Button>
            </Space>
          </div>
        </>
      )}

      {/* 步骤 3：确认创建 */}
      {step === 2 && parsed && (
        <Card title="确认并创建任务">
          <Descriptions column={2} bordered style={{ marginBottom: 16 }}>
            <Descriptions.Item label="任务编号">
              <Tag color="default">创建时自动生成</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="客户">
              {taskForm.customer_no
                ? `${taskForm.customer_no} · ${taskForm.customer_name ?? ''}`
                : '（未选择）'}
            </Descriptions.Item>
            <Descriptions.Item label="借款人">{taskForm.borrower}</Descriptions.Item>
            <Descriptions.Item label="提款">
              {taskForm.drawdown_currency} {taskForm.drawdown_amount == null ? '待核实' : fmt(taskForm.drawdown_amount)}
            </Descriptions.Item>
            <Descriptions.Item label="单据数">{parsed.documents.length} 份</Descriptions.Item>
          </Descriptions>

          <Result
            status={hasPending ? 'warning' : 'info'}
            title={hasPending ? (pendingCount ? `仍有 ${pendingCount} 项字段待核实` : '授信关联仍待核实') : '确认保存字段并创建任务？'}
            subTitle={hasPending ? '可以保存为待核实任务。未决字段和原始证据会保留，创建任务不代表审核通过。'
              : '平台将保存字段及核实记录，创建审核任务并执行规则核对。'}
            extra={
              <Space>
                <Button onClick={() => setStep(1)}>返回修改</Button>
                <Button
                  type="primary"
                  size="large"
                  icon={<CheckCircleOutlined />}
                  loading={creating}
                  onClick={confirmCreate}
                >
                  {hasPending ? '创建待核实任务' : '保存字段并创建任务'}
                </Button>
              </Space>
            }
          />
        </Card>
      )}

      {/* 定位原文：PDF 预览 + 高亮 */}
      <PdfSourceViewer
        visible={pdfVisible}
        source={pdfSource}
        onClose={() => setPdfVisible(false)}
      />
    </div>
  )
}
