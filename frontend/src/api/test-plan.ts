import client from './client'
import type { PlanPage, PlanPayload, PlanRun, PlanRunPage, ReportFile, Schedule, TestPlan } from '@/types/test-plan'

// crypto.randomUUID 仅在安全上下文（HTTPS / localhost）可用；局域网 IP + HTTP 访问时为 undefined。
// 提供降级实现，保证幂等键在任何环境都能生成。
function idempotencyKey(): string {
  const c = globalThis.crypto
  if (c?.randomUUID) return c.randomUUID()
  if (c?.getRandomValues) {
    const b = c.getRandomValues(new Uint8Array(16))
    b[6] = (b[6] & 0x0f) | 0x40
    b[8] = (b[8] & 0x3f) | 0x80
    const h = Array.from(b, x => x.toString(16).padStart(2, '0'))
    return `${h[0]}${h[1]}${h[2]}${h[3]}-${h[4]}${h[5]}-${h[6]}${h[7]}-${h[8]}${h[9]}-${h[10]}${h[11]}${h[12]}${h[13]}${h[14]}${h[15]}`
  }
  return `${Date.now().toString(16)}-${Math.random().toString(16).slice(2, 10)}-${Math.random().toString(16).slice(2, 6)}`
}

export const listPlans = (projectId: number, params?: { page?: number; page_size?: number; status?: string }) => client.get(`/projects/${projectId}/test-plans`, { params }) as unknown as Promise<PlanPage>
export const createPlan = (projectId: number, data: PlanPayload) => client.post(`/projects/${projectId}/test-plans`, data) as unknown as Promise<TestPlan>
export const updatePlan = (projectId: number, planId: number, data: Partial<PlanPayload>) => client.put(`/projects/${projectId}/test-plans/${planId}`, data) as unknown as Promise<TestPlan>
export const deletePlan = (projectId: number, planId: number) => client.delete(`/projects/${projectId}/test-plans/${planId}`) as unknown as Promise<void>
export const syncCaseVersions = (projectId: number, planId: number, caseIds?: number[]) => client.post(`/projects/${projectId}/test-plans/${planId}/sync-versions`, caseIds || null) as unknown as Promise<TestPlan>
export const runPlan = (projectId: number, planId: number, data: object) => client.post(`/projects/${projectId}/test-plans/${planId}/runs`, data, { headers: { 'Idempotency-Key': idempotencyKey() } }) as unknown as Promise<PlanRun>
export const listPlanRuns = (projectId: number, params?: object) => client.get(`/projects/${projectId}/plan-runs`, { params }) as unknown as Promise<PlanRunPage>
export const getPlanRun = (projectId: number, runId: number) => client.get(`/projects/${projectId}/plan-runs/${runId}`) as unknown as Promise<PlanRun>
export const cancelPlanRun = (projectId: number, runId: number) => client.post(`/projects/${projectId}/plan-runs/${runId}/cancel`) as unknown as Promise<PlanRun>
export const listSchedules = (projectId: number) => client.get(`/projects/${projectId}/schedules`) as unknown as Promise<Schedule[]>
export const createSchedule = (projectId: number, planId: number, data: object) => client.post(`/projects/${projectId}/test-plans/${planId}/schedules`, data) as unknown as Promise<Schedule>
export const updateSchedule = (projectId: number, id: number, data: object) => client.put(`/projects/${projectId}/schedules/${id}`, data) as unknown as Promise<Schedule>
export const deleteSchedule = (projectId: number, id: number) => client.delete(`/projects/${projectId}/schedules/${id}`) as unknown as Promise<void>

// ---- WP-08 报告 ----
export const createReport = (projectId: number, params: { report_type?: string; plan_run_id?: number; execution_id?: number }) => client.post(`/projects/${projectId}/reports`, null, { params }) as unknown as Promise<ReportFile>
export const getReport = (projectId: number, reportId: number) => client.get(`/projects/${projectId}/reports/${reportId}`) as unknown as Promise<ReportFile>
export const listPlanRunReports = (projectId: number, planRunId: number) => client.get(`/projects/${projectId}/plan-runs/${planRunId}/reports`) as unknown as Promise<ReportFile[]>
export const deleteReport = (projectId: number, reportId: number) => client.delete(`/projects/${projectId}/reports/${reportId}`) as unknown as Promise<void>
// 下载URL：拼接后端 baseURL；download_url 已是 /api/v1/... 相对路径
export const reportDownloadUrl = (report: ReportFile) => report.download_url || ''