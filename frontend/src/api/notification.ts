// Notification & Feishu Integration API Client
import client from './client'
import type {
  NotificationChannel,
  ChannelCreate,
  ChannelUpdate,
  NotificationRule,
  RuleCreate,
  RuleUpdate,
  NotificationDelivery,
  NotificationCatalog,
} from '@/types/notification'

interface Page<T> {
  total: number
  page?: number
  page_size?: number
  items: T[]
}

export const notificationApi = {
  // Catalog
  getCatalog: (projectId: number): Promise<NotificationCatalog> =>
    client.get(`/projects/${projectId}/notifications/catalog`) as unknown as Promise<NotificationCatalog>,

  // Channels
  listChannels: (projectId: number): Promise<NotificationChannel[]> =>
    client.get(`/projects/${projectId}/notifications/channels`) as unknown as Promise<NotificationChannel[]>,

  createChannel: (projectId: number, data: ChannelCreate): Promise<NotificationChannel> =>
    client.post(`/projects/${projectId}/notifications/channels`, data) as unknown as Promise<NotificationChannel>,

  updateChannel: (
    projectId: number,
    channelId: number,
    data: ChannelUpdate
  ): Promise<NotificationChannel> =>
    client.put(
      `/projects/${projectId}/notifications/channels/${channelId}`,
      data
    ) as unknown as Promise<NotificationChannel>,

  deleteChannel: (projectId: number, channelId: number): Promise<void> =>
    client.delete(`/projects/${projectId}/notifications/channels/${channelId}`) as unknown as Promise<void>,

  testChannel: (
    projectId: number,
    channelId: number,
    data: { message: string }
  ): Promise<{ success: boolean; response?: any; error?: string }> =>
    client.post(
      `/projects/${projectId}/notifications/channels/${channelId}/test`,
      data
    ) as unknown as Promise<{ success: boolean; response?: any; error?: string }>,

  // Rules
  listRules: (projectId: number): Promise<NotificationRule[]> =>
    client.get(`/projects/${projectId}/notifications/rules`) as unknown as Promise<NotificationRule[]>,

  createRule: (projectId: number, data: RuleCreate): Promise<NotificationRule> =>
    client.post(`/projects/${projectId}/notifications/rules`, data) as unknown as Promise<NotificationRule>,

  updateRule: (projectId: number, ruleId: number, data: RuleUpdate): Promise<NotificationRule> =>
    client.put(`/projects/${projectId}/notifications/rules/${ruleId}`, data) as unknown as Promise<NotificationRule>,

  deleteRule: (projectId: number, ruleId: number): Promise<void> =>
    client.delete(`/projects/${projectId}/notifications/rules/${ruleId}`) as unknown as Promise<void>,

  // Deliveries (History)
  listDeliveries: (
    projectId: number,
    params?: {
      page?: number
      page_size?: number
      event_type?: string
      status?: string
      started_from?: string
      started_to?: string
    }
  ): Promise<Page<NotificationDelivery>> =>
    client.get(`/projects/${projectId}/notifications/deliveries`, {
      params,
    }) as unknown as Promise<Page<NotificationDelivery>>,
}