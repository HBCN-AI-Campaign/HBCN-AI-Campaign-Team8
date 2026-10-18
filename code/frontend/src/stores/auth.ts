import { defineStore } from 'pinia'
import type { Role } from '@/types'

interface AuthState {
  token: string
  role: Role | ''
  displayName: string
}

export const useAuthStore = defineStore('auth', {
  state: (): AuthState => ({
    token: localStorage.getItem('token') || '',
    role: (localStorage.getItem('role') as Role) || '',
    displayName: localStorage.getItem('displayName') || '',
  }),
  getters: {
    isAuthenticated: (s) => !!s.token,
    canReview: (s) => s.role === 'reviewer',
    canCreate: (s) => s.role === 'operator',
  },
  actions: {
    setAuth(token: string, role: Role, displayName: string) {
      this.token = token
      this.role = role
      this.displayName = displayName
      localStorage.setItem('token', token)
      localStorage.setItem('role', role)
      localStorage.setItem('displayName', displayName)
    },
    logout() {
      this.token = ''
      this.role = ''
      this.displayName = ''
      localStorage.removeItem('token')
      localStorage.removeItem('role')
      localStorage.removeItem('displayName')
    },
  },
})
