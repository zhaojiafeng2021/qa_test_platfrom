import type { AxiosRequestConfig } from 'axios'
import client from './client'
import type {
  CodeRepository,
  CodeRepositoryPayload,
  RepoBranch,
  RepoService,
  CoverageTask,
  CoverageTaskCreatePayload,
  CoverageTaskPage,
  CoverageTaskUpdatePayload,
  DiffCoverage,
  FileContentWithCoverage,
  FileCoverageSummary,
  JavaCoverageReport,
  JavaCoverageRunPage,
  LedgerDiffCoverage,
  LedgerEvents,
  LedgerFileContent,
  RepoCommit,
  ServiceLedgers,
  TriggerPayload,
  TriggerResponse,
} from '@/types/coverage'

// crypto.randomUUID 仅在安全上下文可用；沿用 test-plan.ts 的降级实现
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

// ─── Task CRUD ───

export const listCoverageTasks = (
  projectId: number,
  params?: {
    page?: number
    page_size?: number
    keyword?: string
    status?: string
    branch?: string
  },
) =>
  client.get(`/projects/${projectId}/coverage-tasks`, { params }) as unknown as Promise<CoverageTaskPage>

export const getCoverageTask = (projectId: number, taskId: number) =>
  client.get(`/projects/${projectId}/coverage-tasks/${taskId}`) as unknown as Promise<CoverageTask>

export const createCoverageTask = (projectId: number, data: CoverageTaskCreatePayload) =>
  client.post(`/projects/${projectId}/coverage-tasks`, data) as unknown as Promise<CoverageTask>

export const updateCoverageTask = (projectId: number, taskId: number, data: CoverageTaskUpdatePayload) =>
  client.patch(`/projects/${projectId}/coverage-tasks/${taskId}`, data) as unknown as Promise<CoverageTask>

export const deleteCoverageTask = (projectId: number, taskId: number) =>
  client.delete(`/projects/${projectId}/coverage-tasks/${taskId}`) as unknown as Promise<void>

// ─── 触发 / 取消 ───

export const triggerCoverageTask = (projectId: number, taskId: number, data?: TriggerPayload) =>
  client.post(
    `/projects/${projectId}/coverage-tasks/${taskId}/trigger`,
    data ?? null,
    { headers: { 'Idempotency-Key': idempotencyKey() } },
  ) as unknown as Promise<TriggerResponse>

export const cancelCoverageTask = (projectId: number, taskId: number) =>
  client.post(`/projects/${projectId}/coverage-tasks/${taskId}/cancel`) as unknown as Promise<void>

// ─── Run / Report 查询 ───

export const listTaskRuns = (
  projectId: number,
  taskId: number,
  params?: { page?: number; page_size?: number },
) =>
  client.get(`/projects/${projectId}/coverage-tasks/${taskId}/runs`, { params }) as unknown as Promise<JavaCoverageRunPage>

export const listRunReports = (runId: number) =>
  client.get(`/coverage/runs/${runId}/reports`) as unknown as Promise<JavaCoverageReport[]>

export const getCoverageReport = (reportId: number) =>
  client.get(`/coverage/reports/${reportId}`) as unknown as Promise<JavaCoverageReport>

export const listReportFiles = (reportId: number) =>
  client.get(`/coverage/reports/${reportId}/files`) as unknown as Promise<FileCoverageSummary[]>

export const getReportFileContent = (reportId: number, path: string) =>
  client.get(`/coverage/reports/${reportId}/file-content`, { params: { path } }) as unknown as Promise<FileContentWithCoverage>

export const getReportDiffCoverage = (reportId: number) =>
  client.get(`/coverage/reports/${reportId}/diff-coverage`, { silent: true } as AxiosRequestConfig) as unknown as Promise<DiffCoverage>

export const getReportBuildLog = (reportId: number) =>
  client.get(`/coverage/reports/${reportId}/build-log`) as unknown as Promise<{ report_id: number; log: string }>

// ─── 代码源 ───

export const listCodeRepos = (projectId: number) =>
  client.get(`/projects/${projectId}/code-repos`) as unknown as Promise<CodeRepository[]>

export const createCodeRepo = (projectId: number, data: CodeRepositoryPayload) =>
  client.post(`/projects/${projectId}/code-repos`, data) as unknown as Promise<CodeRepository>

export const updateCodeRepo = (projectId: number, repoId: number, data: Partial<CodeRepositoryPayload>) =>
  client.patch(`/projects/${projectId}/code-repos/${repoId}`, data) as unknown as Promise<CodeRepository>

export const deleteCodeRepo = (projectId: number, repoId: number) =>
  client.delete(`/projects/${projectId}/code-repos/${repoId}`) as unknown as Promise<void>

export const listRepoBranches = (projectId: number, repoId: number) =>
  client.get(`/projects/${projectId}/code-repos/${repoId}/branches`) as unknown as Promise<RepoBranch[]>

export const listRepoServices = (projectId: number, repoId: number, branch: string) =>
  client.get(`/projects/${projectId}/code-repos/${repoId}/services`, { params: { branch } }) as unknown as Promise<RepoService[]>

export const listRepoCommits = (projectId: number, repoId: number, branch: string, limit = 30) =>
  client.get(`/projects/${projectId}/code-repos/${repoId}/commits`, { params: { branch, limit } }) as unknown as Promise<RepoCommit[]>

// ─── 累积账本 ───

export const getTaskLedgers = (projectId: number, taskId: number) =>
  client.get(`/projects/${projectId}/coverage-tasks/${taskId}/ledger`) as unknown as Promise<ServiceLedgers[]>

export const startLedgerNewRound = (projectId: number, taskId: number, serviceName?: string) =>
  client.post(
    `/projects/${projectId}/coverage-tasks/${taskId}/ledger/new-round`,
    serviceName ? { service_name: serviceName } : null,
  ) as unknown as Promise<{ closed_services: string[] }>

export const listLedgerFiles = (projectId: number, ledgerId: number) =>
  client.get(`/projects/${projectId}/coverage-ledgers/${ledgerId}/files`) as unknown as Promise<FileCoverageSummary[]>

export const getLedgerFile = (projectId: number, ledgerId: number, path: string) =>
  client.get(`/projects/${projectId}/coverage-ledgers/${ledgerId}/file`, { params: { path } }) as unknown as Promise<LedgerFileContent>

export const getLedgerDiffCoverage = (projectId: number, ledgerId: number) =>
  client.get(
    `/projects/${projectId}/coverage-ledgers/${ledgerId}/diff-coverage`,
    { silent: true } as AxiosRequestConfig,
  ) as unknown as Promise<LedgerDiffCoverage>

export const getLedgerEvents = (projectId: number, ledgerId: number, limit = 50) =>
  client.get(`/projects/${projectId}/coverage-ledgers/${ledgerId}/events`, { params: { limit } }) as unknown as Promise<LedgerEvents>

// ─── WebSocket URL ───

export const buildCoverageWsUrl = (taskId: number): string => {
  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
  // WS 路由不带 /api/v1 前缀，直接挂在根路径 /ws/...
  return `${protocol}://${window.location.host}/ws/coverage/tasks/${taskId}/progress`
}
