import { useEffect, useRef, useState } from 'react'
import { useSearchParams, Link } from 'react-router-dom'
import { Bubble, Conversations, Sender, ThoughtChain, XProvider } from '@ant-design/x'
import { Alert, App, Badge, Button, Card, Collapse, Drawer, Empty, Segmented, Select, Skeleton, Space, Tag, Tooltip, Typography } from 'antd'
import { CheckCircleOutlined, DeleteOutlined, HistoryOutlined, LoadingOutlined, PlusOutlined, ReloadOutlined, RobotOutlined, SafetyCertificateOutlined, ThunderboltOutlined, UserOutlined } from '@ant-design/icons'
import { renderMarkdown } from '@/assistant/markdown'
import { useAssistant } from '@/assistant/useAssistant'
import type { AssistantMessage } from '@/assistant/types'
import { CollaborationPanel } from '@/assistant/CollaborationPanel'
import { collaborationApi } from '@/assistant/collaboration'
import type { LibrarySkill } from '@/assistant/collaboration'
import { useAuthStore } from '@/stores/auth'
import './AssistantView.css'

const suggestions = [
  { title: '梳理任务风险', prompt: '请基于当前任务材料和规则结果，梳理主要风险与人工复核点。', caption: '从材料和规则中找到关注点', icon: <SafetyCertificateOutlined /> },
  { title: '解释审核规则', prompt: '请解释当前任务中不通过或需人工处置的规则，列出依据和下一步建议。', caption: '把规则依据转成可执行建议', icon: <ThunderboltOutlined /> },
  { title: '了解助手能力', prompt: '用两句话说明慧眼助手能做什么，并强调审核结论必须由有权限人员确认。', caption: '了解如何配合人工完成审核', icon: <RobotOutlined /> },
]

function AssistantReply({ message }: { message: AssistantMessage }) {
  const [expanded, setExpanded] = useState(Boolean(message.streaming))
  useEffect(() => { setExpanded(Boolean(message.streaming)) }, [message.streaming])
  const failed = message.status === 'error' || message.status === 'stopped'
  const evidenceWarnings = message.steps.filter((step) => /^(retrieval-warning-|citation-warning-)/.test(step.key))
  return (
    <div className="hy-reply">
      {message.steps.length > 0 && <Collapse
        className="hy-execution" size="small" ghost
        activeKey={expanded ? ['execution'] : []}
        onChange={(keys) => setExpanded(keys.includes('execution'))}
        items={[{
          key: 'execution',
          label: <span>{message.streaming ? <LoadingOutlined spin /> : <CheckCircleOutlined />} {message.streaming ? '正在执行' : failed ? '执行已结束' : '执行完成'} · {message.steps.length} 项操作</span>,
          children: <ThoughtChain items={message.steps.map((step) => ({
            key: step.key, title: step.label, description: step.detail,
            status: step.status === 'running' ? 'pending' : step.status === 'completed' ? 'success' : 'error',
          }))} />,
        }]}
      />}
      {message.content ? <div className="hy-markdown" dangerouslySetInnerHTML={{ __html: renderMarkdown(message.content) }} />
        : <span className="hy-muted">{message.streaming ? '正在准备答复…' : failed ? '本轮未获得完整答复，请重新发送。' : '暂无答复内容'}</span>}
      {message.status === 'stopped' && <p className="hy-muted">已停止接收，此答复可能不完整。</p>}
      {message.status === 'error' && <p className="hy-error">本轮未完成，请查看下方错误提示后重试。</p>}
      {evidenceWarnings.length > 0 && <Alert type="warning" showIcon
        message="本轮依据存在限制"
        description={evidenceWarnings.map((step) => <p key={step.key}>{step.detail || step.label}</p>)}
      />}
      {message.citations.length > 0 && <Collapse className="hy-sources" size="small" ghost items={[{
        key: 'sources', label: `参考依据 · ${message.citations.length} 条`,
        children: <ol>{message.citations.map((citation, index) => <li key={`${citation.id}:${index}`}>
          {citation.reference_id && <Tag>{`[${citation.reference_id}]`}</Tag>}
          <strong>{citation.label || citation.source}</strong>
          {citation.page != null && <Tag>第 {citation.page} 页</Tag>}
          {citation.detail && <p>{citation.detail}</p>}
          <small>{citation.source}</small>
        </li>)}</ol>,
      }]} />}
      {message.content && !message.streaming && <Typography.Paragraph className="hy-copy" copyable={{ text: message.content }}>复制答复</Typography.Paragraph>}
    </div>
  )
}

