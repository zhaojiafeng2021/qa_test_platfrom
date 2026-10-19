/**
 * 环境与变量管理相关类型定义
 */

/**
 * 环境信息
 */
export interface Environment {
  id: number
  project_id: number
  name: string
  display_name: string | null
  description: string | null
  base_url: string | null
  sort_order: number
  is_active: boolean
  grafana_target_json?: {
    namespace?: string
    pod_pattern?: string
    dashboard_uid?: string
  } | null
  created_by: number | null
  updated_by: number | null
  created_at: string
  updated_at: string
}

/**
 * 创建环境请求
 */
export interface CreateEnvironmentRequest {
  name: string
  display_name?: string
  description?: string
  base_url?: string
  sort_order?: number
  is_active?: boolean
  grafana_target_json?: {
    namespace?: string
    pod_pattern?: string
    dashboard_uid?: string
  } | null
  grafana_namespace?: string
  grafana_pod_pattern?: string
  grafana_dashboard_uid?: string
}

/**
 * 更新环境请求
 */
export interface UpdateEnvironmentRequest {
  display_name?: string
  description?: string
  base_url?: string
  sort_order?: number
  is_active?: boolean
  grafana_target_json?: {
    namespace?: string
    pod_pattern?: string
    dashboard_uid?: string
  } | null
}

/**
 * 变量作用域
 */
export enum VariableScope {
  GLOBAL = 'global',
  ENVIRONMENT = 'environment'
}

/**
 * 变量信息（已脱敏）
 */
export interface Variable {
  id: number
  project_id: number
  environment_id: number | null
  scope: VariableScope
  key: string
  value: string // 密钥类型会显示为 ******
  description: string | null
  is_secret: boolean
  is_active: boolean
  created_by: number | null
  updated_by: number | null
  created_at: string
  updated_at: string
}

/**
 * 创建变量请求
 */
export interface CreateVariableRequest {
  key: string
  value?: string
  description?: string
  is_secret?: boolean
  is_active?: boolean
}

/**
 * 更新变量请求
 */
export interface UpdateVariableRequest {
  value?: string
  description?: string
  is_secret?: boolean
  is_active?: boolean
}
