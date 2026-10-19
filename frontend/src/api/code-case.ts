import client from './client'
import type {
  BatchResult,
  CodeCaseDetail,
  CodeCasePage,
  CodeCaseStats,
  CodeModuleInfo,
  CodeModuleTreeNode,
  ExecuteRequest,
  ExecutionDetail,
  ExecutionPage,
  ScanResult,
} from '@/types/code-case'

// 代码用例支持按项目隔离，project_id 可选；不传时返回全部（含旧数据/全局用例）
const BASE = '/code-cases'

export const codeCaseApi = {
  /** 扫描代码：解析 code_testcases 目录并同步入库，项目归属由 @case(project=) 自动解析 */
  scan() {
    return client.post(`${BASE}/scan`) as unknown as Promise<ScanResult>
  },
  /** 用例统计 */
  stats(projectId?: number | null) {
    const params = projectId != null ? { project_id: projectId } : undefined
    return client.get(`${BASE}/stats`, { params }) as unknown as Promise<CodeCaseStats>
  },
  /** 用例列表（含模块层级字段） */
  list(params: {
    page?: number
    page_size?: number
    module_id?: number | null
    include_children?: boolean
    level?: string
    keyword?: string
    project_id?: number | null
  }) {
    // 过滤掉 null/undefined，避免 axios 把 null 序列化成空字符串传给后端
    const cleaned: Record<string, unknown> = {}
    for (const [k, v] of Object.entries(params)) {
      if (v != null) cleaned[k] = v
    }
    return client.get(BASE, { params: cleaned }) as unknown as Promise<CodeCasePage>
  },
  /** 用例详情（含代码片段） */
  get(caseId: number) {
    return client.get(`${BASE}/${caseId}`) as unknown as Promise<CodeCaseDetail>
  },
  /** 执行用例（异步，返回批次信息） */
  execute(data: ExecuteRequest) {
    return client.post(`${BASE}/execute`, data) as unknown as Promise<BatchResult>
  },
  /** 轮询批次执行结果 */
  getBatch(batchId: string) {
    return client.get(`${BASE}/batches/${batchId}`) as unknown as Promise<BatchResult>
  },
  /** 执行历史列表 */
  listExecutions(params: {
    case_id?: number
    batch_id?: string
    status?: string
    page?: number
    page_size?: number
  }) {
    return client.get(`${BASE}/executions`, { params }) as unknown as Promise<ExecutionPage>
  },
  /** 单条执行详情（含日志和堆栈） */
  getExecution(execId: number) {
    return client.get(`${BASE}/executions/${execId}`) as unknown as Promise<ExecutionDetail>
  },
}

export const codeModuleApi = {
  getTree(projectId?: number | null) {
    const params = projectId != null ? { project_id: projectId } : undefined
    return client.get(`${BASE}/modules/tree`, { params }) as unknown as Promise<CodeModuleTreeNode[]>
  },
  create(data: { name: string; parent_id?: number | null; sort_order?: number; project_id?: number | null }) {
    return client.post(`${BASE}/modules`, data) as unknown as Promise<CodeModuleInfo>
  },
  update(moduleId: number, data: { name?: string; sort_order?: number }) {
    return client.patch(`${BASE}/modules/${moduleId}`, data) as unknown as Promise<CodeModuleInfo>
  },
  delete(moduleId: number, cascade = false) {
    return client.delete(`${BASE}/modules/${moduleId}`, {
      params: { cascade },
    }) as unknown as Promise<null>
  },
}
