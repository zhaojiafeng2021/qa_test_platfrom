<template>
  <div class="coverage-detail-page" v-loading="store.detailLoading">
    <template v-if="task">
      <div class="page-head">
        <div class="title-row">
          <el-button link :icon="ArrowLeft" @click="goBack">返回</el-button>
          <h1>{{ task.name }}</h1>
          <el-tag :type="statusTagType(task.status)" size="small" effect="light">{{ statusText(task.status) }}</el-tag>
          <div class="ws-indicator" :class="`ws-${store.wsState}`">
            <span class="dot" />
            <span class="ws-text">{{ wsStateText }}</span>
          </div>
        </div>
        <div class="actions">
          <el-button
            v-if="canRun"
            type="primary"
            :icon="VideoPlay"
            :disabled="store.isRunning"
            @click="handleTrigger"
          >触发采集</el-button>
          <el-button
            v-if="canRun && store.isRunning"
            type="danger"
            :icon="CircleClose"
            @click="handleCancel"
          >取消</el-button>
        </div>
      </div>

      <el-card class="info-card" shadow="never">
        <el-descriptions :column="3" size="small" border>
          <el-descriptions-item label="Git 仓库">{{ task.repo_url }}</el-descriptions-item>
          <el-descriptions-item label="目标分支">{{ task.branch }}</el-descriptions-item>
          <el-descriptions-item label="Diff 基准">{{ task.diff_base_branch || '—' }}</el-descriptions-item>
          <el-descriptions-item label="采集模式">
            <el-tag v-if="task.collection_mode === 'runtime'" type="warning" size="small" effect="plain">运行时 (tcpserver dump)</el-tag>
            <span v-else>单元测试</span>
          </el-descriptions-item>
          <el-descriptions-item v-if="task.collection_mode === 'runtime' && task.runtime_config" label="Agent 地址" :span="2">
            {{ task.runtime_config.host || '—' }}:{{ task.runtime_config.port || 6300 }}
            <el-tag v-if="task.runtime_config.reset" type="info" size="small" effect="plain" class="reset-tag">dump 后重置</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="Cron">{{ task.cron_expr || '—' }}</el-descriptions-item>
          <el-descriptions-item label="行阈值">{{ fmtRate(task.threshold_line_rate) }}</el-descriptions-item>
          <el-descriptions-item label="分支阈值">{{ fmtRate(task.threshold_branch_rate) }}</el-descriptions-item>
          <el-descriptions-item label="关联需求">{{ task.requirement_ref || '—' }}</el-descriptions-item>
          <el-descriptions-item label="最近成功">{{ task.last_completed_at ? formatTime(task.last_completed_at) : '—' }}</el-descriptions-item>
          <el-descriptions-item label="最近失败">{{ task.last_failed_at ? formatTime(task.last_failed_at) : '—' }}</el-descriptions-item>
        </el-descriptions>
      </el-card>

      <el-card v-if="task.current_run_id" class="progress-card" shadow="never">
        <template #header>
          <div class="card-head">
            <span>当前运行 #{{ task.current_run_id }}</span>
            <div class="overall">
              <span class="overall-label">整体进度</span>
              <el-progress :percentage="store.overallProgress" :stroke-width="14" class="overall-bar" />
              <span class="overall-stats">
                成功 {{ store.completedCount }} · 失败 {{ store.failedCount }} · 共 {{ store.reports.length }}
              </span>
            </div>
          </div>
        </template>
        <div class="services">
          <ServiceProgressRow
            v-for="r in store.reports"
            :key="r.id"
            :report="r"
            :diff-base="task.diff_base_branch"
            @view-code="goCode"
            @view-diff="goCode"
            @view-log="showLog"
          />
          <el-empty v-if="store.reports.length === 0" description="尚未生成服务报告" :image-size="60" />
        </div>
      </el-card>

      <el-card class="history-card" shadow="never">
        <template #header>
          <span>历史运行</span>
        </template>
        <RunHistoryStrip
          :runs="store.runsHistory"
          :current-run-id="snapshotRun?.id ?? task.current_run_id"
          @select="onSelectRun"
        />
      </el-card>

      <el-card v-if="snapshotRun" class="snapshot-card" shadow="never" v-loading="snapshotLoading">
        <template #header>
          <div class="card-head">
            <span>历史快照 Run #{{ snapshotRun.id }} · {{ formatTime(snapshotRun.finished_at || snapshotRun.started_at || snapshotRun.created_at) }}</span>
            <el-button link type="primary" @click="closeSnapshot">关闭快照</el-button>
          </div>
        </template>
        <div class="services">
          <ServiceProgressRow
            v-for="r in snapshotReports"
            :key="r.id"
            :report="r"
            :diff-base="task.diff_base_branch"
            @view-code="goCode"
            @view-diff="goCode"
            @view-log="showLog"
          />
          <el-empty v-if="!snapshotLoading && snapshotReports.length === 0" description="该次运行无服务报告" :image-size="60" />
        </div>
      </el-card>
    </template>

    <el-dialog v-model="logVisible" title="构建日志" width="70%">
      <pre class="build-log">{{ logContent }}</pre>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, CircleClose, VideoPlay } from '@element-plus/icons-vue'
import { useCoverageStore } from '@/stores/coverage'
import { useProjectStore } from '@/stores/project'
import { usePermission } from '@/composables/usePermission'
import { getReportBuildLog, listRunReports } from '@/api/coverage'
import { formatTime } from '@/utils/format'
import type { JavaCoverageReport, JavaCoverageRun, TaskStatus } from '@/types/coverage'
import ServiceProgressRow from './components/ServiceProgressRow.vue'
import RunHistoryStrip from './components/RunHistoryStrip.vue'

