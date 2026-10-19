// Report types
export interface ReportFile {
  id: number
  project_id: number
  plan_run_id?: number
  execution_id?: number
  report_type: string  // 'html' or 'pdf'
  file_path: string
  file_size?: number
  status: 'pending' | 'generating' | 'generated' | 'failed'
  error_message?: string
  download_url?: string
  created_at: string
  created_by: number
}

export interface ReportListParams {
  page?: number
  page_size?: number
  report_type?: string
  started_from?: string
  started_to?: string
}
