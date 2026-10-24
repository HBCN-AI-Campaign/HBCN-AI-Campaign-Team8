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
  DocumentTypeSelection,
  RunSummary,
  TaskCreate,
  TaskDetail,
  TaskOut,
  AISession,
  AIResolveOut,
  SupplementIn,
  FacilityContext,
  FacilitySelection,
  DocumentIn,
  BusinessReviewAdviceOut,
  BusinessReviewRun,
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

async function waitForParsingRun(runId: string, onProgress?: (text: string) => void): Promise<ParseResult> {
  if (!/^[a-f0-9]{32}$/.test(runId)) throw new Error('解析编号格式不正确')
  const deadline = Date.now() + 30 * 60 * 1000
  while (Date.now() < deadline) {
    const { data: run } = await http.get<{
      state: string; result?: ParseResult; error?: string
      progress?: { stage?: string; filename?: string; page?: number; total_pages?: number }
    }>(`/api/parsing/runs/${runId}`)
    if (run.state === 'completed' && run.result) return run.result
    if (['failed', 'interrupted'].includes(run.state)) {
      const error = run.error || '解析未完成，请重新提交'
      message.error(error)
      throw new Error(error)
    }
    const p = run.progress
    const stage = p?.stage === 'ocr' || p?.stage === 'ocr_region' ? '文字识别'
      : p?.stage === 'vision' || p?.stage === 'vision_region' || p?.stage === 'vision_correction' ? '原件复核'
        : p?.stage === 'structure' ? '整理跨页明细' : p?.stage === 'mapping' ? '整理业务字段' : '排队准备'
    onProgress?.(`${stage}${p?.filename ? ` · ${p.filename}` : ''}${p?.page ? ` · 第 ${p.page}/${p.total_pages} 页` : ''}`)
    await new Promise(resolve => setTimeout(resolve, 1500))
  }
  message.warning(`解析仍可能在后台进行，可用编号 ${runId} 恢复结果`)
  throw new Error('解析等待超时')
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
  async checkFacilityContext(payload: { documents: DocumentIn[]; facility_selection?: FacilitySelection | null;
    borrower: string; drawdown_currency: string; drawdown_amount: string | null }): Promise<FacilityContext> {
    const { data } = await http.post<FacilityContext>('/api/parsing/facility-context', payload)
    return data
  },
  async businessReviewAudit(code: string): Promise<import('@/business-review/types').ReviewAudit[]> {
    const { data } = await http.get(`/api/tasks/${encodeURIComponent(code)}/business-review/audit`)
    return data
  },
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
  async parseFiles(files: File[], onProgress?: (text: string) => void, onStarted?: (runId: string) => void,
    documentTypes?: DocumentTypeSelection[]): Promise<ParseResult> {
    const form = new FormData()
    files.forEach((f) => form.append('files', f))
    if (documentTypes) form.append('document_types', JSON.stringify(documentTypes))
    const { data } = await http.post<{ run_id: string }>('/api/parsing/runs', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 60000,
    })
    onStarted?.(data.run_id)
    const result = await waitForParsingRun(data.run_id, onProgress)
    if (documentTypes?.some(choice => choice.type_code)) {
      const applied = result.documents.length === files.length && documentTypes.every((choice, index) => {
        if (!choice.type_code) return true
        const doc = result.documents[index]
        return doc.source_filename === files[index].name && doc.type_code === choice.type_code &&
          doc.classification?.method === 'operator_selected' && doc.classification.type_code === choice.type_code &&
          doc.classification.reason === choice.reason.trim()
      })
      if (!applied) {
        const text = '服务器未按本次文件类别选择完成识别，请核对服务版本后重新识别'
        message.error(text)
        throw new Error(text)
      }
    }
    return result
  },

  async resumeParsing(runId: string, onProgress?: (text: string) => void): Promise<ParseResult> {
    return waitForParsingRun(runId, onProgress)
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

  async businessReview(code: string): Promise<BusinessReviewRun> {
    const { data } = await http.get<BusinessReviewRun>(
      `/api/tasks/${encodeURIComponent(code)}/business-review`,
    )
    return data
  },

  async runBusinessReview(code: string): Promise<BusinessReviewRun> {
    const { data } = await http.post<BusinessReviewRun>(
      `/api/tasks/${encodeURIComponent(code)}/business-review/run`, {}, { timeout: 60000 },
    )
    return data
  },

  async resolveBusinessReview(
    code: string,
    findingId: string,
    action: 'acknowledge' | 'approve_exception',
    reason: string,
  ): Promise<BusinessReviewRun> {
    const { data } = await http.post<BusinessReviewRun>(
      `/api/tasks/${encodeURIComponent(code)}/business-review/resolve`,
      { finding_id: findingId, action, reason },
    )
    return data
  },

  async businessReviewAdvice(
    code: string,
    findingId: string,
    question: string,
  ): Promise<BusinessReviewAdviceOut> {
    const { data } = await http.post<BusinessReviewAdviceOut>(
      `/api/tasks/${encodeURIComponent(code)}/business-review/advice`,
      { finding_id: findingId, question },
      { timeout: 90000 },
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

  // 本机真实材料套（ BUSINESS_MATERIALS_ROOT 下的原件，不是仓库示例 PDF ）
  async materialSets(): Promise<MaterialSetsResponse> {
    const { data } = await http.get<MaterialSetsResponse>('/api/materials/sets', { timeout: 15000 })
    return data
  },

  async materialDocuments(code: string): Promise<MaterialDocumentsResponse> {
    const { data } = await http.get<MaterialDocumentsResponse>(
      `/api/materials/sets/${encodeURIComponent(code)}/documents`,
      { timeout: 15000 },
    )
    return data
  },

  async materialDocumentBlob(code: string, index: number): Promise<Blob> {
    const { data } = await http.get<Blob>(
      `/api/materials/sets/${encodeURIComponent(code)}/documents/${index}`,
      { responseType: 'blob', timeout: 120000 },
    )
    return data
  },
}

export interface MaterialSetInfo {
  case_code: string
  title: string
  focus: string
  expected_documents: number
  available: boolean
  reason: string
  document_count?: number
  document_types?: string[]
}

export interface MaterialSetsResponse {
  configured: boolean
  reason: string
  sets: MaterialSetInfo[]
}

export interface MaterialDocumentInfo {
  index: number
  filename: string
  type_code: string
}

export interface MaterialDocumentsResponse {
  case_code: string
  focus: string
  documents: MaterialDocumentInfo[]
}
