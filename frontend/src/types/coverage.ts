// JaCoCo 覆盖率采集模块 · TypeScript 类型定义
// 与后端 backend/app/schemas/coverage_java.py 对齐（Phase 0 契约）

// ─── 枚举 ───

export type TaskStatus = 'draft' | 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'
export type RunStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled' | 'partial'
export type ReportStatus = 'queued' | 'running' | 'completed' | 'failed' | 'skipped' | 'cancelled'
export type ProgressStage = 'pending' | 'clone' | 'build' | 'test' | 'report' | 'done'
export type TriggerType = 'manual' | 'cron' | 'retry'
export type LineCoverStatus = 'covered' | 'missed' | 'partial' | 'unknown'

// ─── 服务引用 ───

export interface ServiceRef {
  name: string
  module?: string
  path: string
  /** 运行时模式：该服务 JaCoCo agent 地址，覆盖 runtime_config.host */
  agent_host?: string
  agent_port?: number
}

// ─── 代码源 ───

export interface CodeRepository {
  id: number
  project_id: number
  name: string
  repo_url: string
  default_branch?: string | null
  description?: string | null
  created_at: string
  updated_at: string
}

export interface CodeRepositoryPayload {
  name: string
  repo_url: string
  default_branch?: string
  description?: string
}

export interface RepoBranch {
  name: string
  commit_sha: string
}

export interface RepoService {
  name: string
  path: string
  build_tool: 'maven' | 'gradle'
}

// ─── 采集模式 ───

export type CollectionMode = 'unittest' | 'runtime'

export interface RuntimeConfig {
  host?: string
  port: number
  reset: boolean
}

// ─── 任务 ───

export interface CoverageTask {
  id: number
  project_id: number
  name: string
  repo_id?: number | null
  repo_url: string
  services: ServiceRef[]
  branch: string
  diff_base_branch?: string
  requirement_ref?: string
  cron_expr?: string
  threshold_line_rate?: number
  threshold_branch_rate?: number
  collection_mode: CollectionMode
  runtime_config?: RuntimeConfig | null
  owner_id: number
  status: TaskStatus
  current_run_id?: number
  last_completed_at?: string
  last_failed_at?: string
  created_by?: number
  updated_by?: number
  created_at: string
  updated_at: string
}

export interface CoverageTaskCreatePayload {
  name: string
  /** 选了代码源时后端以代码源 URL 为准，repo_url 可省略 */
  repo_id?: number
  repo_url?: string
  services: ServiceRef[]
  branch?: string
  diff_base_branch?: string
  requirement_ref?: string
  cron_expr?: string
  threshold_line_rate?: number
  threshold_branch_rate?: number
  collection_mode?: CollectionMode
  runtime_config?: RuntimeConfig
}

export type CoverageTaskUpdatePayload = Partial<CoverageTaskCreatePayload>

export interface CoverageTaskPage {
  total: number
  page: number
  page_size: number
  items: CoverageTask[]
}

// ─── 运行实例 ───

export interface JavaCoverageRun {
  id: number
  task_id: number
  trigger_type: TriggerType
  overall_status: RunStatus
  services_total: number
  services_completed: number
  services_failed: number
  started_at?: string
  finished_at?: string
  created_at: string
}

export interface JavaCoverageRunPage {
  total: number
  page: number
  page_size: number
  items: JavaCoverageRun[]
}

// ─── 报告 ───

export interface JavaCoverageReport {
  id: number
  run_id: number
  task_id: number
  service_name: string
  commit_sha?: string
  status: ReportStatus
  progress: number
  stage: ProgressStage
  stage_detail?: string
  line_rate?: number
  branch_rate?: number
  lines_covered?: number
  lines_total?: number
  branches_covered?: number
  branches_total?: number
  xml_report_path?: string
  html_report_path?: string
  exec_file_path?: string
  build_log_path?: string
  source_snapshot_path?: string
  error_message?: string
  created_at: string
  updated_at: string
}

export interface TriggerResponse {
  run_id: number
  job_id?: string
  reports: JavaCoverageReport[]
}

// ─── 行级覆盖 ───

export interface LineCoverage {
  line_no: number
  covered_instructions: number
  missed_instructions: number
  covered_branches: number
  missed_branches: number
  status: LineCoverStatus
}

export interface FileCoverageSummary {
  file_path: string
  package?: string
  class_name?: string
  lines_total: number
  lines_covered: number
  line_rate: number
}

export interface FileContentWithCoverage {
  file_path: string
  source: string
  source_available: boolean
  line_coverage: LineCoverage[]
}

// ─── 增量覆盖率 ───

export type DiffLineStatus = 'covered' | 'partial' | 'missed' | 'not_executable'

export interface DiffCoverageFile {
  changed_lines_total: number
  changed_lines_covered: number
  line_rate: number
  changed_lines: { line_no: number; status: DiffLineStatus }[]
}

export interface DiffCoverage {
  base_branch: string
  merge_base: string
  head_commit?: string | null
  line_rate: number
  lines_total: number
  lines_covered: number
  /** key 与 FileCoverageSummary.file_path 一致 */
  files: Record<string, DiffCoverageFile>
}

// ─── WebSocket 消息 ───

export interface WsSnapshotMessage {
  type: 'snapshot'
  task_id: number
  run_id: number
  reports: JavaCoverageReport[]
}

export interface WsProgressMessage {
  type: 'progress'
  report_id: number
  service_name: string
  progress: number
  stage: ProgressStage
  stage_detail?: string
}

export interface WsServiceDoneMessage {
  type: 'service_done'
  report_id: number
  service_name: string
  success: boolean
  progress: number
  stage: 'done'
  coverage?: {
    line_rate?: number
    branch_rate?: number
    lines_covered?: number
    lines_total?: number
  }
}

export interface WsServiceErrorMessage {
  type: 'service_error'
  report_id: number
  service_name: string
  progress: number
  stage: ProgressStage
  message: string
  build_log_url?: string
}

export interface WsTaskDoneMessage {
  type: 'task_done'
  task_id: number
  run_id: number
  success?: boolean
  partial: boolean
}

export interface WsPingMessage {
  type: 'ping' | 'pong'
}

export type WsMessage =
  | WsSnapshotMessage
  | WsProgressMessage
  | WsServiceDoneMessage
  | WsServiceErrorMessage
  | WsTaskDoneMessage
  | WsPingMessage

// ─── 筛选器（前端本地状态） ───

export interface CoverageTaskFilters {
  keyword: string
  status: TaskStatus[]
  branch: string
  dateRange: [string, string] | []
}
