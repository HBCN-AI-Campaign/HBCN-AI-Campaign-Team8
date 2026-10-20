import axios from 'axios'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import router from '@/router'
import type {
  CheckResult,
  DashboardStats,
  LoginResp,
  ParseResult,
  RunSummary,
  TaskCreate,
  TaskDetail,
  TaskOut,
  AISession,
  AIResolveOut,
  SupplementIn,
} from '@/types'

const http = axios.create({ baseURL: '/', timeout: 20000 })

// 请求拦截：注入 Bearer token
http.interceptors.request.use((config) => {
  const auth = useAuthStore()
  if (auth.token) {
    config.headers.Authorization = `Bearer ${auth.token}`
  }
  return config
})

// 响应拦截：统一错误处理
http.interceptors.response.use(
  (resp) => resp,
  (error) => {
    const status = error.response?.status
    const detail = error.response?.data?.detail
    if (status === 401) {
      const auth = useAuthStore()
      auth.logout()
      router.push('/login')
      ElMessage.error('登录已过期，请重新登录')
    } else if (status === 403) {
      ElMessage.error(detail || '没有权限执行该操作')
    } else {
      ElMessage.error(detail || '请求失败，请稍后重试')
    }
    return Promise.reject(error)
  },
)

export const api = {
  async login(username: string, password: string): Promise<LoginResp> {
    const form = new URLSearchParams()
    form.append('username', username)
    form.append('password', password)
    const { data } = await http.post<LoginResp>('/api/auth/login', form)
    return data
  },

  async dashboard(): Promise<DashboardStats> {
    const { data } = await http.get<DashboardStats>('/api/tasks/dashboard')
    return data
  },

  async listTasks(mine = false): Promise<TaskOut[]> {
    const { data } = await http.get<TaskOut[]>('/api/tasks', { params: { mine } })
    return data
  },

  async taskDetail(code: string): Promise<TaskDetail> {
    const { data } = await http.get<TaskDetail>(`/api/tasks/${encodeURIComponent(code)}`)
    return data
  },

  async runChecks(code: string): Promise<RunSummary> {
    const { data } = await http.post<RunSummary>(`/api/tasks/${encodeURIComponent(code)}/run`)
    return data
  },

  async getResults(code: string): Promise<CheckResult[]> {
    const { data } = await http.get<CheckResult[]>(
      `/api/tasks/${encodeURIComponent(code)}/results`,
    )
    return data
  },

  // 上传材料 → 文件解析 Agent
  async parseFiles(files: File[]): Promise<ParseResult> {
    const form = new FormData()
    files.forEach((f) => form.append('files', f))
    const { data } = await http.post<ParseResult>('/api/tasks/parse', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 60000,
    })
    return data
  },

  // 经办人确认无误 → 写库创建任务
  async createTask(payload: TaskCreate): Promise<TaskOut> {
    const { data } = await http.post<TaskOut>('/api/tasks', payload)
    return data
  },

  // 审核人退回，催促经办人补件
  async returnTask(code: string, comment = ''): Promise<TaskOut> {
    const { data } = await http.post<TaskOut>(
      `/api/tasks/${encodeURIComponent(code)}/return`, { comment },
    )
    return data
  },

  // 审核人确认通过，归档
  async completeTask(code: string, comment = ''): Promise<TaskOut> {
    const { data } = await http.post<TaskOut>(
      `/api/tasks/${encodeURIComponent(code)}/complete`, { comment },
    )
    return data
  },

  // 经办人补件：回填字段值 / 补充文件 + 补件说明
  async supplementTask(code: string, payload: SupplementIn): Promise<TaskOut> {
    const { data } = await http.post<TaskOut>(
      `/api/tasks/${encodeURIComponent(code)}/supplement`, payload,
    )
    return data
  },

  // 智能审核：启动 / 重跑，返回归集树 + 思考流 + 待处置项
  async aiStart(code: string): Promise<AISession> {
    const { data } = await http.post<AISession>(
      `/api/tasks/${encodeURIComponent(code)}/ai/start`, {}, { timeout: 60000 },
    )
    return data
  },

  // 智能审核：审核人处置某待处理项（accept/keep/ack + 意见）
  async aiResolve(
    code: string, pendingId: string, kind: 'accept' | 'keep' | 'ack', comment = '',
  ): Promise<AIResolveOut> {
    const { data } = await http.post<AIResolveOut>(
      `/api/tasks/${encodeURIComponent(code)}/ai/resolve`,
      { pending_id: pendingId, kind, comment },
    )
    return data
  },
}
