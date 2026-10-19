<template>
  <div class="dashboard-view" v-loading="loading">
    <div class="page-head">
      <h1><el-icon><HomeFilled /></el-icon>项目工作台</h1>
      <div class="actions">
        <el-button type="primary" @click="navigateTo('code-cases')">
          <el-icon><Plus /></el-icon>新建代码用例
        </el-button>
      </div>
    </div>

    <div class="stat-row">
      <button class="stat-card s-code" type="button" @click="navigateTo('code-cases')">
        <div class="stat-icon"><el-icon><Cpu /></el-icon></div>
        <div class="sv">{{ summary.code_case_count }}</div>
        <div class="sl">代码用例</div>
        <div class="sd code">本周新增 {{ summary.code_case_weekly_added }} 条</div>
      </button>
      <button class="stat-card s-info" type="button" @click="navigateTo('test-plans')">
        <div class="stat-icon"><el-icon><List /></el-icon></div>
        <div class="sv">{{ summary.test_plan_count }}</div>
        <div class="sl">测试计划</div>
        <div class="sd info">累计执行 {{ summary.execution_count }} 次</div>
      </button>
      <button class="stat-card s-warn" type="button" @click="navigateTo('schedules')">
        <div class="stat-icon"><el-icon><Clock /></el-icon></div>
        <div class="sv">{{ scheduleCount }}</div>
        <div class="sl">定时任务</div>
        <div class="sd warning">已启用的计划调度</div>
      </button>
      <button class="stat-card s-rate" type="button" @click="navigateTo('reports')">
        <div class="stat-icon"><el-icon><TrendCharts /></el-icon></div>
        <div class="sv">{{ passRateText }}</div>
        <div class="sl">最近通过率</div>
        <div class="sd danger">最近 {{ summary.completed_execution_count }} 次有效执行</div>
      </button>
    </div>

    <section class="overview-band">
      <div class="section-heading">
        <div>
          <h2>项目资产</h2>
          <p>当前项目已沉淀的代码用例测试资产</p>
        </div>
      </div>
      <div class="asset-grid">
        <button type="button" class="asset-item" @click="navigateTo('code-cases')">
          <span class="asset-mark code"><el-icon><Cpu /></el-icon></span>
          <span class="asset-copy"><b>{{ summary.code_case_count }}</b><small>代码用例</small></span>
          <el-icon class="asset-arrow"><ArrowRight /></el-icon>
        </button>
        <button type="button" class="asset-item" @click="navigateTo('test-plans')">
          <span class="asset-mark plan"><el-icon><List /></el-icon></span>
          <span class="asset-copy"><b>{{ summary.test_plan_count }}</b><small>测试计划</small></span>
          <el-icon class="asset-arrow"><ArrowRight /></el-icon>
        </button>
        <button type="button" class="asset-item" @click="navigateTo('schedules')">
          <span class="asset-mark schedule"><el-icon><Clock /></el-icon></span>
          <span class="asset-copy"><b>{{ scheduleCount }}</b><small>定时任务</small></span>
          <el-icon class="asset-arrow"><ArrowRight /></el-icon>
        </button>
        <button type="button" class="asset-item" @click="navigateTo('reports')">
          <span class="asset-mark report"><el-icon><Document /></el-icon></span>
          <span class="asset-copy"><b>{{ reportCount }}</b><small>测试报告</small></span>
          <el-icon class="asset-arrow"><ArrowRight /></el-icon>
        </button>
      </div>
    </section>

    <section class="recent-panel">
      <div class="section-heading compact">
        <div>
          <h2>最近代码用例执行</h2>
          <p>展示当前项目最近提交的代码用例执行</p>
        </div>
        <el-button text type="primary" @click="navigateTo('code-cases')">查看用例</el-button>
      </div>
      <div v-if="summary.recent_executions.length" class="execution-table-wrap">
        <table class="execution-table">
          <thead>
            <tr><th>用例</th><th>模块</th><th>级别</th><th>耗时</th><th>时间</th><th>结果</th></tr>
          </thead>
          <tbody>
            <tr v-for="item in summary.recent_executions" :key="item.id">
              <td><span class="case-name">{{ item.case_name }}</span></td>
              <td>{{ item.module || '--' }}</td>
              <td>{{ item.level || '--' }}</td>
              <td>{{ formatDuration(item.duration_ms) }}</td>
              <td>{{ formatDateTimeShort(item.created_at) }}</td>
              <td><span class="status-dot" :class="statusClass(item.status)">{{ statusLabel(item.status) }}</span></td>
            </tr>
          </tbody>
        </table>
      </div>
      <el-empty v-else description="暂无执行记录" :image-size="72" />
    </section>

    <section class="recent-panel">
      <div class="section-heading compact">
        <div>
          <h2>最近测试计划执行</h2>
          <p>展示当前项目最近提交的测试计划执行</p>
        </div>
        <el-button text type="primary" @click="navigateTo('test-plans')">查看计划</el-button>
      </div>
      <div v-if="summary.recent_plan_runs.length" class="execution-table-wrap">
        <table class="execution-table">
          <thead>
            <tr><th>计划运行</th><th>用例总数</th><th>通过</th><th>失败</th><th>时间</th><th>结果</th></tr>
          </thead>
          <tbody>
            <tr v-for="run in summary.recent_plan_runs" :key="run.id">
              <td>
                <span class="plan-run-link" @click="navigateToPlanRun(run.id)">#{{ run.id }}</span>
              </td>
              <td>{{ run.total_items }}</td>
              <td>{{ run.passed_items }}</td>
              <td>{{ run.failed_items }}</td>
              <td>{{ formatDateTimeShort(run.started_at || run.finished_at) }}</td>
              <td><span class="status-dot" :class="statusClass(run.status)">{{ statusLabel(run.status) }}</span></td>
            </tr>
          </tbody>
        </table>
      </div>
      <el-empty v-else description="暂无计划执行记录" :image-size="72" />
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  ArrowRight,
  Clock,
  Cpu,
  Document,
  HomeFilled,
  List,
  Plus,
  TrendCharts,
} from '@element-plus/icons-vue'
import { projectApi, type ProjectSummary } from '@/api/project'
import { listSchedules } from '@/api/test-plan'
import { reportApi } from '@/api/report'
import { useProjectStore } from '@/stores/project'
import { formatDateTimeShort } from '@/utils/datetime'

