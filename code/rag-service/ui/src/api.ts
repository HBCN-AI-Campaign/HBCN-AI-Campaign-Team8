import { XStream } from '@ant-design/x'

export type Scope = 'all' | 'business_rules' | 'project_design' | 'law'
export type Purpose = 'reference' | 'case_assessment'
export interface LegalContext { business_date: string; jurisdiction: string; subject_type: string; business_type: string }
export interface Capabilities {
  workbench_contract_version: number
  engine: string; retrieval: boolean; answer_generation: boolean; enhanced_retrieval: boolean
  external_law_mcp: boolean; document_ingestion: boolean; supported_scopes: string[]
  max_upload_bytes: number; supported_file_extensions: string[]
}
export interface Evidence {
  citation: number; content: string; document_id: string; document_name: string
  chunk_id?: string | null; page?: number | null; score?: number | null
  source_url?: string | null; reader_url?: string | null; metadata: Record<string, unknown>
}
export interface Result {
  query: string; sources: Evidence[]; answer?: string; warnings: string[]; missing: string[]
  grounding?: 'cited' | 'insufficient'; evidence_status?: 'sufficient' | 'insufficient' | 'clarification'
  clarification_question?: string | null; stop_reason: string; retrieval_rounds: number
  source_status: Record<string, string>; rerank_status: string
  legal_applicability: { status?: string }; answer_verification?: { status?: string }
}
export interface Request {
  query: string; scope: Scope; top_k: number; sources: ('knowledge_base' | 'pkulaw')[]
  purpose: Purpose; legal_context?: LegalContext
  conversation: { role: 'user' | 'assistant'; content: string }[]
}
export interface Step { key: string; label: string; status: 'running' | 'done' }
export interface KnowledgeDocument {
  id: string; name: string; scope: Scope; state?: string; stage?: string; error?: string | null
  sha256?: string
  chunk_count?: number; run?: string
  source_available?: boolean
  quality?: { status: string; policy_version: string; blockers: string[]; review_reasons: string[]; unit_count: number; review_status?: string } | null
}
export interface DocumentContent { document: KnowledgeDocument; pages: { page: number | null; text: string }[] }

