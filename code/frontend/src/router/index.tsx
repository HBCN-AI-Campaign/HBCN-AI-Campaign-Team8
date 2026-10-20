import { createBrowserRouter, Navigate } from 'react-router-dom'
import { lazy, Suspense } from 'react'
import { Spin } from 'antd'
import MainLayout from '@/layouts/MainLayout'
import ProtectedRoute from '@/router/ProtectedRoute'
import LoginView from '@/views/LoginView'
import DashboardView from '@/views/DashboardView'
import CreateTaskView from '@/views/CreateTaskView'
import TaskObjectView from '@/views/TaskObjectView'

const AssistantView = lazy(() => import('@/views/AssistantView'))

// 页面导航元数据
export interface NavItem {
  path: string
  title: string
  icon: string
  operatorOnly?: boolean
}

export const navItems: NavItem[] = [
  { path: '/dashboard', title: '审核工作台', icon: 'DataBoard' },
  { path: '/create', title: '发起审核任务', icon: 'Upload', operatorOnly: true },
  { path: '/assistant', title: '慧眼助手', icon: 'Robot' },
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
      { path: 'assistant', element: <Suspense fallback={<Spin tip="加载慧眼助手"><div style={{ minHeight: 200 }} /></Spin>}><AssistantView /></Suspense> },
    ],
  },
  { path: '*', element: <Navigate to="/dashboard" replace /> },
])
