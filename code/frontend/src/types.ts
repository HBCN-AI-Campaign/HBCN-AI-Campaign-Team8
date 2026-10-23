export type Role = 'operator' | 'reviewer'

export interface LoginResp {
  access_token: string
  token_type: string
  role: Role
  display_name: string
}

export interface TaskOut {
  id: number
  task_code: string
  customer_no?: string | null
  customer_name?: string | null
  borrower: string
  drawdown_currency: string
  drawdown_amount: number
  status: string
  needs_recheck?: boolean // 字段被编辑后待重新核对
  created_at?: string | null
  review_comment?: string | null
  supplement_note?: string | null
}

// --- 客户主数据 ---
export interface Customer {
  id: number
  customer_no: string
  name: string
}

// --- 补件（经办人回填） ---
export interface SupplementFieldUpdate {
  doc_code: string
  field_key: string
  value: any
}

export interface SupplementIn {
  note?: string
  field_updates?: SupplementFieldUpdate[]
  added_files?: string[]
}

export interface FieldSource {
  doc_id?: number // 单据主键（编辑字段用）
  doc_code?: string
  type_code?: string
  field_key?: string // 字段键（编辑字段用）
  pdf_file?: string | null
  page?: number | null
  bbox?: number[] | null // [x0, y0, x1, y1] 归一化 0~1
  method?: string | null
  confidence?: number | null
}

export interface DocumentOut {
  id: number
  doc_code: string
  type_code: string
  fields: Record<string, any>
  pdf_file?: string | null
  field_sources?: Record<string, FieldSource>
}

export interface TaskDetail extends TaskOut {
  documents: DocumentOut[]
  result_counts: Record<string, number>
}

export type CheckStatus = 'pass' | 'fail' | 'warn'

export interface CheckResult {
  rule_id: string
  rule_name: string
  dimension: string
  status: CheckStatus
  why: string
  suggestion: string
  // [label, value, flag] 或 [label, value, flag, source]
  detail: (string | FieldSource | null)[][]
}

export type BusinessFindingStatus = 'pass' | 'fail' | 'needs_review' | 'not_applicable'

export interface BusinessReviewResolution {
  action: 'acknowledge' | 'approve_exception'
  reason: string
  actor_id: number
  actor_name: string
  recorded_at: string
}

export interface BusinessReviewFinding {
  finding_id: string
  tier: string
  rule_id: string
  rule_name: string
  dimension: string
  status: BusinessFindingStatus
  raw_status: string
  requires_resolution: boolean
  why: string
  suggestion: string
  evidence: unknown[]
  resolution?: BusinessReviewResolution | null
  business_conflict?: string
}

export interface BusinessReviewAdvisory {
  status: 'available' | 'unavailable'
  answer?: string | null
  citations: { id?: string; label?: string; source?: string; page?: number; detail?: string }[]
  created_at?: string
}

export interface BusinessReviewRun {
  run_id?: number
  task_code?: string
  status: 'not_run' | 'needs_review' | 'ready_for_approval'
  is_current: boolean
  input_hash?: string
  created_at?: string
  findings: BusinessReviewFinding[]
  decision_model: { status: string; threshold: number }
  advisories: Record<string, BusinessReviewAdvisory>
}

export interface BusinessReviewAdviceOut {
  status: 'available' | 'unavailable'
  finding_id: string
  answer?: string | null
  citations: BusinessReviewAdvisory['citations']
}

export interface RunSummary {
  task_code: string
  counts: Record<string, number>
  results: CheckResult[]
}

export interface DashboardStats {
  total_tasks: number
  pending: number
  ai_reviewing: number
  to_recheck: number
  need_supplement: number
  completed: number
}

// --- 文件解析 Agent ---
export interface ParsedField {
  key: string
  label: string
  value: string | number | string[] | null
  kind: 'text' | 'number' | 'currency' | 'list'
  confidence: number
  source?: { page: number; bbox: number[] } | null
}

export interface ParsedDocument {
  doc_code: string
  type_code: string
  type_label: string
  source_filename: string
  pdf_file?: string | null
  fields: ParsedField[]
}

export interface ParseResult {
  suggested_task_code: string
  suggested_borrower: string
  suggested_currency: string
  suggested_amount: number
  suggested_customer_no?: string | null
  suggested_customer_name?: string | null
  documents: ParsedDocument[]
}

// --- 智能审核 Agent ---
export interface AITreeNode {
  doc_code: string
  type_code: string
  level: number
  summary: string
}

export interface AIThought {
  kind: 'phase' | 'parse' | 'pass' | 'warn' | 'fail' | 'special'
  tag: string
  text: string
  pending_id: string | null
  pause: boolean
  parse_index: number | null
  parse_total: number | null
}

export interface AIPending {
  id: string
  rule_name: string
  dimension: string
  status: 'fail' | 'warn' | 'special'
  why: string
  suggestion: string
}

export interface AISession {
  task_code: string
  tree: AITreeNode[]
  thoughts: AIThought[]
  pendings: AIPending[]
  counts: Record<string, number>
}

export interface AIResolveOut {
  pending_id: string
  kind: 'accept' | 'keep' | 'ack'
  new_status: CheckStatus
  counts: Record<string, number>
}

// --- 创建任务入参 ---
export interface DocumentIn {
  doc_code: string
  type_code: string
  fields: Record<string, any>
}

export interface TaskCreate {
  // 任务编号由后端自增生成，前端不再传入
  customer_no?: string | null
  borrower: string
  drawdown_currency: string
  drawdown_amount: number
  documents: DocumentIn[]
}
