import { create } from 'zustand'
import type { Role } from '@/types'

interface AuthState {
  token: string
  role: Role | ''
  displayName: string
  // getters（派生值）
  isAuthenticated: () => boolean
  canReview: () => boolean
  canCreate: () => boolean
  // actions
  setAuth: (token: string, role: Role, displayName: string) => void
  logout: () => void
}

export const useAuthStore = create<AuthState>((set, get) => ({
  token: localStorage.getItem('token') || '',
  role: (localStorage.getItem('role') as Role) || '',
  displayName: localStorage.getItem('displayName') || '',

  isAuthenticated: () => !!get().token,
  canReview: () => get().role === 'reviewer',
  canCreate: () => get().role === 'operator',

  setAuth: (token, role, displayName) => {
    localStorage.setItem('token', token)
    localStorage.setItem('role', role)
    localStorage.setItem('displayName', displayName)
    set({ token, role, displayName })
  },
  logout: () => {
    localStorage.removeItem('token')
    localStorage.removeItem('role')
    localStorage.removeItem('displayName')
    set({ token: '', role: '', displayName: '' })
  },
}))
