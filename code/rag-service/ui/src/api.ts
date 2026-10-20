export type KnowledgeScope = 'business_rules' | 'project_design' | 'all'

export interface Capabilities {
  service?: string
  engine: string
  retrieval: boolean
  document_ingestion: boolean
  supported_scopes: string[]
  max_upload_bytes: number
  upload_timeout_seconds: number
  supported_file_extensions: string[]
}

export interface KnowledgeDocument {
  id: string
  name: string
  scope: Exclude<KnowledgeScope, 'all'>
  created_at?: string | null
  chunk_count?: number | null
}

export interface Evidence {
  content: string
  document_id?: string | null
  document_name?: string | null
  page?: number | null
  score?: number | null
}

export interface QueryResult {
  query: string
  scope: KnowledgeScope
  evidence: Evidence[]
  warnings: string[]
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, { credentials: 'include', ...init })
  if (!response.ok) {
    let detail = `请求失败（${response.status}）`
    try {
      const body = (await response.json()) as { detail?: string }
      if (body && typeof body.detail === 'string') detail = body.detail
    } catch {
      // ignore non-JSON error bodies
    }
    throw new Error(detail)
  }
  return response.json() as Promise<T>
}

export function getCapabilities() {
  return request<Capabilities>('/api/v1/capabilities')
}

export function getDocuments() {
  return request<{ engine: string; documents: KnowledgeDocument[] }>('/api/v1/documents')
}

export function retrieve(query: string, scope: KnowledgeScope, topK: number) {
  return request<QueryResult>('/api/v1/query', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, scope, top_k: topK }),
  })
}

export function uploadDocument(
  scope: Exclude<KnowledgeScope, 'all'>,
  file: File,
  onProgress: (percent: number) => void,
  timeoutMs = 900_000,
): Promise<{ status: string; message: string }> {
  return new Promise((resolve, reject) => {
    const form = new FormData()
    form.append('scope', scope)
    form.append('file', file)
    const xhr = new XMLHttpRequest()
    xhr.open('POST', '/api/v1/documents')
    xhr.withCredentials = true
    xhr.timeout = timeoutMs
    xhr.upload.onprogress = event => {
      if (event.total) onProgress(Math.round((event.loaded / event.total) * 100))
    }
    xhr.onload = () => {
      try {
        const data = JSON.parse(xhr.responseText) as { status: string; message: string; detail?: string }
        if (xhr.status >= 200 && xhr.status < 300) resolve(data)
        else reject(new Error(data.detail || `上传失败（${xhr.status}）`))
      } catch (error) {
        reject(error instanceof Error ? error : new Error('上传失败'))
      }
    }
    xhr.onerror = () => reject(new Error('网络错误，上传失败'))
    xhr.ontimeout = () => reject(new Error('上传超时'))
    xhr.send(form)
  })
}

export function errorMessage(error: unknown) {
  if (error instanceof Error) return error.message
  return '发生未知错误'
}
