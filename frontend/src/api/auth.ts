import http from './client'

// ============ 类型定义 ============
export interface LoginParams {
  username: string
  password: string
}

export interface RegisterParams {
  username: string
  email: string
  password: string
  full_name?: string
}

export interface UserInfo {
  id: number
  username: string
  email: string
  full_name?: string
  avatar_url?: string
  status: string
  is_superuser: boolean
}

export interface CurrentUser extends UserInfo {
  permissions: string[]
}

export interface LoginResult {
  access_token: string
  refresh_token: string
  token_type: string
  user: UserInfo
}

export interface FeishuAuthUrlResult {
  authorization_url: string
  state: string
}

export interface ApiTokenInfo {
  id: number
  name: string
  token_prefix: string
  expires_at?: string | null
  last_used_at?: string | null
  is_active: boolean
  created_at: string
}

export interface ApiTokenCreateParams {
  name: string
  /** 有效天数；不传或 null 表示永不过期 */
  expires_in_days?: number | null
}

export interface ApiTokenCreateResult {
  id: number
  name: string
  /** 令牌明文，仅创建时返回一次 */
  token: string
  token_prefix: string
  expires_at?: string | null
  created_at: string
}

// ============ API ============
export const authApi = {
  /** 用户登录 */
  login(params: LoginParams): Promise<LoginResult> {
    return http.post('/auth/login', params)
  },

  /** 用户注册 */
  register(params: RegisterParams): Promise<{ user: UserInfo }> {
    return http.post('/auth/register', params)
  },

  /** 刷新访问令牌 */
  refresh(refreshToken: string): Promise<{ access_token: string; token_type: string }> {
    return http.post('/auth/refresh', { refresh_token: refreshToken })
  },

  /** 退出登录 */
  logout(): Promise<null> {
    return http.post('/auth/logout')
  },

  /** 获取当前用户信息 */
  getMe(): Promise<CurrentUser> {
    return http.get('/auth/me')
  },

  /** 获取飞书授权地址 */
  getFeishuAuthUrl(params?: { redirect?: string }): Promise<FeishuAuthUrlResult> {
    return http.get('/auth/feishu/login', { params })
  },

  /** 创建个人访问令牌（明文仅返回一次） */
  createApiToken(params: ApiTokenCreateParams): Promise<ApiTokenCreateResult> {
    return http.post('/auth/tokens', params)
  },

  /** 获取个人访问令牌列表 */
  listApiTokens(): Promise<ApiTokenInfo[]> {
    return http.get('/auth/tokens')
  },

  /** 吊销个人访问令牌 */
  revokeApiToken(tokenId: number): Promise<null> {
    return http.delete(`/auth/tokens/${tokenId}`)
  },
}
