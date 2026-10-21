import axios from 'axios'
import { message as staticMessage } from 'antd'
import type { MessageInstance } from 'antd/es/message/interface'
import { useAuthStore } from '@/stores/auth'
import type {
  CheckResult,
  Customer,
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

// 由 App 注入的导航回调（替代 Vue 的 router.push）——避免在非组件环境直接依赖 react-router
let navigate: ((path: string) => void) | null = null
export function bindNavigate(fn: (path: string) => void) {
  navigate = fn
}

// 由 <App> 注入的 message 实例（antd v5 推荐：静态 message 无法消费主题 context）
let message: MessageInstance = staticMessage
export function bindMessage(instance: MessageInstance) {
  message = instance
}

// 请求拦截：注入 Bearer token
http.interceptors.request.use((config) => {
  const { token } = useAuthStore.getState()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
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
      useAuthStore.getState().logout()
      navigate?.('/login')
      message.error('登录已过期，请重新登录')
    } else if (status === 403) {
      message.error(detail || '没有权限执行该操作')
    } else {
      message.error(detail || '请求失败，请稍后重试')
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

  async listTasks(mine = false, customerNo?: string): Promise<TaskOut[]> {
    const params: Record<string, unknown> = { mine }
    if (customerNo) params.customer_no = customerNo
    const { data } = await http.get<TaskOut[]>('/api/tasks', { params })
    return data
  },

  // 客户搜索（按客户号 / 名称模糊）——创建任务、筛选均用
  async searchCustomers(q = '', limit = 20): Promise<Customer[]> {
    const { data } = await http.get<Customer[]>('/api/customers', {
      params: { q, limit },
    })
    return data
  },

  async taskDetail(code: string): Promise<TaskDetail> {
    const { data } = await http.get<TaskDetail>(`/api/tasks/${encodeURIComponent(code)}`)
    return data
  },

  // 更正单据字段抓取值（经办人/审核人皆可）→ 返回最新任务详情（含 needs_recheck）
  async updateDocFields(
    code: string,
    docId: number,
    updates: { field_key: string; value: unknown }[],
  ): Promise<TaskDetail> {
    const { data } = await http.patch<TaskDetail>(
      `/api/tasks/${encodeURIComponent(code)}/documents/${docId}/fields`,
      { updates },
    )
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

  // 智能审核：播放完成后，任务进入「待复核」
  async aiComplete(code: string): Promise<TaskOut> {
    const { data } = await http.post<TaskOut>(
      `/api/tasks/${encodeURIComponent(code)}/ai/complete`, {},
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
