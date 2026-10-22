import { useEffect, useRef, useState } from 'react'
import { Bubble, Sender, ThoughtChain } from '@ant-design/x'
import { Alert, Button, Checkbox, Collapse, ConfigProvider, Drawer, Empty, Input, Popconfirm, Select, Space, Tag } from 'antd'
import { answer, errorMessage, externalLink, getCapabilities, getContent, getDocument, getDocuments, originalPath, readerPath, retrieve, uploadDocument, withdrawDocument } from './api'
import type { Capabilities, DocumentContent, Evidence, KnowledgeDocument, LegalContext, Purpose, Request, Result, Scope, Step } from './api'
import QualityReview, { qualityReason } from './QualityReview'

interface Message { id: number; role: 'user' | 'assistant'; content: string; result?: Result; steps: Step[]; pending?: boolean; error?: string }
const SCOPES = [{ value: 'all', label: '全部资料' }, { value: 'business_rules', label: '内部业务规则' }, { value: 'law', label: '法规' }, { value: 'project_design', label: '项目设计' }]
const LEGAL_STATUS: Record<string, string> = { source_changed: '依据已变化，需要重新核验', not_checked: '尚未核验', not_required: '本轮未要求法规核验', reference_only: '仅资料参考', legal_evidence_required: '缺少法规原文', context_required: '缺少本案条件', review_required: '需要法规复核记录', blocked: '适用条件未通过', reviewed_constraints_match: '已复核条件匹配，仍需业务审批' }
const SOURCE_STATUS: Record<string, string> = { provided_unverified: '快照已提供，真实性未核实', changed: '依据已变化，需要重新检索', ok: '本次调用完成', partial: '部分完成', unavailable: '不可用', disabled: '未启用', time_budget: '时间预算耗尽', blocked_scope: '范围未授权' }

