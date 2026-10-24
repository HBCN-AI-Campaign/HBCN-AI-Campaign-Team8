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
  drawdown_amount: string | number // 新接口返回十进制字符串；兼容已有数值响应
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
  input_digest?: string
}

export interface FieldSource {
  doc_id?: number // 单据主键（编辑字段用）
  doc_code?: string
  type_code?: string
  field_key?: string // 字段键（编辑字段用）
  pdf_file?: string | null
  page: number
  bbox: number[] // [x0, y0, x1, y1] 归一化 0~1
}

export interface DocumentOut {
  id: number
  doc_code: string
  type_code: string
  fields: Record<string, any>
  pdf_file?: string | null
  field_sources?: Record<string, { page: number; bbox: number[] }>
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
export interface ParsedRowResult {
  value: Record<string, unknown> | null
  status: 'accepted' | 'needs_review' | 'conflict'
  issues: string[]
  cells: Record<string, {
    value: unknown
    raw_value?: string
    issues: string[]
    sources: { block_id: string; page: number; bbox: number[]; text: string; method: string; score: number }[]
  }>
}

export interface ParsedField {
  key: string
  label: string
  value: string | number | string[] | Record<string, unknown>[] | null
  kind: 'text' | 'number' | 'currency' | 'list' | 'json'
  confidence: number
  source?: { page: number; bbox: number[] } | null
  status?: 'accepted' | 'missing' | 'needs_review' | 'conflict'
  required?: boolean
  candidates?: Record<string, unknown>[]
  choices?: string[]
  confirmation_reason?: string
  row_results?: ParsedRowResult[]
  issues?: string[]
  margin_blocks?: { block_id: string; page: number; bbox: number[]; text: string }[]
  term_facts?: { schema_version: string; facilities: FacilityTermApplication[] }
}

export interface ParsedDocument {
  doc_code: string
  type_code: string
  type_label: string
  source_filename: string
  pdf_file?: string | null
  fields: ParsedField[]
  status?: string
  issues?: unknown[]
  page_count?: number
  classification?: { method: 'operator_selected'; type_code: string; reason: string; selected_by: number; selected_at: string }
}

export interface DocumentTypeSelection {
  type_code: string | null
  reason: string
}

export interface ParseResult {
  suggested_task_code: string
  suggested_borrower: string
  suggested_currency: string
  suggested_amount: string | number | null
  suggested_customer_no?: string | null
  suggested_customer_name?: string | null
  documents: ParsedDocument[]
  parse_run_id?: string
  status?: string
  facility_context?: FacilityContext | null
}

export interface FacilitySelection {
  borrower_id: string
  allocation_id: string
  reason: string
}

export interface FacilityRecord extends Omit<ParsedRowResult, 'status'> {
  status: ParsedRowResult['status'] | 'confirmed'
  id: string
  doc_code: string
  field_key: string
  row_index: number
  borrower_ids?: string[]
}

export interface FacilityContext {
  status: 'ready' | 'needs_review'
  issues: { code: string; message: string }[]
  request: Record<string, { value: string | null; doc_code: string; source?: { page: number; bbox: number[] } | null }>
  borrowers: FacilityRecord[]
  allocations: FacilityRecord[]
  selected_borrower_id: string | null
  selected_allocation_id: string | null
  association_method: string | null
  nominal_limit: { amount: string; currency: string; facility_name: string; doc_code: string } | null
  comparison: 'within_nominal_limit' | 'exceeds_nominal_limit' | null
  available_balance: null
  selection?: FacilitySelection | null
  confirmed_by?: number | null
  confirmed_at?: string | null
  term_application?: FacilityTermApplication | null
}

export interface TermPeriod { count: number; unit: 'days' | 'months' }
export interface TermFact<T> {
  status: 'accepted' | 'needs_review'
  value: T | null
  issues: string[]
  clause_heading: string | null
  evidence: ParsedRowResult['cells']
}
export interface FacilityTermApplication {
  schema_version?: string
  doc_code?: string
  facility_name: string
  schedule_name?: string
  scope_method?: string
  status: 'accepted' | 'needs_review'
  issues: string[]
  facts: {
    permitted_currencies?: TermFact<{ currencies: string[]; aggregate_limit_currency: string | null; aggregate_limit_condition: string }>
    loan_tenor?: TermFact<{ standard_periods: TermPeriod[]; other_period_requires_lender_agreement: boolean | null;
      absolute_maximum: TermPeriod | null; maximum_includes_extensions_and_rollovers: boolean | null;
      maximum_scope: 'each_loan' | 'each_utilization' | 'each_draft'; instrument_maxima: Record<string, TermPeriod> }>
    purpose?: TermFact<{ clause_text: string }>
    interest?: TermFact<{ clause_text: string }>
    default_interest?: TermFact<{ clause_text: string }>
  }
  date_span?: { status: 'needs_review'; elapsed_days: number | null; drawdown_date?: string; maturity_date?: string; issue: string }
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
  pdf_file?: string | null
  field_sources?: Record<string, { page: number; bbox: number[] } | null | undefined>
  parse_run_id?: string
  field_confirmations?: Record<string, string | undefined>
}

export interface TaskCreate {
  // 任务编号由后端自增生成，前端不再传入
  customer_no?: string | null
  borrower: string
  drawdown_currency: string
  drawdown_amount: string
  documents: DocumentIn[]
  facility_selection?: FacilitySelection | null
}
