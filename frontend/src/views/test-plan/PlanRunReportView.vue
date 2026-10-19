<template>
  <div class="plan-run-report">
    <el-page-header @back="goBack" title="返回">
      <template #content>
        <span class="page-title">执行报告</span>
      </template>
      <template #extra>
        <el-button
          type="primary"
          :icon="Document"
          :loading="generating"
          @click="generateReport"
        >
          生成HTML报告
        </el-button>
      </template>
    </el-page-header>

    <div v-if="loading" class="loading-container">
      <el-skeleton :rows="8" animated />
    </div>

    <div v-else-if="planRun" class="report-content">
      <!-- 报告概览 -->
      <el-card class="summary-card" shadow="never">
        <div class="summary-header">
          <div class="summary-title">
            <h3>{{ planRun.plan_id ? `计划 #${planRun.plan_id}` : '测试计划' }}</h3>
            <el-tag :type="getStatusType(planRun.status) as any" size="large">
              {{ getStatusLabel(planRun.status) }}
            </el-tag>
          </div>
          <div class="summary-meta">
            <span>执行ID: {{ planRun.id }}</span>
            <span>环境: {{ planRun.environment_id ? `#${planRun.environment_id}` : '-' }}</span>
            <span>触发: {{ getTriggerLabel(planRun.trigger_type) }}</span>
          </div>
        </div>

        <el-divider />

        <el-descriptions :column="3" border>
          <el-descriptions-item label="开始时间">
            {{ planRun.started_at ? formatDateTime(planRun.started_at) : '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="结束时间">
            {{ planRun.finished_at ? formatDateTime(planRun.finished_at) : '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="执行耗时">
            {{ formatDuration(planRun.started_at || null, planRun.finished_at || null) }}
          </el-descriptions-item>
          <el-descriptions-item label="总用例数">
            {{ planRun.total_items }}
          </el-descriptions-item>
          <el-descriptions-item label="通过用例">
            <span style="color: #67c23a; font-weight: 600">{{ planRun.passed_items }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="失败用例">
            <span style="color: #f56c6c; font-weight: 600">{{ planRun.failed_items }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="通过率" :span="3">
            <el-progress
              :percentage="passRate"
              :color="passRate >= 80 ? '#67c23a' : passRate >= 60 ? '#e6a23c' : '#f56c6c'"
              :stroke-width="20"
              :text-inside="true"
            />
          </el-descriptions-item>
        </el-descriptions>
      </el-card>

      <!-- 已生成的报告列表 -->
      <el-card v-if="reports.length" class="reports-card" shadow="never">
        <template #header>
          <div class="card-header">
            <span>报告文件</span>
            <el-button link type="primary" :icon="Refresh" @click="loadReports">刷新</el-button>
          </div>
        </template>
        <el-table :data="reports" size="small">
          <el-table-column label="ID" prop="id" width="70" />
          <el-table-column label="类型" prop="report_type" width="80">
            <template #default="{ row }">
              <el-tag size="small">{{ row.report_type.toUpperCase() }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="100" align="center">
            <template #default="{ row }">
              <el-tag :type="reportStatusType(row.status) as any" size="small">
                {{ reportStatusLabel(row.status) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="大小" width="100" align="center">
            <template #default="{ row }">
              {{ row.file_size ? formatSize(row.file_size) : '-' }}
            </template>
          </el-table-column>
          <el-table-column label="生成时间" min-width="170">
            <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="错误信息" prop="error_message" min-width="160" show-overflow-tooltip />
          <el-table-column label="操作" width="160" fixed="right">
            <template #default="{ row }">
              <el-button
                v-if="row.status === 'generated'"
                link
                type="primary"
                :loading="downloadingId === row.id"
                @click="downloadReport(row as ReportFile)"
              >查看</el-button>
              <el-popconfirm title="确认删除该报告？" @confirm="removeReport(row as ReportFile)">
                <template #reference>
                  <el-button link type="danger">删除</el-button>
                </template>
              </el-popconfirm>
            </template>
          </el-table-column>
        </el-table>
      </el-card>

      <!-- 用例执行结果列表 -->
      <el-card class="items-card" shadow="never">
        <template #header>
          <div class="card-header">
            <span>用例执行明细</span>
            <el-radio-group v-model="statusFilter" size="small">
              <el-radio-button label="">全部</el-radio-button>
              <el-radio-button label="passed">通过</el-radio-button>
              <el-radio-button label="failed">失败</el-radio-button>
            </el-radio-group>
          </div>
        </template>

        <el-table :data="filteredItems" stripe border>
          <el-table-column type="expand">
            <template #default="{ row }">
              <div class="execution-detail-panel">
                <!-- 代码用例：执行概要 + 日志预览 -->
                <div v-if="row.case_type === 'code'" class="code-execution-panel">
                  <div class="detail-content">
                    <!-- 执行概要（复用原样式） -->
                    <div class="execution-summary">
                      <el-descriptions :column="3" size="small" border>
                        <el-descriptions-item label="执行ID">
                          {{ row.code_execution_id || '-' }}
                        </el-descriptions-item>
                        <el-descriptions-item label="用例模块">
                          {{ row.module || '-' }}
                        </el-descriptions-item>
                        <el-descriptions-item label="状态">
                          <el-tag :type="getStatusType(row.status) as any" size="small">
                            {{ getStatusLabel(row.status) }}
                          </el-tag>
                        </el-descriptions-item>
                        <el-descriptions-item label="开始时间">
                          {{ row.started_at ? formatDateTime(row.started_at) : '-' }}
                        </el-descriptions-item>
                        <el-descriptions-item label="结束时间">
                          {{ row.finished_at ? formatDateTime(row.finished_at) : '-' }}
                        </el-descriptions-item>
                        <el-descriptions-item label="耗时">
                          {{ row.duration_ms ? `${row.duration_ms}ms` : '-' }}
                        </el-descriptions-item>
                      </el-descriptions>
                    </div>

                    <!-- 错误信息（失败时展示） -->
                    <div v-if="row.error_message" class="error-section">
                      <el-alert
                        :title="row.error_message"
                        type="error"
                        :closable="false"
                        show-icon
                      />
                    </div>

                    <!-- 执行日志预览（代码用例多出的部分） -->
                    <div class="logs-section">
                      <div class="section-title">
                        执行日志
                        <el-tag v-if="row.logs" size="small" effect="plain" class="log-size">
                          {{ (row.logs || '').length }} 字符
                        </el-tag>
                      </div>
                      <pre v-if="row.logs" class="log-view">{{ row.logs }}</pre>
                      <el-empty v-else description="暂无执行日志" :image-size="48" />
                    </div>
                  </div>
                </div>
                <el-empty v-else description="无执行记录" :image-size="60" />
              </div>
            </template>
          </el-table-column>
          <el-table-column label="用例名称" prop="case_name" min-width="200" show-overflow-tooltip>
            <template #default="{ row }">
              <div style="display: flex; align-items: center; gap: 8px;">
                <el-tag v-if="row.case_type === 'code'" size="small" type="success">代码</el-tag>
                <span>{{ row.case_name || `代码用例 #${row.case_id}` }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="优先级" prop="priority" width="80" align="center">
            <template #default="{ row }">
              <el-tag v-if="row.priority" size="small" :type="getPriorityType(row.priority) as any">
                {{ getPriorityText(row.priority) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="状态" prop="status" width="100" align="center">
            <template #default="{ row }">
              <el-tag :type="getStatusType(row.status) as any" size="small">
                {{ getStatusLabel(row.status) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="步骤" width="120" align="center">
            <template #default="{ row }">
              <span style="color: #67c23a">{{ row.passed_steps || 0 }}</span>
              /
              <span style="color: #f56c6c">{{ row.failed_steps || 0 }}</span>
              /
              <span>{{ row.total_steps || 0 }}</span>
            </template>
          </el-table-column>
          <el-table-column label="耗时" prop="duration_ms" width="100" align="center">
            <template #default="{ row }">
              {{ row.duration_ms ? `${row.duration_ms}ms` : '-' }}
            </template>
          </el-table-column>
          <el-table-column label="错误信息" prop="error_message" min-width="200" show-overflow-tooltip />
        </el-table>
      </el-card>
    </div>

    <el-empty v-else description="未找到执行报告" />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Document, Refresh } from '@element-plus/icons-vue'
import { getPlanRun, createReport, listPlanRunReports, deleteReport } from '@/api/test-plan'
import type { PlanRun, ReportFile } from '@/types/test-plan'
import { formatDateTime, parseUTC } from '@/utils/datetime'

const route = useRoute()
const router = useRouter()

const projectId = computed(() => {
  const code = route.params.projectCode as string
  // Extract project ID from store or route - for now assuming it's in meta or we need to resolve
  // This is a simplification; in real app you'd get this from projectStore
  return Number(route.query.projectId) || 33 // Fallback for now
})

const runId = computed(() => Number(route.params.runId))

const loading = ref(false)
const planRun = ref<PlanRun | null>(null)
const statusFilter = ref('')
const reports = ref<ReportFile[]>([])
const generating = ref(false)
const downloadingId = ref<number | null>(null)

const reportStatusMap: Record<string, { label: string; type: string }> = {
  pending: { label: '生成中', type: 'info' },
  generated: { label: '已生成', type: 'success' },
  failed: { label: '失败', type: 'danger' },
}

const statusMap: Record<string, { label: string; type: string }> = {
  pending: { label: '等待中', type: 'info' },
  running: { label: '执行中', type: 'warning' },
  passed: { label: '通过', type: 'success' },
  failed: { label: '失败', type: 'danger' },
  cancelled: { label: '已取消', type: 'info' },
}

const triggerMap: Record<string, string> = {
  manual: '手动',
  schedule: '定时',
  api: 'API',
  ci: 'CI',
}

const priorityMap: Record<string, string> = {
  P0: 'danger',
  P1: 'warning',
  P2: '',
  P3: 'info',
  critical: 'danger',
  high: 'warning',
  medium: '',
  low: 'info',
}

const priorityTextMap: Record<string, string> = {
  critical: 'P0',
  high: 'P1',
  medium: 'P2',
  low: 'P3',
}

const filteredItems = computed(() => {
  if (!planRun.value?.items) return []
  if (!statusFilter.value) return planRun.value.items
  return planRun.value.items.filter(item => item.status === statusFilter.value)
})

const passRate = computed(() => {
  if (!planRun.value || planRun.value.total_items === 0) return 0
  return Math.round((planRun.value.passed_items / planRun.value.total_items) * 100)
})

function getStatusLabel(status: string) {
  return statusMap[status]?.label || status
}

function getStatusType(status: string) {
  return statusMap[status]?.type || 'info'
}

function getTriggerLabel(trigger: string) {
  return triggerMap[trigger] || trigger
}

function getPriorityType(priority: string) {
  return priorityMap[priority] || ''
}

function getPriorityText(priority: string) {
  return priorityTextMap[priority] || priority
}

function formatDuration(start: string | null, end: string | null) {
  if (!start || !end) return '-'
  const ms = parseUTC(end).getTime() - parseUTC(start).getTime()
  if (ms < 1000) return `${ms}ms`
  const seconds = Math.floor(ms / 1000)
  if (seconds < 60) return `${seconds}s`
  const minutes = Math.floor(seconds / 60)
  const remainingSeconds = seconds % 60
  return `${minutes}m ${remainingSeconds}s`
}

function goBack() {
  router.back()
}

function reportStatusLabel(status: string) {
  return reportStatusMap[status]?.label || status
}

function reportStatusType(status: string) {
  return reportStatusMap[status]?.type || 'info'
}

function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

async function loadReport() {
  loading.value = true
  try {
    planRun.value = await getPlanRun(projectId.value, runId.value)
  } catch (err: any) {
    ElMessage.error(err?.message || '加载执行报告失败')
  } finally {
    loading.value = false
  }
}

async function loadReports() {
  try {
    reports.value = await listPlanRunReports(projectId.value, runId.value)
  } catch {
    // 报告列表加载失败不阻断主流程
  }
}

async function generateReport() {
  generating.value = true
  try {
    await createReport(projectId.value, { report_type: 'html', plan_run_id: runId.value })
    ElMessage.success('报告已生成')
    await loadReports()
  } catch (err: any) {
    ElMessage.error(err?.message || '生成报告失败')
  } finally {
    generating.value = false
  }
}

async function downloadReport(report: ReportFile) {
  if (!report.download_url) {
    ElMessage.warning('报告文件不可用')
    return
  }
  downloadingId.value = report.id
  try {
    // download_url 是二进制响应，不走统一 {code,data} 包装，
    // 故绕过 axios 拦截器，直接用 fetch 带 token 取回 blob 后新窗口打开。
    const token = localStorage.getItem('access_token')
    const resp = await fetch(report.download_url, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    const blob = await resp.blob()
    const url = URL.createObjectURL(blob)
    window.open(url, '_blank')
    setTimeout(() => URL.revokeObjectURL(url), 60000)
  } catch (err: any) {
    ElMessage.error(err?.message || '打开报告失败')
  } finally {
    downloadingId.value = null
  }
}

async function removeReport(report: ReportFile) {
  try {
    await deleteReport(projectId.value, report.id)
    ElMessage.success('报告已删除')
    await loadReports()
  } catch (err: any) {
    ElMessage.error(err?.message || '删除报告失败')
  }
}

onMounted(() => {
  loadReport()
  loadReports()
})
</script>

<style scoped>
.plan-run-report {
  padding: 20px;
  background: #f5f7fa;
  min-height: calc(100vh - 60px);
}

.page-title {
  font-size: 18px;
  font-weight: 600;
}

.loading-container {
  padding: 40px;
  background: white;
  border-radius: 4px;
  margin-top: 20px;
}

.report-content {
  margin-top: 20px;
}

.summary-card {
  margin-bottom: 20px;
}

.summary-header {
  margin-bottom: 16px;
}

.summary-title {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 12px;
}

.summary-title h3 {
  margin: 0;
  font-size: 20px;
  color: #303133;
}

.summary-meta {
  display: flex;
  gap: 24px;
  font-size: 14px;
  color: #606266;
}

.reports-card {
  margin-bottom: 20px;
}

.items-card {
  margin-bottom: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.execution-detail-panel {
  padding: 16px;
  background: #f7f8fa;
}

/* 代码用例执行面板 */
.code-execution-panel .detail-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.code-execution-panel .execution-summary {
  background: white;
  padding: 12px;
  border-radius: 4px;
}

.code-execution-panel .error-section {
  background: white;
  padding: 0 12px;
  border-radius: 4px;
}

.code-execution-panel .logs-section {
  background: white;
  padding: 12px;
  border-radius: 4px;
}

.code-execution-panel .section-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 12px;
}

.code-execution-panel .log-size {
  font-family: monospace;
  font-weight: 400;
}

.code-execution-panel .log-view {
  background: #1e1e1e;
  color: #d4d4d4;
  border: 1px solid #ebeef5;
  border-radius: 4px;
  padding: 12px;
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
  font-size: 12px;
  line-height: 1.6;
  max-height: 420px;
  overflow: auto;
  margin: 0;
  white-space: pre-wrap;
  word-wrap: break-word;
}
</style>
