<template>
  <div class="coverage-list-page" v-loading="store.tasksLoading">
    <div class="page-head">
      <h1><el-icon><DataAnalysis /></el-icon>覆盖率任务</h1>
      <div class="actions">
        <el-button v-if="canCreate" type="primary" :icon="Plus" @click="openEditor()">新建任务</el-button>
      </div>
    </div>

    <div class="toolbar">
      <el-input
        v-model="store.filters.keyword"
        placeholder="按名称搜索"
        :prefix-icon="Search"
        clearable
        class="search-input"
        @change="() => refresh(1)"
      />
      <el-select
        v-model="store.filters.status"
        multiple
        collapse-tags
        placeholder="状态筛选"
        class="status-select"
        @change="() => refresh(1)"
      >
        <el-option v-for="opt in statusOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
      </el-select>
      <el-input
        v-model="store.filters.branch"
        placeholder="分支"
        clearable
        class="branch-input"
        @change="() => refresh(1)"
      />
      <el-button :icon="Refresh" circle @click="() => refresh()" />
    </div>

    <el-table :data="store.tasks" empty-text="暂无覆盖率任务" class="task-table">
      <el-table-column label="任务名称" min-width="220">
        <template #default="scope">
          <div class="task-name" @click="goDetail(scope.row as any)">{{ scope.row.name }}</div>
          <div class="task-meta">
            <span>{{ scope.row.repo_url }} · {{ scope.row.branch }}</span>
            <el-tag v-if="scope.row.collection_mode === 'runtime'" type="warning" size="small" effect="plain" class="mode-tag">运行时</el-tag>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="服务数" width="80" align="center">
        <template #default="scope">{{ scope.row.services?.length || 0 }}</template>
      </el-table-column>
      <el-table-column label="状态" width="110">
        <template #default="scope">
          <el-tag :type="statusTagType((scope.row as any).status)" size="small" effect="light">{{ statusText((scope.row as any).status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="最近成功" width="160">
        <template #default="scope">
          <span class="time-text">{{ scope.row.last_completed_at ? formatTime(scope.row.last_completed_at) : '—' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="最近失败" width="160">
        <template #default="scope">
          <span class="time-text">{{ scope.row.last_failed_at ? formatTime(scope.row.last_failed_at) : '—' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="260" align="center" fixed="right">
        <template #default="scope">
          <el-button link type="primary" size="small" @click="goDetail(scope.row as any)">查看</el-button>
          <el-button v-if="canUpdate" link type="primary" size="small" @click="openEditor(scope.row as any)">编辑</el-button>
          <el-button
            v-if="canRun"
            link
            type="primary"
            size="small"
            :disabled="scope.row.status === 'running' || scope.row.status === 'queued'"
            @click="handleTrigger(scope.row as any)"
          >触发</el-button>
          <el-button v-if="canDelete" link type="danger" size="small" @click="handleDelete(scope.row as any)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-pagination
      v-model:current-page="store.tasksPage"
      v-model:page-size="store.tasksPageSize"
      :total="store.tasksTotal"
      :page-sizes="[10, 20, 50]"
      layout="total, sizes, prev, pager, next, jumper"
      class="pagination"
      @current-change="() => refresh()"
      @size-change="() => refresh(1)"
    />

    <CoverageTaskFormDialog v-model="editorVisible" :task="editingTask" :project-id="pid ?? undefined" @submit="handleSubmit" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { DataAnalysis, Plus, Refresh, Search } from '@element-plus/icons-vue'
import { useCoverageStore } from '@/stores/coverage'
import { useProjectStore } from '@/stores/project'
import { usePermission } from '@/composables/usePermission'
import { formatTime } from '@/utils/format'
import type { CoverageTask, CoverageTaskCreatePayload, TaskStatus } from '@/types/coverage'
import CoverageTaskFormDialog from './components/CoverageTaskFormDialog.vue'

const store = useCoverageStore()
const projectStore = useProjectStore()
const { hasPermission } = usePermission()
const router = useRouter()

const pid = computed(() => projectStore.currentProjectId)

const canCreate = computed(() => hasPermission('coverage:create'))
const canUpdate = computed(() => hasPermission('coverage:update'))
const canDelete = computed(() => hasPermission('coverage:delete'))
const canRun = computed(() => hasPermission('coverage:run'))

const editorVisible = ref(false)
const editingTask = ref<CoverageTask | null>(null)

const statusOptions: Array<{ label: string; value: TaskStatus }> = [
  { label: '草稿', value: 'draft' },
  { label: '排队中', value: 'queued' },
  { label: '运行中', value: 'running' },
  { label: '已完成', value: 'completed' },
  { label: '失败', value: 'failed' },
  { label: '已取消', value: 'cancelled' },
]

function statusText(s: TaskStatus): string {
  return statusOptions.find((o) => o.value === s)?.label || s
}

function statusTagType(s: TaskStatus): 'success' | 'warning' | 'danger' | 'info' | 'primary' {
  switch (s) {
    case 'completed': return 'success'
    case 'failed': return 'danger'
    case 'running': return 'primary'
    case 'queued': return 'warning'
    default: return 'info'
  }
}

async function refresh(page?: number): Promise<void> {
  if (!pid.value) return
  await store.fetchTasks(pid.value, page ?? store.tasksPage)
}

function openEditor(task?: CoverageTask): void {
  editingTask.value = task || null
  editorVisible.value = true
}

async function handleSubmit(payload: CoverageTaskCreatePayload, isEdit: boolean): Promise<void> {
  if (!pid.value) return
  try {
    if (isEdit && editingTask.value) {
      await store.updateTask(pid.value, editingTask.value.id, payload)
      ElMessage.success('任务已更新')
    } else {
      await store.createTask(pid.value, payload)
      ElMessage.success('任务已创建')
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '操作失败')
  }
}

async function handleDelete(row: CoverageTask): Promise<void> {
  if (!pid.value) return
  try {
    await ElMessageBox.confirm(`确认删除任务「${row.name}」？`, '删除确认', { type: 'warning' })
  } catch {
    return
  }
  try {
    await store.removeTask(pid.value, row.id)
    ElMessage.success('已删除')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '删除失败')
  }
}

async function handleTrigger(row: CoverageTask): Promise<void> {
  if (!pid.value) return
  try {
    const runId = await store.trigger(pid.value, row.id)
    ElMessage.success(`已触发，Run #${runId}`)
    goDetail(row)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '触发失败')
  }
}

function goDetail(row: CoverageTask): void {
  router.push({ name: 'CoverageDetail', params: { taskId: row.id } })
}

onMounted(() => {
  refresh(1)
})

// MainLayout 异步加载 project，pid 初次可能是 undefined；等它就绪后补一次拉取
watch(pid, (v) => {
  if (v) refresh(1)
})
</script>

<style scoped>
.coverage-list-page {
  padding: 20px;
}
.page-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.page-head h1 {
  font-size: 20px;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
}
.toolbar {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
  align-items: center;
}
.search-input { width: 240px; }
.status-select { width: 200px; }
.branch-input { width: 140px; }
.task-table { margin-top: 8px; }
.task-name {
  font-weight: 500;
  color: var(--el-color-primary);
  cursor: pointer;
}
.task-name:hover { text-decoration: underline; }
.task-meta {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-top: 2px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.mode-tag { margin: 0; }
.time-text {
  font-size: 12px;
  color: var(--el-text-color-regular);
}
.pagination {
  margin-top: 12px;
  justify-content: flex-end;
}
</style>
