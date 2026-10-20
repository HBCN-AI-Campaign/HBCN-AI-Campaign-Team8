import { useState } from 'react'
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
import type { ParseResult, ParsedDocument, ParsedField, FieldSource } from '@/types'
import { fmt, TYPE_LABEL } from '@/utils'
import PdfSourceViewer from '@/components/PdfSourceViewer'

// 与后端 parse_agent 对齐的文件名→类型推断（仅用于上传列表预览）
const HINTS: [string[], string][] = [
  [['贷款合同', '授信函', 'facility', 'fol'], 'FACILITY_LETTER'],
  [['授信请求', '提款', '使用申请', 'drawdown'], 'DRAWDOWN_INSTRUCTION'],
  [['支付', '汇款', 'payment'], 'PAYMENT_INSTRUCTION'],
  [['商务合同', '商业合同', 'contract'], 'COMMERCIAL_CONTRACT'],
  [['订单', 'order'], 'COMMERCIAL_ORDER'],
  [['运单', '提单', 'waybill'], 'WAYBILL'],
  [['报关', 'customs'], 'CUSTOMS_DECLARATION'],
  [['形式发票', '发票', 'invoice'], 'PROFORMA_INVOICE'],
]
function guessType(name: string): string {
  const n = name.toLowerCase()
  for (const [keys, t] of HINTS) if (keys.some((k) => n.includes(k.toLowerCase()))) return t
  return ''
}

// 快捷键：从 sample_pdfs 载入 8 个真实 PDF（走和真人上传完全一致的 multipart 流程）
// 每项 [前端呈现的模板名(决定解析类型), 服务器样本文件名(真实二进制来源)]
const TEMPLATE_FILES: [string, string][] = [
  ['贷款合同.pdf', 'facility_letter.pdf'],
  ['授信请求.pdf', 'drawdown_instruction_zn.pdf'],
  ['提款指令.pdf', 'drawdown_instruction_zn.pdf'],
  ['支付指令-01.pdf', 'payment_instruction.pdf'],
  ['支付指令-02.pdf', 'payment_instruction.pdf'],
  ['商务合同.pdf', 'commercial_contract.pdf'],
  ['形式发票.pdf', 'invoice.pdf'],
  ['报关单.pdf', 'customs_declaration.pdf'],
]

interface TaskForm {
  task_code: string
  borrower: string
  drawdown_currency: string
  drawdown_amount: number
}

function lowConfCount(doc: ParsedDocument): number {
  return doc.fields.filter((f) => f.confidence < 0.8).length
}

