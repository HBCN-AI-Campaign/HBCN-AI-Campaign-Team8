import { useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { Card, Form, Input, Button, Tag, Space, App } from 'antd'
import { UserOutlined, LockOutlined } from '@ant-design/icons'
import { api } from '@/api'
import { useAuthStore } from '@/stores/auth'

interface LocationState {
  redirect?: string
}

const accounts = [
  { u: 'reviewer', p: 'reviewer123', label: '审核人员 reviewer' },
  { u: 'operator', p: 'operator123', label: '业务经办人 operator' },
]

export default function LoginView() {
  const navigate = useNavigate()
  const location = useLocation()
  const setAuth = useAuthStore((s) => s.setAuth)
  const { message } = App.useApp()

  const [form] = Form.useForm<{ username: string; password: string }>()
  const [loading, setLoading] = useState(false)

  const fill = (a: { u: string; p: string }) => {
    form.setFieldsValue({ username: a.u, password: a.p })
  }

  const onSubmit = async () => {
    const values = await form.validateFields().catch(() => null)
    if (!values) return
    if (!values.username || !values.password) {
      message.warning('请输入用户名和密码')
      return
    }
    setLoading(true)
    try {
      const resp = await api.login(values.username, values.password)
      setAuth(resp.access_token, resp.role, resp.display_name)
      message.success(`欢迎，${resp.display_name}`)
      const redirect = (location.state as LocationState)?.redirect || '/dashboard'
      navigate(redirect, { replace: true })
    } catch {
      /* 错误已在拦截器统一提示 */
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'linear-gradient(135deg, #1a2b4a 0%, #3b6fd4 100%)',
      }}
    >
      <Card style={{ width: 420, padding: '12px 8px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 24 }}>
          <div
            style={{
              width: 48,
              height: 48,
              borderRadius: 12,
              background: 'var(--navy)',
              color: '#fff',
              fontSize: 24,
              fontWeight: 700,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            贷
          </div>
          <div>
            <h1 style={{ margin: 0, fontSize: 18 }}>境外贷款单据智能审核平台</h1>
            <p style={{ margin: '2px 0 0', color: 'var(--muted)', fontSize: 12 }}>
              Overseas Loan Document Review
            </p>
          </div>
        </div>

        <Form form={form} onFinish={onSubmit}>
          <Form.Item name="username">
            <Input size="large" placeholder="用户名" prefix={<UserOutlined />} />
          </Form.Item>
          <Form.Item name="password">
            <Input.Password size="large" placeholder="密码" prefix={<LockOutlined />} />
          </Form.Item>
          <Button type="primary" size="large" block loading={loading} htmlType="submit">
            登 录
          </Button>
        </Form>

        <div style={{ marginTop: 18, fontSize: 12, color: 'var(--muted)' }}>
          <p style={{ margin: '0 0 8px' }}>演示账号（点击填入）：</p>
          <Space wrap>
            {accounts.map((a) => (
              <Tag key={a.u} style={{ cursor: 'pointer' }} onClick={() => fill(a)}>
                {a.label}
              </Tag>
            ))}
          </Space>
        </div>
      </Card>
    </div>
  )
}
