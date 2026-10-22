export type AssistantRole = 'user' | 'assistant'

export interface AssistantSession {
  id: number
  title: string
  task_code?: string | null
  message_count: number
  updated_at: string
  owner_id?: number
  shared?: boolean
  can_manage?: boolean
}

export interface AssistantStep {
  key: string
  label: string
  detail?: string
  status: 'running' | 'completed' | 'error'
}

export interface AssistantCitation {
  id: string
  label: string
  source: string
  detail?: string
  page?: number | null
  status?: 'pass' | 'fail' | 'warn'
  reference_id?: string
  source_id?: string
}

export interface AssistantMessage {
  id: number | string
  role: AssistantRole
  content: string
  status: string
  steps: AssistantStep[]
  citations: AssistantCitation[]
  created_at?: string
  streaming?: boolean
  author_id?: number | null
  author_name?: string
  run_id?: string | null
}

export interface AssistantSessionDetail extends AssistantSession {
  messages: AssistantMessage[]
  event_cursor?: number
  active_run?: import('./collaboration').Run | null
}

export interface AssistantTaskOption {
  id: number
  task_code: string
  borrower: string
  status: string
}

export interface AssistantCapabilities {
  sdk: string
  configured: boolean
  model?: string | null
  rag_available: boolean
  supports_stream: boolean
  message: string
}

export interface AssistantToolActivity {
  name: string
  status: 'running' | 'completed' | 'error'
  result_count?: number
}

export interface AssistantSkill {
  id: string
  name: string
  desc: string
  version: string
  owner: string
  license: string
  permissions: string[]
}

export interface AssistantStreamEvent {
  event: string
  message_id?: string
  task_code?: string | null
  delta?: string
  step?: AssistantStep
  citations?: AssistantCitation[]
  tool?: AssistantToolActivity
  message?: AssistantMessage
  error_message?: string
}
