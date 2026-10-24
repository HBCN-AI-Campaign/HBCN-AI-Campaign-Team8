import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react'
import { Alert, App, Button, Card, Drawer, Empty, Form, Input, List, Modal, Popconfirm, Space, Spin, Tabs, Tag, Typography } from 'antd'
import { DeleteOutlined, EditOutlined, PlusOutlined, SearchOutlined, ThunderboltOutlined } from '@ant-design/icons'
import { CollaborationApiError, collaborationApi } from './collaboration'
import type { CustomSkillDetail, CustomSkillInput, LibrarySkill } from './collaboration'
import type { AssistantSkill } from './types'

interface SkillLibraryDrawerProps {
  open: boolean
  disabled?: boolean
  selectedSkillId?: string
  onClose: () => void
  onChoose: (skill?: AssistantSkill) => void
  onRefreshSkills: () => Promise<AssistantSkill[]>
}

export function SkillLibraryDrawer({ open, disabled = false, selectedSkillId, onClose, onChoose, onRefreshSkills }: SkillLibraryDrawerProps) {
  const { message, modal } = App.useApp()
  const [form] = Form.useForm<CustomSkillInput>()
  const editorTitleId = useId()
  const [library, setLibrary] = useState<LibrarySkill[]>([])
  const [query, setQuery] = useState('')
  const [activeTab, setActiveTab] = useState('mine')
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [formError, setFormError] = useState('')
  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<CustomSkillDetail>()
  const [editingRevision, setEditingRevision] = useState<number>()
  const [conflictVersion, setConflictVersion] = useState<CustomSkillDetail>()
  const initialValues = useRef<CustomSkillInput | null>(null)

  const reload = useCallback(async () => {
    setLoading(true)
    setLoadError('')
    try {
      const [items] = await Promise.all([collaborationApi.library(), onRefreshSkills()])
      setLibrary(items)
    } catch (cause) {
      setLoadError(cause instanceof Error ? cause.message : '技能目录暂时无法读取。')
    } finally { setLoading(false) }
  }, [onRefreshSkills])

  useEffect(() => { if (open) void reload() }, [open, reload])
  const projectSkills = useMemo(() => library.filter((item) => !item.is_custom), [library])
  const personalSkills = useMemo(() => library.filter((item) => item.is_custom || item.installed), [library])
  const visible = (activeTab === 'catalog' ? projectSkills : personalSkills).filter((item) =>
    `${item.name} ${item.desc} ${item.owner}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()),
  )

  const mutate = async (operation: () => Promise<unknown>, success: string, removedId?: string) => {
    setBusy(true)
    try {
      await operation()
      if (removedId && selectedSkillId === removedId) onChoose(undefined)
      await reload()
      message.success(success)
    } catch (cause) {
      const text = cause instanceof Error ? cause.message : '技能操作失败，请重试。'
      setLoadError(text)
      message.error(text)
    } finally { setBusy(false) }
  }

  const beginCreate = () => {
    const blank = { name: '', desc: '', instructions: '' }
    initialValues.current = blank
    form.resetFields()
    form.setFieldsValue(blank)
    setEditing(undefined)
    setEditingRevision(undefined)
    setConflictVersion(undefined)
    setFormError('')
    setFormOpen(true)
  }
  const beginEdit = async (skill: LibrarySkill) => {
    setBusy(true)
    setLoadError('')
    setFormError('')
    try {
      const detail = await collaborationApi.customSkill(skill.id)
      const values = { name: detail.name, desc: detail.desc, instructions: detail.instructions }
      initialValues.current = values
      form.setFieldsValue(values)
      setEditing(detail)
      setEditingRevision(detail.revision)
      setConflictVersion(undefined)
      setFormOpen(true)
    } catch (cause) {
      const text = cause instanceof Error ? cause.message : '技能详情读取失败。'
      setLoadError(text)
      message.error(text)
    } finally { setBusy(false) }
  }
  const saveCustom = async (values: CustomSkillInput) => {
    setFormError('')
    setBusy(true)
    try {
      if (editing) {
        await collaborationApi.updateCustomSkill(editing.id, values, editingRevision || editing.revision || 1)
        message.success('技能已更新')
      } else {
        await collaborationApi.createCustomSkill(values)
        message.success('技能已添加到我的技能')
      }
      initialValues.current = null
      setFormOpen(false)
      setEditing(undefined)
      setEditingRevision(undefined)
      setConflictVersion(undefined)
      await reload()
    } catch (cause) {
      if (cause instanceof CollaborationApiError && cause.status === 409 && editing) {
        try {
          const latest = await collaborationApi.customSkill(editing.id)
          initialValues.current = { name: latest.name, desc: latest.desc, instructions: latest.instructions }
          setEditingRevision(latest.revision)
          setConflictVersion(latest)
          setFormError('这项技能已被其他人更新。你的未保存修改仍保留在表单中，请对照最新版本合并后再保存。')
        } catch {
          setFormError('保存时发现版本冲突，但暂时无法读取最新版本。你的输入仍保留，请检查连接后重试。')
        }
        message.error('技能已更新，你的输入仍保留')
      } else {
        const text = cause instanceof Error ? cause.message : '保存失败，请检查后重试。'
        setFormError(text)
        message.error(text)
      }
    } finally { setBusy(false) }
  }

  const closeEditor = () => {
    const close = () => {
      initialValues.current = null
      setFormOpen(false)
      setEditing(undefined)
      setEditingRevision(undefined)
      setConflictVersion(undefined)
      setFormError('')
    }
    const initial = initialValues.current
    const current = form.getFieldsValue(true)
    const hasChanges = !initial || current.name !== initial.name || current.desc !== initial.desc || current.instructions !== initial.instructions
    if (!hasChanges) { close(); return }
    modal.confirm({
      title: '放弃未保存的技能修改？',
      content: '当前表单内容尚未保存。',
      okText: '放弃修改', cancelText: '继续编辑',
      onOk: close,
    })
  }

  const choose = (skill: LibrarySkill) => {
    const { source: _source, installed: _installed, update_available: _update, ...selected } = skill
    onChoose(selected)
    message.success('已应用于下一条 AI 提问')
    onClose()
  }

  const remove = (skill: LibrarySkill) => {
    if (skill.is_custom) void mutate(() => collaborationApi.deleteCustomSkill(skill.id), '个人技能已删除', skill.id)
    else void mutate(() => collaborationApi.uninstallSkill(skill.id), '技能已从个人库移除', skill.id)
  }

  return <>
    <Drawer
      title="审核技能"
      placement="right"
      width="min(480px, calc(100vw - 2px))"
      open={open}
      onClose={onClose}
      extra={<Button type="primary" icon={<PlusOutlined />} onClick={beginCreate}>新建技能</Button>}
    >
      <Typography.Paragraph type="secondary">
        个人技能只对你可见，且只提供文字指引；选择后用于下一条 AI 提问，不会改变任务或审批权限。
      </Typography.Paragraph>
      <Input allowClear prefix={<SearchOutlined />} placeholder="搜索技能名称或说明" value={query} onChange={(event) => setQuery(event.target.value)} />
      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={[
          { key: 'mine', label: `我的技能 ${personalSkills.length}` },
          { key: 'catalog', label: `项目目录 ${projectSkills.length}` },
        ]}
      />
      {loadError && <Typography.Text type="danger" role="alert">{loadError}</Typography.Text>}
      {loading ? <div className="hy-skill-loading"><Spin /></div> : visible.length === 0
        ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={query ? '没有匹配的技能' : activeTab === 'mine' ? '还没有个人技能，或尚未加入项目技能' : '项目目录暂无技能'} />
        : <List
          className="hy-skill-list"
          dataSource={visible}
          split={false}
          renderItem={(skill) => <List.Item key={skill.id}>
            <Card size="small" className="hy-skill-card" title={<Space wrap><span>{skill.name}</span><Tag>{skill.version}</Tag>{skill.is_custom && <Tag color="cyan">个人</Tag>}</Space>}>
              <p>{skill.desc}</p>
              <Typography.Text type="secondary">{skill.owner} · {skill.source}</Typography.Text>
              {skill.permissions.length > 0 && <div className="hy-skill-permissions">{skill.permissions.map((permission) => <Tag key={permission}>{permission}</Tag>)}</div>}
              <div className="hy-skill-actions">
                {activeTab === 'catalog' ? skill.installed
                  ? <>
                    <Button type="primary" disabled={disabled} onClick={() => choose(skill)}>应用于下一问</Button>
                    {skill.update_available && <Button loading={busy} disabled={disabled} onClick={() => void mutate(() => collaborationApi.installSkill(skill.id), '已更新到项目版本')}>更新</Button>}
                    <Popconfirm title="从个人技能中移除？" onConfirm={() => remove(skill)} okText="移除" cancelText="取消">
                      <Button danger loading={busy} disabled={disabled}>移除</Button>
                    </Popconfirm>
                  </>
                  : <Button loading={busy} disabled={disabled} onClick={() => void mutate(() => collaborationApi.installSkill(skill.id), '已加入我的技能')}>加入我的技能</Button>
                  : <>
                    <Button type={skill.id === selectedSkillId ? 'primary' : 'default'} icon={<ThunderboltOutlined />} disabled={disabled} onClick={() => choose(skill)}>
                      {skill.id === selectedSkillId ? '已选择' : '应用于下一问'}
                    </Button>
                    {skill.is_custom
                      ? <>
                        <Button icon={<EditOutlined />} loading={busy} disabled={disabled} onClick={() => void beginEdit(skill)}>编辑</Button>
                        <Popconfirm title="删除这项个人技能？" description="删除后不能恢复。" onConfirm={() => remove(skill)} okText="删除" cancelText="取消">
                          <Button danger icon={<DeleteOutlined />} loading={busy} disabled={disabled}>删除</Button>
                        </Popconfirm>
                      </>
                      : <Popconfirm title="从个人技能中移除？" onConfirm={() => remove(skill)} okText="移除" cancelText="取消">
                        <Button danger loading={busy} disabled={disabled}>移除</Button>
                      </Popconfirm>}
                  </>}
              </div>
            </Card>
          </List.Item>}
        />}
    </Drawer>

    <Modal
      title={<span id={editorTitleId}>{editing ? '编辑个人技能' : '新建个人技能'}</span>}
      className="hy-skill-editor-modal"
      aria-labelledby={editorTitleId}
      open={formOpen}
      onCancel={() => { if (!busy) closeEditor() }}
      onOk={() => form.submit()}
      confirmLoading={busy}
      cancelButtonProps={{ disabled: busy }}
      closable={!busy}
      keyboard={!busy}
      maskClosable={!busy}
      okText="保存"
      cancelText="取消"
      destroyOnHidden
    >
      {formError && <Alert
        showIcon
        type={conflictVersion ? 'warning' : 'error'}
        message={formError}
        description={conflictVersion && <div className="hy-skill-conflict-version">
          <strong>最新服务器版本 · r{conflictVersion.revision}</strong>
          <div>{conflictVersion.name} · {conflictVersion.desc}</div>
          <Typography.Paragraph>{conflictVersion.instructions}</Typography.Paragraph>
        </div>}
      />}
      <Form form={form} layout="vertical" onFinish={(values) => void saveCustom(values)}>
        <Form.Item label="技能名称" name="name" rules={[{ required: true, whitespace: true, message: '请填写技能名称' }, { max: 80, message: '最多 80 个字符' }]}>
          <Input maxLength={80} showCount placeholder="例如：贸易背景复核" />
        </Form.Item>
        <Form.Item label="用途说明" name="desc" rules={[{ required: true, whitespace: true, message: '请说明技能适用场景' }, { max: 1024, message: '最多 1024 个字符' }]}>
          <Input.TextArea rows={2} maxLength={1024} showCount placeholder="说明这项技能适合协助处理什么问题" />
        </Form.Item>
        <Form.Item label="工作指引" name="instructions" rules={[{ required: true, whitespace: true, message: '请填写工作指引' }, { max: 12000, message: '最多 12000 个字符' }]}>
          <Input.TextArea rows={7} maxLength={12000} showCount placeholder="写明核对重点、输出格式和需要提醒审核人的事项" />
        </Form.Item>
        <Typography.Text type="secondary">个人技能是文字指引，不支持脚本或额外工具权限。</Typography.Text>
      </Form>
    </Modal>
  </>
}
