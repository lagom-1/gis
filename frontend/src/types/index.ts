export type {
  Conversation,
  ConversationCreateRequest,
  ConversationListResponse,
  ConversationMessage,
  Message,
  MessageCreateRequest,
  OutputFile,
  SendMessageResponse,
  SSEEvent,
  SSEEventType,
  ExecutionPhase,
  ToolCall,
} from './conversation'

export interface User {
  id: number
  username: string
  email: string
  credits: number
  created_at: string
}

export interface Task {
  id: number
  user_id: number
  input_text: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
  created_at: string
  started_at: string | null
  completed_at: string | null
  output_files: Record<string, string> | Array<{ name: string; path: string; relative_path?: string; size: number; modified: string }>
  final_answer: string | null
  error_message: string | null
  run_log_path: string | null
  current_step: number | null
  step_description: string | null
}

export interface Order {
  id: number
  user_id: number
  task_id: number
  amount_cents: number
  currency: string
  status: 'pending' | 'paid' | 'refunded'
  payment_method: string | null
  payment_id: string | null
  created_at: string
  paid_at: string | null
}

export interface LoginRequest {
  username: string
  password: string
}

export interface RegisterRequest {
  username: string
  email: string
  password: string
}

export interface AuthResponse {
  access_token: string
  token_type: string
}

export interface TaskCreateRequest {
  input_text: string
}

export interface PaymentCreateRequest {
  task_id: number
  tier: 'free' | 'basic' | 'standard' | 'premium'
}

export const PRICING_TIERS = {
  free: { price: 0, label: '免费预览', description: '仅预览（缩略图、元数据）' },
  basic: { price: 9.9, label: '基础版', description: 'PNG 输出（专题图、图表）' },
  standard: { price: 29.9, label: '标准版', description: '所有图像 + HTML 交互地图' },
  premium: { price: 49.9, label: '高级版', description: '所有输出 + TIF + GIF' },
} as const

export type PricingTier = keyof typeof PRICING_TIERS

export interface SendCodeRequest {
  email: string
}

export interface LoginWithCodeRequest {
  email: string
  code: string
}

export interface WechatAuthResponse {
  auth_url: string
}
