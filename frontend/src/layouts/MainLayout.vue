<template>
  <div :class="['main-layout', { 'sb-col': collapsed, 'mobile-open': mobileOpen }]">
    <button v-if="mobileOpen" class="sidebar-mask" aria-label="关闭导航" @click="mobileOpen = false" />
    <aside :class="['sidebar', { collapsed }]">
      <button class="sb-logo" type="button" @click="navigate('dashboard')">
        <span class="mk"><el-icon><DataAnalysis /></el-icon></span>
        <span class="nm">测试平台</span>
      </button>

      <nav class="sb-nav" aria-label="项目导航">
        <template v-for="group in filteredNavGroups" :key="group.label">
          <div class="sb-sec">{{ group.label }}</div>
          <el-tooltip
            v-for="item in group.items"
            :key="item.key"
            :content="item.label"
            placement="right"
            :disabled="!collapsed"
          >
            <button
              type="button"
              :class="['nav-item', { active: activeMenu === item.key, navigating }]"
              :disabled="navigating"
              @click="navigate(item.key)"
            >
              <span v-if="item.emoji" class="ic">{{ item.emoji }}</span>
              <el-icon v-else class="ic"><component :is="item.icon" /></el-icon>
              <span class="lb">{{ item.label }}</span>
            </button>
          </el-tooltip>
        </template>
      </nav>

      <div class="sb-foot">
        <div class="sb-user">
          <div class="av">{{ userInitial }}</div>
          <div class="info">
            <div class="n">{{ user?.full_name || user?.username }}</div>
            <div class="r">{{ user?.is_superuser ? '平台管理员' : '测试工程师' }}</div>
          </div>
        </div>
      </div>
    </aside>

    <header class="topbar">
      <el-tooltip content="折叠导航" placement="bottom">
        <button class="tb-icon toggle-desktop" type="button" @click="toggleSidebar">
          <el-icon><component :is="collapsed ? Expand : Fold" /></el-icon>
        </button>
      </el-tooltip>
      <button class="tb-icon toggle-mobile" type="button" aria-label="打开导航" @click="mobileOpen = true">
        <el-icon><Menu /></el-icon>
      </button>

      <el-dropdown trigger="click" @command="handleProjectCommand">
        <button class="tb-proj" type="button">
          <span class="pic" :style="projectMarkStyle">{{ projectInitial }}</span>
          <span class="pt">
            {{ currentProject?.name || '请选择项目' }}
            <small>{{ currentProject?.code || '切换工作项目' }}</small>
          </span>
          <el-icon class="proj-arrow"><ArrowDown /></el-icon>
        </button>
        <template #dropdown>
          <el-dropdown-menu class="project-menu">
            <el-dropdown-item
              v-for="project in projectStore.projects"
              :key="project.id"
              :command="project.code"
              :class="{ 'is-current': project.code === currentProject?.code }"
            >
              <span class="project-option-mark" :style="{ background: project.color || '#3B7BF5' }">
                {{ project.name.charAt(0) }}
              </span>
              <span>{{ project.name }}</span>
              <small>{{ project.code }}</small>
            </el-dropdown-item>
            <el-dropdown-item divided command="__projects">
              <el-icon><Grid /></el-icon>全部项目
            </el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>

      <div class="context-chip"><el-icon><CollectionTag /></el-icon><span>当前项目</span></div>
      <div class="tb-spacer" />

      <el-tooltip content="通知" placement="bottom">
        <button class="tb-icon" type="button" @click="ElMessage.info('暂无新通知')">
          <el-icon><Bell /></el-icon>
        </button>
      </el-tooltip>
      <div class="tb-sep" />
      <el-dropdown @command="handleUserCommand">
        <button class="tb-user" type="button">
          <span class="av-sm">{{ userInitial }}</span>
          <span class="tb-uname">{{ user?.full_name || user?.username }}</span>
          <el-icon><ArrowDown /></el-icon>
        </button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="projects"><el-icon><Grid /></el-icon>项目列表</el-dropdown-item>
            <el-dropdown-item command="tokens"><el-icon><Key /></el-icon>访问令牌</el-dropdown-item>
            <el-dropdown-item divided command="logout"><el-icon><SwitchButton /></el-icon>退出登录</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </header>

    <main class="main-area">
      <router-view />
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, markRaw, nextTick, onMounted, ref, watch, type Component } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  ArrowDown,
  Bell,
  Calendar,
  CollectionTag,
  DataAnalysis,
  DocumentCopy,
  Expand,
  Fold,
  Grid,
  HomeFilled,
  Key,
  Menu,
  SwitchButton,
  Timer,
  UserFilled,
} from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { useProjectStore } from '@/stores/project'
import { usePermission } from '@/composables/usePermission'
import { authApi } from '@/api/auth'
import { isChunkLoadError, reloadForChunkError } from '@/utils/chunk-error-handler'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const projectStore = useProjectStore()

