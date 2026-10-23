import type { FieldSource, ParsedField } from '@/types'

export interface ArchivedDocument {
  doc_code: string
  type_code: string
  pdf_file: string | null
  fields: Record<string, unknown> & { _parsing?: {
    classification?: import('@/types').ParsedDocument['classification']
    unresolved_required?: string[]
    unresolved_fields?: string[]
    fields?: Record<string, { machine: ParsedField; final_value: ParsedField['value']; status: string;
      confirmation_reason?: string | null; confirmed_by?: number | null; confirmed_at?: string | null }>
  } }
  field_sources?: Record<string, Omit<FieldSource, 'doc_code' | 'pdf_file'>>
}

export interface ReviewEvidence {
  ref: string
  doc_code: string
  field: string
  value: unknown
  file: string | null
  page: number
  bbox: number[] | null
  quote: string
  confidence: number | null
  verification: string
}
export interface ReviewFinding {
  id: string
  rule_id: string
  name: string
  group: string
  rule_source: string
  status: 'pass' | 'fail' | 'pending' | 'not_applicable'
  reason: string
  lane: 'rule' | 'decision' | 'llm' | 'human'
  route: string
  evidence: ReviewEvidence[]
  original_status: string | null
  model_version: string | null
  probability: number | null
  notes: string[]
}
export interface BusinessReview {
  id?: string
  status: string
  revision?: number
  input_digest?: string
  current_input_digest?: string
  stale: boolean
  error?: string | null
  report: null | {
    input_digest: string
    task_code: string
    business_date: string
    ruleset: string
    findings: ReviewFinding[]
    counts: Record<string, number>
    ready_to_complete: boolean
    trace: string[]
  }
}
export interface ReviewDisposition {
  input_digest: string
  revision: number
  finding_id: string
  decision: 'pass' | 'fail' | 'not_applicable'
  reason: string
  evidence_refs: string[]
}
export interface FieldCorrection {
  input_digest: string
  doc_code: string
  field: string
  value: unknown
  reason: string
  page: number
  quote: string
}

export const goodsColumns = ['description', 'quantity', 'unit', 'line_no', 'unit_price', 'amount', 'currency'] as const
export type GoodsColumn = typeof goodsColumns[number]
export interface GoodsCellSource { page: number; quote: string; bbox?: number[] | null }
export interface GoodsReadRow {
  value: Partial<Record<GoodsColumn, string>> & { description: string; quantity: string; unit: string }
  cells: Partial<Record<GoodsColumn, GoodsCellSource[]>>
}
export interface GoodsReviewInput {
  input_digest: string; doc_code: string; file_sha256: string; page_count: number
  all_pages_checked: boolean; references: 'none' | 'included' | 'missing'; expected_rows: number
  rows: GoodsReadRow[]; reason: string
}
export interface GoodsReviewContext {
  input_digest: string
  documents: { doc_code: string; type_code: string; pdf_file: string; file_sha256: string; page_count: number
    verification: 'reviewer' | 'unreviewed'; review: GoodsReviewInput | null }[]
}
export interface ReviewRetry {
  input_digest: string
  revision: number
  reason: string
}
export interface ReviewAudit {
  id: string
  user_id: number
  kind: string
  reason: string
  created_at: string
  data: {
    previous_revision?: number
    previous_report?: NonNullable<BusinessReview['report']>
    changes?: { doc_code: string; replaces?: string | null; previous_pdf?: string | null;
      pdf_file?: string | null; previous_document?: ArchivedDocument | null }[]
  }
}
