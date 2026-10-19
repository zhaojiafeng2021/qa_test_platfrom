export interface PlanItem {
  id: number
  case_id: number
  case_version: number
  sort_order: number
  enabled: boolean
  case_type: 'manual' | 'code'
  case_name?: string | null
  priority?: string | null
  step_count?: number
  // 代码用例额外字段
  module?: string | null
  level?: string | null
}

export interface TestPlan {
  id: number
  project_id: number
  name: string
  description?: string | null
  failure_strategy: 'continue' | 'stop'
  status: 'draft' | 'active' | 'archived'
  owner_id?: number | null
  due_date?: string | null
  notification_channel_id?: number | null
  notification_template_code?: string | null
  created_by: number
  updated_by: number
  created_by_name?: string
  updated_by_name?: string
  created_at: string
  updated_at: string
  items: PlanItem[]
}

export interface PlanPage {
  total: number
  items: TestPlan[]
}

export interface PlanRunItem {
  id: number
  case_id: number
  case_version: number
  execution_id?: number | null
  sort_order: number
  status: string
  case_type: 'manual' | 'code'
  case_name?: string | null
  priority?: string | null
  duration_ms?: number | null
  error_message?: string | null
  total_steps?: number | null
  passed_steps?: number | null
  failed_steps?: number | null
  started_at?: string | null
  finished_at?: string | null
  // 代码用例额外字段
  code_execution_id?: number | null
  logs?: string | null
  module?: string | null
  level?: string | null
}

export interface PlanRun {
  id: number
  plan_id: number
  project_id: number
  trigger_type: string
  status: string
  failure_strategy: string
  total_items: number
  passed_items: number
  failed_items: number
  created_at: string
  started_at?: string | null
  finished_at?: string | null
  items: PlanRunItem[]
}

export interface PlanRunPage {
  total: number
  items: PlanRun[]
}

export interface Schedule {
  id: number
  plan_id: number
  project_id: number
  name: string
  cron_expression: string
  timezone: string
  enabled: boolean
  next_run_at?: string
  last_run_at?: string
  last_status?: string
}

export interface PlanPayload {
  name: string
  description?: string
  failure_strategy: string
  status: string
  owner_id?: number
  due_date?: string
  notification_channel_id?: number
  notification_template_code?: string
  items: Array<{
    case_id: number
    case_version?: number
    sort_order: number
    enabled: boolean
    case_type: 'manual' | 'code'
  }>
}

export interface ReportFile {
  id: number
  project_id: number
  plan_run_id?: number | null
  execution_id?: number | null
  report_type: string
  file_path: string
  file_size?: number | null
  status: 'pending' | 'generated' | 'failed'
  error_message?: string | null
  download_url?: string | null
  created_by: number
  created_at: string
}