const collapsed = ref(localStorage.getItem('qa-sidebar-collapsed') === '1')
const mobileOpen = ref(false)
const navigating = ref(false)
const user = computed(() => authStore.user)
const currentProject = computed(() => projectStore.currentProject)

const { hasPermission, hasAnyPermission, loading: permLoading } = usePermission()

interface NavItem {
  key: string
  label: string
  emoji: string
  icon: Component
  /** 不设置则始终显示；支持 | 分隔的 OR 权限 */
  permission?: string
}

const navGroups: { label: string; items: NavItem[] }[] = [
  { label: '工作台', items: [
    { key: 'dashboard', label: '项目工作台', emoji: '🏠', icon: markRaw(HomeFilled), permission: 'menu:dashboard:view' },
  ] },
  {
    label: '用例管理',
    items: [
      { key: 'code-cases', label: '代码用例', emoji: '💻', icon: markRaw(DocumentCopy), permission: 'menu:code-cases:view' },
    ],
  },
  {
    label: '测试执行',
    items: [
      { key: 'test-plans', label: '测试计划', emoji: '🎯', icon: markRaw(Calendar) },
      { key: 'coverage', label: '代码覆盖率', emoji: '📊', icon: markRaw(DataAnalysis) },
    ],
  },
  {
    label: '任务调度',
    items: [
      { key: 'schedules', label: '定时任务', emoji: '⏰', icon: markRaw(Timer), permission: 'menu:schedules:view' },
    ],
  },
  {
    label: '运维基础设施',
    items: [
      { key: 'reports', label: '测试报告', emoji: '📄', icon: markRaw(DataAnalysis), permission: 'menu:reports:view' },
    ],
  },
  {
    label: '系统管理',
    items: [
      { key: 'permissions', label: '权限管理', emoji: '🔐', icon: markRaw(UserFilled), permission: 'menu:permissions:view' },
      { key: 'notifications', label: '飞书通知', emoji: '🔔', icon: markRaw(Bell), permission: 'menu:notifications:view' },
    ],
  }
]

// 按权限过滤菜单：权限加载中时只显示 dashboard，避免闪烁
const filteredNavGroups = computed(() => {
  return navGroups
    .map(group => ({
      ...group,
      items: group.items.filter(item => {
        // 无权限要求的菜单项（dashboard）始终显示
        if (!item.permission) return true
        // 权限加载中只显示无权限要求的项
        if (permLoading.value) return false
        // 支持 | 分隔的 OR 权限
        const perms = item.permission.split('|')
        return hasAnyPermission(...perms)
      }),
    }))
    .filter(group => group.items.length > 0)
})
const userInitial = computed(() => (user.value?.full_name || user.value?.username || '?').charAt(0).toUpperCase())
const projectInitial = computed(() => currentProject.value?.name?.charAt(0) || '?')
const projectMarkStyle = computed(() => ({ background: currentProject.value?.color || '#0EA5E9' }))
const activeMenu = computed(() => {
  const segments = route.path.split('/')
  if (segments[2] === 'coverage') return 'coverage'
  return String(segments[segments.length - 1] || 'dashboard')
})

watch(
  () => route.params.projectCode,
  async (projectCode) => {
    mobileOpen.value = false
    if (typeof projectCode !== 'string') return
    try {
      await projectStore.loadProjectByCode(projectCode)
    } catch {
      router.push('/projects')
    }
  },
  { immediate: true }
)

onMounted(() => {
  if (!projectStore.projects.length) projectStore.loadProjects().catch(() => undefined)
})

function toggleSidebar() {
  collapsed.value = !collapsed.value
  localStorage.setItem('qa-sidebar-collapsed', collapsed.value ? '1' : '0')
}

async function navigate(view: string) {
  if (navigating.value) return

  const projectCode = route.params.projectCode as string | undefined
  if (!projectCode) {
    ElMessage.warning('请先选择项目')
    return
  }

  const targetPath = `/${projectCode}/${view}`

  // 如果已经在目标页面，不重复导航
  if (route.path === targetPath) {
    return
  }

  navigating.value = true
  try {
    await router.push(targetPath)
    mobileOpen.value = false // 移动端关闭侧边栏
  } catch (error: any) {
    // 部署更新后旧 chunk 失效：走自动刷新恢复，不弹错误提示
    if (isChunkLoadError(error)) {
      if (reloadForChunkError(targetPath)) return
      ElMessage.error('页面资源已更新，请刷新页面（Ctrl+F5）后重试')
    } else if (error?.name !== 'NavigationDuplicated') {
      // 忽略重复导航错误（NavigationDuplicated）
      console.error('导航失败:', error)
      ElMessage.error('页面跳转失败，请重试')
    }
  } finally {
    // 延迟重置，防止快速连续点击
    setTimeout(() => {
      navigating.value = false
    }, 300)
  }
}

