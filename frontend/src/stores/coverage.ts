// 覆盖率模块 Pinia store
// 状态分组：
// - 任务列表（分页 + 筛选）
// - 当前任务详情 + 当前 run + reports（WS 实时合并）
// - WS client 生命周期（详情页挂载时连接，卸载时断开）
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import {
  cancelCoverageTask,
  createCoverageTask,
  deleteCoverageTask,
  getCoverageTask,
  listCoverageTasks,
  listRunReports,
  listTaskRuns,
  triggerCoverageTask,
  updateCoverageTask,
} from '@/api/coverage'
import type {
  CoverageTask,
  CoverageTaskCreatePayload,
  CoverageTaskFilters,
  CoverageTaskUpdatePayload,
  JavaCoverageReport,
  JavaCoverageRun,
  TaskStatus,
  WsMessage,
} from '@/types/coverage'
import { CoverageProgressClient } from '@/utils/progress-ws'

export const useCoverageStore = defineStore('coverage', () => {
  // ─── 任务列表 ───

  const tasks = ref<CoverageTask[]>([])
  const tasksTotal = ref(0)
  const tasksPage = ref(1)
  const tasksPageSize = ref(20)
  const tasksLoading = ref(false)
  const filters = ref<CoverageTaskFilters>({
    keyword: '',
    status: [],
    branch: '',
    dateRange: [],
  })

  async function fetchTasks(projectId: number, page = tasksPage.value): Promise<void> {
    tasksLoading.value = true
    try {
      const statusParam = filters.value.status.length ? filters.value.status.join(',') : undefined
      const data = await listCoverageTasks(projectId, {
        page,
        page_size: tasksPageSize.value,
        keyword: filters.value.keyword || undefined,
        status: statusParam,
        branch: filters.value.branch || undefined,
      })
      tasks.value = data.items
      tasksTotal.value = data.total
      tasksPage.value = data.page
      tasksPageSize.value = data.page_size
    } finally {
      tasksLoading.value = false
    }
  }

  async function createTask(projectId: number, payload: CoverageTaskCreatePayload): Promise<CoverageTask> {
    const task = await createCoverageTask(projectId, payload)
    await fetchTasks(projectId, 1)
    return task
  }

  async function updateTask(projectId: number, taskId: number, payload: CoverageTaskUpdatePayload): Promise<CoverageTask> {
    const task = await updateCoverageTask(projectId, taskId, payload)
    const idx = tasks.value.findIndex((t) => t.id === taskId)
    if (idx >= 0) tasks.value[idx] = task
    if (currentTask.value?.id === taskId) currentTask.value = task
    return task
  }

  async function removeTask(projectId: number, taskId: number): Promise<void> {
    await deleteCoverageTask(projectId, taskId)
    await fetchTasks(projectId, tasksPage.value)
  }

  // ─── 当前任务 + run + reports ───

  const currentTask = ref<CoverageTask | null>(null)
  const currentRun = ref<JavaCoverageRun | null>(null)
  const reports = ref<JavaCoverageReport[]>([])
  const detailLoading = ref(false)
  const runsHistory = ref<JavaCoverageRun[]>([])
  const runsTotal = ref(0)

  async function loadTaskDetail(projectId: number, taskId: number): Promise<void> {
    detailLoading.value = true
    try {
      const task = await getCoverageTask(projectId, taskId)
      currentTask.value = task
      if (task.current_run_id) {
        reports.value = await listRunReports(task.current_run_id)
      } else {
        reports.value = []
      }
    } finally {
      detailLoading.value = false
    }
  }

  async function loadRunsHistory(projectId: number, taskId: number, page = 1): Promise<void> {
    const data = await listTaskRuns(projectId, taskId, { page, page_size: 10 })
    runsHistory.value = data.items
    runsTotal.value = data.total
  }

  async function trigger(projectId: number, taskId: number): Promise<number> {
    const resp = await triggerCoverageTask(projectId, taskId)
    if (currentTask.value?.id === taskId) {
      currentTask.value = {
        ...currentTask.value,
        status: 'queued' as TaskStatus,
        current_run_id: resp.run_id,
      }
      reports.value = resp.reports
      wsClient?.setRunId(resp.run_id)
    }
    return resp.run_id
  }

  async function cancel(projectId: number, taskId: number): Promise<void> {
    await cancelCoverageTask(projectId, taskId)
    if (currentTask.value?.id === taskId) {
      currentTask.value = { ...currentTask.value, status: 'cancelled' as TaskStatus }
    }
  }

  // ─── WebSocket 实时进度 ───

  const wsState = ref<'connecting' | 'open' | 'reconnecting' | 'polling' | 'closed'>('closed')
  let wsClient: CoverageProgressClient | null = null

  function connectProgress(taskId: number, runId?: number): void {
    disconnectProgress()
    wsClient = new CoverageProgressClient(taskId, {
      onMessage: handleWsMessage,
      onPollingReports: (rs) => {
        reports.value = rs
      },
      onStateChange: (s) => {
        wsState.value = s
      },
    })
    wsClient.connect(runId)
  }

  function disconnectProgress(): void {
    wsClient?.disconnect()
    wsClient = null
    wsState.value = 'closed'
  }

  function handleWsMessage(msg: WsMessage): void {
    switch (msg.type) {
      case 'snapshot': {
        reports.value = msg.reports
        if (currentTask.value && msg.run_id) {
          currentTask.value = { ...currentTask.value, current_run_id: msg.run_id }
        }
        break
      }
      case 'progress': {
        const r = reports.value.find((x) => x.id === msg.report_id)
        if (r) {
          r.progress = msg.progress
          r.stage = msg.stage
          r.stage_detail = msg.stage_detail
          if (r.status === 'queued') r.status = 'running'
        }
        break
      }
      case 'service_done': {
        const r = reports.value.find((x) => x.id === msg.report_id)
        if (r) {
          r.status = 'completed'
          r.progress = 100
          r.stage = 'done'
          if (msg.coverage) {
            r.line_rate = msg.coverage.line_rate
            r.branch_rate = msg.coverage.branch_rate
            r.lines_covered = msg.coverage.lines_covered
            r.lines_total = msg.coverage.lines_total
          }
        }
        break
      }
      case 'service_error': {
        const r = reports.value.find((x) => x.id === msg.report_id)
        if (r) {
          r.status = 'failed'
          r.error_message = msg.message
          r.progress = msg.progress
          r.stage = msg.stage
        }
        break
      }
      case 'task_done': {
        if (currentTask.value?.id === msg.task_id) {
          const newStatus: TaskStatus = msg.success === true ? 'completed' : msg.success === false ? 'failed' : 'completed'
          currentTask.value = { ...currentTask.value, status: newStatus }
          // 刷新历史 run 列表，让 RunHistoryStrip 能立即看到新 run
          void listTaskRuns(currentTask.value.project_id, msg.task_id, { page: 1, page_size: 10 }).then((data) => {
            runsHistory.value = data.items
            runsTotal.value = data.total
          })
        }
        // run 结束后再刷新一次 reports 保证数据一致
        if (msg.run_id) {
          void listRunReports(msg.run_id).then((rs) => {
            reports.value = rs
          })
        }
        break
      }
      case 'ping':
      case 'pong':
        // 心跳，忽略
        break
    }
  }

  // ─── 计算属性 ───

  const overallProgress = computed(() => {
    if (reports.value.length === 0) return 0
    const sum = reports.value.reduce((acc, r) => acc + (r.progress || 0), 0)
    return Math.round(sum / reports.value.length)
  })

  const completedCount = computed(() => reports.value.filter((r) => r.status === 'completed').length)
  const failedCount = computed(() => reports.value.filter((r) => r.status === 'failed').length)
  const isRunning = computed(() => currentTask.value?.status === 'running' || currentTask.value?.status === 'queued')

  return {
    // list
    tasks, tasksTotal, tasksPage, tasksPageSize, tasksLoading, filters,
    fetchTasks, createTask, updateTask, removeTask,
    // detail
    currentTask, currentRun, reports, detailLoading,
    runsHistory, runsTotal,
    loadTaskDetail, loadRunsHistory, trigger, cancel,
    // ws
    wsState, connectProgress, disconnectProgress,
    // computed
    overallProgress, completedCount, failedCount, isRunning,
  }
})
