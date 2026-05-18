import api from './api'
import type {
  Conversation,
  ConversationCreateRequest,
  ConversationListResponse,
  ConversationMessage,
  MessageCreateRequest,
  SendMessageResponse,
} from '../types'

export const conversationsService = {
  async createConversation(data: ConversationCreateRequest): Promise<Conversation> {
    const response = await api.post<Conversation>('/conversations', data)
    return response.data
  },

  async getConversations(params?: { page?: number; page_size?: number }): Promise<ConversationListResponse> {
    const response = await api.get<ConversationListResponse>('/conversations', { params })
    return response.data
  },

  async getConversation(convId: number): Promise<Conversation> {
    const response = await api.get<Conversation>(`/conversations/${convId}`)
    return response.data
  },

  async deleteConversation(convId: number): Promise<void> {
    await api.delete(`/conversations/${convId}`)
  },

  async getMessages(
    convId: number,
    params?: { before?: number; limit?: number }
  ): Promise<{ messages: ConversationMessage[]; has_more: boolean }> {
    const response = await api.get(`/conversations/${convId}/messages`, { params })
    return response.data
  },

  async sendMessage(convId: number, data: MessageCreateRequest): Promise<SendMessageResponse> {
    const response = await api.post<SendMessageResponse>(
      `/conversations/${convId}/messages`,
      data
    )
    return response.data
  },
}