function handleProjectCommand(command: string) {
  if (navigating.value) return

  if (command === '__projects') {
    navigating.value = true
    router.push('/projects').catch(err => {
      if (err?.name !== 'NavigationDuplicated') {
        console.error('导航失败:', err)
      }
    }).finally(() => {
      setTimeout(() => { navigating.value = false }, 300)
    })
    return
  }

  const project = projectStore.projects.find(item => item.code === command)
  if (project) {
    projectStore.setCurrentProject(project)
    navigating.value = true
    router.push(`/${command}/dashboard`).catch(err => {
      if (err?.name !== 'NavigationDuplicated') {
        console.error('导航失败:', err)
      }
    }).finally(() => {
      setTimeout(() => { navigating.value = false }, 300)
    })
  }
}

function handleUserCommand(command: string) {
  if (navigating.value) return

  if (command === 'projects') {
    navigating.value = true
    router.push('/projects').catch(err => {
      if (err?.name !== 'NavigationDuplicated') {
        console.error('导航失败:', err)
      }
    }).finally(() => {
      setTimeout(() => { navigating.value = false }, 300)
    })
  }
  if (command === 'tokens') {
    navigating.value = true
    router.push('/settings/tokens').catch(err => {
      if (err?.name !== 'NavigationDuplicated') {
        console.error('导航失败:', err)
      }
    }).finally(() => {
      setTimeout(() => { navigating.value = false }, 300)
    })
  }
  if (command === 'logout') {
    // Call backend to invalidate token, then clear local state
    authApi.logout().catch(() => {})
    authStore.logout()
    projectStore.clearCurrentProject()
    navigating.value = true
    router.push('/login').catch(err => {
      if (err?.name !== 'NavigationDuplicated') {
        console.error('导航失败:', err)
      }
    }).finally(() => {
      setTimeout(() => { navigating.value = false }, 300)
    })
  }
}
</script>

