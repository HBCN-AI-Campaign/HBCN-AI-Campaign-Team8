import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  App as AntdApp,
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  Col,
  Collapse,
  Empty,
  Form,
  Input,
  Modal,
  Progress,
  Result,
  Row,
  Space,
  Statistic,
  Table,
  Tabs,
  Tag,
  Tooltip,
} from 'antd'
import {
  ArrowLeftOutlined,
  AuditOutlined,
  CheckOutlined,
  DownloadOutlined,
  EditOutlined,
  EyeOutlined,
  FileDoneOutlined,
  MailOutlined,
  PaperClipOutlined,
  ReloadOutlined,
  RollbackOutlined,
  SendOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { useAuthStore } from '@/stores/auth'
import { api } from '@/api'
import { checkText, checkType, DIMENSION_NAME, fmt, statusText, statusType, typeLabel } from '@/utils'
import PdfSourceViewer from '@/components/PdfSourceViewer'
import type { AIPending, CheckResult, DocumentOut } from '@/types'
import { useChecks, toRows, type RowData } from './task-object/hooks/useChecks'
import { useAiSession } from './task-object/hooks/useAiSession'
import { usePdfLocator } from './task-object/hooks/usePdfLocator'
import { useSupplement } from './task-object/hooks/useSupplement'
import { useObjectGraph } from './task-object/hooks/useObjectGraph'
import ObjectGraph from './task-object/ObjectGraph'
import BusinessReviewPanel from './task-object/BusinessReviewPanel'

const statColor: Record<string, string> = {
  pass: 'var(--green)',
  fail: 'var(--red)',
  warn: 'var(--amber)',
}

export default function TaskObjectView() {
  const { code = '' } = useParams<{ code: string }>()
  const navigate = useNavigate()
  const { message } = AntdApp.useApp()
  const role = useAuthStore((s) => s.role)
  const displayName = useAuthStore((s) => s.displayName)
  const canReview = role === 'reviewer'

  const checks = useChecks(code, displayName, message)
  const {
    detail,
    setDetail,
    results,
    loading,
    acting,
    comment,
    setComment,
    mail,
    setMail,
    includeAttachments,
    setIncludeAttachments,
    counts,
    attachableDocs,
    downloadDoc,
    genMail,
    copyMail,
    load,
    refreshResults,
    patchFieldValue,
    doReturn,
    doComplete,
  } = checks

  const ai = useAiSession(
    code,
    async () => {
      await refreshResults()
    },
    (status) => setDetail((prev) => (prev ? { ...prev, status } : prev)),
  )

  const pdf = usePdfLocator(detail, message)
  const supp = useSupplement(code, (d) => setDetail(d), message)

  // 对象链路图 + 支付指令↔支持性材料匹配 + 节点状态灯
  const graph = useObjectGraph(detail, results)

  const canSupplement = !canReview && detail?.status === 'need_supplement'

  // 初始加载：详情 + 结果
  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [code])

  // 结果/详情/意见/附件选项变化时重新生成邮件草稿（对应 Vue 的 watch(results, genMail)）
  useEffect(() => {
    genMail()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [results, detail, comment, includeAttachments])

  const aiStatusTag = useMemo(() => {
    if (ai.aiWaiting) return { color: 'warning', label: '已挂起 · 等待处置' }
    if (ai.aiRunning) return { color: 'processing', label: '分析中' }
    if (ai.thoughtLines.length) return { color: 'success', label: '分析完成' }
    return { color: 'default', label: '待启动' }
  }, [ai.aiWaiting, ai.aiRunning, ai.thoughtLines.length])

  // ======= Tab 1：规则审核结果 =======
  // 字段编辑（经办人/审核人皆可更正抓取内容）
  const [editRow, setEditRow] = useState<{
    docId: number
    fieldKey: string
    label: string
  } | null>(null)
  const [editValue, setEditValue] = useState('')
  const [savingEdit, setSavingEdit] = useState(false)

  const openEdit = (row: RowData) => {
    const s = row.source
    if (!s?.doc_id || !s?.field_key) {
      message.info('该行无法定位到具体单据字段，暂不支持编辑')
      return
    }
    setEditRow({ docId: s.doc_id, fieldKey: s.field_key, label: row.label })
    setEditValue(row.value)
  }

  const saveEdit = async () => {
    if (!editRow) return
    setSavingEdit(true)
    try {
      const updated = await api.updateDocFields(code, editRow.docId, [
        { field_key: editRow.fieldKey, value: editValue },
      ])
      setDetail(updated) // 后端已自动重跑核对
      // 先即时把该字段显示值换成新值，再拉取最新核对结果
      patchFieldValue(editRow.docId, editRow.fieldKey, editValue)
      setEditRow(null)
      await refreshResults()
      message.success('已更新并自动重新核对')
    } catch {
      /* 拦截器已提示 */
    } finally {
      setSavingEdit(false)
    }
  }

  const detailColumns: ColumnsType<RowData> = [
    { title: '项目', dataIndex: 'label', width: 180 },
    {
      title: '值',
      dataIndex: 'value',
      render: (v: string, row) => {
        const editable = !!(row.source?.doc_id && row.source?.field_key)
        return (
          <span className="rule-value-cell">
            <span className={row.flag === 'bad' ? 'badvalue' : undefined}>{v}</span>
            {editable && (
              <Tooltip title="更正该字段抓取值">
                <Button
                  type="text"
                  size="small"
                  icon={<EditOutlined />}
                  className="rule-edit-btn"
                  onClick={() => openEdit(row)}
                />
              </Tooltip>
            )}
          </span>
        )
      },
    },
    {
      title: '原文定位',
      width: 120,
      align: 'center',
      render: (_, row) =>
        row.source?.pdf_file ? (
          <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => pdf.locateRow(row.source)}>
            定位原文
          </Button>
        ) : (
          <span className="muted">—</span>
        ),
    },
  ]

  const rulesTab = (
    <>
      <div className="tab-head">
        {results.length ? (
          <Space size="large">
            <Statistic title="通过" value={counts.pass || 0} valueStyle={{ color: statColor.pass }} />
            <Statistic title="不通过" value={counts.fail || 0} valueStyle={{ color: statColor.fail }} />
            <Statistic title="提示" value={counts.warn || 0} valueStyle={{ color: statColor.warn }} />
            <Statistic title="合计" value={results.length} />
          </Space>
        ) : (
          <span className="muted">尚未核对</span>
        )}
      </div>

      {!canReview && (
        <Alert
          type="info"
          showIcon
          style={{ margin: '10px 0' }}
          message="核对结果在任务创建时已自动生成。如发现抓取内容有误，可在下方结果中点击字段旁的编辑图标更正，系统将自动重新核对。"
        />
      )}

      <Row gutter={16} style={{ marginTop: 10 }}>
        {/* 左：规则核对结果（主内容，占更宽） */}
        <Col xs={24} lg={16}>
          {!results.length ? (
            <Empty description="暂无核对结果" />
          ) : (
            <Collapse
              accordion
              items={results.map((r: CheckResult) => ({
                key: r.rule_id,
                label: (
                  <span>
                    <Tag color={checkType(r.status)} style={{ marginRight: 10 }}>
                      {checkText(r.status)}
                    </Tag>
                    <span className="rname">{r.rule_name}</span>
                    <Tag style={{ marginLeft: 10 }}>
                      {r.dimension} · {DIMENSION_NAME[r.dimension]}
                    </Tag>
                    <code className="rid">{r.rule_id}</code>
                  </span>
                ),
                children: (
                  <div>
                    <div className="why">
                      <strong>判定说明：</strong>
                      {r.why}
                    </div>
                    {r.detail?.length > 0 && (
                      <Table<RowData>
                        columns={detailColumns}
                        dataSource={toRows(r.detail)}
                        size="small"
                        bordered
                        pagination={false}
                        style={{ margin: '10px 0' }}
                      />
                    )}
                    {r.suggestion && (
                      <div className="sug">
                        <strong>处理建议：</strong>
                        {r.suggestion}
                      </div>
                    )}
                  </div>
                ),
              }))}
            />
          )}
        </Col>

        {/* 右：对象链路树（可折叠；左侧规则很长时右侧可缩起避免失衡） */}
        <Col xs={24} lg={8}>
          <Collapse
            defaultActiveKey={['graph']}
            className="og-collapse"
            items={[
              {
                key: 'graph',
                label: <span className="og-collapse-title">🔗 对象链路（业务对象为主键）</span>,
                children: detail ? (
                  <ObjectGraph
                    nodes={graph.nodes}
                    supports={graph.supports}
                    onView={(docId) => pdf.viewDoc(docId)}
                  />
                ) : (
                  <Empty description="加载中…" />
                ),
              },
            ]}
          />
        </Col>
      </Row>
    </>
  )

  // ======= Tab 2：智能审核 =======
  const aiTab = (
    <>
      <div className="ai-head">
        <div className="ai-status">
          <Tag color={aiStatusTag.color}>{aiStatusTag.label}</Tag>
          {ai.aiTotal > 0 && (
            <span className="muted">
              已解析 {ai.aiParsed} / {ai.aiTotal}
            </span>
          )}
        </div>
        <Space>
          <Button
            type="primary"
            icon={<FileDoneOutlined />}
            loading={ai.aiRunning && !ai.aiWaiting}
            disabled={ai.aiRunning}
            onClick={() => void ai.aiStart()}
          >
            开始智能处理
          </Button>
          <Button icon={<ReloadOutlined />} disabled={ai.aiRunning} onClick={ai.aiRestart}>
            重跑
          </Button>
        </Space>
      </div>

      <Row gutter={16}>
        {/* 左：关联归集树 */}
        <Col span={10}>
          <Card
            size="small"
            title={
              <div className="card-head">
                <span>🌳 关联归集树</span>
                {ai.aiTotal > 0 && (
                  <Progress
                    percent={Math.round((ai.aiParsed / ai.aiTotal) * 100)}
                    strokeWidth={8}
                    style={{ width: 120 }}
                    size="small"
                  />
                )}
              </div>
            }
          >
            {!ai.aiTree.length ? (
              <Empty description="点击「开始智能处理」启动解析与归集" />
            ) : (
              <div className="tree">
                {ai.aiTree.map((n, i) => {
                  const st = ai.treeState[i]
                  const tagColor = st === 'done' ? 'success' : st === 'parsing' ? 'warning' : 'default'
                  const tagText = st === 'done' ? '已解析' : st === 'parsing' ? '解析中' : '待解析'
                  return (
                    <div key={n.doc_code} className="tnode" style={{ marginLeft: n.level * 16 }}>
                      <Tag color={tagColor}>{tagText}</Tag>
                      <span className="tcode">{n.doc_code}</span>
                      <span className="ttype">{n.type_code}</span>
                      {n.summary && <div className="tsum">{n.summary}</div>}
                    </div>
                  )
                })}
              </div>
            )}
          </Card>
        </Col>

        {/* 右：Agent 思考流 */}
        <Col span={14}>
          <Card size="small" title="💭 Agent 推理 · 思考流">
            <div ref={ai.thinkBoxRef} className="think">
              {!ai.thoughtLines.length ? (
                <div className="muted" style={{ textAlign: 'center', padding: 30 }}>
                  点击「开始智能处理」启动解析与思考…
                </div>
              ) : (
                ai.thoughtLines.map((l, i) => (
                  <div key={i} className={`th-line ${l.kind}`}>
                    <span className="th-tag">{l.tag}</span>
                    <span className="th-tx">{l.text}</span>
                  </div>
                ))
              )}
              {ai.aiWaiting && (
                <div className="th-line fail">
                  <span className="th-tag">挂起</span>
                  <span className="th-tx">已暂停，等待审核人在下方「需处理项」回复意见后继续…</span>
                </div>
              )}
            </div>
          </Card>
        </Col>
      </Row>

      {/* 需处理项 */}
      <Card
        size="small"
        style={{ marginTop: 16 }}
        title={
          <div className="card-head">
            <span>🚦 需处理项（人工处置队列）</span>
            {ai.openPendings.length > 0 && (
              <Button size="small" onClick={() => void ai.keepAll()}>
                全部保留异常并继续
              </Button>
            )}
          </div>
        }
      >
        {!ai.pendings.length ? (
          <Empty description="解析推理过程中命中的「不通过 / 提示」将在此排队" />
        ) : (
          ai.pendings.map((p: AIPending) => (
            <div key={p.id} className={`pend ${p.status}${ai.resolved[p.id] ? ' resolved' : ''}`}>
              <div className="pend-top">
                <Tag
                  color={p.status === 'fail' ? 'error' : p.status === 'special' ? 'processing' : 'warning'}
                >
                  {p.status === 'fail' ? '不通过' : p.status === 'special' ? '专项审核' : '提示'}
                </Tag>
                <span className="pend-name">{p.rule_name}</span>
                <Tag>
                  {p.dimension} · {DIMENSION_NAME[p.dimension]}
                </Tag>
              </div>
              <div className="pend-why">{p.why}</div>
              {p.suggestion && <div className="pend-sug">建议：{p.suggestion}</div>}

              {!ai.resolved[p.id] ? (
                <>
                  <Input.TextArea
                    value={ai.pendComment[p.id] || ''}
                    rows={2}
                    placeholder="审核意见（可选，将记入核对结论）"
                    style={{ margin: '8px 0' }}
                    onChange={(e) => ai.setPendCommentFor(p.id, e.target.value)}
                  />
                  <div className="pend-act">
                    {p.status === 'fail' && (
                      <>
                        <Button size="small" type="primary" onClick={() => void ai.resolve(p, 'accept')}>
                          确认无问题，继续
                        </Button>
                        <Button size="small" onClick={() => void ai.resolve(p, 'keep')}>
                          保留异常，继续
                        </Button>
                      </>
                    )}
                    {p.status === 'special' && (
                      <>
                        <Button size="small" type="primary" onClick={() => void ai.resolve(p, 'accept')}>
                          外部核验通过，判为通过
                        </Button>
                        <Button size="small" onClick={() => void ai.resolve(p, 'ack')}>
                          记录结论，继续
                        </Button>
                      </>
                    )}
                    {p.status === 'warn' && (
                      <Button size="small" onClick={() => void ai.resolve(p, 'ack')}>
                        已知悉，记录在案
                      </Button>
                    )}
                  </div>
                </>
              ) : (
                <div className={`pend-done ${ai.resolved[p.id]}`}>{ai.resolvedLabel(p.id)}</div>
              )}
            </div>
          ))
        )}

        <Alert
          type="info"
          showIcon
          style={{ marginTop: 14 }}
          message="说明：智能审核由后端 Agent 执行，命中「不通过」会暂停并等待审核人回复意见后继续；「提示」仅记录不阻断。处置结果同步到「规则审核结果」与「最终结果」。"
        />
      </Card>
    </>
  )

  // ======= Tab 3：最终结果 =======
  const attachColumns: ColumnsType<DocumentOut> = [
    { title: '单据号', dataIndex: 'doc_code', width: 150 },
    { title: '类型', render: (_, row) => typeLabel(row.type_code), width: 120 },
    {
      title: '原件',
      width: 90,
      align: 'center',
      render: (_, row) => (row.pdf_file ? <Tag color="success">PDF</Tag> : <Tag>无</Tag>),
    },
    {
      title: '操作',
      width: 170,
      align: 'center',
      render: (_, row) =>
        row.pdf_file ? (
          <Space size={4}>
            <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => pdf.viewDoc(row.id)}>
              查看
            </Button>
            <Button type="link" size="small" icon={<DownloadOutlined />} onClick={() => downloadDoc(row)}>
              下载
            </Button>
          </Space>
        ) : (
          <span className="muted">—</span>
        ),
    },
  ]

  const finalTab = (
    <Row gutter={16}>
      {canReview && (
        <Col span={14}>
          <Card size="small" title="回复邮件草稿">
            <Form labelCol={{ flex: '72px' }} labelAlign="left">
              <Form.Item label="收件人">
                <Input value={mail.to} onChange={(e) => setMail({ ...mail, to: e.target.value })} />
              </Form.Item>
              <Form.Item label="主题">
                <Input value={mail.subject} onChange={(e) => setMail({ ...mail, subject: e.target.value })} />
              </Form.Item>
              <Form.Item label="正文">
                <Input.TextArea
                  value={mail.body}
                  rows={14}
                  onChange={(e) => setMail({ ...mail, body: e.target.value })}
                />
              </Form.Item>
            </Form>
            <div style={{ textAlign: 'right' }}>
              <Space>
                <Button icon={<ReloadOutlined />} onClick={genMail}>
                  重新生成草稿
                </Button>
                <Button type="primary" icon={<SendOutlined />} onClick={() => void copyMail()}>
                  复制邮件内容
                </Button>
              </Space>
            </div>
          </Card>

          <Card
            size="small"
            style={{ marginTop: 16 }}
            title={
              <div className="attach-head">
                <span>
                  <PaperClipOutlined style={{ verticalAlign: -2 }} /> 附件原文（回复邮件随附）
                </span>
                <Checkbox
                  checked={includeAttachments}
                  onChange={(e) => setIncludeAttachments(e.target.checked)}
                >
                  在邮件正文中列出附件清单
                </Checkbox>
              </div>
            }
          >
            {!detail?.documents?.length ? (
              <Empty description="本任务暂无单据" imageStyle={{ height: 60 }} />
            ) : (
              <Table
                rowKey="id"
                columns={attachColumns}
                dataSource={detail.documents}
                size="small"
                bordered
                pagination={false}
              />
            )}
            <p className="attach-tip">
              共 {attachableDocs.length} 份可随附原件。回复邮件时请将上述 PDF 作为附件一并发送给经办人。
            </p>
          </Card>
        </Col>
      )}

      <Col span={canReview ? 10 : 24}>
        <Card size="small" title="审核决定">
          {canReview ? (
            <>
              <Alert
                type={counts.fail ? 'error' : 'success'}
                showIcon
                style={{ marginBottom: 14 }}
                message={
                  counts.fail
                    ? `存在 ${counts.fail} 项不通过，建议退回要求补件`
                    : '未发现不通过项，可审核通过'
                }
              />
              <Input.TextArea
                value={comment}
                rows={4}
                placeholder="审核意见 / 补件说明（将同步给经办人）"
                style={{ marginBottom: 12 }}
                onChange={(e) => setComment(e.target.value)}
              />
              <Button
                danger
                type="primary"
                style={{ width: '100%', marginBottom: 10 }}
                icon={<RollbackOutlined />}
                loading={acting}
                onClick={() => void doReturn()}
              >
                退回补件（催促经办人）
              </Button>
              <Button
                type="primary"
                style={{ width: '100%', background: 'var(--green)', borderColor: 'var(--green)' }}
                icon={<CheckOutlined />}
                loading={acting}
                onClick={() => void doComplete()}
              >
                审核通过，归档
              </Button>
            </>
          ) : canSupplement ? (
            <>
              <Alert
                type="warning"
                showIcon
                style={{ marginBottom: 14 }}
                message="审核人已退回，请根据下方补件意见更正字段或补充材料后提交。"
              />

              {detail?.review_comment && (
                <Card
                  size="small"
                  style={{ marginBottom: 14 }}
                  title={
                    <span>
                      <RollbackOutlined style={{ verticalAlign: -2 }} /> 审核人退回意见
                    </span>
                  }
                >
                  <div className="supp-comment">{detail.review_comment}</div>
                </Card>
              )}

              <Card size="small" style={{ marginBottom: 14 }} title="✏️ 字段补充 / 更正">
                <Form layout="vertical">
                  {detail!.documents.map((d) => (
                    <div key={d.id} className="supp-doc">
                      <div className="supp-doc-head">
                        <Tag>{d.doc_code}</Tag>
                        <span className="supp-doc-type">{typeLabel(d.type_code)}</span>
                      </div>
                      <Row gutter={12}>
                        {Object.entries(d.fields).map(([key, val]) => (
                          <Col span={12} key={key}>
                            <Form.Item label={key} style={{ marginBottom: 12 }}>
                              <Input
                                size="small"
                                value={supp.fieldVal(d.doc_code, key, val)}
                                onChange={(e) => supp.setField(d.doc_code, key, e.target.value)}
                              />
                            </Form.Item>
                          </Col>
                        ))}
                      </Row>
                    </div>
                  ))}
                </Form>
              </Card>

              <Card
                size="small"
                style={{ marginBottom: 14 }}
                title={
                  <span>
                    <PaperClipOutlined style={{ verticalAlign: -2 }} /> 补充文件
                  </span>
                }
              >
                <Space>
                  <Button
                    size="small"
                    icon={<PaperClipOutlined />}
                    onClick={() => {
                      const name = window.prompt('输入要补充的文件名（仅登记文件名）')
                      if (name) supp.setSuppFileList([...supp.suppFileList, { name }])
                    }}
                  >
                    选择要补充的文件
                  </Button>
                </Space>
                {supp.suppFileList.length > 0 && (
                  <div style={{ marginTop: 8 }}>
                    {supp.suppFileList.map((f, i) => (
                      <Tag
                        key={i}
                        closable
                        onClose={() => supp.setSuppFileList(supp.suppFileList.filter((_, j) => j !== i))}
                        style={{ marginBottom: 4 }}
                      >
                        {f.name}
                      </Tag>
                    ))}
                  </div>
                )}
                <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
                  可补充审核人要求的缺失单据（仅登记文件名，随补件说明一并提交）。
                </div>
              </Card>

              <Input.TextArea
                value={supp.suppNote}
                rows={3}
                placeholder="补件说明（说明本次补充/更正了什么，将同步给审核人）"
                style={{ marginBottom: 12 }}
                onChange={(e) => supp.setSuppNote(e.target.value)}
              />
              <Button
                type="primary"
                style={{ width: '100%' }}
                icon={<SendOutlined />}
                loading={supp.supping}
                onClick={() => void supp.doSupplement()}
              >
                提交补件（转交审核人复核）
              </Button>
            </>
          ) : (
            <Result
              status={detail?.status === 'completed' ? 'success' : 'info'}
              title={statusText(detail?.status || '', role)}
              subTitle={
                detail?.status === 'completed' ? '任务已审核通过并归档' : '审核进行中，请等待审核人处理'
              }
            />
          )}
        </Card>
      </Col>
    </Row>
  )

  const tabItems = [
    {
      key: 'rules',
      label: (
        <span className="tab-label">
          <FileDoneOutlined /> 规则审核结果
          {counts.fail > 0 && <Badge count={counts.fail} />}
        </span>
      ),
      children: rulesTab,
    },
    {
      key: 'business-review',
      label: <span className="tab-label"><AuditOutlined /> 业务审核</span>,
      children: <BusinessReviewPanel
        code={code}
        canReview={canReview && detail?.status !== 'completed'}
        onLocate={pdf.locateRow}
      />,
    },
    ...(canReview
      ? [
          {
            key: 'ai',
            label: (
              <span className="tab-label">
                ✨ 智能审核
                {ai.openPendings.length > 0 && <Badge count={ai.openPendings.length} color="orange" />}
              </span>
            ),
            children: aiTab,
          },
        ]
      : []),
    {
      key: 'final',
      label: (
        <span className="tab-label">
          <MailOutlined /> {canReview ? '最终结果（回复邮件）' : '最终结果'}
        </span>
      ),
      children: finalTab,
    },
  ]

  return (
    <div>
      <div
        className="page-head"
        style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', marginBottom: 12 }}
      >
        <div>
          <div className="title-row">
            <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate('/dashboard')}>
              返回工作台
            </Button>
            <h2>{code}</h2>
            {(counts.fail > 0 || counts.warn > 0) && (
              <Tag color={counts.fail > 0 ? 'error' : 'warning'} className="hdr-redline">
                <Badge color={counts.fail > 0 ? 'red' : 'orange'} />
                {counts.fail > 0 && `存在 ${counts.fail} 项红线`}
                {counts.fail > 0 && counts.warn > 0 && ' · '}
                {counts.warn > 0 && `${counts.warn} 项待复核`}
              </Tag>
            )}
            {detail?.customer_name && (
              <span className="hdr-customer">客户：{detail.customer_name}</span>
            )}
            {detail && <Tag color={statusType(detail.status)}>{statusText(detail.status, role)}</Tag>}
          </div>
          {detail && (
            <div className="hdr-facts">
              {graph.headerFacts.contractNo && (
                <span className="hf">合同号 <b>{graph.headerFacts.contractNo}</b></span>
              )}
              {graph.headerFacts.facilityAmount && (
                <span className="hf">额度 <b>{graph.headerFacts.facilityAmount}</b></span>
              )}
              {graph.headerFacts.purpose && (
                <span className="hf">用途 <b>{graph.headerFacts.purpose}</b></span>
              )}
              {graph.headerFacts.rate && (
                <span className="hf">利率 <b>{graph.headerFacts.rate}</b></span>
              )}
              {(graph.headerFacts.termStart || graph.headerFacts.termEnd) && (
                <span className="hf">
                  期限 <b>{graph.headerFacts.termStart ?? '—'} ~ {graph.headerFacts.termEnd ?? '—'}</b>
                </span>
              )}
              <span className="hf">
                提款金额 <b>{detail.drawdown_currency} {fmt(detail.drawdown_amount)}</b>
              </span>
              {graph.headerFacts.drawdownDate && (
                <span className="hf">放款日 <b>{graph.headerFacts.drawdownDate}</b></span>
              )}
              {graph.headerFacts.maturityDate && (
                <span className="hf">到期日 <b>{graph.headerFacts.maturityDate}</b></span>
              )}
              <span className="hf muted">单据 {detail.documents.length} 份</span>
            </div>
          )}
        </div>
      </div>

      <Card loading={loading}>
        <Tabs items={tabItems} />
      </Card>

      <PdfSourceViewer visible={pdf.pdfVisible} source={pdf.pdfSource} onClose={pdf.close} />

      {/* 字段更正弹窗（经办人/审核人皆可） */}
      <Modal
        title={`更正字段：${editRow?.label ?? ''}`}
        open={!!editRow}
        onCancel={() => setEditRow(null)}
        onOk={() => void saveEdit()}
        confirmLoading={savingEdit}
        okText="保存并重新核对"
        cancelText="取消"
        destroyOnHidden
      >
        <p className="muted" style={{ marginBottom: 8 }}>
          修改抓取到的识别值。保存后系统将自动重新核对并刷新判定结果。
        </p>
        <Input
          value={editValue}
          onChange={(e) => setEditValue(e.target.value)}
          onPressEnter={() => void saveEdit()}
          placeholder="请输入正确的值"
          autoFocus
        />
      </Modal>
    </div>
  )
}
