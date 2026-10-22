import { Layout, Tag, Avatar, Button, Dropdown, type MenuProps } from 'antd'
import { RobotOutlined } from '@ant-design/icons'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useAuthStore } from '@/stores/auth'

const { Header, Content } = Layout

function roleTag(role: string): { label: string; color: string } {
  const map: Record<string, { label: string; color: string }> = {
    reviewer: { label: '审核人员', color: 'success' },
    operator: { label: '业务经办人', color: 'warning' },
  }
  return map[role] || { label: '未知', color: 'default' }
}

export default function MainLayout() {
  const navigate = useNavigate()
  const isAssistant = useLocation().pathname === '/assistant'
  const displayName = useAuthStore((s) => s.displayName)
  const role = useAuthStore((s) => s.role)
  const logout = useAuthStore((s) => s.logout)

  const tag = roleTag(role)

  const menuItems: MenuProps['items'] = [{ key: 'logout', label: '退出登录' }]
  const onMenuClick: MenuProps['onClick'] = ({ key }) => {
    if (key === 'logout') {
      logout()
      navigate('/login')
    }
  }

  return (
    <Layout style={{ height: '100%' }}>
      <Header
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          background: '#fff',
          borderBottom: '1px solid #e2e8f0',
          padding: '0 20px',
        }}
      >
        {/* 无侧边栏：顶栏左侧显示品牌，点击回工作台 */}
        <div
          style={{ fontWeight: 600, display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}
          onClick={() => navigate('/dashboard')}
        >
          <span
            style={{
              width: 26,
              height: 26,
              borderRadius: 7,
              background: 'var(--blue)',
              color: '#fff',
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontWeight: 700,
              fontSize: 14,
            }}
          >
            贷
          </span>
          <span className="platform-name">境外贷款单据审核平台</span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <Button type={isAssistant ? 'primary' : 'text'} icon={<RobotOutlined />} onClick={() => navigate('/assistant')}>慧眼助手</Button>
          <Tag color={tag.color}>{tag.label}</Tag>
          <span style={{ fontSize: 13, color: 'var(--muted)' }}>{displayName}</span>
          <Dropdown menu={{ items: menuItems, onClick: onMenuClick }} placement="bottomRight">
            <Avatar size={32} style={{ cursor: 'pointer', background: 'var(--blue)' }}>
              {displayName?.slice(0, 1)}
            </Avatar>
          </Dropdown>
        </div>
      </Header>

      <Content style={{ background: 'var(--bg)', padding: isAssistant ? 0 : 20, overflow: isAssistant ? 'hidden' : 'auto', minHeight: 0 }}>
        <Outlet />
      </Content>
    </Layout>
  )
}
