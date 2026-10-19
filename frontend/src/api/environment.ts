/**
 * 环境与变量管理API
 */
import client from './client'
import type {
  Environment,
  CreateEnvironmentRequest,
  UpdateEnvironmentRequest,
  Variable,
  CreateVariableRequest,
  UpdateVariableRequest
} from '@/types/environment'

/**
 * 环境管理API
 */
export const environmentApi = {
  /**
   * 创建环境
   */
  create: async (projectId: number, data: CreateEnvironmentRequest): Promise<Environment> => {
    return client.post(`/projects/${projectId}/environments`, data) as unknown as Promise<Environment>
  },

  /**
   * 获取项目的环境列表
   */
  list: async (projectId: number): Promise<Environment[]> => {
    return client.get(`/projects/${projectId}/environments`) as unknown as Promise<Environment[]>
  },

  /**
   * 获取环境详情
   */
  get: async (projectId: number, envId: number): Promise<Environment> => {
    return client.get(`/projects/${projectId}/environments/${envId}`) as unknown as Promise<Environment>
  },

  /**
   * 更新环境
   */
  update: async (
    projectId: number,
    envId: number,
    data: UpdateEnvironmentRequest
  ): Promise<Environment> => {
    return client.patch(`/projects/${projectId}/environments/${envId}`, data) as unknown as Promise<Environment>
  },

  /**
   * 删除环境
   */
  delete: async (projectId: number, envId: number): Promise<void> => {
    await client.delete(`/projects/${projectId}/environments/${envId}`)
  }
}

/**
 * 变量管理API
 */
export const variableApi = {
  /**
   * 创建全局变量
   */
  createGlobal: async (projectId: number, data: CreateVariableRequest): Promise<Variable> => {
    return client.post(`/projects/${projectId}/variables`, {
      ...data,
      scope: 'global'
    }) as unknown as Promise<Variable>
  },

  /**
   * 创建环境变量
   */
  createEnvironment: async (
    projectId: number,
    environmentId: number,
    data: CreateVariableRequest
  ): Promise<Variable> => {
    return client.post(`/projects/${projectId}/variables`, {
      ...data,
      scope: 'environment',
      environment_id: environmentId
    }) as unknown as Promise<Variable>
  },

  /**
   * 获取项目的变量列表
   */
  list: async (
    projectId: number,
    options?: {
      scope?: 'global' | 'environment'
      environmentId?: number
      maskSecret?: boolean
    }
  ): Promise<Variable[]> => {
    const params = new URLSearchParams()
    if (options?.scope) params.append('scope', options.scope)
    if (options?.environmentId) params.append('environment_id', options.environmentId.toString())
    if (options?.maskSecret !== undefined)
      params.append('mask_secret', options.maskSecret.toString())

    return client.get(
      `/projects/${projectId}/variables${params.toString() ? '?' + params.toString() : ''}`
    ) as unknown as Promise<Variable[]>
  },

  /**
   * 获取变量详情
   */
  get: async (projectId: number, varId: number, maskSecret = true): Promise<Variable> => {
    return client.get(
      `/projects/${projectId}/variables/${varId}?mask_secret=${maskSecret}`
    ) as unknown as Promise<Variable>
  },

  /**
   * 更新变量
   */
  update: async (
    projectId: number,
    varId: number,
    data: UpdateVariableRequest
  ): Promise<Variable> => {
    return client.patch(`/projects/${projectId}/variables/${varId}`, data) as unknown as Promise<Variable>
  },

  /**
   * 删除变量
   */
  delete: async (projectId: number, varId: number): Promise<void> => {
    await client.delete(`/projects/${projectId}/variables/${varId}`)
  }
}