export default function AssistantView() {
  const [query] = useSearchParams()
  const assistant = useAssistant(query.get('task_code') || query.get('task') || '')
  const { modal } = App.useApp()
  const [draft, setDraft] = useState('')
  const [historyOpen, setHistoryOpen] = useState(false)
  const [skillsOpen, setSkillsOpen] = useState(false)
  const [collaborationOpen, setCollaborationOpen] = useState(false)
  const [messageMode, setMessageMode] = useState('问 AI')
  const [library, setLibrary] = useState<LibrarySkill[] | null>(null)
  const [libraryBusy, setLibraryBusy] = useState(false)
  const role = useAuthStore((state) => state.role)
  const scrollArea = useRef<HTMLDivElement>(null)
  const follow = useRef(true)
  const disabled = assistant.loading || assistant.switching || assistant.sending
  const activeSession = assistant.sessions.find((item) => item.id === assistant.activeId)
  const activeSkill = assistant.skills.find((skill) => skill.id === assistant.skillId)
  const requestedSession = query.get('session_id')

  useEffect(() => {
    if (!assistant.loading && requestedSession && /^\d+$/.test(requestedSession)) void assistant.selectSession(Number(requestedSession))
  }, [requestedSession, assistant.loading, assistant.selectSession])

  useEffect(() => {
    if (!skillsOpen) return
    let current = true
    // Older deployments still expose the shipped read-only catalog.
    void collaborationApi.library().then((items) => { if (current) setLibrary(items) }).catch(() => undefined)
    return () => { current = false }
  }, [skillsOpen])

  useEffect(() => {
    const area = scrollArea.current
    if (area && follow.current) area.scrollTop = area.scrollHeight
  }, [assistant.messages])

  const submit = (value: string) => {
    if (value.trim().length > 8000) {
      assistant.setError('单条消息最多 8000 字，请精简后再发送。')
      return
    }
    follow.current = true
    if (messageMode === '发给成员' && assistant.shared) void assistant.discuss(value, () => setDraft(''))
    else void assistant.send(value, () => setDraft(''))
  }

  const history = <>
    <div className="hy-brand"><span className="hy-logo"><ThunderboltOutlined /></span><div><strong>慧眼助手</strong><small>审核协作空间</small></div></div>
    <Button block type="primary" icon={<PlusOutlined />} disabled={disabled} onClick={() => { assistant.newConversation(); setHistoryOpen(false); setDraft('') }}>新建会话</Button>
    <div className="hy-history-label">最近会话</div>
    {assistant.loading ? <Skeleton active paragraph={{ rows: 4 }} /> : assistant.sessions.length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="开始你的第一轮问答" /> : <Conversations
      className="hy-conversations"
      items={assistant.sessions.map((item) => ({ key: String(item.id), label: `${item.shared ? '协作 · ' : ''}${item.title}`, disabled, icon: <HistoryOutlined /> }))}
      activeKey={assistant.activeId === null ? '' : String(assistant.activeId)}
      onActiveChange={(key) => { follow.current = true; void assistant.selectSession(Number(key)); setHistoryOpen(false) }}
      menu={(item) => ({
        items: [{ key: 'delete', label: '删除会话', icon: <DeleteOutlined />, danger: true, disabled: disabled || assistant.sessions.find((session) => String(session.id) === item.key)?.can_manage === false }],
        onClick: () => modal.confirm({ title: '删除这段会话？', content: '会话及其消息将被永久删除。', okText: '删除', cancelText: '取消', okButtonProps: { danger: true }, onOk: () => assistant.deleteSession(Number(item.key)) }),
      })}
    />}
    <div className="hy-service">
      <Badge status={assistant.capabilities?.configured ? 'success' : 'warning'} text={assistant.capabilities?.configured ? '模型服务就绪' : assistant.loading ? '正在检查服务' : '模型服务待检查'} />
      <small>{assistant.capabilities?.model || 'OpenCode Agent Runtime'}</small>
      <Badge status={assistant.capabilities?.rag_available ? 'success' : 'default'} text={assistant.capabilities?.rag_available ? '知识库可用' : '知识库未就绪'} />
    </div>
  </>

  return <XProvider>
    <section className="hy-assistant" aria-label="慧眼助手">
      <aside className="hy-rail">{history}</aside>
      <Drawer title="会话记录" placement="left" open={historyOpen} onClose={() => setHistoryOpen(false)} width={290}><div className="hy-mobile-history">{history}</div></Drawer>
      <main className="hy-main">
        <header className="hy-toolbar">
          <div className="hy-title"><Button className="hy-mobile-button" type="text" aria-label="打开会话记录" icon={<HistoryOutlined />} onClick={() => setHistoryOpen(true)} /><strong>{activeSession?.title || '新会话'}</strong><Tag color={assistant.shared ? 'green' : 'blue'}>{assistant.shared ? '协作会话' : '审核辅助'}</Tag></div>
          <Space wrap>
            <Select className="hy-task-select" aria-label="关联审核任务" placeholder="关联审核任务（可选）" allowClear showSearch optionFilterProp="label"
              value={assistant.taskCode || undefined} disabled={disabled}
              options={[
                ...(assistant.taskCode && !assistant.tasks.some((task) => task.task_code === assistant.taskCode) ? [{ value: assistant.taskCode, label: assistant.taskCode }] : []),
                ...assistant.tasks.map((task) => ({ value: task.task_code, label: `${task.task_code} · ${task.borrower}` })),
              ]}
              onChange={(value?: string) => { assistant.newConversation(value || ''); setDraft('') }} />
            <Tooltip title="更换任务会开启新的会话，避免混用材料"><SafetyCertificateOutlined className="hy-muted" /></Tooltip>
            <Button aria-label="业务技能" icon={<ThunderboltOutlined />} onClick={() => setSkillsOpen(true)}>业务技能</Button>
            {role === 'reviewer' && <Tooltip title={assistant.activeId ? '专家库、成员和共享权限' : '先开始一段对话，再邀请同事'}><Button disabled={!assistant.activeId} onClick={() => setCollaborationOpen(true)}>专家与成员</Button></Tooltip>}
          </Space>
        </header>

        <div className="hy-chat-scroll" ref={scrollArea} onScroll={() => {
          const area = scrollArea.current
          if (area) follow.current = area.scrollHeight - area.scrollTop - area.clientHeight < 100
        }}>
          <div className="hy-chat-content">
            {assistant.switching ? <Skeleton active paragraph={{ rows: 8 }} /> : assistant.messages.length === 0 ? <div className="hy-welcome">
              <span className="hy-welcome-logo"><ThunderboltOutlined /></span>
              <span className="hy-eyebrow">EVIDENCE → INSIGHT → ACTION</span>
              <h1>让每一次审核，<br />都有据可循。</h1>
              <p>一起读材料、找依据、理清风险。<br />把判断所需的信息留给你，把重复工作交给助手。</p>
              {assistant.taskCode && <Tag color="blue">当前任务：{assistant.taskCode}</Tag>}
              <div className="hy-suggestions">{suggestions.map((item) => <button key={item.title} disabled={disabled} onClick={() => { setDraft(item.prompt) }}>
                {item.icon}<strong>{item.title}</strong><span>{item.caption}</span>
              </button>)}</div>
            </div> : <div className="hy-messages" role="log" aria-label="聊天记录" aria-live="off">
              {assistant.messages.map((message) => <Bubble key={message.id}
                className={message.role === 'user' ? 'hy-user-message' : 'hy-assistant-message'}
                placement={message.role === 'user' ? 'end' : 'start'}
                variant={message.role === 'user' ? 'filled' : 'borderless'}
                avatar={{ icon: message.role === 'user' ? <UserOutlined /> : <ThunderboltOutlined />, style: { background: message.role === 'user' ? '#edf1f8' : '#315fc4', color: message.role === 'user' ? '#58657d' : '#fff' } }}
                header={message.role === 'user' ? message.author_name || (assistant.shared ? '审核成员' : '你') : '慧眼助手'}
                content={message.role === 'user' ? <div className="hy-user-text">{message.content}</div> : <AssistantReply message={message} />}
              />)}
            </div>}
          </div>
        </div>

        <div className="hy-composer">
          {assistant.shared && <div className="hy-collab-mode"><Segmented aria-label="消息发送方式" options={['问 AI', '发给成员']} value={messageMode} onChange={setMessageMode} disabled={assistant.sending} /><span className="hy-muted">{messageMode === '问 AI' ? '本轮回答将对全部会话成员可见' : '仅发给会话成员，不调用模型'}</span></div>}
          {assistant.activeRun && !assistant.sending && <Alert type="info" showIcon message="会话中的 AI 正在工作，执行状态会自动同步。" action={activeSession?.can_manage ? <Button size="small" onClick={() => { void collaborationApi.cancel(assistant.activeId!, assistant.activeRun!.id).then(assistant.refreshSession).catch((cause: Error) => assistant.setError(cause.message)) }}>停止运行</Button> : undefined} />}
          {assistant.error && <Alert type="error" showIcon message={assistant.error} closable onClose={() => assistant.setError('')} />}
          {assistant.notice && <Alert type="warning" showIcon message={assistant.notice} />}
          {!assistant.loading && !assistant.capabilities?.configured && <Alert type="warning" showIcon
            message={assistant.capabilities?.message || '暂未确认模型服务状态，请检查后端与 OpenCode runtime。'}
            action={<Button size="small" icon={<ReloadOutlined />} onClick={() => void assistant.refreshCapabilities()}>重新检查</Button>} />}
          <Sender value={draft} onChange={setDraft} onSubmit={submit} onCancel={assistant.stop}
            loading={assistant.sending} disabled={assistant.loading || assistant.switching}
            placeholder={assistant.taskCode ? '询问此任务的风险、依据或复核建议…' : '输入问题，或关联任务后开始审核问答…'}
            autoSize={{ minRows: 2, maxRows: 6 }}
            actions={(_, { components: { SendButton, LoadingButton } }) => assistant.sending
              ? <LoadingButton aria-label="停止接收" title="停止接收" />
              : <SendButton aria-label="发送消息" title="发送消息" disabled={!draft.trim() || assistant.loading || assistant.switching} />}
            header={activeSkill ? <div className="hy-selected-skill"><ThunderboltOutlined /> 本轮技能：<Tag closable onClose={() => assistant.setSkillId(undefined)}>{activeSkill.name}</Tag></div> : undefined}
          />
          <div className="hy-composer-footer"><span role="status">{assistant.sending ? '正在处理，可随时停止接收' : 'Enter 发送 · Shift + Enter 换行'}</span><span>审核结论须由有权限人员确认</span></div>
        </div>
      </main>
      <CollaborationPanel open={collaborationOpen} onClose={() => setCollaborationOpen(false)} session={activeSession} onChanged={assistant.refreshSession} context={assistant.messages.slice(-8).map((message) => message.content).join('\n')} />
      <Drawer title="业务技能" width={400} open={skillsOpen} onClose={() => setSkillsOpen(false)}>
        <p className="hy-muted">项目审核目录：查看来源、版本和权限后加入个人技能库。选择后应用于下一轮问答，数据权限保持不变。</p>
        {assistant.skills.length === 0 && <Empty description="暂无可用技能" />}
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>{assistant.skills.map((skill) => <Card key={skill.id} size="small" title={skill.name} extra={<Tag>{skill.version}</Tag>}>
          <p>{skill.desc}</p><p className="hy-muted">{skill.owner} · {skill.license}</p>
          <div>{skill.permissions.map((permission) => <Tag key={permission}>{permission}</Tag>)}</div>
          {library?.find((item) => item.id === skill.id) && <div className="hy-library-actions"><small className="hy-muted">{library.find((item) => item.id === skill.id)?.source}</small><Button size="small" loading={libraryBusy} onClick={async () => {
            setLibraryBusy(true)
            try {
              const saved = library.find((item) => item.id === skill.id)!
              if (saved.installed && !saved.update_available) await collaborationApi.uninstallSkill(skill.id)
              else await collaborationApi.installSkill(skill.id)
              setLibrary(await collaborationApi.library())
            } catch (cause) { assistant.setError(cause instanceof Error ? cause.message : '技能库更新失败') }
            finally { setLibraryBusy(false) }
          }}>{library.find((item) => item.id === skill.id)?.update_available ? '确认更新版本' : library.find((item) => item.id === skill.id)?.installed ? '从我的技能移除' : '加入我的技能'}</Button></div>}
          <Button block type={skill.id === assistant.skillId ? 'primary' : 'default'} disabled={disabled} onClick={() => { assistant.setSkillId(skill.id); setSkillsOpen(false) }}>{skill.id === assistant.skillId ? '已选择' : '使用此技能'}</Button>
        </Card>)}</Space>
        {assistant.taskCode && <p><Link to={`/tasks/${encodeURIComponent(assistant.taskCode)}`}>返回关联任务核对原件</Link></p>}
      </Drawer>
    </section>
  </XProvider>
}