const route = useRoute()
const router = useRouter()
const store = useCoverageStore()
const projectStore = useProjectStore()
const { hasPermission } = usePermission()

const pid = computed(() => projectStore.currentProjectId)
const taskId = computed(() => Number(route.params.taskId))
const task = computed(() => store.currentTask)

const canRun = computed(() => hasPermission('coverage:run'))

const logVisible = ref(false)
const logContent = ref('')

const wsStateText = computed(() => {
  switch (store.wsState) {
    case 'connecting': return 'WS 连接中'
    case 'open': return 'WS 已连接'
    case 'reconnecting': return 'WS 重连中'
    case 'polling': return '轮询模式'
    default: return 'WS 未连接'
  }
})

function statusText(s: TaskStatus): string {
  switch (s) {
    case 'draft': return '草稿'
    case 'queued': return '排队中'
    case 'running': return '运行中'
    case 'completed': return '已完成'
    case 'failed': return '失败'
    case 'cancelled': return '已取消'
    default: return s
  }
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

function fmtRate(v?: number): string {
  if (v === undefined || v === null) return '—'
  return `${Math.round((v > 1 ? v : v * 100) * 10) / 10}%`
}

function goBack(): void {
  router.push({ name: 'CoverageList' })
}

async function handleTrigger(): Promise<void> {
  if (!pid.value) return
  try {
    await store.trigger(pid.value, taskId.value)
    ElMessage.success('已触发')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '触发失败')
  }
}

async function handleCancel(): Promise<void> {
  if (!pid.value) return
  try {
    await ElMessageBox.confirm('确认取消当前运行？', '取消确认', { type: 'warning' })
  } catch {
    return
  }
  try {
    await store.cancel(pid.value, taskId.value)
    ElMessage.success('已请求取消')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '取消失败')
  }
}

function goCode(report: JavaCoverageReport): void {
  router.push({
    name: 'CoverageCode',
    params: { taskId: taskId.value, reportId: report.id },
  })
}

async function showLog(report: JavaCoverageReport): Promise<void> {
  logVisible.value = true
  logContent.value = '加载中…'
  try {
    const data = await getReportBuildLog(report.id)
    logContent.value = data.log || '(空)'
  } catch (e: any) {
    logContent.value = `加载失败：${e?.response?.data?.detail || e?.message || '未知错误'}`
  }
}

// 历史快照：单独加载，不覆盖 store.reports，避免干扰当前运行的 WS 进度
const snapshotRun = ref<JavaCoverageRun | null>(null)
const snapshotReports = ref<JavaCoverageReport[]>([])
const snapshotLoading = ref(false)

async function onSelectRun(run: JavaCoverageRun): Promise<void> {
  if (run.id === task.value?.current_run_id || run.id === snapshotRun.value?.id) {
    closeSnapshot()
    return
  }
  snapshotRun.value = run
  snapshotReports.value = []
  snapshotLoading.value = true
  try {
    const reports = await listRunReports(run.id)
    // 加载期间用户可能切换到别的 run，丢弃过期结果
    if (snapshotRun.value?.id === run.id) snapshotReports.value = reports
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '加载历史快照失败')
    if (snapshotRun.value?.id === run.id) snapshotRun.value = null
  } finally {
    if (snapshotRun.value?.id === run.id || !snapshotRun.value) snapshotLoading.value = false
  }
}

function closeSnapshot(): void {
  snapshotRun.value = null
  snapshotReports.value = []
}

watch(
  () => task.value?.current_run_id,
  (runId) => {
    if (runId) store.connectProgress(taskId.value, runId)
  },
)

onMounted(async () => {
  if (!pid.value) return
  await store.loadTaskDetail(pid.value, taskId.value)
  await store.loadRunsHistory(pid.value, taskId.value)
  if (task.value?.current_run_id) {
    store.connectProgress(taskId.value, task.value.current_run_id)
  }
})

// MainLayout 异步加载 project，pid 初次可能是 undefined；就绪后补一次拉取
watch(pid, async (v) => {
  if (!v) return
  if (!store.currentTask || store.currentTask.id !== taskId.value) {
    await store.loadTaskDetail(v, taskId.value)
    await store.loadRunsHistory(v, taskId.value)
    if (task.value?.current_run_id) {
      store.connectProgress(taskId.value, task.value.current_run_id)
    }
  }
})

onBeforeUnmount(() => {
  store.disconnectProgress()
})
</script>

<style scoped>
.coverage-detail-page {
  padding: 20px;
}
.reset-tag { margin-left: 8px; }
.page-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.title-row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.title-row h1 {
  font-size: 20px;
  font-weight: 600;
  margin: 0;
}
.ws-indicator {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  padding: 2px 8px;
  border-radius: 10px;
  background: var(--el-fill-color-light);
}
.ws-indicator .dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--el-text-color-placeholder);
}
.ws-open .dot { background: var(--el-color-success); }
.ws-connecting .dot,
.ws-reconnecting .dot { background: var(--el-color-warning); }
.ws-polling .dot { background: var(--el-color-primary); }
.info-card, .progress-card, .history-card, .snapshot-card {
  margin-bottom: 16px;
}
.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 24px;
}
.overall {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
  max-width: 520px;
}
.overall-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  white-space: nowrap;
}
.overall-bar {
  flex: 1;
}
.overall-stats {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  white-space: nowrap;
}
.services {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.build-log {
  background: var(--el-fill-color-darker);
  color: var(--el-text-color-primary);
  padding: 12px;
  border-radius: 4px;
  font-size: 12px;
  line-height: 1.6;
  max-height: 60vh;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
  font-family: 'JetBrains Mono', 'Consolas', monospace;
}
</style>
