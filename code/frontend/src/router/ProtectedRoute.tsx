import { Navigate, useLocation } from 'react-router-dom'
import type { ReactNode } from 'react'
import { useAuthStore } from '@/stores/auth'

interface Props {
  children: ReactNode
  /** 仅经办人可进（对应 Vue meta.operatorOnly） */
  operatorOnly?: boolean
}

/**
 * 路由鉴权守卫，替代 Vue Router 的 router.beforeEach：
 *  - 未登录 → 重定向到 /login，并带上 redirect 回跳地址
 *  - 已登录但无权限（operatorOnly）→ 回 /dashboard
 */
export default function ProtectedRoute({ children, operatorOnly }: Props) {
  const location = useLocation()
  const token = useAuthStore((s) => s.token)
  const role = useAuthStore((s) => s.role)

  if (!token) {
    return <Navigate to="/login" replace state={{ redirect: location.pathname + location.search }} />
  }
  if (operatorOnly && role !== 'operator') {
    return <Navigate to="/dashboard" replace />
  }
  return <>{children}</>
}
