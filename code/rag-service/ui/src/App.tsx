import { useEffect, useRef, useState } from 'react'
import { getCapabilities } from './api'

interface DemoSource {
  name: string
  page: number
  score: number
  hit: string
  snippet: string
}

interface Message {
  id: number
  role: 'user' | 'assistant'
  content: string
  tag?: string
  streaming?: boolean
  sources?: DemoSource[]
}

type PanelState = 'none' | 'list' | 'doc'

const SOURCES: DemoSource[] = [
  { name: '测试版授信函 - 中文空白.pdf', page: 1, score: 0.92, hit: '授信额度 USD 3,000,000.00，期限 12 个月', snippet: '授信额度 USD 3,000,000.00，期限 12 个月。提款前提：授信批复项下支持性材料齐备，担保手续办妥，并完成合规核查。' },
  { name: '商业合同 - 编造完.pdf', page: 2, score: 0.88, hit: '合同金额 USD 2,860,000.00，币种为美元', snippet: '本合同项下货物单价、数量与付款安排应与形式发票一致；合同金额 USD 2,860,000.00，币种为美元。' },
  { name: '形式发票 - 编造完.pdf', page: 1, score: 0.85, hit: '发票号码 INV-2024-0871', snippet: '商业发票号码 INV-2024-0871，货物为跨境采购设备，总金额与商业合同一致。' },
  { name: '提款指令 - 编造完.pdf', page: 1, score: 0.91, hit: '提款金额、币种与授信批复及合同一致', snippet: '收款人：智汇跨境贸易有限公司；提款金额、币种与授信批复及合同一致；请于提款日前确认资金用途。' },
  { name: 'DD notice (masked).pdf', page: 3, score: 0.83, hit: '需核查 UBO 并比对制裁名单与 PEP 名单', snippet: '交易对手含开曼群岛注册主体，需执行加强型尽调；需核查 UBO 并比对制裁名单与 PEP 名单。' },
]

const ANSWER = '根据知识库中的授信文件与提款流程资料，提款前应重点核对以下材料与要点：\n\n1. 授信批复与授信函：确认额度、期限、利率及提款前提条件与授信批复一致[1]。\n\n2. 支持性单据：商业合同、形式发票、报关单、运单需与贷款用途匹配，金额、币种与期限一致[2][3]。\n\n3. 支付与提款指令：提款指令、支付指令的收款人、金额、币种须与合同及授信一致[4]。\n\n4. 合规核查：交易对手涉及离岸主体的，需核查 UBO 并比对制裁名单与 PEP 名单[5]。\n\n以上为按知识库文件归纳的核对要点，请以正式授信批复与银行政策为准。'

const RETRIEVAL_ANSWER = '已从知识库检索到 5 处相关原文，按相关性排序如下（纯检索模式，未做 AI 归纳）：\n\n1. 测试版授信函 - 中文空白.pdf（第 1 页 · 92%）\n2. 商业合同 - 编造完.pdf（第 2 页 · 88%）\n3. 形式发票 - 编造完.pdf（第 1 页 · 85%）\n4. 提款指令 - 编造完.pdf（第 1 页 · 91%）\n5. DD notice (masked).pdf（第 3 页 · 83%）\n\n点击下方「引用来源」可在右侧逐条打开原文。'

const AI_ONLY_ANSWER = '可根据授信批复、贷款协议与合规要求进行核对，建议优先确认支持性材料与审批留痕是否齐备。\n\n（未启用知识库，此回答不引用原文。）'

const SUGGESTIONS = [
  '境外贷款提款前通常需要核对哪些材料？',
  '如何处理材料中的制裁与受益所有人风险？',
  '现有资料对人工终审有什么要求？',
]

type Seg = { text?: string; cite?: number }

function parseInline(text: string): Seg[] {
  const out: Seg[] = []
  const re = /\[(\d+)\]/g
  let last = 0
  let match: RegExpExecArray | null
  while ((match = re.exec(text))) {
    if (match.index > last) out.push({ text: text.slice(last, match.index) })
    out.push({ cite: Number(match[1]) })
    last = match.index + match[0].length
  }
  if (last < text.length) out.push({ text: text.slice(last) })
  return out
}

