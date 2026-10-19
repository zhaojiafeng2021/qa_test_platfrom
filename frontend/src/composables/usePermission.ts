/**
 * 权限检查 Composable
 *
 * 用于前端权限控制，支持按钮显示/隐藏、禁用等场景
 */
import { ref, computed, watch } from 'vue'
import { useProjectStore } from '@/stores/project'
import { useAuthStore } from '@/stores/auth'
import http from '@/api/client'

interface ProjectPermissions {
  permissions: string[]
  is_member: boolean
  is_superuser: boolean
}

// 全局缓存：projectId -> permissions
const permissionCache = new Map<number, ProjectPermissions>()
const loadingCache = new Map<number, Promise<ProjectPermissions>>()

/**
 * 获取项目权限
 */
async function fetchProjectPermissions(projectId: number): Promise<ProjectPermissions> {
  // 如果正在加载，返回现有 Promise
  if (loadingCache.has(projectId)) {
    return loadingCache.get(projectId)!
  }

  // 如果已缓存，直接返回
  if (permissionCache.has(projectId)) {
    return permissionCache.get(projectId)!
  }

  // 发起请求
  const promise = http
    .get(`/projects/${projectId}/my-permissions`)
    .then((data: any) => {
      const result: ProjectPermissions = data
      console.log(`[usePermission] 获取项目 ${projectId} 权限成功:`, result)
      permissionCache.set(projectId, result)
      loadingCache.delete(projectId)
      return result
    })
    .catch((error) => {
      console.error(`[usePermission] 获取项目 ${projectId} 权限失败:`, error)
      loadingCache.delete(projectId)
      // 失败时返回无权限（不缓存，允许重试）
      const fallback: ProjectPermissions = {
        permissions: [],
        is_member: false,
        is_superuser: false,
      }
      return fallback
    })

  loadingCache.set(projectId, promise)
  return promise
}

/**
 * 清除权限缓存（切换项目或登出时调用）
 */
export function clearPermissionCache(projectId?: number) {
  if (projectId) {
    permissionCache.delete(projectId)
    loadingCache.delete(projectId)
  } else {
    permissionCache.clear()
    loadingCache.clear()
  }
}

/**
 * 检查权限匹配
 */
function checkPermission(granted: string[], required: string): boolean {
  // 超级管理员或拥有 * 权限
  if (granted.includes('*')) {
    return true
  }

  // 精确匹配
  if (granted.includes(required)) {
    return true
  }

  // 前缀通配符匹配 (如 asset:* 匹配 asset:create)
  for (const perm of granted) {
    if (perm.endsWith(':*') && required.startsWith(perm.slice(0, -1))) {
      return true
    }
  }

  return false
}

/**
 * 权限检查 Hook
 *
 * @example
 * ```vue
 * <script setup>
 * const { hasPermission, hasAnyPermission, hasAllPermissions, loading } = usePermission()
 *
 * const canCreate = computed(() => hasPermission('asset:create'))
 * const canEdit = computed(() => hasPermission('asset:update'))
 * </script>
 *
 * <template>
 *   <el-button v-if="canCreate" @click="create">创建</el-button>
 *   <el-button :disabled="!canEdit" @click="edit">编辑</el-button>
 * </template>
 * ```
 */
export function usePermission() {
  const projectStore = useProjectStore()
  const authStore = useAuthStore()
  const permissions = ref<string[]>([])
  const loading = ref(true)
  const isMember = ref(false)
  const isSuperuser = ref(false)

  const projectId = computed(() => projectStore.currentProjectId)

  // 监听项目变化，自动加载权限
  watch(
    projectId,
    async (id) => {
      console.log('[usePermission] projectId 变化:', id)
      if (!id) {
        console.log('[usePermission] projectId 为空，清空权限')
        permissions.value = []
        isMember.value = false
        isSuperuser.value = false
        loading.value = false
        return
      }

      loading.value = true
      try {
        const data = await fetchProjectPermissions(id)
        permissions.value = data.permissions
        isMember.value = data.is_member
        isSuperuser.value = data.is_superuser
        console.log('[usePermission] 权限加载完成:', {
          projectId: id,
          permissionsCount: data.permissions.length,
          isMember: data.is_member,
          isSuperuser: data.is_superuser
        })
      } finally {
        loading.value = false
      }
    },
    { immediate: true }
  )

  /**
   * 检查是否拥有指定权限
   *
   * 超级管理员（authStore.user.is_superuser）同步放行，
   * 不依赖异步 my-permissions 请求，避免权限加载完成前按钮被隐藏。
   */
  const hasPermission = (permission: string): boolean => {
    // 超管同步兜底：即使异步权限请求还在飞、或失败了，也直接通过
    if (authStore.user?.is_superuser) {
      return true
    }
    const result = checkPermission(permissions.value, permission)
    if (!result && permissions.value.length === 0 && !loading.value) {
      console.warn(`[usePermission] 权限检查失败: ${permission} (当前无任何权限, projectId=${projectId.value})`)
    }
    return result
  }

  /**
   * 检查是否拥有任一权限（OR）
   */
  const hasAnyPermission = (...requiredPermissions: string[]): boolean => {
    return requiredPermissions.some((perm) => hasPermission(perm))
  }

  /**
   * 检查是否拥有所有权限（AND）
   */
  const hasAllPermissions = (...requiredPermissions: string[]): boolean => {
    return requiredPermissions.every((perm) => hasPermission(perm))
  }

  return {
    permissions: computed(() => permissions.value),
    loading: computed(() => loading.value),
    isMember: computed(() => isMember.value),
    isSuperuser: computed(() => isSuperuser.value),
    hasPermission,
    hasAnyPermission,
    hasAllPermissions,
  }
}
