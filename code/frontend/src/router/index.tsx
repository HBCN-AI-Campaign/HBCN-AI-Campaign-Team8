import { createBrowserRouter, Navigate } from 'react-router-dom'
import MainLayout from '@/layouts/MainLayout'
import ProtectedRoute from '@/router/ProtectedRoute'
import LoginView from '@/views/LoginView'
import DashboardView from '@/views/DashboardView'
import CreateTaskView from '@/views/CreateTaskView'
import TaskObjectView from '@/views/TaskObjectView'

// 侧边菜单元数据（对应 Vue 路由 meta.title / meta.icon）
export interface NavItem {
  path: string
  title: string
  icon: string
  operatorOnly?: boolean
}

export const navItems: NavItem[] = [
  { path: '/dashboard', title: '审核工作台', icon: 'DataBoard' },
  { path: '/create', title: '发起审核任务', icon: 'Upload', operatorOnly: true },
]

export const router = createBrowserRouter([
  {
    path: '/login',
    element: <LoginView />,
  },
  {
    path: '/',
    element: (
      <ProtectedRoute>
        <MainLayout />
      </ProtectedRoute>
    ),
    children: [
      { index: true, element: <Navigate to="/dashboard" replace /> },
      { path: 'dashboard', element: <DashboardView /> },
      {
        path: 'create',
        element: (
          <ProtectedRoute operatorOnly>
            <CreateTaskView />
          </ProtectedRoute>
        ),
      },
      { path: 'tasks/:code', element: <TaskObjectView /> },
    ],
  },
  { path: '*', element: <Navigate to="/dashboard" replace /> },
])
