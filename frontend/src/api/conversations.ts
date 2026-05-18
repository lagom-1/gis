import { api } from './client'
import type { Conversation, Message } from '../types/conversation'

export const conversationsApi = {
  list: () =>
    api.get<{ conversations: Conversation[]; total: number; page: number; page_size: number }>('/api/conversations'),

  get: (id: number) =>
    api.get<Conversation>(`/api/conversations/${id}`),

  create: (title?: string) =>
    api.post<Conversation>('/api/conversations', { title }),

  delete: (id: number) =>
    api.delete(`/api/conversations/${id}`),

  getMessages: (id: number, limit = 50) =>
    api.get<{ messages: Message[]; has_more: boolean }>(`/api/conversations/${id}/messages?limit=${limit}`),
}
