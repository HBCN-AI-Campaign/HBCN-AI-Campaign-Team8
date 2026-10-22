import { useEffect, useRef, useState } from 'react'
import { Alert, App, Avatar, Button, Drawer, Empty, Form, Input, List, Modal, Space, Spin, Tabs, Tag, Typography } from 'antd'
import { TeamOutlined, UserAddOutlined } from '@ant-design/icons'
import { collaborationApi } from './collaboration'
import type { Expert, Member } from './collaboration'
import type { AssistantSession } from './types'

interface Props {
  open: boolean; onClose: () => void; session: AssistantSession | undefined
  onChanged: () => Promise<void>; context: string
}

export function CollaborationPanel({ open, onClose, session, onChanged, context }: Props) {
  const { modal } = App.useApp()
  const [tab, setTab] = useState('experts')
  const [experts, setExperts] = useState<Expert[]>([])
  const [members, setMembers] = useState<Member[]>([])
  const [query, setQuery] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(false)
  const [editing, setEditing] = useState(false)
  const [profileLoading, setProfileLoading] = useState(false)
  const [revision, setRevision] = useState(0)
  const scope = useRef(0)
  const [form] = Form.useForm<{ specialty: string; bio: string; tags: string }>()
  const id = session?.id

  useEffect(() => {
    scope.current += 1
    setEditing(false); setProfileLoading(false); setQuery(''); setBusy(false)
    return () => { scope.current += 1 }
  }, [open, id])

  useEffect(() => {
    if (!open || !id) return
    let current = true
    setLoading(true); setError(''); setExperts([]); setMembers([])
    const timer = setTimeout(() => {
      void Promise.all([collaborationApi.members(id), collaborationApi.experts(id, query.trim())]).then(([people, directory]) => {
        if (current) { setMembers(people); setExperts(directory) }
      }).catch((cause: unknown) => { if (current) setError(cause instanceof Error ? cause.message : '目录读取失败') })
        .finally(() => { if (current) setLoading(false) })
    }, query.trim() ? 250 : 0)
    return () => { current = false; clearTimeout(timer) }
  }, [open, id, query, revision])

  async function change(operation: () => Promise<unknown>) {
    const current = scope.current
    setBusy(true); setError('')
    try {
      await operation()
      if (current !== scope.current) return false
      setRevision((value) => value + 1)
      await onChanged()
      return current === scope.current
    }
    catch (cause) { if (current === scope.current) setError(cause instanceof Error ? cause.message : '操作失败'); return false }
    finally { if (current === scope.current) setBusy(false) }
  }

  const recommended = experts.filter((expert) => !expert.joined && !expert.is_self && expert.tags.some((tag) => context.includes(tag))).slice(0, 3)
  async function editProfile() {
    const current = scope.current
    setProfileLoading(true); setError('')
    try {
      const mine = await collaborationApi.myProfile()
      if (current !== scope.current) return
      form.setFieldsValue({ specialty: mine.specialty, bio: mine.bio, tags: mine.tags.join('，') })
      setEditing(true)
    } catch (cause) {
      if (current === scope.current) setError(cause instanceof Error ? cause.message : '本人资料读取失败')
    } finally { if (current === scope.current) setProfileLoading(false) }
  }
  const invite = (expert: Expert) => {
    const current = scope.current
    return modal.confirm({
    title: `邀请 ${expert.name} 加入当前审核会话？`,
    content: <><p>对方将能阅读当前会话的完整历史，并参与之后的讨论和 AI 问答。</p><p>任务：{session?.task_code}。材料仍按主站任务权限校验；加入会话不授予审批权。</p></>,
    okText: '确认共享并邀请', cancelText: '取消',
    onOk: () => current === scope.current ? change(() => collaborationApi.invite(id!, expert.user_id)) : undefined,
    })
  }
  const revoke = (member: Member) => {
    const current = scope.current
    return modal.confirm({
      title: `撤销 ${member.name} 的会话访问？`, content: '撤销后对方不能再读取此会话的历史、事件或材料引用；已阅读的信息无法收回。', okText: '撤销访问', cancelText: '取消',
      onOk: () => current === scope.current ? change(() => collaborationApi.revoke(id!, member.user_id)) : undefined,
    })
  }

  return <>
    <Drawer title={<><TeamOutlined /> 专家与协作</>} width={420} open={open} onClose={onClose}>
      {error && <Alert type="error" showIcon message={error} />}
      <Tabs activeKey={tab} onChange={setTab} items={[{ key: 'experts', label: '专家库' }, { key: 'members', label: `会话成员 · ${members.length}` }]} />
      <Spin spinning={loading}>
        {tab === 'experts' ? <>
          <Input.Search aria-label="搜索专家" placeholder="搜索姓名、专业方向或技能标签" maxLength={128} value={query} onChange={(event) => setQuery(event.target.value)} allowClear />
          <Typography.Paragraph className="hy-muted">每次最多显示 50 位；输入关键词搜索全部可邀请审核人员。</Typography.Paragraph>
          {recommended.length > 0 && !query && <Alert className="hy-directory-note" type="info" showIcon message="与当前讨论匹配的专家"
            description={<><p>依据本人填写的专业标签匹配，供审核人员选择。</p>{recommended.map((expert) => <Tag key={expert.user_id}>{expert.name} · {expert.tags.join(' / ')}</Tag>)}</>} />}
          <List dataSource={experts} locale={{ emptyText: <Empty description={loading ? '正在搜索专家' : '暂无匹配专家；可请同事维护自己的专业资料'} /> }} renderItem={(expert) => <List.Item>
            <div className="hy-expert-card">
              <Space align="start"><Avatar>{expert.name.slice(0, 1)}</Avatar><div><strong>{expert.name}</strong>{expert.is_self && <Tag>你</Tag>}<p className="hy-muted">{expert.specialty || '审核人员 · 尚未填写专业方向'}</p></div></Space>
              <p>{expert.bio || '暂无个人介绍，不推测该同事的专业资历。'}</p>
              <div>{expert.tags.map((tag) => <Tag key={tag}>{tag}</Tag>)}</div>
              <div className="hy-expert-footer"><small className="hy-muted">{expert.profile_source}</small>
                <Button size="small" icon={<UserAddOutlined />} disabled={busy || expert.joined || expert.is_self || !session?.can_manage || !session.task_code} onClick={() => invite(expert)}>{expert.joined ? '已在会话' : '邀请加入'}</Button>
              </div>
            </div>
          </List.Item>} />
          {!session?.task_code && <Alert type="info" message="共享前请新建并关联审核任务；普通问答保持个人会话。" />}
          <Button block disabled={busy || loading} loading={profileLoading} onClick={() => void editProfile()}>维护我的专业资料</Button>
        </> : <>
          <List dataSource={members} renderItem={(member) => <List.Item actions={session?.can_manage && member.role !== 'owner' ? [<Button key="remove" size="small" danger disabled={busy} onClick={() => revoke(member)}>撤销访问</Button>] : []}>
            <List.Item.Meta avatar={<Avatar>{member.name.slice(0, 1)}</Avatar>} title={<>{member.name} {member.is_self && <Tag>你</Tag>}</>} description={member.role === 'owner' ? '创建审核人员 · 管理成员' : '参与审核讨论 · 可向 AI 提问'} />
          </List.Item>} />
          <Typography.Paragraph className="hy-muted">会话成员与任务权限同时生效。最终结论必须由有权限的审核人员确认。</Typography.Paragraph>
        </>}
      </Spin>
    </Drawer>
    <Modal title="我的专业资料" open={editing} onCancel={() => setEditing(false)} confirmLoading={busy} okText="保存资料" cancelText="取消" onOk={async () => {
      const values = await form.validateFields()
      const saved = await change(() => collaborationApi.profile({ specialty: values.specialty || '', bio: values.bio || '', tags: (values.tags || '').split(/[,，]/).map((tag) => tag.trim()).filter(Boolean) }))
      if (saved) setEditing(false)
    }}>
      {error && <Alert type="error" showIcon message={error} />}
      <Form form={form} layout="vertical"><Form.Item name="specialty" label="专业方向"><Input maxLength={128} /></Form.Item><Form.Item name="bio" label="个人介绍"><Input.TextArea rows={4} maxLength={1000} showCount /></Form.Item><Form.Item name="tags" label="擅长标签（逗号分隔，最多 8 项）" rules={[{ validator: (_, value: string) => (value || '').split(/[,，]/).filter((tag) => tag.trim()).length <= 8 ? Promise.resolve() : Promise.reject(new Error('最多填写 8 项')) }]}><Input maxLength={320} /></Form.Item></Form>
    </Modal>
  </>
}
