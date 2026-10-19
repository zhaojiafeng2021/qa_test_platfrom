import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { CurrentUser } from '@/api/auth'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<CurrentUser | null>(null)
  const accessToken = ref<string>(localStorage.getItem('access_token') || '')
  const refreshToken = ref<string>(localStorage.getItem('refresh_token') || '')

  const setUser = (userData: CurrentUser) => {
    user.value = userData
  }

  const setTokens = (access: string, refresh: string) => {
    accessToken.value = access
    refreshToken.value = refresh
    localStorage.setItem('access_token', access)
    localStorage.setItem('refresh_token', refresh)
  }

  const setAccessToken = (access: string) => {
    accessToken.value = access
    localStorage.setItem('access_token', access)
  }

  const logout = async () => {
    user.value = null
    accessToken.value = ''
    refreshToken.value = ''
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')

    // 动态导入避免循环依赖
    const { clearPermissionCache } = await import('@/composables/usePermission')
    clearPermissionCache()
  }

  const isAuthenticated = () => {
    return !!accessToken.value || !!localStorage.getItem('access_token')
  }

  /** 是否拥有指定权限（超管或含通配符即通过） */
  const hasPermission = (permission: string) => {
    const perms = user.value?.permissions || []
    if (user.value?.is_superuser || perms.includes('*')) return true
    return perms.includes(permission)
  }

  return {
    user,
    accessToken,
    refreshToken,
    setUser,
    setTokens,
    setAccessToken,
    logout,
    isAuthenticated,
    hasPermission,
  }
})
