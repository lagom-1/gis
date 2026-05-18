export interface Conversation {
  id: number
  title: string
  status: 'active' | 'processing' | 'archived'
  created_at: string
  updated_at: string
  last_message?: Message
  message_count?: number
}

export interface Message {
  id: number
  conversation_id: number
  role: 'user' | 'assistant' | 'system' | 'tool_call' | 'tool_result'
  content: string
  tool_name?: string
  tool_args?: Record<string, unknown>
  tool_result?: Record<string, unknown>
  output_files?: OutputFile[]
  created_at: string
}

export interface OutputFile {
  name: string
  path: string
  size: number
  modified: string
}

export type SSEEventType =
  | 'thinking' | 'step_start' | 'tool_start' | 'tool_result'
  | 'ask_user' | 'final_answer' | 'error' | 'done' | 'heartbeat'

export interface SSEEvent {
  type: SSEEventType
  data: Record<string, unknown>
}

export type ExecutionPhase = 'idle' | 'thinking' | 'executing' | 'waiting_for_user' | 'done'

export interface ToolCall {
  tool: string
  args: Record<string, unknown>
  result?: Record<string, unknown>
  status: 'pending' | 'running' | 'success' | 'error'
}

export interface ConversationCreateRequest {
  title?: string
  initial_message?: string
}

export interface ConversationListResponse {
  conversations: Conversation[]
  total: number
  page: number
  page_size: number
}

export interface MessageCreateRequest {
  content: string
}

export interface SendMessageResponse {
  success: boolean
  message_id: number
  type: 'final' | 'ask_user'
  answer?: string
  question?: string
  options?: string[]
  steps: number
}

export type ConversationMessage = Message