async function checkedResponse(url: string, init?: RequestInit) {
  const response = await fetch(url, { credentials: 'same-origin', ...init })
  if (!response.ok) {
    if (response.status === 401) throw new Error('会话无效，请重新打开本机 /ui/ 页面。')
    if (response.status === 422) throw new Error('请求条件不完整或格式有误，请检查日期、范围和输入长度。')
    // Do not render upstream error bodies, credentials, exception traces or HTML.
    throw new Error(`服务请求未完成（${response.status}），请检查服务状态后重试。`)
  }
  return response
}
async function json<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await checkedResponse(url, init)
  try { return await response.json() as T }
  catch (error) {
    if (init?.signal?.aborted) throw error
    throw new Error('服务返回的数据格式异常，本轮未完成。')
  }
}
function post(body: unknown, signal?: AbortSignal): RequestInit {
  return { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal }
}
function checkedResult(value: unknown): Result {
  const result = value as Result
  if (!result || typeof result.query !== 'string' || !Array.isArray(result.sources)
    || !Array.isArray(result.warnings) || !Array.isArray(result.missing)
    || ![...result.warnings, ...result.missing].every(text => typeof text === 'string')
    || !result.sources.every(source => Number.isInteger(source.citation) && source.citation > 0
      && typeof source.content === 'string' && typeof source.document_name === 'string' && typeof source.document_id === 'string'
      && source.metadata && typeof source.metadata === 'object' && !Array.isArray(source.metadata))
    || new Set(result.sources.map(source => source.citation)).size !== result.sources.length
    || (result.answer !== undefined && typeof result.answer !== 'string')) throw new Error('服务返回格式异常，本轮未完成。')
  return result
}
export const getCapabilities = (signal?: AbortSignal) => json<Capabilities>('/api/v1/capabilities', { signal })
export function withdrawDocument(document: KnowledgeDocument, signal?: AbortSignal) {
  if (!originalPath(document.id) || !/^[0-9a-f]{64}$/.test(document.sha256 || '')) throw new Error('文档编号或版本无效，请刷新后重试。')
  return json<{ document: KnowledgeDocument }>(`/api/v1/documents/${document.id}/withdraw`, post({ expected_sha256: document.sha256, reason: 'other' }, signal))
}
export async function retrieve(payload: Request, signal?: AbortSignal) {
  return checkedResult(await json<unknown>('/api/v1/retrievals', post(payload, signal)))
}
export async function answer(payload: Request, signal: AbortSignal, onStep: (step: Step) => void) {
  const response = await checkedResponse('/api/v1/answers/stream', post(payload, signal))
  if (!response.body || !response.headers.get('content-type')?.startsWith('text/event-stream')) throw new Error('未收到有效事件流。')
  let result: Result | undefined
  const reader = XStream({ readableStream: response.body }).getReader()
  try { while (true) {
    const next = await reader.read()
    if (next.done) break
    const event = next.value
    // XStream 1.6 keeps the optional leading space after an SSE field colon.
    const type = String(event.event || '').trim()
    if (signal.aborted) throw new DOMException('Aborted', 'AbortError')
    if (type === 'error') throw new Error('检索或生成服务未完成本轮请求，请稍后重试。')
    if (!['step', 'result'].includes(type)) continue
    let value
    try { value = JSON.parse(event.data) } catch { throw new Error('事件流格式异常，本轮未完成。') }
    if (type === 'result') {
      if (result) throw new Error('收到重复结果，本轮未完成。')
      result = checkedResult(value)
    } else if (typeof value.key === 'string' && typeof value.label === 'string' && ['running', 'done'].includes(value.status)) {
      onStep(value)
    }
  } } finally { await reader.cancel().catch(() => undefined); reader.releaseLock() }
  if (signal.aborted) throw new DOMException('Aborted', 'AbortError')
  if (!result) throw new Error('连接提前结束，未收到完整结果。')
  return result
}
const UUID = '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'
export function readerPath(value?: string | null) {
  return value && new RegExp(`^/api/v1/documents/${UUID}/content(?:\\?chunk_id=${UUID})?$`).test(value) ? value : null
}
export function originalPath(id: string) {
  return new RegExp(`^${UUID}$`).test(id) ? `/api/v1/documents/${id}/source` : null
}
export function externalLink(value?: string | null) {
  try {
    const url = new URL(value || '')
    return url.protocol === 'https:' && !url.username && !url.password ? url.href : null
  } catch { return null }
}
export async function getContent(path: string, signal?: AbortSignal) {
  if (!readerPath(path)) throw new Error('原文地址不符合本地文档接口。')
  const data = await json<DocumentContent>(path, { signal })
  const expectedId = path.split('/')[4].toLowerCase()
  if (!data?.document || typeof data.document.id !== 'string' || data.document.id.toLowerCase() !== expectedId
    || (data.document.source_available !== undefined && typeof data.document.source_available !== 'boolean')
    || !Array.isArray(data.pages) || !data.pages.every(page => page && typeof page.text === 'string'
      && (page.page === null || (Number.isInteger(page.page) && page.page! > 0)))) throw new Error('原文格式或文档归属异常。')
  return data
}
export const getDocuments = (signal?: AbortSignal) => json<{ documents: KnowledgeDocument[] }>('/api/v1/documents', { signal })
export const getDocument = (id: string, signal?: AbortSignal) => {
  if (!originalPath(id)) throw new Error('文档编号无效。')
  return json<KnowledgeDocument>(`/api/v1/documents/${id}`, { signal })
}
export function uploadDocument(file: File, scope: Exclude<Scope, 'all'>, signal?: AbortSignal) {
  const form = new FormData()
  form.append('file', file); form.append('scope', scope)
  return json<{ document: KnowledgeDocument; created: boolean }>('/api/v1/ingestions', { method: 'POST', body: form, signal })
}
export function errorMessage(error: unknown) { return error instanceof Error ? error.message : '本轮未完成，请重试。' }
