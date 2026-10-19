<template>
  <div class="report-center-view">
    <!-- Page Header -->
    <div class="page-head">
      <h1>📊 测试报告</h1>
      <div class="actions">
        <el-button @click="showGuideDialog = true">📖 使用说明</el-button>
      </div>
    </div>

    <!-- Quick Stats -->
    <div class="stats-cards">
      <div class="stat-card">
        <div class="stat-label">总报告数</div>
        <div class="stat-value">{{ totalReports }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">近7天</div>
        <div class="stat-value">{{ recentReports }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">平均通过率</div>
        <div class="stat-value">{{ avgPassRate }}%</div>
      </div>
    </div>

    <!-- Filters -->
    <div class="toolbar">
      <el-input
        v-model="searchKeyword"
        placeholder="🔍 搜索报告..."
        clearable
        style="width: 300px"
        @change="loadReports"
      >
        <template #append>
          <el-button :icon="Search" @click="loadReports" />
        </template>
      </el-input>
      <el-select
        v-model="filterType"
        placeholder="报告类型"
        style="width: 150px"
        @change="loadReports"
      >
        <el-option label="全部类型" :value="null as any" />
        <el-option label="HTML报告" value="html" />
        <el-option label="PDF报告" value="pdf" />
      </el-select>
      <el-date-picker
        v-model="dateRange"
        type="daterange"
        range-separator="至"
        start-placeholder="开始日期"
        end-placeholder="结束日期"
        style="width: 300px"
        @change="loadReports"
      />
    </div>

    <!-- Reports Table -->
    <el-table
      :data="reports"
      v-loading="loading"
      style="width: 100%"
      @row-click="handleRowClick"
    >
      <el-table-column prop="id" label="报告ID" width="80" />
      <el-table-column prop="report_type" label="类型" width="100">
        <template #default="{ row }">
          <el-tag size="small" type="info">{{ row.report_type.toUpperCase() }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="关联对象" min-width="200">
        <template #default="{ row }">
          <div class="report-target">
            <strong v-if="row.plan_run_id">测试计划运行 #{{ row.plan_run_id }}</strong>
            <strong v-else-if="row.execution_id">用例执行 #{{ row.execution_id }}</strong>
            <strong v-else>未关联</strong>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="file_size" label="大小" width="100">
        <template #default="{ row }">
          {{ formatFileSize(row.file_size) }}
        </template>
      </el-table-column>
      <el-table-column prop="status" label="状态" width="100">
        <template #default="{ row }">
          <el-tag
            :type="statusType(row.status)"
            size="small"
          >
            {{ statusLabel(row.status) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="生成时间" width="160">
        <template #default="{ row }">
          {{ formatTime(row.created_at) }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="150" fixed="right">
        <template #default="{ row }">
          <el-button
            v-if="row.status === 'generated'"
            link
            type="primary"
            size="small"
            @click.stop="handleDownload(row as ReportFile)"
          >
            下载
          </el-button>
          <el-button
            link
            type="danger"
            size="small"
            @click.stop="handleDelete(row as ReportFile)"
          >
            删除
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- Pagination -->
    <el-pagination
      v-if="totalReports > pageSize"
      v-model:current-page="currentPage"
      :page-size="pageSize"
      :total="totalReports"
      layout="total, prev, pager, next"
      style="margin-top: 20px; text-align: right"
      @current-change="loadReports"
    />

    <!-- Guide Dialog -->
    <el-dialog v-model="showGuideDialog" title="📊 测试报告中心使用说明" width="680px">
      <div class="usage-guide">
        <section>
          <h4>📌 什么是测试报告中心？</h4>
          <p>
            测试报告中心是<strong>所有测试报告的统一入口</strong>。
            聚合展示测试计划、自动化用例、性能测试的报告，支持筛选、下载、删除。
          </p>
        </section>

        <section>
          <h4>🚀 快速开始</h4>
          <ol>
            <li><strong>查看报告列表</strong>：所有已生成的报告按时间倒序展示</li>
            <li><strong>筛选报告</strong>：按类型、日期范围筛选</li>
            <li><strong>下载报告</strong>：点击"下载"按钮获取 HTML/PDF 报告文件</li>
            <li><strong>删除报告</strong>：删除不再需要的报告释放存储空间</li>
          </ol>
        </section>

        <section>
          <h4>✨ 报告类型</h4>
          <ul>
            <li><strong>测试计划报告</strong>：计划运行的汇总报告（用例通过率、执行时长、失败明细）</li>
            <li><strong>自动化用例报告</strong>：单个用例执行的详细报告（步骤、断言、提取变量）</li>
            <li><strong>性能测试报告</strong>：性能压测的指标报告（TPS、响应时间、错误率）</li>
          </ul>
        </section>

        <section>
          <h4>💡 最佳实践</h4>
          <ul>
            <li>定期清理超过保留期（默认90天）的报告</li>
            <li>重要报告可手动下载到本地归档</li>
            <li>通过筛选快速定位特定时间段或类型的报告</li>
          </ul>
        </section>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search } from '@element-plus/icons-vue'
import { useProjectStore } from '@/stores/project'
import { reportApi } from '@/api/report'
import type { ReportFile } from '@/types/report'
import dayjs from 'dayjs'

const projectStore = useProjectStore()
const projectId = computed(() => projectStore.currentProjectId)

// State
const loading = ref(false)
const showGuideDialog = ref(false)
const reports = ref<ReportFile[]>([])
const totalReports = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)
const searchKeyword = ref('')
const filterType = ref<string | null>(null)
const dateRange = ref<[Date, Date] | null>(null)

// Computed stats
const recentReports = computed(() =>
  reports.value.filter(r =>
    dayjs(r.created_at).isAfter(dayjs().subtract(7, 'days'))
  ).length
)

const avgPassRate = computed(() => {
  // This would need additional data from backend
  // For now, return placeholder
  return 0
})

// Methods
const loadReports = async () => {
  if (!projectId.value) return
  loading.value = true
  try {
    const params: any = {
      page: currentPage.value,
      page_size: pageSize.value,
    }

    if (filterType.value) {
      params.report_type = filterType.value
    }

    if (dateRange.value) {
      params.started_from = dateRange.value[0].toISOString()
      params.started_to = dateRange.value[1].toISOString()
    }

    const response = await reportApi.listProjectReports(projectId.value, params)
    reports.value = response.items
    totalReports.value = response.total
  } catch (error: any) {
    ElMessage.error(error.message || '加载报告失败')
  } finally {
    loading.value = false
  }
}

const handleRowClick = (row: ReportFile) => {
  // Navigate to report detail if applicable
  if (row.plan_run_id) {
    // Navigate to plan run report view
    window.open(`/#/${projectStore.currentProject?.code}/plan-runs/${row.plan_run_id}`, '_blank')
  }
}

const handleDownload = async (row: ReportFile) => {
  try {
    await reportApi.downloadReport(projectId.value!, row.id)
    ElMessage.success('报告已开始下载')
  } catch (error: any) {
    ElMessage.error(error.message || '下载失败')
  }
}

const handleDelete = async (row: ReportFile) => {
  try {
    await ElMessageBox.confirm(
      `确定删除报告"${row.id}"？删除后无法恢复。`,
      '确认删除',
      { type: 'warning' }
    )
    await reportApi.deleteReport(projectId.value!, row.id)
    ElMessage.success('删除成功')
    await loadReports()
  } catch (error: any) {
    if (error !== 'cancel') {
      ElMessage.error(error.message || '删除失败')
    }
  }
}

// Helper functions
const statusType = (status: string) => {
  const types: Record<string, any> = {
    pending: 'info',
    generating: 'warning',
    generated: 'success',
    failed: 'danger',
  }
  return types[status] || 'info'
}

const statusLabel = (status: string) => {
  const labels: Record<string, string> = {
    pending: '待生成',
    generating: '生成中',
    generated: '已完成',
    failed: '失败',
  }
  return labels[status] || status
}

const formatFileSize = (bytes: number | null) => {
  if (!bytes) return '-'
  const kb = bytes / 1024
  if (kb < 1024) return `${kb.toFixed(1)} KB`
  const mb = kb / 1024
  return `${mb.toFixed(2)} MB`
}

const formatTime = (time: string) => {
  return dayjs(time).format('YYYY-MM-DD HH:mm:ss')
}

// Lifecycle
onMounted(() => {
  loadReports()
})

// Watch for projectId becoming available (e.g. after store loads)
watch(projectId, (newVal) => {
  if (newVal) {
    loadReports()
  }
})
</script>

<style scoped>
.report-center-view {
  padding: 20px;
}

.page-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.page-head h1 {
  font-size: 24px;
  font-weight: bold;
  margin: 0;
}

.page-head .actions {
  display: flex;
  gap: 10px;
}

.stats-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 16px;
  margin-bottom: 20px;
}

.stat-card {
  background: white;
  border-radius: 8px;
  padding: 16px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

.stat-label {
  font-size: 14px;
  color: #666;
  margin-bottom: 8px;
}

.stat-value {
  font-size: 28px;
  font-weight: bold;
  color: #409eff;
}

.toolbar {
  display: flex;
  gap: 10px;
  margin-bottom: 20px;
}

.report-target strong {
  font-size: 14px;
}

.usage-guide section {
  margin-bottom: 24px;
}

.usage-guide h4 {
  font-size: 16px;
  font-weight: bold;
  margin-bottom: 12px;
  color: #333;
}

.usage-guide p,
.usage-guide li {
  font-size: 14px;
  line-height: 1.6;
  color: #666;
}

.usage-guide ol,
.usage-guide ul {
  margin: 8px 0;
  padding-left: 24px;
}

.usage-guide li {
  margin-bottom: 8px;
}
</style>
