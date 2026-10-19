import http from './client'

// ============ 类型定义 ============
export interface ProjectInfo {
  id: number
  code: string
  name: string
  description?: string
  owner_id: number
  status: string
  icon?: string
  color?: string
  is_public?: boolean
  grafana_config_json?: {
    url?: string
    token?: string
    datasource_uid?: string
    cluster?: string
  } | null
  created_at: string
  updated_at: string
}

export interface ProjectDetail extends ProjectInfo {
  my_role?: string
  member_count: number
}

export interface ProjectListResult {
  items: ProjectInfo[]
  total: number
  page: number
  page_size: number
}

export interface ProjectCreateParams {
  code: string
  name: string
  description?: string
  icon?: string
  color?: string
}

export interface ProjectUpdateParams {
  name?: string
  description?: string
  icon?: string
  color?: string
  is_public?: boolean
  grafana_config_json?: {
    url?: string
    token?: string
    datasource_uid?: string
    cluster?: string
  } | null
}

export interface MemberInfo {
  id: number
  project_id: number
  user_id: number
  role: string
  invited_by?: number
  created_at: string
  username?: string
  email?: string
  full_name?: string
  avatar_url?: string
}


export interface RecentExecutionInfo {
  id: number
  case_id: number
  case_name: string
  module: string | null
  level: string | null
  status: string
  duration_ms: number | null
  created_at: string
}

export interface RecentPlanRunInfo {
  id: number
  plan_id: number
  status: string
  total_items: number
  passed_items: number
  failed_items: number
  started_at: string | null
  finished_at: string | null
}

export interface ProjectSummary {
  code_case_count: number
  code_case_weekly_added: number
  test_plan_count: number
  environment_count: number
  execution_count: number
  completed_execution_count: number
  passed_execution_count: number
  recent_pass_rate: number
  recent_executions: RecentExecutionInfo[]
  recent_plan_runs: RecentPlanRunInfo[]
}
// ============ API ============
export const projectApi = {
  /** 获取项目列表 */
  list(params?: {
    page?: number
    page_size?: number
    keyword?: string
    status?: string
  }): Promise<ProjectListResult> {
    return http.get('/projects', { params })
  },

  /** 创建项目 */
  create(params: ProjectCreateParams): Promise<ProjectInfo> {
    return http.post('/projects', params)
  },

  /** 获取项目工作台汇总 */
  summary(projectId: number): Promise<ProjectSummary> {
    return http.get(`/projects/${projectId}/summary`)
  },
  /** 获取项目详情 */
  detail(projectId: number): Promise<ProjectDetail> {
    return http.get(`/projects/${projectId}`)
  },

  /** 更新项目 */
  update(projectId: number, params: ProjectUpdateParams): Promise<ProjectInfo> {
    return http.patch(`/projects/${projectId}`, params)
  },

  /** 删除项目 */
  remove(projectId: number): Promise<null> {
    return http.delete(`/projects/${projectId}`)
  },

  /** 获取项目成员列表 */
  listMembers(projectId: number): Promise<{ items: MemberInfo[]; total: number }> {
    return http.get(`/projects/${projectId}/members`)
  },

  /** 添加项目成员 */
  addMember(projectId: number, userId: number, role: string): Promise<MemberInfo> {
    return http.post(`/projects/${projectId}/members`, { user_id: userId, role })
  },

  /** 更新成员角色 */
  updateMember(projectId: number, userId: number, role: string): Promise<MemberInfo> {
    return http.patch(`/projects/${projectId}/members/${userId}`, { role })
  },

  /** 移除成员 */
  removeMember(projectId: number, userId: number): Promise<null> {
    return http.delete(`/projects/${projectId}/members/${userId}`)
  },
}

// ============ 简化导出（兼容直接调用） ============
export const getProjects = () => projectApi.list().then(res => res.items || res)
export const createProject = (params: ProjectCreateParams) => projectApi.create(params)
export const getProjectDetail = (id: number) => projectApi.detail(id)
export const updateProject = (id: number, params: ProjectUpdateParams) => projectApi.update(id, params)
export const deleteProject = (id: number) => projectApi.remove(id)
export const getProjectMembers = (id: number) => projectApi.listMembers(id).then(res => res.items || res)
export const addProjectMember = (id: number, params: { user_id: number; role: string }) =>
  projectApi.addMember(id, params.user_id, params.role)
export const updateMemberRole = (projectId: number, userId: number, params: { role: string }) =>
  projectApi.updateMember(projectId, userId, params.role)
export const removeMember = (projectId: number, userId: number) =>
  projectApi.removeMember(projectId, userId)
