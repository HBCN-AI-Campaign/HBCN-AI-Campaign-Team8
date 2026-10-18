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
  borrower: string
  drawdown_currency: string
  drawdown_amount: number
  status: string
}

export interface DocumentOut {
  id: number
  doc_code: string
  type_code: string
  fields: Record<string, any>
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
  detail: [string, string, string][] // [label, value, flag]
}

export interface RunSummary {
  task_code: string
  counts: Record<string, number>
  results: CheckResult[]
}

export interface DashboardStats {
  total_tasks: number
  created: number
  reviewing: number
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
}

export interface ParsedDocument {
  doc_code: string
  type_code: string
  type_label: string
  source_filename: string
  fields: ParsedField[]
}

export interface ParseResult {
  suggested_task_code: string
  suggested_borrower: string
  suggested_currency: string
  suggested_amount: number
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
  task_code: string
  borrower: string
  drawdown_currency: string
  drawdown_amount: number
  documents: DocumentIn[]
}
