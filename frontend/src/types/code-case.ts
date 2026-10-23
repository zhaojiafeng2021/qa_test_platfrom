// 代码用例类型定义

/** el-tag 的 type 取值 */
export type TagType = 'primary' | 'success' | 'warning' | 'info' | 'danger'

export type CaseLevel = 'P0' | 'P1' | 'P2' | 'P3'
export type CaseStatus = 'idle' | 'running' | 'passed' | 'failed'

export const LEVEL_LABELS: Record<CaseLevel, string> = {
  P0: 'P0',
  P1: 'P1',
  P2: 'P2',
  P3: 'P3',
}

export const LEVEL_TYPES: Record<CaseLevel, TagType> = {
  P0: 'danger',
  P1: 'warning',
  P2: 'primary',
  P3: 'info',
}

export const STATUS_LABELS: Record<CaseStatus, string> = {
  idle: '未执行',
  running: '运行中',
  passed: '通过',
  failed: '失败',
}

export const STATUS_TYPES: Record<CaseStatus, TagType> = {
  idle: 'info',
  running: 'warning',
  passed: 'success',
  failed: 'danger',
}

// 执行状态
export const EXEC_STATUS_LABELS: Record<string, string> = {
  pending: '等待中',
  running: '运行中',
  passed: '通过',
  failed: '失败',
  error: '异常',
  timeout: '超时',
}

export const EXEC_STATUS_TYPES: Record<string, TagType> = {
  pending: 'info',
  running: 'warning',
  passed: 'success',
  failed: 'danger',
  error: 'danger',
  timeout: 'warning',
}

export interface CodeModuleInfo {
  id: number
  parent_id: number | null
  name: string
  level: number
  full_path: string
  sort_order: number
  created_at: string
  updated_at: string
}

export interface CodeModuleTreeNode {
  id: number
  parent_id: number | null
  name: string
  level: number
  full_path: string
  sort_order: number
  case_count: number
  total_case_count: number
  children: CodeModuleTreeNode[]
}

export interface CodeCaseListItem {
  id: number
  module_id: number | null
  module: string
  module_path: string[]
  name: string
  level: CaseLevel
  description: string | null
  file_path: string
  function_name: string
  line_number: number | null
  status: CaseStatus
  last_run_at: string | null
  created_at: string
  updated_at: string
  last_execution_id?: number | null
  last_duration_ms?: number | null
  last_message?: string | null
}

export interface CodeCaseDetail extends CodeCaseListItem {
  code_snippet: string | null
}

export interface CodeCasePage {
  total: number
  page: number
  page_size: number
  items: CodeCaseListItem[]
}

export interface CodeCaseStats {
  total: number
  module_count: number
  by_level: Record<string, number>
  by_status: Record<string, number>
}

export interface ScanResult {
  scanned_files: number
  scanned_cases: number
  created: number
  updated: number
  restored: number
  deleted: number
  modules_created: number
  /** 按项目扫描时跳过的其他项目/全局用例数 */
  skipped: number
  project_id?: number | null
  errors: string[]
}

// ──────────────────────────────────────────────
// 执行相关类型
// ──────────────────────────────────────────────

export interface ExecuteRequest {
  case_ids?: number[]
  module_id?: number
  all_cases?: boolean
  timeout?: number
}

export interface ExecutionInfo {
  id: number
  batch_id: string
  case_id: number
  case_name: string
  module?: string | null
  level?: string | null
  file_path?: string | null
  function_name?: string | null
  status: string
  message?: string | null
  duration_ms?: number | null
  started_at?: string | null
  finished_at?: string | null
  trigger_by?: number | null
  created_at: string
}

export interface ExecutionDetail extends ExecutionInfo {
  logs?: string | null
  traceback?: string | null
}

export interface BatchSummary {
  batch_id: string
  total: number
  pending: number
  running: number
  passed: number
  failed: number
  error: number
  timeout: number
  finished: boolean
  pass_rate: number
  duration_ms: number
}

export interface BatchResult {
  summary: BatchSummary
  items: ExecutionInfo[]
}

export interface ExecutionPage {
  total: number
  page: number
  page_size: number
  items: ExecutionInfo[]
}