const emptySummary = (): ProjectSummary => ({
  code_case_count: 0,
  code_case_weekly_added: 0,
  test_plan_count: 0,
  environment_count: 0,
  execution_count: 0,
  completed_execution_count: 0,
  passed_execution_count: 0,
  recent_pass_rate: 0,
  recent_executions: [],
  recent_plan_runs: [],
})

const router = useRouter()
const route = useRoute()
const projectStore = useProjectStore()
const loading = ref(false)
const summary = ref<ProjectSummary>(emptySummary())
const scheduleCount = ref(0)
const reportCount = ref(0)
const projectId = computed(() => projectStore.currentProjectId)
const passRateText = computed(() => summary.value.completed_execution_count
  ? `${summary.value.recent_pass_rate}%`
  : '--')

async function loadSummary(id: number) {
  loading.value = true
  try {
    summary.value = await projectApi.summary(id)
  } catch {
    summary.value = emptySummary()
    ElMessage.error('加载工作台数据失败')
  } finally {
    loading.value = false
  }
}

async function loadScheduleCount(id: number) {
  try {
    const schedules = await listSchedules(id)
    scheduleCount.value = schedules.length
  } catch {
    scheduleCount.value = 0
  }
}

async function loadReportCount(id: number) {
  try {
    const res = await reportApi.listProjectReports(id, { page: 1, page_size: 1 })
    reportCount.value = res.total ?? 0
  } catch {
    reportCount.value = 0
  }
}

function navigateTo(view: string) {
  router.push(`/${String(route.params.projectCode)}/${view}`)
}

function navigateToPlanRun(runId: number) {
  router.push(`/${String(route.params.projectCode)}/plan-runs/${runId}`)
}

