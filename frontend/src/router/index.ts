import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { authApi } from '@/api/auth'
import { isChunkLoadError, reloadForChunkError, clearChunkReloadCounter } from '@/utils/chunk-error-handler'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    redirect: '/projects'
  },
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/login/LoginView.vue'),
    meta: { title: '登录' }
  },
  {
    path: '/auth/callback',
    name: 'FeishuCallback',
    component: () => import('@/views/login/FeishuCallbackView.vue'),
    meta: { title: '登录中' }
  },
  {
    path: '/projects',
    name: 'Projects',
    component: () => import('@/views/project/ProjectListView.vue'),
    meta: { title: '项目列表', requiresAuth: true }
  },
  {
    path: '/settings/tokens',
    name: 'AccessTokens',
    component: () => import('@/views/settings/AccessTokenView.vue'),
    meta: { title: '访问令牌', requiresAuth: true }
  },
  {
    path: '/:projectCode',
    component: () => import('@/layouts/MainLayout.vue'),
    meta: { requiresAuth: true },
    children: [
      {
        path: 'dashboard',
        name: 'Dashboard',
        component: () => import('@/views/dashboard/DashboardView.vue'),
        meta: { title: '工作台' }
      },
      {
        path: 'code-cases',
        name: 'CodeCases',
        component: () => import('@/views/code-case/CodeCaseView.vue'),
        meta: { title: '代码用例' }
      },
      {
        path: 'test-plans',
        name: 'TestPlans',
        component: () => import('@/views/test-plan/TestPlanView.vue'),
        meta: { title: '测试计划' }
      },
      {
        path: 'schedules',
        name: 'Schedules',
        component: () => import('@/views/test-plan/ScheduleView.vue'),
        meta: { title: '定时任务' }
      },
      {
        path: 'plan-runs/:runId',
        name: 'PlanRunReport',
        component: () => import('@/views/test-plan/PlanRunReportView.vue'),
        meta: { title: '执行报告' }
      },
      {
        path: 'reports',
        name: 'ReportCenter',
        component: () => import('@/views/report/ReportCenterView.vue'),
        meta: { title: '测试报告' }
      },
      {
        path: 'permissions',
        name: 'Permissions',
        component: () => import('@/views/permission/PermissionManagementView.vue'),
        meta: { title: '权限管理' }
      },
      {
        path: 'notifications',
        name: 'Notifications',
        component: () => import('@/views/notification/NotificationCenterView.vue'),
        meta: { title: '飞书通知' }
      },
      {
        path: 'coverage',
        name: 'CoverageList',
        component: () => import('@/views/coverage/CoverageListView.vue'),
        meta: { title: '覆盖率任务' }
      },
      {
        path: 'coverage/:taskId',
        name: 'CoverageDetail',
        component: () => import('@/views/coverage/CoverageDetailView.vue'),
        meta: { title: '覆盖率任务详情' }
      },
      {
        path: 'coverage/:taskId/reports/:reportId/code',
        name: 'CoverageCode',
        component: () => import('@/views/coverage/CoverageCodeView.vue'),
        meta: { title: '覆盖率代码' }
      },
      {
        path: 'coverage/:taskId/ledgers/:ledgerId/code',
        name: 'CoverageLedgerCode',
        component: () => import('@/views/coverage/CoverageCodeView.vue'),
        meta: { title: '累积覆盖代码' }
      }
    ]
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'NotFound',
    component: () => import('@/views/error/NotFoundView.vue'),
    meta: { title: '页面不存在' }
  }
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes
})

// 路由守卫
router.beforeEach(async (to, from, next) => {
  // 设置页面标题
  if (to.meta.title) {
    document.title = `${to.meta.title} - QA测试平台`
  }

  const requiresAuth = to.matched.some(record => record.meta.requiresAuth)
  const token = localStorage.getItem('access_token')

  // 访问登录页：若仍持有有效 token，直接进入主页（无需重新登录）
  if (to.name === 'Login') {
    if (token) {
      const authStore = useAuthStore()
      try {
        // 校验 token 是否仍有效（有效则拉取用户信息并放行到主页）
        if (!authStore.user) {
          const me = await authApi.getMe()
          authStore.setUser(me)
        }
        next({ path: '/projects' })
        return
      } catch {
        // token 已失效，清除后停留在登录页
        authStore.logout()
        next()
        return
      }
    }
    next()
    return
  }

  if (to.name === 'FeishuCallback') {
    next()
    return
  }

  if (requiresAuth && !token) {
    next({ name: 'Login', query: { redirect: to.fullPath } })
  } else if (token) {
    // 有 token 但 user 为空（新标签页打开或刷新），自动加载用户信息
    const authStore = useAuthStore()
    if (!authStore.user) {
      try {
        const me = await authApi.getMe()
        authStore.setUser(me)
      } catch {
        // token 无效，清除并跳转登录
        authStore.logout()
        next({ name: 'Login', query: { redirect: to.fullPath } })
        return
      }
    }

    // 检查超级管理员权限
    const requiresSuperuser = to.matched.some(record => record.meta.requiresSuperuser)
    if (requiresSuperuser && !authStore.user?.is_superuser) {
      // 非超级管理员访问管理员页面，跳转到项目列表
      next({ name: 'Projects' })
      return
    }

    next()
  } else {
    next()
  }
})

// ==================== Chunk 加载失败自动恢复机制 ====================
// 详见 @/utils/chunk-error-handler.ts

// 捕获路由级别的 chunk 加载错误
router.onError((error, to) => {
  if (!isChunkLoadError(error)) return
  reloadForChunkError(to?.fullPath || router.currentRoute.value.fullPath)
})

// 导航成功后清除刷新计数器
router.afterEach(() => {
  clearChunkReloadCounter()
})

export default router
