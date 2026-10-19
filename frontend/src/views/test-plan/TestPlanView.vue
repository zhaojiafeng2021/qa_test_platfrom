<template>
  <div class="plan-page" v-loading="loading">
    <div class="page-head">
      <h1><el-icon><Aim /></el-icon>测试计划</h1>
      <div class="actions">
        <el-button v-if="canCreate" type="primary" :icon="Plus" @click="openEditor()">新建计划</el-button>
      </div>
    </div>

    <div class="plan-layout">
      <div class="list-toolbar">
        <h3>测试计划</h3>
        <el-segmented v-model="filter" :options="filterOptions" size="small" />
      </div>
      <el-table
        :data="visiblePlans"
        :show-header="true"
        class="plan-table"
        empty-text="暂无测试计划"
        @row-click="selectPlan"
      >
        <el-table-column label="计划名称" min-width="200">
          <template #default="scope">
            <div class="plan-name">{{ scope.row.name }}</div>
            <div class="plan-meta">{{ ownerName(scope.row.owner_id) }} · {{ dueText(scope.row.due_date) }}</div>
          </template>
        </el-table-column>
        <el-table-column label="用例数" width="80" align="center">
          <template #default="scope">{{ scope.row.items.length }}</template>
        </el-table-column>
        <el-table-column label="创建人" width="90">
          <template #default="scope">
            <span style="font-size:12px;color:var(--txt3)">{{ scope.row.created_by_name || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="140" show-overflow-tooltip>
          <template #default="scope">
            <span style="font-size:12px;color:var(--txt3)">{{ formatTime(scope.row.created_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="scope">
            <span :class="['status-dot', statusClass(latestRun(scope.row.id)?.status)]">
              {{ planStatusText(scope.row.id) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="240" align="center" fixed="right">
          <template #default="scope">
            <el-button link type="primary" size="small" @click.stop="selectPlan(scope.row as any)">查看</el-button>
            <el-button link type="primary" size="small" @click.stop="openEditor(scope.row as any)">编辑</el-button>
            <el-button link type="primary" size="small" @click.stop="selectPlan(scope.row as any); openRunDialog()">执行</el-button>
            <el-button link type="primary" size="small" @click.stop="selectPlan(scope.row as any); openReport()">报告</el-button>
            <el-button v-if="canDelete" link type="danger" size="small" @click.stop="handleDeletePlan(scope.row as any)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 计划详情抽屉 -->
    <el-drawer v-model="detailVisible" :title="selected?.name || '计划详情'" size="70%" direction="rtl" destroy-on-close>
      <template v-if="selected">
        <div class="drawer-summary">
          <div class="summary-item">
            <span class="label">用例数</span>
            <span class="value">{{ selected.items.length }}</span>
          </div>
          <div class="summary-item">
            <span class="label">通过率</span>
            <span class="value">{{ passRate(latestRun(selected.id)) }}</span>
          </div>
          <div class="summary-item">
            <span class="label">负责人</span>
            <span class="value">{{ ownerName(selected.owner_id) }}</span>
          </div>
          <div class="summary-item">
            <span class="label">截止日期</span>
            <span class="value">{{ dueText(selected.due_date) }}</span>
          </div>
        </div>

        <div class="drawer-actions">
          <el-button :icon="DataAnalysis" :disabled="!planHasRuns(selected.id)" @click="openReport()">查看报告</el-button>
          <el-button v-if="canUpdate" :icon="Edit" @click="openEditor(selected)">编辑</el-button>
          <el-button v-if="canCreate" :icon="Plus" @click="openEditor(selected, true)">添加用例</el-button>
          <el-button v-if="canUpdate" :icon="RefreshRight" @click="handleSyncVersions">同步到最新版本</el-button>
          <el-button v-if="canExecute" type="primary" :icon="VideoPlay" :disabled="!selected.items.length" @click="openRunDialog">执行计划</el-button>
          <el-button v-if="canDelete" type="danger" :icon="Delete" @click="handleDeletePlan(selected!)">删除计划</el-button>
        </div>

        <el-tabs v-model="drawerActiveTab" class="drawer-tabs">
          <el-tab-pane label="包含用例" name="cases">
            <el-table :data="selected.items" class="case-table" empty-text="计划中暂无用例" max-height="500">
              <el-table-column label="用例名称" min-width="210">
                <template #default="scope">
                  <div class="case-name">
                    <el-tag v-if="scope.row.case_type === 'code'" size="small" type="success" style="margin-right:6px">代码</el-tag>
                    {{ scope.row.case_name || codeCaseInfo(scope.row.case_id)?.name || `代码用例 #${scope.row.case_id}` }}
                  </div>
                  <div class="case-version">{{ scope.row.module || '代码用例' }}</div>
                </template>
              </el-table-column>
              <el-table-column label="步骤数" width="80" align="center">
                <template #default="scope">{{ scope.row.step_count ?? '—' }}</template>
              </el-table-column>
              <el-table-column label="优先级" width="90">
                <template #default="scope"><span :class="['priority', priorityClass(scope.row.priority)]">{{ priorityText(scope.row.priority) }}</span></template>
              </el-table-column>
              <el-table-column label="最近结果" width="110">
                <template #default="scope">
                  <span :class="['status-dot', statusClass(runItem(scope.row.case_id)?.status)]">{{ runStatusText(runItem(scope.row.case_id)?.status) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="80" align="center">
                <template #default="scope"><el-button link type="primary" @click.stop="removeCase(scope.row.case_id)">移除</el-button></template>
              </el-table-column>
            </el-table>
          </el-tab-pane>

          <el-tab-pane name="history">
            <template #label>
              <span>执行历史 <el-badge v-if="planRunsCount(selected.id)" :value="planRunsCount(selected.id)" :max="99" /></span>
            </template>
            <div class="history-toolbar">
              <el-segmented v-model="historyFilter" :options="historyFilterOptions" size="small" />
              <el-button link :icon="RefreshRight" @click="refreshRuns">刷新</el-button>
            </div>
            <el-scrollbar max-height="500px">
              <el-table :data="filteredPlanRuns" class="history-table" @row-click="viewRunDetail">
                <el-table-column label="运行 ID" width="90">
                  <template #default="scope"><span class="run-id">#{{ scope.row.id }}</span></template>
                </el-table-column>
                <el-table-column label="触发方式" width="100">
                  <template #default="scope">{{ triggerText(scope.row.trigger_type) }}</template>
                </el-table-column>
                <el-table-column label="状态" width="100">
                  <template #default="scope">
                    <span :class="['status-dot', statusClass(scope.row.status)]">{{ runStatusText(scope.row.status) }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="通过率" width="90">
                  <template #default="scope">{{ passRate(scope.row as PlanRun) }}</template>
                </el-table-column>
                <el-table-column label="用例数" width="90">
                  <template #default="scope">{{ scope.row.total_items }}</template>
                </el-table-column>
                <el-table-column label="完成时间" min-width="140">
                  <template #default="scope">{{ formatTime(scope.row.finished_at || scope.row.created_at) }}</template>
                </el-table-column>
                <el-table-column label="操作" width="100" align="center" fixed="right">
                  <template #default="scope">
                    <el-button
                      v-if="scope.row.status === 'running' || scope.row.status === 'pending'"
                      link
                      type="danger"
                      size="small"
                      @click.stop="handleCancelRun(scope.row)"
                    >
                      停止
                    </el-button>
                    <span v-else style="color: var(--txt4); font-size: 12px;">—</span>
                  </template>
                </el-table-column>
              </el-table>
              <el-empty v-if="!filteredPlanRuns.length" :image-size="80" description="暂无执行记录" />
            </el-scrollbar>
          </el-tab-pane>

          <el-tab-pane label="计划配置" name="config">
            <div class="config-section">
              <el-descriptions :column="2" border>
                <el-descriptions-item label="计划名称">{{ selected.name }}</el-descriptions-item>
                <el-descriptions-item label="状态">
                  <el-tag :type="selected.status === 'active' ? 'success' : 'info'">{{ selected.status === 'active' ? '活跃' : '已完成' }}</el-tag>
                </el-descriptions-item>
                <el-descriptions-item label="负责人">{{ ownerName(selected.owner_id) }}</el-descriptions-item>
                <el-descriptions-item label="截止日期">{{ selected.due_date || '未设置' }}</el-descriptions-item>
                <el-descriptions-item label="失败策略">
                  {{ selected.failure_strategy === 'continue' ? '继续执行' : '遇错停止' }}
                </el-descriptions-item>
                <el-descriptions-item label="创建时间">{{ formatTime(selected.created_at) }}</el-descriptions-item>
                <el-descriptions-item label="更新时间" :span="2">{{ formatTime(selected.updated_at) }}</el-descriptions-item>
                <el-descriptions-item label="描述" :span="2">
                  <span style="color: var(--txt3)">{{ selected.description || '无描述' }}</span>
                </el-descriptions-item>
              </el-descriptions>
            </div>
          </el-tab-pane>
        </el-tabs>
      </template>
    </el-drawer>

    <el-dialog v-model="editorVisible" :title="editingId ? '编辑测试计划' : '新建测试计划'" width="700px" class="plan-dialog" destroy-on-close>
      <el-form label-position="top">
        <el-form-item label="计划名称" required><el-input v-model="form.name" placeholder="例如：v1.2.3 支付回归" /></el-form-item>
        <div class="form-grid">
          <el-form-item label="负责人">
            <el-select v-model="form.owner_id" clearable filterable placeholder="选择负责人">
              <el-option v-for="member in members" :key="member.user_id" :label="memberLabel(member)" :value="member.user_id" />
            </el-select>
          </el-form-item>
          <el-form-item label="截止日期"><el-date-picker v-model="form.due_date" value-format="YYYY-MM-DD" type="date" /></el-form-item>
        </div>

        <!-- 通知规则选择 -->
        <el-form-item label="通知规则">
          <el-select
            v-model="form.notification_rule_ids"
            multiple
            clearable
            filterable
            placeholder="选择通知规则（可选多个）"
            style="width: 100%"
          >
            <el-option
              v-for="rule in notificationRules"
              :key="rule.id"
              :label="rule.name"
              :value="rule.id"
            >
              <span>{{ rule.name }}</span>
              <span class="option-note">{{ eventTypeText(rule.event_type) }} → {{ recipientTypeText(rule.recipient_type) }}</span>
            </el-option>
          </el-select>
          <div class="tip">
            选择此测试计划执行时触发的通知规则。规则需要在
            <a @click="goToNotification" style="color: #409EFF; cursor: pointer;">飞书通知中心</a>
            创建和管理。
          </div>
        </el-form-item>

        <el-form-item label="描述"><el-input v-model="form.description" type="textarea" :rows="3" placeholder="计划的测试范围与目标" /></el-form-item>
        <el-form-item label="包含代码用例">
          <div class="case-picker code-case-tree">
            <el-tree
              v-if="visibleCodeModuleTree.length"
              :data="visibleCodeModuleTree"
              node-key="id"
              :props="{ label: 'name', children: 'children' }"
              :expand-on-click-node="false"
              highlight-current
              @node-click="handleModuleNodeClick"
            >
              <template #default="{ data }">
                <span class="tree-node-label">
                  <span>{{ data.name }}</span>
                  <el-tag size="small" type="info">{{ data.total_case_count }}</el-tag>
                </span>
              </template>
            </el-tree>
            <!-- 层级全被剪掉时左栏会空白，给个说明避免看起来像加载失败 -->
            <div v-else class="tree-empty-hint">暂无包含用例的层级</div>
            <div class="code-case-list" v-if="filteredCodeCases.length">
              <el-checkbox-group v-model="form.codeCaseIds">
                <el-checkbox v-for="item in filteredCodeCases" :key="item.id" :value="item.id" class="case-option">
                  <span class="case-option-text">
                    <b :title="item.name">{{ item.name }}</b>
                    <small>{{ item.level }} · {{ item.module || '未分类' }}</small>
                  </span>
                </el-checkbox>
              </el-checkbox-group>
            </div>
            <el-empty v-else-if="!codeCases.length" :image-size="48" description="暂无代码用例，请先在代码用例页扫描" />
            <el-empty v-else :image-size="48" description="该模块下暂无用例" />
          </div>
        </el-form-item>
      </el-form>
      <template #footer><el-button @click="editorVisible = false">取消</el-button><el-button type="primary" :loading="saving" @click="save">保存计划</el-button></template>
    </el-dialog>

    <el-dialog v-model="runVisible" title="执行测试计划" width="600px" class="plan-dialog">
      <div class="run-summary">计划：<b>{{ selected?.name }}</b> · 共 <b>{{ selected?.items.length || 0 }}</b> 个用例</div>
      <el-form label-position="top">
        <el-form-item label="失败策略">
          <el-radio-group v-model="runForm.failure_strategy"><el-radio value="continue">继续执行</el-radio><el-radio value="stop">遇错停止</el-radio></el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer><el-button @click="runVisible = false">取消</el-button><el-button type="primary" :loading="executing" @click="execute">立即执行</el-button></template>
    </el-dialog>

    <el-dialog v-model="reportVisible" :title="`执行报告 · ${selected?.name || ''}`" width="1040px" class="report-dialog" @open="loadPlanRunHistory">
      <div class="report-body">
        <aside class="run-history" v-loading="historyLoading">
          <div class="run-history-head">
            <span>执行历史</span>
            <el-button link type="primary" :icon="RefreshRight" @click="loadPlanRunHistory" />
          </div>
          <el-scrollbar max-height="440px">
            <ul class="run-history-list">
              <li
                v-for="run in planRunHistory"
                :key="run.id"
                :class="['run-history-item', { active: reportRun?.id === run.id, running: run.status === 'pending' || run.status === 'running' }]"
                @click="selectHistoryRun(run)"
              >
                <div class="rh-top">
                  <b>#{{ run.id }}</b>
                  <span :class="['status-dot', statusClass(run.status)]">{{ runStatusText(run.status) }}</span>
                </div>
                <div class="rh-meta">
                  <span>{{ triggerText(run.trigger_type) }}</span>
                  <span>{{ passRate(run) }}</span>
                </div>
                <div class="rh-time">{{ formatTime(run.finished_at || run.created_at) }}</div>
              </li>
            </ul>
            <el-empty v-if="!planRunHistory.length && !historyLoading" :image-size="48" description="暂无执行记录" />
          </el-scrollbar>
        </aside>

        <div class="report-main">
      <template v-if="reportRun">
        <div class="report-meta">
          <div><small>报告 ID</small><b>#{{ reportRun.id }}</b></div>
          <div><small>关联计划</small><b>{{ selected?.name }}</b></div>
          <div><small>完成时间</small><b>{{ formatTime(reportRun.finished_at || reportRun.created_at) }}</b></div>
          <div><small>执行耗时</small><b>{{ runDuration(reportRun) }}</b></div>
        </div>
        <h4 class="section-title">统计概览</h4>
        <div class="report-stats">
          <div><small>总用例数</small><strong>{{ reportRun.total_items }}</strong></div>
          <div class="passed"><small>通过</small><strong>{{ reportRun.passed_items }}</strong></div>
          <div class="failed"><small>失败</small><strong>{{ reportRun.failed_items }}</strong></div>
          <div><small>通过率</small><strong>{{ passRate(reportRun) }}</strong></div>
        </div>
        <div class="report-list-head">
          <h4 class="section-title">用例执行明细</h4>
          <el-segmented v-model="reportFilter" :options="reportFilterOptions" size="small" />
        </div>
        <el-table :data="filteredReportItems" border class="report-table">
          <el-table-column label="用例名称" min-width="210"><template #default="scope">{{ scope.row.case_name || `用例 #${scope.row.case_id}` }}</template></el-table-column>
          <el-table-column label="优先级" width="80"><template #default="scope"><span :class="['priority', priorityClass(scope.row.priority)]">{{ priorityText(scope.row.priority) }}</span></template></el-table-column>
          <el-table-column label="状态" width="90"><template #default="scope"><span :class="['status-dot', statusClass(scope.row.status)]">{{ runStatusText(scope.row.status) }}</span></template></el-table-column>
          <el-table-column label="实际接口步骤" width="130">
            <template #default="scope">{{ scope.row.passed_steps ?? 0 }} 通过 / {{ scope.row.failed_steps ?? 0 }} 失败</template>
          </el-table-column>
          <el-table-column label="耗时" width="90"><template #default="scope">{{ durationText(scope.row.duration_ms) }}</template></el-table-column>
          <el-table-column label="失败原因" min-width="220"><template #default="scope"><span :class="{ 'error-text': scope.row.error_message }">{{ scope.row.error_message || '—' }}</span></template></el-table-column>
        </el-table>
      </template>
      <el-empty v-else description="从左侧选择一次执行查看报告" />
        </div>
      </div>
      <template #footer>
        <el-button @click="reportVisible = false">关闭</el-button>
        <el-button v-if="reportRun" :icon="Document" @click="openFullReport">生成/查看HTML报告</el-button>
        <el-button v-if="canExecute" type="primary" :icon="RefreshRight" @click="rerunFromReport">重新执行</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Aim, DataAnalysis, Delete, Document, Edit, InfoFilled, Plus, RefreshRight, VideoPlay } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useProjectStore } from '@/stores/project'
import { useAuthStore } from '@/stores/auth'
import { usePermission } from '@/composables/usePermission'
import { codeCaseApi, codeModuleApi } from '@/api/code-case'
import { projectApi, type MemberInfo } from '@/api/project'
import { notificationApi } from '@/api/notification'
import * as api from '@/api/test-plan'
import type { CodeCaseListItem, CodeModuleTreeNode } from '@/types/code-case'
import { collectSubtreeIds, pruneEmptyModules } from '@/views/code-case/module-tree'
import type { PlanRun, PlanRunItem, TestPlan } from '@/types/test-plan'
import { formatTime } from '@/utils/format'

const projectStore = useProjectStore()
const authStore = useAuthStore()
const { hasPermission } = usePermission()
const route = useRoute()
const router = useRouter()

// 权限检查
const canCreate = computed(() => hasPermission('asset:create'))
const canUpdate = computed(() => hasPermission('asset:update'))
const canDelete = computed(() => hasPermission('asset:delete'))
const canExecute = computed(() => hasPermission('execution:run'))

const loading = ref(false)
const saving = ref(false)
const executing = ref(false)
const plans = ref<TestPlan[]>([])
const runs = ref<PlanRun[]>([])
const selected = ref<TestPlan>()
const detailVisible = ref(false)
const codeCases = ref<CodeCaseListItem[]>([])
const codeModuleTree = ref<CodeModuleTreeNode[]>([])
const selectedCodeModuleId = ref<number | null>(null)
// 与代码用例页一致：不展示整棵子树都没有有效用例的层级（这里是只读选择树，无需管理空层级）
const visibleCodeModuleTree = computed(() =>
  pruneEmptyModules(codeModuleTree.value, selectedCodeModuleId.value)
)
const filteredCodeCases = computed(() => {
  if (!selectedCodeModuleId.value) return codeCases.value
  // 节点标签显示的是 total_case_count（含子孙），筛选也要含子层级，否则点父级会是空列表
  const ids = collectSubtreeIds(codeModuleTree.value, selectedCodeModuleId.value)
  const idSet = new Set(ids.length ? ids : [selectedCodeModuleId.value])
  return codeCases.value.filter(c => c.module_id !== null && idSet.has(c.module_id))
})
const members = ref<MemberInfo[]>([])
const notificationRules = ref<any[]>([])  // 通知规则列表
const filter = ref('全部')
const editorVisible = ref(false)
const runVisible = ref(false)
const reportVisible = ref(false)
const editingId = ref<number>()
const reportRun = ref<PlanRun>()
const reportFilter = ref('全部')
const planRunHistory = ref<PlanRun[]>([])
const historyLoading = ref(false)
const drawerActiveTab = ref('cases')
const historyFilter = ref('全部')
const historyFilterOptions = ['全部', '进行中', '已完成']
let pollTimer: ReturnType<typeof setInterval> | undefined

const filterOptions = ['全部', '进行中', '已完成']
const reportFilterOptions = ['全部', '通过', '失败']
const terminalStatuses = new Set(['passed', 'failed', 'error', 'cancelled', 'timeout'])
const form = reactive({
  name: '',
  description: '',
  due_date: '',
  owner_id: undefined as number | undefined,
  notification_channel_id: undefined as number | undefined,
  notification_template_code: undefined as string | undefined,
  notification_rule_ids: [] as number[],  // 新增：通知规则ID列表
  codeCaseIds: [] as number[]
})
const runForm = reactive({ failure_strategy: 'continue' })
const pid = computed(() => projectStore.currentProjectId)
const latestRunMap = computed(() => {
  const map = new Map<number, PlanRun>()
  for (const run of runs.value) if (!map.has(run.plan_id)) map.set(run.plan_id, run)
  return map
})
const visiblePlans = computed(() => plans.value.filter(plan => {
  const status = latestRun(plan.id)?.status
  if (filter.value === '进行中') return status === 'pending' || status === 'running'
  if (filter.value === '已完成') return isTerminal(status)
  return true
}))
const filteredReportItems = computed(() => (reportRun.value?.items || []).filter(item => {
  if (reportFilter.value === '通过') return item.status === 'passed'
  if (reportFilter.value === '失败') return item.status !== 'passed'
  return true
}))
const filteredPlanRuns = computed(() => {
  if (!selected.value) return []
  const planRuns = runs.value.filter(run => run.plan_id === selected.value!.id)
  if (historyFilter.value === '进行中') return planRuns.filter(r => r.status === 'pending' || r.status === 'running')
  if (historyFilter.value === '已完成') return planRuns.filter(r => isTerminal(r.status))
  return planRuns
})

watch(pid, id => { if (id) load() }, { immediate: true })
onBeforeUnmount(() => stopPolling())

async function load() {
  if (!pid.value) return
  loading.value = true
  try {
    const [planPage, codeCasePage, codeTreeData, memberPage, runPage, ruleList] = await Promise.all([
      api.listPlans(pid.value, { page_size: 100 }),
      codeCaseApi.list({ page_size: 100, project_id: pid.value }),
      codeModuleApi.getTree(pid.value),
      projectApi.listMembers(pid.value),
      api.listPlanRuns(pid.value, { page: 1, page_size: 100 }),
      notificationApi.listRules(pid.value),
    ])
    plans.value = planPage.items
    codeCases.value = codeCasePage.items
    codeModuleTree.value = codeTreeData
    members.value = memberPage.items
    runs.value = runPage.items

    // 调试日志
    console.log('[TestPlan] Raw ruleList:', ruleList)
    console.log('[TestPlan] Enabled rules:', ruleList.filter((r: any) => r.enabled))

    notificationRules.value = ruleList.filter((r: any) => r.enabled)  // 只显示启用的规则
    selected.value = plans.value.find(item => item.id === selected.value?.id) || plans.value[0]
    configurePolling()
  } catch {
    ElMessage.error('测试计划加载失败')
  } finally {
    loading.value = false
  }
}

async function refreshRuns() {
  if (!pid.value) return
  const page = await api.listPlanRuns(pid.value, { page: 1, page_size: 100 })
  runs.value = page.items
  if (reportRun.value) reportRun.value = runs.value.find(item => item.id === reportRun.value?.id) || reportRun.value
  configurePolling()
}

function configurePolling() {
  const active = runs.value.some(item => item.status === 'pending' || item.status === 'running')
  if (active && !pollTimer) pollTimer = setInterval(() => refreshRuns().catch(() => undefined), 3000)
  if (!active) stopPolling()
}
function stopPolling() { if (pollTimer) clearInterval(pollTimer); pollTimer = undefined }
function latestRun(planId: number) { return latestRunMap.value.get(planId) }
function runItem(caseId: number) { return latestRun(selected.value?.id || 0)?.items.find(item => item.case_id === caseId) }
function isTerminal(status?: string) { return !!status && terminalStatuses.has(status) }
function selectPlan(plan: TestPlan) {
  selected.value = plan
  detailVisible.value = true
}

async function handleDeletePlan(plan: TestPlan) {
  await ElMessageBox.confirm(`确定删除计划「${plan.name}」吗？关联的执行记录不会删除。`, '删除确认', { type: 'warning' })
  try {
    await api.deletePlan(pid.value!, plan.id)
    if (selected.value?.id === plan.id) { selected.value = undefined; detailVisible.value = false }
    await load()
    ElMessage.success('计划已删除')
  } catch { ElMessage.error('删除失败') }
}

async function handleCancelRun(run: PlanRun) {
  await ElMessageBox.confirm(`确定停止执行「运行 #${run.id}」吗？已完成的用例结果将保留。`, '停止确认', {
    type: 'warning',
    confirmButtonText: '停止',
    cancelButtonText: '取消'
  })
  try {
    await api.cancelPlanRun(pid.value!, run.id)
    ElMessage.success('已发送停止指令')
    await refreshRuns()
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.message || '停止失败')
  }
}

function openEditor(plan?: TestPlan, focusCases = false) {
  editingId.value = plan?.id

  // 代码用例
  const codeCaseIds = plan?.items.filter(item => item.case_type === 'code').map(item => item.case_id) || []

  const ruleIds = (plan as any)?.notification_rule_ids || []

  // 调试日志
  console.log('[openEditor] Plan:', plan?.name)
  console.log('[openEditor] notification_rule_ids from plan:', ruleIds)
  console.log('[openEditor] Available notificationRules:', notificationRules.value)

  Object.assign(form, {
    name: plan?.name || '', description: plan?.description || '', due_date: plan?.due_date || '',
    owner_id: plan?.owner_id || authStore.user?.id,
    notification_channel_id: plan?.notification_channel_id,
    notification_template_code: plan?.notification_template_code,
    notification_rule_ids: ruleIds,  // 加载通知规则IDs
    codeCaseIds,
  })
  selectedCodeModuleId.value = null
  editorVisible.value = true
  if (focusCases) requestAnimationFrame(() => document.querySelector('.case-picker')?.scrollIntoView({ block: 'center' }))
}

function handleModuleNodeClick(data: CodeModuleTreeNode) {
  selectedCodeModuleId.value = data.id
}

async function save() {
  if (!pid.value || !form.name.trim()) return ElMessage.warning('请输入计划名称')
  if (!form.codeCaseIds.length) return ElMessage.warning('请至少选择一个用例')
  saving.value = true
  try {
    const existing = editingId.value ? plans.value.find(item => item.id === editingId.value) : undefined

    const items = form.codeCaseIds.map((case_id, index) => ({
      case_id,
      case_type: 'code' as const,
      sort_order: index,
      enabled: true
    }))

    const data = {
      name: form.name.trim(), description: form.description || undefined, due_date: form.due_date || undefined,
      owner_id: form.owner_id,
      failure_strategy: existing?.failure_strategy || 'continue', status: existing?.status || 'active',
      notification_channel_id: form.notification_channel_id,
      notification_template_code: form.notification_template_code,
      notification_rule_ids: form.notification_rule_ids,  // 保存通知规则IDs
      items,
    }
    const saved = editingId.value ? await api.updatePlan(pid.value, editingId.value, data) : await api.createPlan(pid.value, data)
    editorVisible.value = false
    selected.value = saved
    await load()
    ElMessage.success('测试计划已保存')
  } catch {
    ElMessage.error('测试计划保存失败')
  } finally { saving.value = false }
}

async function removeCase(caseId: number) {
  if (!pid.value || !selected.value) return
  await ElMessageBox.confirm('确定从该计划移除此用例吗？历史运行结果不会被删除。', '移除用例', { type: 'warning' })
  const plan = selected.value
  await api.updatePlan(pid.value, plan.id, {
    items: plan.items.filter(item => item.case_id !== caseId).map((item, index) => ({
      case_id: item.case_id,
      case_version: item.case_version,
      case_type: item.case_type,
      sort_order: index,
      enabled: item.enabled
    })),
  })
  await load()
  ElMessage.success('用例已移除')
}

async function handleSyncVersions() {
  if (!pid.value || !selected.value) return
  const codePlanItems = selected.value.items.filter(item => item.case_type === 'code')
  if (!codePlanItems.length) {
    return ElMessage.warning('当前计划没有代码用例需要同步版本')
  }

  try {
    await ElMessageBox.confirm(
      `即将同步 ${codePlanItems.length} 个代码用例到最新版本，确定继续吗？`,
      '同步用例版本',
      { type: 'warning', confirmButtonText: '确定同步' }
    )

    loading.value = true
    const updated = await api.syncCaseVersions(pid.value, selected.value.id)
    selected.value = updated
    await load()
    ElMessage.success('用例版本已同步到最新')
  } catch (err: any) {
    if (err !== 'cancel') {
      ElMessage.error(err?.response?.data?.message || '同步失败')
    }
  } finally {
    loading.value = false
  }
}

function openRunDialog() {
  if (!selected.value) return
  runForm.failure_strategy = selected.value.failure_strategy
  runVisible.value = true
}

async function execute() {
  if (!pid.value || !selected.value) return
  executing.value = true
  try {
    const run = await api.runPlan(pid.value, selected.value.id, {
      failure_strategy: runForm.failure_strategy,
    })
    runs.value = [run, ...runs.value.filter(item => item.id !== run.id)]
    runVisible.value = false
    configurePolling()
    ElMessage.success('计划已进入执行队列，页面会自动更新结果')
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.message || err?.message || '测试计划执行失败')
  } finally { executing.value = false }
}

function planHasRuns(planId: number) { return runs.value.some(run => run.plan_id === planId) }

function planRunsCount(planId: number) {
  return runs.value.filter(run => run.plan_id === planId).length
}

function viewRunDetail(run: PlanRun) {
  router.push({
    name: 'PlanRunReport',
    params: { projectCode: route.params.projectCode, runId: run.id },
    query: { projectId: pid.value },
  })
}

// 导航到飞书通知中心
function goToNotification() {
  router.push({
    name: 'Notifications',
    params: { projectCode: route.params.projectCode },
  })
}

async function openReport() {
  if (!pid.value || !selected.value) return
  reportFilter.value = '全部'
  reportRun.value = undefined
  planRunHistory.value = []
  reportVisible.value = true
}

async function loadPlanRunHistory() {
  if (!pid.value || !selected.value) return
  historyLoading.value = true
  try {
    const page = await api.listPlanRuns(pid.value, { plan_id: selected.value.id, page: 1, page_size: 100 })
    planRunHistory.value = page.items
    // 默认选中最近一次执行；若已有选中项则尽量保留
    const keep = reportRun.value && planRunHistory.value.find(run => run.id === reportRun.value?.id)
    await selectHistoryRun(keep || planRunHistory.value[0])
  } catch {
    ElMessage.error('执行历史加载失败')
  } finally {
    historyLoading.value = false
  }
}

async function selectHistoryRun(run?: PlanRun) {
  if (!pid.value || !run) { reportRun.value = undefined; return }
  // 拉取完整明细（含 items），列表接口已带 items 但详情接口保证最新
  reportRun.value = await api.getPlanRun(pid.value, run.id)
  reportFilter.value = '全部'
}

function openFullReport() {
  if (!reportRun.value) return
  reportVisible.value = false
  router.push({
    name: 'PlanRunReport',
    params: { projectCode: route.params.projectCode, runId: reportRun.value.id },
    query: { projectId: pid.value },
  })
}

function triggerText(value?: string) { return value === 'schedule' ? '定时触发' : value === 'ci' ? 'CI 触发' : '手动触发' }
function rerunFromReport() { reportVisible.value = false; openRunDialog() }

function codeCaseInfo(id: number) { return codeCases.value.find(item => item.id === id) }
function ownerName(id?: number | null) { if (!id) return '未指定'; const member = members.value.find(item => item.user_id === id); return member?.full_name || member?.username || `用户 #${id}` }
function memberLabel(member: MemberInfo) { const name = member.full_name || member.username || `用户 #${member.user_id}`; return member.user_id === authStore.user?.id ? `${name}（我）` : name }
function dueText(value?: string | null) { return value ? `截止 ${value.slice(5)}` : '未设置截止日期' }
function planStatusText(planId: number) { const status = latestRun(planId)?.status; return status ? runStatusText(status) : '未开始' }
function runStatusText(status?: string) { return ({ pending: '排队中', running: '执行中', passed: '通过', failed: '失败', error: '异常', cancelled: '已取消', timeout: '超时' } as Record<string, string>)[status || ''] || '未运行' }
function statusClass(status?: string) { if (status === 'passed') return 'is-passed'; if (status === 'pending' || status === 'running') return 'is-running'; if (status === 'failed' || status === 'error' || status === 'timeout') return 'is-failed'; return 'is-idle' }
function priorityText(priority?: string | null) {
  const map: Record<string, string> = { critical: 'P0', high: 'P1', medium: 'P2', low: 'P3' }
  if (!priority) return '—'
  return map[priority] || priority
}
function priorityClass(priority?: string | null) {
  if (!priority) return 'priority-none'
  const levelMap: Record<string, string> = { critical: 'critical', high: 'high', medium: 'medium', low: 'low', 'P0': 'critical', 'P1': 'high', 'P2': 'medium', 'P3': 'low' }
  return `priority-${levelMap[priority] || 'none'}`
}
function passRate(run?: PlanRun) { return run?.total_items ? `${Math.round(run.passed_items / run.total_items * 100)}%` : '—' }
function durationText(ms?: number | null) { if (ms == null) return '—'; return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s` }
function runDuration(run: PlanRun) { if (!run.started_at || !run.finished_at) return '—'; return durationText(new Date(run.finished_at).getTime() - new Date(run.started_at).getTime()) }
function channelTypeText(type?: string) {
  const map: Record<string, string> = { feishu_webhook: '飞书机器人', email: '邮件', dingtalk_webhook: '钉钉机器人', custom_webhook: '自定义Webhook' }
  return map[type || ''] || type || '未知'
}

// 事件类型中文映射
function eventTypeText(eventType?: string) {
  const map: Record<string, string> = {
    'execution.completed': '执行完成',
    'execution.failed': '执行失败',
    'execution.started': '执行开始',
    'plan_run.completed': '计划执行完成',
    'plan_run.failed': '计划执行失败',
  }
  return map[eventType || ''] || eventType || '未知事件'
}

// 接收人类型中文映射
function recipientTypeText(recipientType?: string) {
  const map: Record<string, string> = {
    'all_members': '全体成员',
    'project_admins': '项目管理员',
    'plan_owner': '计划负责人',
    'event_owner': '事件责任人',
    'custom': '自定义',
  }
  return map[recipientType || ''] || recipientType || '未知'
}

</script>

<style scoped>
.plan-page{min-width:0}.page-head h1{display:flex;align-items:center;gap:8px}.plan-layout{display:flex;flex-direction:column;gap:16px;background:var(--card);border:1px solid var(--line);border-radius:var(--r);overflow:hidden}.list-toolbar{height:52px;padding:0 14px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--line)}.list-toolbar h3{font-size:14px;margin:0}.plan-table :deep(th.el-table__cell){font-size:12px;color:var(--txt2);background:var(--line2)}.plan-table :deep(.el-table__row){cursor:pointer}.plan-table :deep(.el-table__row:hover){background:var(--line2)}.plan-name{font-size:13px;font-weight:600;color:var(--txt)}.plan-meta{margin-top:4px;font-size:11px;color:var(--txt3)}.drawer-summary{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;padding:16px;margin-bottom:16px;background:var(--line2);border-radius:var(--r)}.summary-item{display:flex;flex-direction:column;gap:4px}.summary-item .label{font-size:11px;color:var(--txt3)}.summary-item .value{font-size:14px;font-weight:600;color:var(--txt)}.drawer-actions{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:20px;padding-bottom:16px;border-bottom:1px solid var(--line)}.drawer-tabs{margin-top:12px}.drawer-tabs :deep(.el-tabs__content){padding-top:12px}.history-toolbar{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;padding-bottom:12px;border-bottom:1px solid var(--line2)}.history-table :deep(.el-table__row){cursor:pointer}.history-table :deep(.el-table__row:hover){background:var(--line2)}.run-id{font-weight:600;color:var(--primary)}.config-section{padding:8px 0}.drawer-section h3{font-size:14px;margin:0 0 12px;color:var(--txt2)}.case-name{font-size:13px;font-weight:600;color:var(--txt)}.case-version{margin-top:4px;font-size:11px;color:var(--txt3)}.case-table :deep(th.el-table__cell){background:var(--line2);color:var(--txt2)}.status-dot{display:inline-flex;align-items:center;gap:6px;white-space:nowrap;font-size:12px}.status-dot::before{content:'';width:7px;height:7px;border-radius:50%;background:var(--txt3)}.status-dot.is-running::before{background:var(--primary)}.status-dot.is-passed::before{background:var(--success)}.status-dot.is-failed::before{background:var(--err)}.priority{display:inline-flex;padding:2px 7px;border-radius:4px;font-size:11px;font-weight:600;background:var(--line2);color:var(--txt2)}.priority-critical{background:var(--err-bg);color:var(--err)}.priority-high{background:var(--warn-bg);color:var(--warn)}.priority-medium{background:var(--primary-bg);color:var(--primary)}.info-strip,.run-summary{display:flex;align-items:center;gap:7px;padding:9px 12px;margin-bottom:14px;border:1px solid #c4b5fd;border-radius:var(--r);background:var(--info-bg);font-size:12px;color:var(--info)}.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}.form-grid :deep(.el-select),.form-grid :deep(.el-date-editor){width:100%}.option-note{float:right;margin-left:24px;color:var(--txt3);font-size:11px}.case-picker{width:100%;border:1px solid var(--line);border-radius:var(--r);overflow:hidden}.case-picker-head{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:6px 12px;border-bottom:1px solid var(--line);background:var(--line2)}.case-picker-count{font-size:11px;color:var(--txt3)}.case-group{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:2px 12px;max-height:240px;overflow-y:auto;padding:6px 12px}.case-option{display:flex;align-items:flex-start;gap:8px;min-width:0;height:auto;margin:0;padding:7px 4px;border-radius:var(--r)}.case-option:hover{background:var(--line2)}.case-option :deep(.el-checkbox__input){margin-top:2px}.case-option :deep(.el-checkbox__label){flex:1;min-width:0;padding-left:8px;line-height:1.4;font-weight:400}.case-option-text{display:flex;flex-direction:column;min-width:0}.case-option-text b{font-size:13px;color:var(--txt);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.case-option-text small{font-size:11px;color:var(--txt3);margin-top:3px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.report-meta{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px;padding:14px;margin-bottom:20px;background:var(--line2);border-radius:var(--r)}.report-meta div{display:flex;flex-direction:column;gap:5px;min-width:0}.report-meta small{font-size:11px;color:var(--txt3)}.report-meta b{font-size:13px;overflow-wrap:anywhere}.section-title{margin:0 0 12px;font-size:13px}.report-stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:20px}.report-stats>div{display:flex;flex-direction:column;gap:5px;padding:12px;border:1px solid var(--line);border-radius:var(--r)}.report-stats small{font-size:11px;color:var(--txt3)}.report-stats strong{font-size:24px}.report-stats .passed{border-color:var(--success);background:var(--success-bg);color:var(--success)}.report-stats .failed{border-color:var(--err);background:var(--err-bg);color:var(--err)}.report-list-head{display:flex;align-items:center;justify-content:space-between}.report-list-head .section-title{margin:0}.report-table{margin-top:12px}.error-text{color:var(--err)}.report-body{display:grid;grid-template-columns:220px minmax(0,1fr);gap:16px;align-items:start}.report-main{min-width:0}.run-history{border:1px solid var(--line);border-radius:var(--r);overflow:hidden}.run-history-head{display:flex;align-items:center;justify-content:space-between;padding:8px 10px;border-bottom:1px solid var(--line);font-size:13px;font-weight:600;background:var(--line2)}.run-history-list{list-style:none;margin:0;padding:0}.run-history-item{padding:9px 10px;border-bottom:1px solid var(--line2);cursor:pointer}.run-history-item:hover{background:var(--line2)}.run-history-item.active{background:var(--primary-bg);box-shadow:inset 3px 0 0 var(--primary)}.run-history-item.running .rh-top b{color:var(--primary)}.rh-top{display:flex;align-items:center;justify-content:space-between}.rh-top b{font-size:13px}.rh-meta{display:flex;justify-content:space-between;margin-top:4px;font-size:11px;color:var(--txt3)}.rh-time{margin-top:3px;font-size:11px;color:var(--txt3)}
.case-picker.code-case-tree{display:grid;grid-template-columns:200px minmax(0,1fr);gap:0}.code-case-tree :deep(.el-tree){border-right:1px solid var(--line);padding:8px;max-height:240px;overflow-y:auto}.code-case-tree .tree-node-label{display:flex;align-items:center;gap:6px;font-size:13px;width:100%}.code-case-tree .tree-node-label .el-tag{margin-left:auto}.code-case-tree .tree-empty-hint{border-right:1px solid var(--line);padding:16px 8px;max-height:240px;font-size:12px;color:var(--el-text-color-secondary);text-align:center}.code-case-list{max-height:240px;overflow-y:auto;padding:6px 12px}.code-case-list .el-checkbox-group{display:flex;flex-direction:column}
@media(max-width:1100px){.report-meta,.report-stats{grid-template-columns:repeat(2,1fr)}.report-body{grid-template-columns:1fr}.drawer-summary{grid-template-columns:repeat(2,1fr)}}
@media(max-width:760px){.form-grid,.drawer-summary,.case-group{grid-template-columns:1fr}.report-meta,.report-stats{grid-template-columns:1fr 1fr}.report-list-head{align-items:flex-start;gap:10px;flex-direction:column}}
</style>