function formatDuration(ms: number | null) {
  if (ms == null) return '--'
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

function statusLabel(status: string) {
  return ({ pending: '等待中', queued: '排队中', running: '执行中', passed: '通过', failed: '失败', error: '错误', timeout: '超时', cancelled: '已取消', canceled: '已取消' } as Record<string, string>)[status] || status
}

function statusClass(status: string) {
  if (status === 'passed') return 'st-pass'
  if (status === 'failed' || status === 'error' || status === 'timeout') return 'st-fail'
  if (status === 'running') return 'st-run'
  if (status === 'pending' || status === 'queued') return 'st-warn'
  return 'st-skip'
}

watch(projectId, (id) => {
  if (id) {
    loadSummary(id)
    loadScheduleCount(id)
    loadReportCount(id)
  }
}, { immediate: true })
</script>

<style scoped>
.dashboard-view { min-height: 100%; }
.page-head { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 16px; }
.page-head h1 { display: flex; align-items: center; gap: 8px; margin: 0; font-size: 18px; color: var(--txt); }
.page-head h1 .el-icon { color: var(--primary); }
.stat-row { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; margin-bottom: 16px; }
.stat-card { position: relative; min-height: 130px; padding: 18px 20px; text-align: left; background: var(--card); border: 1px solid var(--line); border-radius: var(--r2); box-shadow: var(--shadow); cursor: pointer; transition: transform .15s, border-color .15s, box-shadow .15s; }
.stat-card:hover { transform: translateY(-1px); border-color: #BFD2FA; box-shadow: var(--shadow2); }
.stat-icon { position: absolute; top: 18px; right: 18px; width: 34px; height: 34px; display: grid; place-items: center; border-radius: 8px; font-size: 17px; }
.s-code .stat-icon { color: #7c3aed; background: #ede9fe; }
.s-info .stat-icon { color: var(--info); background: var(--info-bg); }
.s-warn .stat-icon { color: var(--warn); background: var(--warn-bg); }
.s-rate .stat-icon { color: var(--err); background: var(--err-bg); }
.sv { font-size: 28px; font-weight: 700; line-height: 1; color: var(--txt); }
.s-code .sv { color: #7c3aed; }
.s-info .sv { color: var(--info); }
.s-warn .sv { color: var(--warn); }
.s-rate .sv { color: var(--err); }
.sl { margin-top: 8px; font-size: 12px; color: var(--txt2); }
.sd { margin-top: 10px; font-size: 11px; }
.sd.info { color: var(--info); } .sd.warning { color: var(--warn); } .sd.danger { color: var(--err); } .sd.code { color: #7c3aed; }
.overview-band, .recent-panel { padding: 20px; background: var(--card); border: 1px solid var(--line); border-radius: var(--r2); box-shadow: var(--shadow); }
.overview-band, .recent-panel { margin-bottom: 16px; }
.section-heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 16px; }
.section-heading.compact { margin-bottom: 10px; }
.section-heading h2 { margin: 0; font-size: 15px; color: var(--txt); }
.section-heading p { margin: 4px 0 0; font-size: 12px; color: var(--txt3); }
.asset-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); border: 1px solid var(--line); border-radius: var(--r); overflow: hidden; }
.asset-item { display: flex; align-items: center; gap: 12px; min-width: 0; padding: 16px; background: #fff; border: 0; border-right: 1px solid var(--line); cursor: pointer; text-align: left; }
.asset-item:last-child { border-right: 0; }
.asset-item:hover { background: var(--line2); }
.asset-mark { width: 36px; height: 36px; flex: 0 0 36px; display: grid; place-items: center; border-radius: 8px; }
.asset-mark.code { color: #7c3aed; background: #ede9fe; }
.asset-mark.plan { color: var(--info); background: var(--info-bg); }
.asset-mark.schedule { color: var(--warn); background: var(--warn-bg); }
.asset-mark.report { color: var(--success); background: var(--success-bg); }
.asset-copy { min-width: 0; display: flex; flex-direction: column; }
.asset-copy b { font-size: 18px; color: var(--txt); }
.asset-copy small { margin-top: 2px; color: var(--txt2); font-size: 11px; }
.asset-arrow { margin-left: auto; color: var(--txt3); }
.execution-table-wrap { overflow-x: auto; }
.execution-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.execution-table th { padding: 10px 12px; text-align: left; color: var(--txt3); background: #F8FAFC; border-bottom: 1px solid var(--line); font-weight: 600; white-space: nowrap; }
.execution-table td { padding: 12px; color: var(--txt2); border-bottom: 1px solid var(--line2); white-space: nowrap; }
.execution-table tbody tr:last-child td { border-bottom: 0; }
.execution-table tbody tr:hover { background: #FAFCFF; }
.case-name { display: block; max-width: 260px; overflow: hidden; text-overflow: ellipsis; color: var(--txt); font-weight: 600; }
.plan-run-link { color: var(--primary); cursor: pointer; font-weight: 600; }
.status-dot { padding: 2px 10px; font-size: 11px; border-radius: 10px; }
.status-dot.st-pass { color: var(--success); background: var(--success-bg); }
.status-dot.st-fail { color: var(--err); background: var(--err-bg); }
.status-dot.st-run { color: var(--info); background: var(--info-bg); }
.status-dot.st-warn { color: var(--warn); background: var(--warn-bg); }
.status-dot.st-skip { color: var(--txt3); background: #F1F5F9; }
@media (max-width: 1280px) { .stat-row { grid-template-columns: repeat(2, minmax(0, 1fr)); } .asset-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .asset-item:nth-child(2n) { border-right: 0; } .asset-item:nth-child(-n+2) { border-bottom: 1px solid var(--line); } }
@media (max-width: 720px) { .stat-row { grid-template-columns: 1fr; } .asset-grid { grid-template-columns: 1fr; } .asset-item { border-right: 0; border-bottom: 1px solid var(--line); } .asset-item:last-child { border-bottom: 0; } .page-head { align-items: flex-start; } }
</style>
