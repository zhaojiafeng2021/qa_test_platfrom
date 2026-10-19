// Permission & RBAC v2 API Client
import client from './client'
import type {
  Permission,
  Role,
  RoleCreate,
  RoleUpdate,
  DataPolicy,
  DataPolicyUpdate,
  ProjectMember,
  MemberAssign,
  AvailableUser,
  AuditLog,
} from '@/types/permission'

interface Page<T> {
  total: number
  page?: number
  page_size?: number
  items: T[]
}

export const permissionApi = {
  // Catalog
  getCatalog: (projectId: number): Promise<Permission[]> =>
    client.get(`/projects/${projectId}/permissions/catalog`) as unknown as Promise<Permission[]>,

  // Roles
  listRoles: (projectId: number): Promise<Role[]> =>
    client.get(`/projects/${projectId}/permissions/roles`) as unknown as Promise<Role[]>,

  createRole: (projectId: number, data: RoleCreate): Promise<Role> =>
    client.post(`/projects/${projectId}/permissions/roles`, data) as unknown as Promise<Role>,

  updateRole: (projectId: number, roleId: number, data: RoleUpdate): Promise<Role> =>
    client.put(`/projects/${projectId}/permissions/roles/${roleId}`, data) as unknown as Promise<Role>,

  deleteRole: (projectId: number, roleId: number): Promise<void> =>
    client.delete(`/projects/${projectId}/permissions/roles/${roleId}`) as unknown as Promise<void>,

  // Data Policies
  listDataPolicies: (projectId: number): Promise<DataPolicy[]> =>
    client.get(`/projects/${projectId}/permissions/data-policies`) as unknown as Promise<DataPolicy[]>,

  updateDataPolicy: (
    projectId: number,
    resourceType: string,
    data: DataPolicyUpdate
  ): Promise<DataPolicy> =>
    client.put(
      `/projects/${projectId}/permissions/data-policies/${resourceType}`,
      data
    ) as unknown as Promise<DataPolicy>,

  // Members
  listMembers: (projectId: number): Promise<ProjectMember[]> =>
    client.get(`/projects/${projectId}/permissions/members`) as unknown as Promise<ProjectMember[]>,

  searchAvailableUsers: (projectId: number, query?: string): Promise<AvailableUser[]> =>
    client.get(`/projects/${projectId}/permissions/available-users`, {
      params: { query },
    }) as unknown as Promise<AvailableUser[]>,

  addMember: (projectId: number, data: MemberAssign): Promise<ProjectMember> =>
    client.post(`/projects/${projectId}/permissions/members`, data) as unknown as Promise<ProjectMember>,

  assignMemberRole: (
    projectId: number,
    userId: number,
    data: { role_ids: number[] }
  ): Promise<ProjectMember> =>
    client.patch(
      `/projects/${projectId}/permissions/members/${userId}`,
      data
    ) as unknown as Promise<ProjectMember>,

  removeMember: (projectId: number, userId: number): Promise<void> =>
    client.delete(`/projects/${projectId}/permissions/members/${userId}`) as unknown as Promise<void>,

  // Audit Logs
  listAuditLogs: (
    projectId: number,
    params?: {
      page?: number
      page_size?: number
      action?: string
      user_id?: number
      started_from?: string
      started_to?: string
    }
  ): Promise<Page<AuditLog>> =>
    client.get(`/projects/${projectId}/audit-logs`, { params }) as unknown as Promise<Page<AuditLog>>,
}