<style scoped>
.main-layout { height: 100vh; overflow: hidden; }
.sidebar { position: fixed; inset: 0 auto 0 0; width: var(--sidebar-w); background: var(--sidebar); display: flex; flex-direction: column; transition: width .22s ease; z-index: 100; overflow: hidden; }
.sidebar.collapsed { width: var(--sidebar-w-col); }
.sb-logo { height: var(--top-h); display: flex; align-items: center; gap: 10px; width: 100%; padding: 0 14px; flex-shrink: 0; border: 0; border-bottom: 1px solid rgba(255,255,255,.07); background: transparent; cursor: pointer; text-align: left; }
.sb-logo .mk { width: 30px; height: 30px; border-radius: 7px; background: var(--primary); color: #fff; display: grid; place-items: center; font-size: 17px; flex-shrink: 0; }
.sb-logo .nm { color: #fff; font-weight: 700; font-size: 16px; white-space: nowrap; }
.sb-nav { flex: 1; padding: 10px 8px; display: flex; flex-direction: column; gap: 2px; overflow-y: auto; overflow-x: hidden; }
.sb-sec { color: #52627A; font-size: 10px; font-weight: 700; padding: 10px 10px 4px; letter-spacing: 0; white-space: nowrap; }
.nav-item { width: 100%; min-height: 36px; display: flex; align-items: center; gap: 10px; padding: 8px 10px; border: 0; border-radius: 7px; background: transparent; cursor: pointer; white-space: nowrap; text-align: left; transition: all .15s ease; }
.nav-item:hover { background: rgba(255,255,255,.07); }
.nav-item.active { background: rgba(59,123,245,.22); box-shadow: inset 2px 0 0 var(--primary); }
.nav-item:disabled, .nav-item.navigating { opacity: 0.6; cursor: not-allowed; pointer-events: none; }
.nav-item .ic { width: 20px; flex: 0 0 20px; font-size: 16px; text-align: center; line-height: 1; filter: grayscale(0%); transition: transform .15s ease; }
.nav-item.active .ic { transform: scale(1.05); }
.nav-item .lb { color: #C8D6EE; font-size: 13px; flex: 1; }
.nav-item.active .lb { color: #fff; font-weight: 600; }
.sidebar.collapsed .nm, .sidebar.collapsed .sb-sec, .sidebar.collapsed .lb, .sidebar.collapsed .info { opacity: 0; pointer-events: none; }
.sidebar.collapsed .nav-item { padding-inline: 10px; }
.sb-foot { padding: 10px 8px; border-top: 1px solid rgba(255,255,255,.07); flex-shrink: 0; }
.sb-user { display: flex; align-items: center; gap: 10px; padding: 7px 10px; }
.av, .av-sm { display: grid; place-items: center; border-radius: 50%; background: var(--primary); color: #fff; font-weight: 700; flex-shrink: 0; }
.av { width: 28px; height: 28px; font-size: 13px; }
.sb-user .n { color: #fff; font-size: 12px; font-weight: 600; white-space: nowrap; }
.sb-user .r { color: #71839D; font-size: 10px; white-space: nowrap; margin-top: 2px; }
.topbar { position: fixed; top: 0; left: var(--sidebar-w); right: 0; height: var(--top-h); background: #fff; border-bottom: 1px solid var(--line); display: flex; align-items: center; gap: 8px; padding: 0 18px; z-index: 90; transition: left .22s ease; }
.sb-col .topbar { left: var(--sidebar-w-col); }
.tb-icon { width: 34px; height: 34px; display: grid; place-items: center; flex: 0 0 34px; border: 0; border-radius: 7px; background: transparent; color: var(--txt2); font-size: 17px; cursor: pointer; }
.tb-icon:hover { background: var(--line2); color: var(--txt); }
.toggle-mobile { display: none; }
.tb-proj { display: flex; align-items: center; gap: 8px; padding: 4px 9px; border: 0; border-radius: 7px; background: transparent; cursor: pointer; text-align: left; }
.tb-proj:hover { background: var(--line2); }
.tb-proj .pic { width: 26px; height: 26px; display: grid; place-items: center; border-radius: 6px; color: #fff; font-size: 11px; font-weight: 700; }
.tb-proj .pt { min-width: 110px; color: var(--txt); font-size: 12px; font-weight: 600; line-height: 1.15; }
.tb-proj .pt small { display: block; margin-top: 3px; color: var(--txt3); font-size: 10px; font-weight: 400; }
.proj-arrow { color: var(--txt3); font-size: 12px; }
.context-chip { display: flex; align-items: center; gap: 5px; height: 28px; padding: 0 9px; border-left: 1px solid var(--line); color: var(--txt3); font-size: 11px; }
.tb-spacer { flex: 1; }
.tb-sep { width: 1px; height: 22px; background: var(--line); margin: 0 2px; }
.tb-user { display: flex; align-items: center; gap: 7px; padding: 3px 7px; border: 0; border-radius: 7px; background: transparent; color: var(--txt); cursor: pointer; }
.tb-user:hover { background: var(--line2); }
.av-sm { width: 28px; height: 28px; font-size: 12px; }
.tb-uname { max-width: 100px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; }
.main-area { position: fixed; top: var(--top-h); left: var(--sidebar-w); right: 0; bottom: 0; overflow-y: auto; background: var(--bg); padding: 24px 28px; transition: left .22s ease; }
.sb-col .main-area { left: var(--sidebar-w-col); }
.sidebar-mask { display: none; }
:global(.project-menu .el-dropdown-menu__item) { min-width: 230px; gap: 8px; }
:global(.project-menu .el-dropdown-menu__item small) { margin-left: auto; color: var(--txt3); }
:global(.project-menu .el-dropdown-menu__item.is-current) { color: var(--primary); background: var(--primary-bg); }
.project-option-mark { width: 22px; height: 22px; display: grid; place-items: center; border-radius: 5px; color: #fff; font-size: 10px; }
@media (max-width: 760px) {
  .sidebar { width: var(--sidebar-w); transform: translateX(-100%); transition: transform .22s ease; }
  .sidebar.collapsed { width: var(--sidebar-w); }
  .mobile-open .sidebar { transform: translateX(0); }
  .sidebar.collapsed .nm, .sidebar.collapsed .sb-sec, .sidebar.collapsed .lb, .sidebar.collapsed .info { opacity: 1; pointer-events: auto; }
  .topbar, .sb-col .topbar { left: 0; padding-inline: 10px; }
  .main-area, .sb-col .main-area { left: 0; padding: 18px 14px; }
  .toggle-desktop, .context-chip, .tb-uname { display: none; }
  .toggle-mobile { display: grid; }
  .tb-proj .pt { min-width: 0; max-width: 145px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .tb-proj .pt small { display: none; }
  .sidebar-mask { display: block; position: fixed; inset: 0; border: 0; background: rgba(15,25,41,.42); z-index: 95; }
}
</style>