export interface NotificationChannel {
  id: number
  project_id: number
  name: string
  channel_type: string
  enabled: boolean
  webhook_masked: string
  last_test_status?: string
  last_test_at?: string
  last_triggered_at?: string
  created_at: string
  updated_at: string
}

export interface NotificationRule {
  id: number
  project_id: number
  name: string
  enabled: boolean
  event_type: string
  channel_id?: number
  channel_name?: string
  template_code: string
  recipient_type: string
  recipient_config: Record<string, any>
  conditions_json: Record<string, any>
  created_at: string
  updated_at: string
}

export interface NotificationDelivery {
  id: number
  project_id: number
  rule_id?: number
  rule_name?: string
  channel_id?: number
  channel_name?: string
  event_id: string
  event_type: string
  status: 'pending' | 'sending' | 'sent' | 'retrying' | 'failed' | 'skipped'
  attempt_count: number
  max_attempts: number
  next_attempt_at?: string
  error_message?: string
  message_summary?: string
  created_at: string
  sent_at?: string
}

export interface EventCatalog {
  code: string
  name: string
  description: string
}

export interface TemplateCatalog {
  code: string
  name: string
  event_types: string[]
  tone: string
}

export interface ChannelCreate {
  name: string
  webhook_url: string
  enabled?: boolean
}

export interface ChannelUpdate {
  name?: string
  webhook_url?: string
  enabled?: boolean
}

export interface RuleCreate {
  name: string
  event_type: string
  channel_id: number
  template_code?: string
  recipient_type?: string
  recipient_config?: Record<string, any>
  conditions_json?: Record<string, any>
  enabled?: boolean
}

export interface RuleUpdate {
  name?: string
  event_type?: string
  channel_id?: number
  template_code?: string
  recipient_type?: string
  recipient_config?: Record<string, any>
  conditions_json?: Record<string, any>
  enabled?: boolean
}

export interface NotificationCatalog {
  events: EventCatalog[]
  templates: TemplateCatalog[]
}
