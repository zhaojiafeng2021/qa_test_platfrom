// Report API Client
import client from './client'
import type { ReportFile, ReportListParams } from '@/types/report'

export const reportApi = {
  // List all reports for a project
  listProjectReports(
    projectId: number,
    params: ReportListParams = {}
  ): Promise<{ total: number; items: ReportFile[] }> {
    return client.get(`/projects/${projectId}/reports`, {
      params,
    }) as unknown as Promise<{ total: number; items: ReportFile[] }>
  },

  // Get single report
  getReport(projectId: number, reportId: number) {
    return client.get<ReportFile>(`/projects/${projectId}/reports/${reportId}`)
  },

  // Download report (opens in new tab via authenticated fetch)
  async downloadReport(projectId: number, reportId: number) {
    const token = localStorage.getItem('access_token')
    const response = await fetch(
      `${import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'}/api/v1/projects/${projectId}/reports/${reportId}/download`,
      {
        headers: {
          'Authorization': `Bearer ${token}`,
        },
      }
    )

    if (!response.ok) {
      throw new Error('下载失败')
    }

    // Get filename from Content-Disposition header
    const disposition = response.headers.get('Content-Disposition')
    let filename = `report_${reportId}.html`
    if (disposition) {
      const filenameMatch = disposition.match(/filename\*=UTF-8''(.+)/)
      if (filenameMatch) {
        filename = decodeURIComponent(filenameMatch[1])
      }
    }

    // Create blob and download
    const blob = await response.blob()
    const url = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    window.URL.revokeObjectURL(url)
    document.body.removeChild(a)
  },

  // Delete report
  deleteReport(projectId: number, reportId: number) {
    return client.delete(`/projects/${projectId}/reports/${reportId}`)
  },

  // Create report
  createReport(projectId: number, data: { report_type?: string; plan_run_id?: number; execution_id?: number }) {
    return client.post<ReportFile>(`/projects/${projectId}/reports`, null, { params: data })
  },
}