export default function CreateTaskView() {
  const navigate = useNavigate()
  const { message } = App.useApp()

  const [step, setStep] = useState(0)
  const [files, setFiles] = useState<File[]>([])
  const [fileList, setFileList] = useState<UploadFile[]>([])
  const [parsing, setParsing] = useState(false)
  const [creating, setCreating] = useState(false)
  const [loadingTpl, setLoadingTpl] = useState(false)
  const [parsed, setParsed] = useState<ParseResult | null>(null)
  const [activeDocs, setActiveDocs] = useState<string[]>([])
  const [taskForm, setTaskForm] = useState<TaskForm>({
    task_code: '',
    borrower: '',
    drawdown_currency: '',
    drawdown_amount: 0,
  })

  // 定位原文（PDF 预览 + 高亮）
  const [pdfVisible, setPdfVisible] = useState(false)
  const [pdfSource, setPdfSource] = useState<FieldSource | null>(null)

  const goBack = () => navigate('/dashboard')

  // 上传列表变化（阻止自动上传，手动收集 File）
  const onUploadChange = (info: { fileList: UploadFile[] }) => {
    setFileList(info.fileList)
    setFiles(info.fileList.map((f) => f.originFileObj as File).filter(Boolean))
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

  // 开始智能识别
  const doParse = async () => {
    setParsing(true)
    try {
      const res = await api.parseFiles(files)
      setParsed(res)
      setTaskForm({
        task_code: res.suggested_task_code,
        borrower: res.suggested_borrower,
        drawdown_currency: res.suggested_currency,
        drawdown_amount: res.suggested_amount,
      })
      setActiveDocs(res.documents.map((_, i) => String(i)))
      setStep(1)
      message.success(`识别完成：共 ${res.documents.length} 份单据`)
    } catch {
      /* 拦截器已提示 */
    } finally {
      setParsing(false)
    }
  }

  // 字段编辑：不可变更新 parsed
  const updateField = (docIdx: number, fieldIdx: number, value: ParsedField['value']) => {
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

  // 确认创建
  const confirmCreate = async () => {
    if (!parsed) return
    setCreating(true)
    try {
      const documents = parsed.documents.map((d) => ({
        doc_code: d.doc_code,
        type_code: d.type_code,
        fields: Object.fromEntries(d.fields.map((f) => [f.key, f.value])),
        pdf_file: d.pdf_file ?? null,
        field_sources: Object.fromEntries(
          d.fields.filter((f) => f.source).map((f) => [f.key, f.source]),
        ),
      }))
      await api.createTask({
        task_code: taskForm.task_code,
        borrower: taskForm.borrower,
        drawdown_currency: taskForm.drawdown_currency,
        drawdown_amount: taskForm.drawdown_amount,
        documents,
      })
      message.success('任务已创建，可交审核人员核对')
      navigate(`/tasks/${encodeURIComponent(taskForm.task_code)}`)
    } catch {
      /* 拦截器已提示（如任务编号重复 409）*/
    } finally {
      setCreating(false)
    }
  }

  // 上传列表预览表格列
  const uploadColumns: TableColumnsType<File> = [
    { title: '文件名', dataIndex: 'name' },
    {
      title: '推断类型',
      width: 200,
      render: (_, row) => <Tag>{TYPE_LABEL[guessType(row.name)] || '未识别(可在下一步调整)'}</Tag>,
    },
    {
      title: '大小',
      width: 120,
      render: (_, row) => `${(row.size / 1024).toFixed(0)} KB`,
    },
  ]

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
            <InputNumber
              controls={false}
              value={row.value as number}
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
      title: '置信度',
      width: 110,
      render: (_, row) => (
        <Tag color={row.confidence < 0.8 ? 'warning' : 'success'}>
          {(row.confidence * 100).toFixed(0)}%
        </Tag>
      ),
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
          <p>上传材料 → 智能识别字段 → 经办人复核确认 → 创建任务</p>
        </div>
        <Button icon={<ArrowLeftOutlined />} onClick={goBack}>
          返回工作台
        </Button>
      </div>

      <Steps
        current={step}
        style={{ marginBottom: 20 }}
        items={[{ title: '上传材料' }, { title: '复核识别结果' }, { title: '确认创建' }]}
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
              onClick={loadTemplate}
            >
              一键载入模板 8 个文件
            </Button>
          }
        >
          <Upload.Dragger
            multiple
            fileList={fileList}
            beforeUpload={() => false}
            onChange={onUploadChange}
          >
            <p className="ant-upload-drag-icon">
              <InboxOutlined />
            </p>
            <p className="ant-upload-text">点击或拖拽上传材料</p>
            <p className="ant-upload-hint">支持 PDF / Word / 图片，可多选</p>
          </Upload.Dragger>

          <p style={{ fontSize: 13, color: 'var(--muted)', marginTop: 10 }}>
            材料类型：贷款合同 · 授信请求 · 提款指令 · 支付指令 · 商务合同 · 形式发票 · 报关单 · 运单
          </p>

          {files.length > 0 && (
            <Table<File>
              rowKey="name"
              size="small"
              style={{ marginTop: 12 }}
              dataSource={files}
              columns={uploadColumns}
              pagination={false}
            />
          )}

          <div style={{ marginTop: 18, textAlign: 'right' }}>
            <Button
              type="primary"
              icon={<SendOutlined />}
              loading={parsing}
              disabled={!files.length}
              onClick={doParse}
            >
              开始智能识别（{files.length} 个文件）
            </Button>
          </div>
        </Card>
      )}

      {/* 步骤 2：复核编辑 */}
      {step === 1 && parsed && (
        <>
          <Card title="任务基本信息（可修改）" style={{ marginBottom: 16 }}>
            <Form layout="inline">
              <Form.Item label="任务编号">
                <Input
                  style={{ width: 240 }}
                  value={taskForm.task_code}
                  onChange={(e) => setTaskForm((s) => ({ ...s, task_code: e.target.value }))}
                />
              </Form.Item>
              <Form.Item label="借款人">
                <Input
                  style={{ width: 260 }}
                  value={taskForm.borrower}
                  onChange={(e) => setTaskForm((s) => ({ ...s, borrower: e.target.value }))}
                />
              </Form.Item>
              <Form.Item label="提款币种">
                <Input
                  style={{ width: 110 }}
                  value={taskForm.drawdown_currency}
                  onChange={(e) =>
                    setTaskForm((s) => ({ ...s, drawdown_currency: e.target.value }))
                  }
                />
              </Form.Item>
              <Form.Item label="提款金额">
                <InputNumber
                  min={0}
                  step={100000}
                  controls={false}
                  style={{ width: 180 }}
                  value={taskForm.drawdown_amount}
                  onChange={(v) => setTaskForm((s) => ({ ...s, drawdown_amount: v ?? 0 }))}
                />
              </Form.Item>
            </Form>
          </Card>

          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 14 }}
            message="黄色高亮字段为识别置信度较低项，请经办人重点复核；所有字段均可直接修改。"
          />

          <Collapse
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
                <Table<ParsedField>
                  rowKey="key"
                  size="small"
                  bordered
                  dataSource={doc.fields}
                  columns={fieldColumns(doc, di)}
                  pagination={false}
                />
              ),
            }))}
          />

          <div style={{ marginTop: 18, textAlign: 'right' }}>
            <Space>
              <Button onClick={() => setStep(0)}>上一步</Button>
              <Button type="primary" icon={<CheckOutlined />} onClick={() => setStep(2)}>
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
            <Descriptions.Item label="任务编号">{taskForm.task_code}</Descriptions.Item>
            <Descriptions.Item label="借款人">{taskForm.borrower}</Descriptions.Item>
            <Descriptions.Item label="提款">
              {taskForm.drawdown_currency} {fmt(taskForm.drawdown_amount)}
            </Descriptions.Item>
            <Descriptions.Item label="单据数">{parsed.documents.length} 份</Descriptions.Item>
          </Descriptions>

          <Result
            status="info"
            title="确认识别结果无误？"
            subTitle="点击「确认无误」后，平台将把上述字段写入数据库并创建审核任务，随后可交审核人员核对。"
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
                  确认无误，创建任务
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