function SourceReader({ source }: { source: Evidence }) {
  const [content, setContent] = useState<DocumentContent>()
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const path = readerPath(source.reader_url)
  useEffect(() => {
    setContent(undefined); setError('')
    if (!path) { setLoading(false); return }
    const controller = new AbortController()
    setLoading(true)
    getContent(path, controller.signal).then(content => { if (!controller.signal.aborted) setContent(content) }).catch(error => {
      if (!controller.signal.aborted) setError(errorMessage(error))
    }).finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [source, path])
  const external = externalLink(source.source_url)
  const original = content?.document.source_available ? originalPath(source.document_id) : null
  return <>
    <h3>{source.document_name}</h3>
    <Space wrap><Tag>引用 {source.citation}</Tag>{source.page != null && <Tag>第 {source.page} 页</Tag>}
      {original && <a href={original} target="_blank" rel="noopener noreferrer">打开原始文件</a>}
      {external && <a href={external} target="_blank" rel="noopener noreferrer">打开外部来源</a>}
    </Space>
    <h4>本轮实际引用片段</h4><pre className="original-text" data-testid="source-content">{source.content}</pre>
    {source.metadata.excerpt != null && <Alert type="info" message="此处是原文窗口，可能只覆盖父片段的一部分；不能视为已读取全文。" />}
    {source.metadata.source_type === 'pkulaw' && <Alert type="warning" message="外部法规片段；完整正文、附件与本案适用范围须按授权及复核状态确认。" />}
    {source.metadata.source_type === 'web_context' && <Alert type="warning" message="调用方提供的网页文本快照；本服务未核实网页真实性或全文完整性，不能作为本案法规或审批依据。" description={`采集时间：${String(source.metadata.captured_at || '未知')}；范围：${source.metadata.capture_completeness === 'selection' ? '选中片段' : '调用方声明的页面文本'}。外部链接可能已变化。`} />}
    {loading && <p role="status">正在读取已入库原文…</p>}
    {error && <Alert type="error" message={error} />}
    {content && <><h4>已入库解析原文</h4><p>以下为解析文本；版式和附件请对照原始文件。</p>{content.pages.map((page, index) => <section className="parsed-page" key={index}>
      <b>{page.page == null ? `段落 ${index + 1}` : `第 ${page.page} 页`}</b><pre className="original-text">{page.text}</pre>
    </section>)}</>}
    {!path && !external && <p>本来源未提供可打开的原文地址，当前仅展示返回片段。</p>}
  </>
}

function ResultDetails({ result }: { result: Result }) {
  const sufficient = result.grounding === 'cited' || result.evidence_status === 'sufficient'
  return <div className="result-details">
    <Space wrap><Tag color={sufficient ? 'blue' : 'orange'}>{sufficient ? '本轮依据覆盖检查通过' : '依据不足或需澄清'}</Tag>
      <Tag>检索 {result.retrieval_rounds} 轮</Tag><Tag>{LEGAL_STATUS[result.legal_applicability?.status || 'not_checked'] || '适用性待核验'}</Tag></Space>
    {result.missing?.length > 0 && <Alert type="warning" message="仍缺少的条件或依据" description={<ul>{result.missing.map((text, i) => <li key={i}>{text}</li>)}</ul>} />}
    {result.warnings?.length > 0 && <Alert type="info" message="本轮局限" description={<ul>{result.warnings.map((text, i) => <li key={i}>{text}</li>)}</ul>} />}
    <Collapse size="small" ghost items={[{ key: 'status', label: '来源与核验状态', children: <>
      {Object.entries(result.source_status || {}).map(([source, status]) => <p key={source}>{source === 'pkulaw' ? '北大法宝' : source === 'knowledge_base' ? '知识库' : source === 'web_context' ? '网页上下文' : source}：{SOURCE_STATUS[status] || status}</p>)}
      <p>重排：{result.rerank_status === 'disabled' ? '未启用专用模型' : result.rerank_status}</p>
      <p>答复支持核验：{result.answer_verification?.status || '增强检索不生成答复'}</p>
      <p>停止原因：{result.stop_reason}</p><p>相关性与短引核验不能代替法律、信贷或放款审批。</p>
    </> }]} />
  </div>
}

function Library({ capabilities }: { capabilities: Capabilities }) {
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([])
  const [scope, setScope] = useState<Exclude<Scope, 'all'>>('business_rules')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [active, setActive] = useState<KnowledgeDocument>()
  const [reviewing, setReviewing] = useState<KnowledgeDocument>()
  const controller = useRef<AbortController>()
  async function refresh() {
    try { setError(''); setDocuments((await getDocuments(controller.current?.signal)).documents) } catch (error) { if (!controller.current?.signal.aborted) setError(errorMessage(error)) }
  }
  useEffect(() => { controller.current = new AbortController(); void refresh(); return () => controller.current?.abort() }, [])
  useEffect(() => {
    if (!active || !['queued', 'processing'].includes(active.state || '')) return
    const abort = new AbortController()
    const timer = window.setTimeout(() => {
      getDocument(active.id, abort.signal).then(doc => { setActive(doc); void refresh() }).catch(error => {
        if (!abort.signal.aborted) { setError(errorMessage(error)); setActive(undefined) }
      })
    }, 1500)
    return () => { window.clearTimeout(timer); abort.abort() }
  }, [active])
  async function submit(file: File) {
    setError('')
    const extension = '.' + file.name.split('.').pop()?.toLowerCase()
    if (!capabilities.supported_file_extensions.includes(extension)) { setError('此文件类型尚未受支持。'); return }
    if (file.size === 0 || file.size > capabilities.max_upload_bytes) { setError('文件为空或超过服务上传大小限制。'); return }
    setBusy(true)
    try { const result = await uploadDocument(file, scope, controller.current?.signal); setActive(result.document); await refresh() }
    catch (error) { if (!controller.current?.signal.aborted) setError(errorMessage(error)) }
    finally { if (!controller.current?.signal.aborted) setBusy(false) }
  }
  async function withdraw(document: KnowledgeDocument) {
    setBusy(true); setError('')
    try {
      const result = await withdrawDocument(document, controller.current?.signal)
      setActive(result.document); await refresh()
    } catch (error) { if (!controller.current?.signal.aborted) setError(errorMessage(error)) }
    finally { if (!controller.current?.signal.aborted) setBusy(false) }
  }
  return <>
    <p>上传到选定共享知识范围；本入口尚不支持任务私有文件或历史案件。请先确认资料可在该知识库使用。</p>
    <p>{capabilities.document_quality_review_scopes?.length ? `本机解析复核操作员：${capabilities.document_quality_review_subject}；仅可处理已授权范围。` : '本工作台尚未配置解析复核操作员。待复核资料请由部署者配置授权；刷新不会自动放行。'}</p>
    <Space wrap><Select aria-label="入库范围" value={scope} options={SCOPES.filter(option => option.value !== 'all')} onChange={setScope} disabled={busy} />
      <label className="file-upload">{busy ? '正在提交…' : '选择文件入库'}<input aria-label="选择文件入库" type="file" disabled={busy || !capabilities.document_ingestion}
        accept={capabilities.supported_file_extensions.join(',')} onChange={event => { const file = event.target.files?.[0]; if (file) void submit(file); event.target.value = '' }} /></label>
      <Button onClick={() => void refresh()}>刷新文档状态</Button></Space>
    {error && <Alert type="error" message={error} />}
    {active && <Alert type={['failed', 'quarantined'].includes(active.state || '') ? 'error' : active.state === 'quality_review' ? 'warning' : 'info'} message={`${active.name}：${active.state} / ${active.stage || ''}`} description={active.error || (active.state === 'quality_review' ? '解析结果尚未核验，当前不能用于检索；请由获授权审核人逐页核对原件后处理。' : '仅 ready 的文档可用于检索；关闭面板不会撤销已提交的入库任务。')} />}
    <div className="document-list">{documents.map(doc => <article key={doc.id}><b>{doc.name}</b><p>{doc.scope} · {doc.state === 'withdrawn' ? '已撤回' : doc.state || doc.run || '状态未知'} · {doc.chunk_count ?? '未知'} 个片段</p>
      {doc.quality && <p>解析检查：{doc.quality.review_status === 'approved' ? '本版解析原文复核已记录' : doc.quality.status === 'mechanically_checked' ? '基础字符检查完成，仍需核对完整性' : doc.quality.status === 'quarantined' ? '解析已隔离，不参与检索' : '解析待原文复核'} · {doc.quality.unit_count} 个解析单元；不代表 OCR 准确率或业务审批。</p>}
      {doc.quality && [...doc.quality.blockers, ...doc.quality.review_reasons].map(reason => <p key={reason}>{qualityReason(reason)}</p>)}
      {capabilities.document_quality_review_scopes?.includes(doc.scope) && ['quality_review', 'quarantined', 'failed', 'ready'].includes(doc.state || '') && <Button onClick={() => setReviewing(doc)}>查看解析与复核</Button>}
      {doc.sha256 && doc.state !== 'withdrawn' && <Popconfirm title="确认撤回这份资料？" description="停止检索和原文访问，保留存档；恢复使用需要重新复核版本。" okText="确认撤回" cancelText="取消" onConfirm={() => withdraw(doc)}>
        <Button danger disabled={busy}>撤回资料</Button></Popconfirm>}
    </article>)}</div>
    {documents.length === 0 && <Empty description="尚无可展示的文档" />}
    <Drawer title="解析原文对照与复核" open={Boolean(reviewing)} onClose={() => setReviewing(undefined)} width={900} destroyOnClose>
      {reviewing && <QualityReview document={reviewing} onChanged={doc => { setActive(doc); setReviewing(undefined); void refresh() }} />}
    </Drawer>
  </>
}

export default function App() {
  const [capabilities, setCapabilities] = useState<Capabilities>()
  const [connectionError, setConnectionError] = useState('')
  const [mode, setMode] = useState<'answer' | 'retrieval'>('answer')
  const [scope, setScope] = useState<Scope>('all')
  const [purpose, setPurpose] = useState<Purpose>('reference')
  const [legal, setLegal] = useState<LegalContext>({ business_date: '', jurisdiction: '', subject_type: '', business_type: '' })
  const [pkulaw, setPkulaw] = useState(false)
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState<Message[]>([])
  const [busy, setBusy] = useState(false)
  const [sources, setSources] = useState<Evidence[]>([])
  const [selected, setSelected] = useState<Evidence>()
  const [showSources, setShowSources] = useState(false)
  const [library, setLibrary] = useState(false)
  const abort = useRef<AbortController>()
  const sequence = useRef(0)
  const chat = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const controller = new AbortController()
    getCapabilities(controller.signal).then(setCapabilities).catch(error => { if (!controller.signal.aborted) setConnectionError(errorMessage(error)) })
    return () => { controller.abort(); abort.current?.abort() }
  }, [])
  useEffect(() => { chat.current?.scrollTo?.({ top: chat.current.scrollHeight }) }, [messages])
  const compatible = capabilities?.workbench_contract_version === 1
  const allowed = Boolean(compatible && capabilities && (mode === 'answer' ? capabilities.answer_generation : capabilities.enhanced_retrieval))
  const legalComplete = purpose === 'reference' || Object.values(legal).every(value => value.trim())
  function openSources(items: Evidence[], source?: Evidence) { setSources(items); setSelected(source); setShowSources(true) }
  async function ask(text: string) {
    const query = text.trim()
    if (!query || query.length > 4000 || busy || !allowed || !legalComplete || abort.current) return
    const controller = new AbortController()
    abort.current = controller
    const userId = ++sequence.current, assistantId = ++sequence.current
    const payload: Request = { query, scope, top_k: 5, sources: pkulaw && ['all', 'law'].includes(scope) ? ['knowledge_base', 'pkulaw'] : ['knowledge_base'], purpose,
      ...(purpose === 'case_assessment' ? { legal_context: legal } : {}),
      conversation: messages.filter(message => message.role === 'user' && message.content.length <= 4000).slice(-12).map(message => ({ role: 'user', content: message.content })) }
    setInput(''); setBusy(true)
    setMessages(previous => [...previous, { id: userId, role: 'user', content: query, steps: [] }, { id: assistantId, role: 'assistant', content: '', steps: [], pending: true }])
    function update(change: Partial<Message>) { setMessages(previous => previous.map(message => message.id === assistantId ? { ...message, ...change } : message)) }
    let timedOut = false
    const timeout = window.setTimeout(() => { timedOut = true; controller.abort() }, 300_000)
    try {
      const result = mode === 'answer' ? await answer(payload, controller.signal, step => {
        setMessages(previous => previous.map(message => message.id !== assistantId ? message : { ...message, steps: [...message.steps.filter(item => item.key !== step.key), step] }))
      }) : await retrieve(payload, controller.signal)
      if (controller.signal.aborted) throw new DOMException('Aborted', 'AbortError')
      update({ result, pending: false, content: result.answer ?? result.clarification_question ?? `返回 ${result.sources.length} 处原文片段。增强检索未生成最终业务答复。` })
    } catch (error) {
      update({ pending: false, error: controller.signal.aborted ? timedOut ? '本轮接收超时，未获得完整答复。' : '已停止接收。本轮未获得完整答复，服务端可能仍在处理。' : errorMessage(error) })
    } finally { window.clearTimeout(timeout); abort.current = undefined; setBusy(false) }
  }
  function renderContent(message: Message) {
    return <div className="answer">{message.content.split(/(\[\d+\])/g).map((part, index) => {
      const match = /^\[(\d+)\]$/.exec(part)
      const source = match && message.result?.sources.find(source => source.citation === Number(match[1]))
      return source ? <button className="cite" key={index} aria-label={`打开引用 ${source.citation}`} onClick={() => openSources(message.result!.sources, source)}>{part}</button> : <span key={index}>{part}</span>
    })}</div>
  }
  return <ConfigProvider theme={{ token: { colorPrimary: '#2f5fd0', borderRadius: 10 } }}><div className="app live-app">
    <header className="topbar"><div className="brand"><span className="logo">H</span><span><b>HBCN 知识库工作台</b><small>Agentic RAG · 原文可追溯</small></span></div>
      <Space wrap><Button onClick={() => setLibrary(true)} disabled={!compatible || !capabilities?.document_ingestion}>资料入库</Button><Button disabled={busy} onClick={() => { setMessages([]); setShowSources(false) }}>新会话</Button></Space></header>
    {connectionError && <Alert type="error" message={connectionError} />}
    <div className="query-controls"><Space wrap>
      <Select aria-label="查询模式" value={mode} disabled={busy} onChange={setMode} options={[{ value: 'answer', label: '引用问答' }, { value: 'retrieval', label: '增强检索（仅原文）' }]} />
      <Select aria-label="检索范围" value={scope} options={SCOPES.filter(option => option.value === 'all' || capabilities?.supported_scopes.includes(option.value))} disabled={busy} onChange={value => { setScope(value); if (!['law', 'all'].includes(value)) setPkulaw(false) }} />
      <Select aria-label="查询用途" value={purpose} disabled={busy} onChange={setPurpose} options={[{ value: 'reference', label: '资料参考' }, { value: 'case_assessment', label: '本案法规判断' }]} />
      <Checkbox checked={pkulaw} disabled={busy || !capabilities?.external_law_mcp || !['all', 'law'].includes(scope)} onChange={event => setPkulaw(event.target.checked)}>同时检索北大法宝{!capabilities?.external_law_mcp && '（未启用）'}</Checkbox>
    </Space><p className="control-hint">{capabilities ? '服务接口可访问；模型、索引与外部来源可用性以本次调用结果为准。' : '正在检查服务接口…'} 资料参考不作本案法律或放款批准。</p>
    {purpose === 'case_assessment' && <div className="legal-fields">
      <label>业务日期<Input type="date" aria-label="业务日期" value={legal.business_date} disabled={busy} onChange={event => setLegal({ ...legal, business_date: event.target.value })} /></label>
      <label>司法辖区<Input aria-label="司法辖区" placeholder="如 CN、HK" value={legal.jurisdiction} disabled={busy} onChange={event => setLegal({ ...legal, jurisdiction: event.target.value.toUpperCase() })} /></label>
      <label>主体类型<Input aria-label="主体类型" placeholder="使用已复核分类值" value={legal.subject_type} disabled={busy} onChange={event => setLegal({ ...legal, subject_type: event.target.value })} /></label>
      <label>业务类型<Input aria-label="业务类型" placeholder="使用已复核分类值" value={legal.business_type} disabled={busy} onChange={event => setLegal({ ...legal, business_type: event.target.value })} /></label>
      <p>四项均需明确，且须有服务端法规复核记录；模型不能猜测缺失条件。</p>
    </div>}</div>
    <main className="live-chat" ref={chat}>
      {messages.length === 0 && <div className="welcome"><h2>查证业务资料，结论可溯源</h2><p>输入具体问题，查看本轮检索依据、缺口与原文。金额和币种将保留在问题中。</p><Button disabled={!allowed || busy || !legalComplete} onClick={() => void ask('支付指令金额与支持单据不一致时应如何处理？')}>查询金额不一致的处理依据</Button></div>}
      {messages.map(message => <div className="live-message" key={message.id}><Bubble placement={message.role === 'user' ? 'end' : 'start'} avatar={{ children: message.role === 'user' ? '我' : 'H' }}
        header={message.role === 'assistant' ? '知识库助手' : undefined} content={message.content} messageRender={() => <>
          {message.steps.length > 0 && <Collapse ghost size="small" items={[{ key: 'steps', label: message.pending ? '正在执行检索与核对' : '查看执行记录', children: <ThoughtChain items={message.steps.map(step => ({ key: step.key, title: step.label, status: step.status === 'running' ? 'pending' : 'success' }))} /> }]} />}
          {message.pending && <p role="status">正在处理；以服务返回的执行事件为准…</p>}{renderContent(message)}
          {message.error && <Alert type="error" message={message.error} />}
          {message.result && <><ResultDetails result={message.result} />{message.result.sources.length > 0 && <Button onClick={() => openSources(message.result!.sources)}>引用来源（{message.result.sources.length}）</Button>}</>}
        </>} /></div>)}
    </main>
    <footer className="live-composer">{!allowed && capabilities && <Alert type="warning" message={compatible ? '当前服务未开放此模式，请检查服务引擎配置。' : '工作台与后端接口版本不匹配，需要部署匹配版本后使用。'} />}
      <Sender value={input} onChange={setInput} onSubmit={text => void ask(text)} loading={busy} readOnly={busy}
        actions={(original, { components }) => busy ? <components.LoadingButton aria-label="停止接收" title="停止接收" /> : original}
        disabled={!allowed || !legalComplete} onCancel={() => abort.current?.abort()} placeholder="描述要核对的问题，Shift+Enter 换行" />
      {input.length > 4000 && <p role="alert">问题超过 4000 字符，请拆分后发送。</p>}
    </footer>
    <Drawer title="本轮引用来源" open={showSources} onClose={() => setShowSources(false)} width="min(720px, 100vw)">
      {selected ? <><Button onClick={() => setSelected(undefined)}>返回本轮来源列表</Button><SourceReader source={selected} /></> : sources.map(source => <button key={source.citation} className="live-source" onClick={() => setSelected(source)}>
        <b>[{source.citation}] {source.document_name}</b><span>{source.page == null ? '未提供页码' : `第 ${source.page} 页`} · {source.metadata.source_type === 'pkulaw' ? '北大法宝' : '知识库'}</span><p>{source.content.slice(0, 240)}{source.content.length > 240 ? '…' : ''}</p></button>)}
    </Drawer>
    <Drawer title="资料入库与处理状态" open={library} onClose={() => setLibrary(false)} width="min(720px, 100vw)" destroyOnClose>{capabilities && <Library capabilities={capabilities} />}</Drawer>
  </div></ConfigProvider>
}
