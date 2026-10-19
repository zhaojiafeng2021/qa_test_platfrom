export interface Permission {
  id: number
  code: string
  name: string
  module: string
  action: string
  description?: string
  platform_only: boolean
  sort_order: number
}

export interface Role {
  id: number
  project_id: number | null
  code: string
  name: string
  description?: string
  scope: string
  is_builtin: boolean
  parent_role_id: number | null
  parent_role_name?: string
  direct_permission_codes: string[]
  permission_codes: string[]
  member_count: number
  created_at: string
  updated_at: string
}

export interface DataPolicy {
  id: number
  project_id: number
  resource_type: string
  visibility_scope: 'all' | 'owner' | 'members'
  member_ids: number[]
  updated_by?: number
  updated_at: string
}

export interface ProjectMember {
  id: number
  user_id: number
  username: string
  full_name?: string
  email?: string
  avatar_url?: string
  role_id?: number
  role_code: string
  role_name: string
  role_ids: number[]
  role_codes: string[]
  role_names: string[]
  is_project_owner: boolean
  invited_by?: number
  created_at: string
  is_virtual?: boolean  // 虚拟成员标识（公开项目的访客）
}

export interface AvailableUser {
  id: number
  username: string
  full_name?: string
  email: string
  avatar_url?: string
}

export interface AuditLog {
  id: number
  user_id?: number
  username?: string
  full_name?: string
  project_id?: number
  action: string
  resource_type: string
  resource_id?: string
  detail_json?: Record<string, any>
  ip_address?: string
  created_at: string
}


export interface RoleCreate {
  name: string
  code?: string
  description?: string
  parent_role_id?: number
  permission_codes?: string[]
}

export interface RoleUpdate {
  name?: string
  description?: string
  parent_role_id?: number
  permission_codes?: string[]
}

export interface DataPolicyUpdate {
  visibility_scope: 'all' | 'owner' | 'members'
  member_ids?: number[]
}

export interface MemberAssign {
  user_id: number
  role_id: number
}