function escapeHtml(text: string) {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function highlight(text: string, hit: string) {
  return escapeHtml(text).replace(escapeHtml(hit), `<mark>${escapeHtml(hit)}</mark>`)
}

export default function App() {
  const [aiOn, setAiOn] = useState(true)
  const [kbOn, setKbOn] = useState(true)
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [connected, setConnected] = useState(true)
  const [panel, setPanel] = useState<{ state: PanelState; width: number; docIndex: number }>({ state: 'none', width: 0, docIndex: 0 })

  const chatRef = useRef<HTMLDivElement>(null)
  const workspaceRef = useRef<HTMLDivElement>(null)
  const timersRef = useRef<number[]>([])

  useEffect(() => {
    getCapabilities()
      .then(() => setConnected(true))
      .catch(() => setConnected(false))
  }, [])

  useEffect(() => {
    chatRef.current?.scrollTo({ top: chatRef.current.scrollHeight })
  }, [messages])

  useEffect(() => () => { timersRef.current.forEach(window.clearInterval) }, [])

  function toggleAi() {
    if (!kbOn && aiOn) return
    setAiOn(value => !value)
  }

  function toggleKb() {
    if (!aiOn && kbOn) return
    setKbOn(value => !value)
    if (kbOn) closePanel()
  }

  function ask(text?: string) {
    const q = (text ?? input).trim()
    if (!q || busy || (!aiOn && !kbOn)) return
    setInput('')

    const user: Message = { id: Date.now(), role: 'user', content: q }
    setMessages(prev => [...prev, user])

    if (aiOn && kbOn) {
      const id = Date.now() + 1
      const assistant: Message = { id, role: 'assistant', content: '', tag: '知识库 · AI', streaming: true }
      setMessages(prev => [...prev, assistant])
      setBusy(true)
      let index = 0
      const timer = window.setInterval(() => {
        index = Math.min(ANSWER.length, index + 3)
        setMessages(prev => prev.map(m => (m.id === id ? { ...m, content: ANSWER.slice(0, index) } : m)))
        if (index >= ANSWER.length) {
          window.clearInterval(timer)
          setMessages(prev => prev.map(m => (m.id === id ? { ...m, streaming: false, sources: SOURCES } : m)))
          setBusy(false)
        }
      }, 16)
      timersRef.current.push(timer)
    } else if (kbOn) {
      const id = Date.now() + 1
      setMessages(prev => [...prev, { id, role: 'assistant', content: RETRIEVAL_ANSWER, tag: '纯检索', sources: SOURCES }])
    } else {
      const id = Date.now() + 1
      setMessages(prev => [...prev, { id, role: 'assistant', content: AI_ONLY_ANSWER, tag: '通用 AI' }])
    }
  }

  function showList() {
    setPanel({ state: 'list', width: Math.min(400, window.innerWidth * 0.44), docIndex: 0 })
  }

  function openDoc(index: number) {
    setPanel({ state: 'doc', width: Math.min(680, window.innerWidth * 0.62), docIndex: index })
  }

  function closePanel() {
    setPanel(prev => ({ ...prev, state: 'none', width: 0 }))
  }

  function startDrag(event: React.MouseEvent) {
    event.preventDefault()
    const onMove = (ev: MouseEvent) => {
      const rect = workspaceRef.current?.getBoundingClientRect()
      if (!rect) return
      const rightWidth = rect.right - ev.clientX
      if (rightWidth > 240) {
        setPanel(prev => (prev.state === 'none' ? prev : { ...prev, width: Math.min(rightWidth, rect.width * 0.75) }))
      }
    }
    const onUp = () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }

  function renderAnswer(message: Message) {
    return (
      <div className="answer">
        {parseInline(message.content).map((seg, i) =>
          seg.cite ? (
            <button key={i} className="cite" onClick={() => openDoc(seg.cite! - 1)}>{seg.cite}</button>
          ) : (
            <span key={i}>{seg.text}</span>
          ),
        )}
        {message.streaming && <span className="caret" />}
      </div>
    )
  }

  function renderMessage(message: Message) {
    if (message.role === 'user') {
      return (
        <div key={message.id} className="msg user">
          <div className="avatar user">我</div>
          <div className="bubble-user">{message.content}</div>
        </div>
      )
    }
    return (
      <div key={message.id} className="msg">
        <div className="avatar ai">✦</div>
        <div className="msg-body">
          <div className="meta">
            <b>慧眼助手</b>
            {message.tag && <span className="tag">{message.tag}</span>}
          </div>
          <div className="card">
            {renderAnswer(message)}
            {!message.streaming && message.sources && message.sources.length > 0 && (
              <div className="answer-actions">
                <button className="src-btn" onClick={showList}>📚 引用来源（{message.sources.length}）</button>
              </div>
            )}
          </div>
        </div>
      </div>
    )
  }

  function renderSources() {
    const source = SOURCES[panel.docIndex]
    const pages = [1, 2, 3, 4].map(page => {
      const body = page === source.page
        ? <span dangerouslySetInnerHTML={{ __html: highlight(source.snippet, source.hit) }} />
        : page === 1
          ? '本文件为银行授信及贷款业务相关文件（演示占位）。正式使用中，此处为按页解析后的原文文本。'
          : `（第 ${page} 页原文占位）本页为文档正文的后续内容，展示可上下滚动、逐页阅读整本文件的阅读体验。`
      return (
        <div key={page} className="pdf-page">
          <h4>{source.name}</h4>
          <div className="p">{body}</div>
          <div className="pageno">第 {page} 页</div>
        </div>
      )
    })

    return (
      <>
        <div className="source-head">
          <button className="back-btn" onClick={showList}>‹ 返回引用列表</button>
          <button className="close" onClick={closePanel}>✕</button>
        </div>
        <div className="doc-view">
          <div className="doc-snippet">
            <div className="t">命中片段（第 {source.page} 页）</div>
            <p dangerouslySetInnerHTML={{ __html: highlight(source.snippet, source.hit) }} />
          </div>
          <div className="pdf-box">
            <div className="bar">
              <span>{source.name}</span>
              <span>共 4 页 · 上下滚动阅读整本</span>
            </div>
            {pages}
          </div>
          <div className="pdf-note">原型演示：正式版由 PDF 渲染引擎逐页显示真实原件，命中句高亮。</div>
        </div>
      </>
    )
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="logo">H</span>
          <span><b>HBCN 知识库工作台</b><small>Agentic RAG</small></span>
        </div>
        <div className="modes">
          <button className={`mode ${aiOn ? 'on' : ''}`} onClick={toggleAi}><span className="dot" />AI 回答</button>
          <button className={`mode ${kbOn ? 'on' : ''}`} onClick={toggleKb}><span className="dot" />知识库检索</button>
        </div>
        <span className="conn"><span className={`dot ${connected ? 'ok' : 'bad'}`} />{connected ? '知识库已连接' : '知识库未连接'}</span>
      </header>

      <div className="workspace" ref={workspaceRef}>
        <main className="chat">
          <div className="chat-scroll" ref={chatRef}>
            {messages.length === 0 ? (
              <div className="welcome">
                <div className="icon">✦</div>
                <h2>查证业务资料，结论可溯源</h2>
                <p>AI 生成回答并逐条溯源到原文；点「引用来源」在右侧查看并打开整本原文。</p>
                <div className="prompts">
                  {SUGGESTIONS.map(prompt => (
                    <button key={prompt} onClick={() => ask(prompt)}>{prompt}</button>
                  ))}
                </div>
              </div>
            ) : (
              messages.map(renderMessage)
            )}
          </div>
          <div className="composer">
            <div className="composer-inner">
              <textarea
                rows={1}
                value={input}
                disabled={busy}
                placeholder={kbOn ? '描述你想核对的问题，按回车检索…' : '输入问题…'}
                onChange={event => setInput(event.target.value)}
                onKeyDown={event => {
                  if (event.key === 'Enter' && !event.shiftKey) {
                    event.preventDefault()
                    ask()
                  }
                }}
              />
              <button className="send" disabled={!input.trim() || busy} onClick={() => ask()}>🔍</button>
            </div>
          </div>
        </main>

        <div className="divider" onMouseDown={startDrag} />

        <aside className="source" style={{ width: panel.state === 'none' ? 0 : panel.width }}>
          {panel.state === 'list' && (
            <>
              <div className="source-head">
                <div><b>引用来源</b><div className="sub">{SOURCES.length} 项 · 按相关性排序</div></div>
                <button className="close" onClick={closePanel}>✕</button>
              </div>
              <div className="source-list">
                {SOURCES.map((source, index) => (
                  <button key={source.name} className="src-item" onClick={() => openDoc(index)}>
                    <span className="src-rank">{index + 1}</span>
                    <span className="src-copy"><b>{source.name}</b><span className="loc">第 {source.page} 页</span></span>
                    <span className="src-pct">{Math.round(source.score * 100)}%</span>
                  </button>
                ))}
                <div className="src-hint">点击任意来源，在右侧展开原文</div>
              </div>
            </>
          )}
          {panel.state === 'doc' && renderSources()}
        </aside>
      </div>
    </div>
  )
}
