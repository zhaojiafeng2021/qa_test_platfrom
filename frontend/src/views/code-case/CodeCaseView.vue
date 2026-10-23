<template>
  <div class="cc-view">
    <div class="page-head cc-page-head">
      <div>
        <h1><el-icon><Document /></el-icon>代码用例</h1>
        <p>扫描 master 分支获取最新的代码用例数据，项目归属由 <code>@case(project="项目名")</code> 自动解析；若 project 参数为空或未匹配到项目，该用例不归属任何项目，不会出现在项目列表中</p>
      </div>
      <div class="actions">
        <el-button type="primary" :icon="Refresh" :loading="scanning" @click="scanCode">
          扫描代码
        </el-button>
      </div>
    </div>

    <div class="cc-stats">
      <span class="stats-label">共</span>
      <b class="stats-total">{{ stats.total }}</b>
      <span class="stats-label">条用例</span>
      <span class="stats-sep" />
      <span class="stats-label">模块</span>
      <b class="stats-total">{{ stats.module_count }}</b>
      <span class="stats-sep" />
      <span class="pri pri-p0">P0</span><b class="p0-count">{{ stats.by_level.P0 || 0 }}</b>
      <span class="pri pri-p1">P1</span><b class="p1-count">{{ stats.by_level.P1 || 0 }}</b>
      <span class="pri pri-p2">P2</span><b class="p2-count">{{ stats.by_level.P2 || 0 }}</b>
      <span class="pri pri-p3">P3</span><b class="p3-count">{{ stats.by_level.P3 || 0 }}</b>
      <span class="stats-note">数据来源：code_testcases 目录扫描</span>
    </div>

    <div class="cc-layout">
      <!-- 左：用例模块树 -->
      <div class="cc-tree-panel">
        <div class="panel-header">
          <span class="panel-title">用例模块</span>
          <el-tooltip content="新增根模块">
            <el-button :icon="Plus" size="small" circle @click="openModuleDialog(null)" />
          </el-tooltip>
        </div>
        <div class="panel-search">
          <el-input v-model="treeSearch" placeholder="搜索模块" clearable size="small" :prefix-icon="Search" />
        </div>
        <div class="panel-filter">
          <el-checkbox v-model="hideEmptyModules" size="small">
            仅显示有用例的层级
          </el-checkbox>
          <el-tooltip
            v-if="hideEmptyModules && hiddenModuleCount > 0"
            :content="`已隐藏 ${hiddenModuleCount} 个无用例层级，取消勾选可显示并管理`"
          >
            <span class="hidden-hint">{{ hiddenModuleCount }}</span>
          </el-tooltip>
        </div>
        <div class="tree-container">
          <button
            type="button"
            :class="['all-case-row', { active: selectedModuleId === null }]"
            @click="selectAllCases"
          >
            <el-icon><FolderOpened /></el-icon>
            <span>全部用例</span>
            <b>{{ stats.total }}</b>
          </button>
          <el-tree
            ref="treeRef"
            :data="filteredTree"
            :props="{ label: 'name', children: 'children' }"
            node-key="id"
            highlight-current
            default-expand-all
            @node-click="onNodeClick"
          >
            <template #default="{ data }">
              <div class="tree-node">
                <el-icon class="node-icon"><Folder /></el-icon>
                <span class="node-label">{{ data.name }}</span>
                <span class="node-count" v-if="data.total_case_count > 0">{{ data.total_case_count }}</span>
                <div class="node-actions" @click.stop>
                  <el-tooltip content="新增子模块">
                    <el-button :icon="Plus" size="small" link @click="openModuleDialog(data.id)" />
                  </el-tooltip>
                  <el-tooltip content="重命名">
                    <el-button :icon="Edit" size="small" link @click="openRenameDialog(data)" />
                  </el-tooltip>
                  <el-tooltip content="删除层级">
                    <el-button :icon="Delete" size="small" link type="danger" @click="deleteModule(data)" />
                  </el-tooltip>
                </div>
              </div>
            </template>
          </el-tree>
          <div v-if="filteredTree.length === 0 && !treeSearch" class="empty-tree">
            <!-- 区分「真的没模块」和「模块都被空层级过滤掉了」，否则会误报需要扫描 -->
            <template v-if="tree.length > 0 && hideEmptyModules">
              <el-empty :description="`${hiddenModuleCount} 个层级均无用例，已全部隐藏`" :image-size="60" />
              <el-button size="small" @click="hideEmptyModules = false">显示空层级</el-button>
            </template>
            <template v-else>
              <el-empty description="暂无模块，点击「扫描代码」获取" :image-size="60" />
              <el-button type="primary" size="small" @click="openModuleDialog(null)">新增模块</el-button>
            </template>
          </div>
        </div>
      </div>

      <!-- 右：用例列表 -->
      <div class="cc-main">
        <div class="cc-toolbar">
          <div class="toolbar-left">
            <span class="module-breadcrumb">
              <el-icon><Document /></el-icon>
              {{ currentModuleName }}
            </span>
            <el-tag v-if="selectedIds.length > 0" type="info" size="small" class="selected-tag">
              已选 {{ selectedIds.length }} 项
            </el-tag>
          </div>
          <div class="toolbar-right">
            <el-button
              type="primary"
              :icon="VideoPlay"
              :disabled="selectedIds.length === 0"
              :loading="executing"
              @click="executeBatch"
            >
              {{ executing ? '执行中...' : `批量执行${selectedIds.length ? ` (${selectedIds.length})` : ''}` }}
            </el-button>
            <el-input
              v-model="keyword"
              placeholder="搜索用例名/模块/函数名"
              clearable
              size="small"
              style="width: 220px"
              :prefix-icon="Search"
              @change="loadCases"
            />
            <el-select v-model="filterLevel" placeholder="等级" clearable size="small"
                       style="width: 100px" @change="loadCases">
              <el-option v-for="lv in (['P0','P1','P2','P3'] as CaseLevel[])" :key="lv" :label="lv" :value="lv" />
            </el-select>
          </div>
        </div>

        <div class="cc-content">
          <el-table
            ref="tableRef"
            :data="cases"
            size="small"
            highlight-current-row
            v-loading="listLoading"
            row-key="id"
            @row-click="openDetail"
            @selection-change="onSelectionChange"
          >
            <el-table-column type="selection" width="42" @click.stop />
            <el-table-column label="用例名称" prop="name" min-width="160" show-overflow-tooltip />
            <el-table-column label="模块层级" min-width="180" show-overflow-tooltip>
              <template #default="{ row }">
                <span class="module-path">{{ row.module }}</span>
              </template>
            </el-table-column>
            <el-table-column label="等级" width="70">
              <template #default="{ row }">
                <el-tag :type="LEVEL_TYPES[row.level as CaseLevel]" size="small">{{ row.level }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="80">
              <template #default="{ row }">
                <el-tag :type="STATUS_TYPES[row.status as CaseStatus]" size="small">
                  {{ STATUS_LABELS[row.status as CaseStatus] }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="函数" prop="function_name" min-width="140" show-overflow-tooltip />
            <el-table-column label="上次执行" width="100">
              <template #default="{ row }">
                <span v-if="row.last_run_at" class="last-run">{{ formatTime(row.last_run_at) }}</span>
                <span v-else class="text-placeholder">-</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="140" fixed="right">
              <template #default="{ row }">
                <el-button size="small" link type="primary" @click.stop="openDetail(row as CodeCaseListItem)">查看</el-button>
                <el-button size="small" link type="success" @click.stop="executeSingle(row as CodeCaseListItem)">执行</el-button>
              </template>
            </el-table-column>
            <template #empty>
              <el-empty description="暂无代码用例，点击右上角「扫描代码」" :image-size="80" />
            </template>
          </el-table>

          <div class="cc-pager" v-if="total > 0">
            <el-pagination
              v-model:current-page="page"
              v-model:page-size="pageSize"
              :total="total"
              :page-sizes="[20, 50, 100]"
              layout="total, sizes, prev, pager, next"
              size="small"
              @current-change="loadCases"
              @size-change="loadCases"
            />
          </div>
        </div>
      </div>
    </div>

    <!-- 新增/重命名模块 -->
    <el-dialog v-model="moduleDialog" :title="moduleDialogTitle" width="420px">
      <el-form label-width="80px">
        <el-form-item label="模块名称">
          <el-input v-model="moduleForm.name" placeholder="请输入模块名称" maxlength="100" show-word-limit />
        </el-form-item>
        <el-form-item label="上级模块" v-if="!moduleForm.id">
          <span class="parent-hint">{{ parentHint }}</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="moduleDialog = false">取消</el-button>
        <el-button type="primary" :loading="moduleSaving" @click="saveModule">确定</el-button>
      </template>
    </el-dialog>

    <!-- 用例详情 -->
    <el-drawer v-model="detailDrawer" :title="detail?.name || '用例详情'" size="52%">
      <div v-if="detail" class="cc-detail">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="模块层级">{{ detail.module }}</el-descriptions-item>
          <el-descriptions-item label="用例等级">
            <el-tag :type="LEVEL_TYPES[detail.level]" size="small">{{ detail.level }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="STATUS_TYPES[detail.status]" size="small">
              {{ STATUS_LABELS[detail.status] }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="用例描述">{{ detail.description || '-' }}</el-descriptions-item>
          <el-descriptions-item label="函数名">{{ detail.function_name }}</el-descriptions-item>
          <el-descriptions-item label="文件路径">
            {{ detail.file_path }}<span v-if="detail.line_number">:{{ detail.line_number }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="最近执行">
            <div v-if="detail.last_execution_id">
              <el-tag :type="EXEC_STATUS_TYPES[batchResult?.items?.find((i: any) => i.id === detail!.last_execution_id)?.status || ''] || 'info'" size="small">
                {{ batchResult?.items?.find((i: any) => i.id === detail!.last_execution_id)?.status || '-' }}
              </el-tag>
              <span v-if="detail.last_duration_ms" class="ms-gap">{{ detail.last_duration_ms }}ms</span>
              <el-button size="small" link type="primary" @click="viewExecutionDetail(detail.last_execution_id!)">查看结果</el-button>
            </div>
            <span v-else class="text-placeholder">从未执行</span>
          </el-descriptions-item>
        </el-descriptions>
        <div class="code-block-title">代码片段</div>
        <pre class="code-block"><code>{{ detail.code_snippet || '（无）' }}</code></pre>
      </div>
    </el-drawer>

    <!-- 批次执行结果抽屉 -->
    <el-drawer v-model="resultDrawer" :title="resultDrawerTitle" size="60%" destroy-on-close>
      <div v-if="batchResult" class="batch-result">
        <!-- 汇总 -->
        <div class="batch-summary">
          <div class="summary-item total">
            <div class="summary-value">{{ batchResult.summary.total }}</div>
            <div class="summary-label">总数</div>
          </div>
          <div class="summary-item passed">
            <div class="summary-value">{{ batchResult.summary.passed }}</div>
            <div class="summary-label">通过</div>
          </div>
          <div class="summary-item failed">
            <div class="summary-value">{{ batchResult.summary.failed + batchResult.summary.error }}</div>
            <div class="summary-label">失败/异常</div>
          </div>
          <div class="summary-item rate">
            <div class="summary-value">{{ batchResult.summary.pass_rate }}%</div>
            <div class="summary-label">通过率</div>
          </div>
          <div class="summary-item duration">
            <div class="summary-value">{{ formatDuration(batchResult.summary.duration_ms) }}</div>
            <div class="summary-label">总耗时</div>
          </div>
          <div class="summary-item status-indicator">
            <el-tag
              :type="batchResult.summary.finished ? (batchResult.summary.failed > 0 ? 'warning' : 'success') : 'warning'"
              size="large"
            >
              {{ batchResult.summary.finished ? '执行完成' : '执行中...' }}
            </el-tag>
          </div>
        </div>

        <!-- 进度条 -->
        <el-progress
          v-if="!batchResult.summary.finished"
          :percentage="Math.round((batchResult.summary.passed + batchResult.summary.failed + batchResult.summary.error) / batchResult.summary.total * 100)"
          :status="batchResult.summary.finished ? 'success' : ''"
          :indeterminate="!batchResult.summary.finished"
          class="batch-progress"
        />

        <!-- 用例明细表格 -->
        <el-table :data="batchResult.items" size="small" v-loading="resultLoading" class="result-table">
          <el-table-column type="index" label="序号" width="50" />
          <el-table-column label="用例名称" prop="case_name" min-width="160" show-overflow-tooltip />
          <el-table-column label="模块" prop="module" min-width="140" show-overflow-tooltip />
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <el-tag :type="EXEC_STATUS_TYPES[row.status] || 'info'" size="small">
                {{ EXEC_STATUS_LABELS[row.status] || row.status }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="耗时" width="90">
            <template #default="{ row }">
              {{ row.duration_ms ? formatDuration(row.duration_ms) : '-' }}
            </template>
          </el-table-column>
          <el-table-column label="消息" prop="message" min-width="160" show-overflow-tooltip />
          <el-table-column label="操作" width="80" fixed="right">
            <template #default="{ row }">
              <el-button size="small" link type="primary" @click.stop="viewExecutionDetail(row.id)">详情</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <el-empty v-else description="暂无执行结果" />
    </el-drawer>

    <!-- 单条执行详情 -->
    <el-drawer v-model="execDetailDrawer" title="执行详情" size="55%" destroy-on-close>
      <div v-if="execDetail" class="exec-detail">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="用例">{{ execDetail.case_name }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="EXEC_STATUS_TYPES[execDetail.status] || 'info'" size="small">
              {{ EXEC_STATUS_LABELS[execDetail.status] || execDetail.status }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="模块">{{ execDetail.module || '-' }}</el-descriptions-item>
          <el-descriptions-item label="耗时">{{ execDetail.duration_ms ? formatDuration(execDetail.duration_ms) : '-' }}</el-descriptions-item>
          <el-descriptions-item label="函数">{{ execDetail.function_name || '-' }}</el-descriptions-item>
          <el-descriptions-item label="等级">{{ execDetail.level || '-' }}</el-descriptions-item>
          <el-descriptions-item label="开始时间">{{ formatDateTime(execDetail.started_at) }}</el-descriptions-item>
          <el-descriptions-item label="结束时间">{{ formatDateTime(execDetail.finished_at) }}</el-descriptions-item>
        </el-descriptions>

        <div v-if="execDetail.message" class="detail-section">
          <div class="section-title">执行消息</div>
          <div class="message-box" :class="{ 'message-error': isErrorStatus(execDetail.status) }">
            {{ execDetail.message }}
          </div>
        </div>

        <div class="detail-section">
          <div class="section-title">
            执行日志
            <el-tag type="info" size="small">{{ (execDetail.logs || '').length }} 字符</el-tag>
          </div>
          <pre class="log-block"><code>{{ execDetail.logs || '（无日志输出）' }}</code></pre>
        </div>

        <div v-if="execDetail.traceback" class="detail-section">
          <div class="section-title">异常堆栈</div>
          <pre class="traceback-block"><code>{{ execDetail.traceback }}</code></pre>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Delete, Document, Edit, Folder, FolderOpened, Plus, Refresh, Search, VideoPlay,
} from '@element-plus/icons-vue'
import { codeCaseApi, codeModuleApi } from '@/api/code-case'
import { useProjectStore } from '@/stores/project'
import { formatDateTime, formatTime } from '@/utils/datetime'
import {
  EXEC_STATUS_LABELS, EXEC_STATUS_TYPES, LEVEL_TYPES,
  STATUS_LABELS, STATUS_TYPES,
  type BatchResult, type CaseLevel, type CaseStatus,
  type CodeCaseDetail, type CodeCaseListItem, type CodeCaseStats,
  type CodeModuleTreeNode, type ExecutionDetail,
} from '@/types/code-case'
import { countModules, pruneEmptyModules } from './module-tree'

const scanning = ref(false)
const listLoading = ref(false)
const executing = ref(false)
const resultLoading = ref(false)

const projectStore = useProjectStore()
const currentProjectId = computed(() => projectStore.currentProjectId ?? null)

const tree = ref<CodeModuleTreeNode[]>([])
const treeSearch = ref('')
const selectedModuleId = ref<number | null>(null)
// 默认隐藏「整棵子树都没有有效用例」的层级；关掉可看到空层级以便管理（新建/重命名/删除）
const hideEmptyModules = ref(true)

const cases = ref<CodeCaseListItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const keyword = ref('')
const filterLevel = ref<string>('')

const stats = ref<CodeCaseStats>({ total: 0, module_count: 0, by_level: {}, by_status: {} })

const detailDrawer = ref(false)
const detail = ref<CodeCaseDetail | null>(null)

const moduleDialog = ref(false)
const moduleSaving = ref(false)
const moduleForm = reactive<{ id: number | null; name: string; parent_id: number | null }>({
  id: null, name: '', parent_id: null,
})

const moduleDialogTitle = computed(() => (moduleForm.id ? '重命名模块' : '新增用例模块'))

const parentHint = computed(() => {
  if (moduleForm.parent_id === null) return '根级'
  return findNode(tree.value, moduleForm.parent_id)?.full_path || '-'
})

const currentModuleName = computed(() => {
  if (selectedModuleId.value === null) return '全部用例'
  return findNode(tree.value, selectedModuleId.value)?.full_path || '全部用例'
})

// 剪掉没有有效用例的层级；当前选中项即使为空也保留，避免选中态指向不可见节点
const prunedTree = computed(() => pruneEmptyModules(tree.value, selectedModuleId.value))

const filteredTree = computed(() => {
  const base = hideEmptyModules.value ? prunedTree.value : tree.value
  if (!treeSearch.value.trim()) return base
  const kw = treeSearch.value.trim().toLowerCase()
  const filter = (nodes: CodeModuleTreeNode[]): CodeModuleTreeNode[] =>
    nodes.reduce<CodeModuleTreeNode[]>((acc, n) => {
      const children = filter(n.children || [])
      if (n.name.toLowerCase().includes(kw) || children.length) {
        acc.push({ ...n, children })
      }
      return acc
    }, [])
  return filter(base)
})

// 被隐藏的空层级数量（用于开关提示）
const hiddenModuleCount = computed(() => countModules(tree.value) - countModules(prunedTree.value))

// 表格选择
const tableRef = ref()
const selectedIds = ref<number[]>([])

// 执行结果
const resultDrawer = ref(false)
const resultDrawerTitle = ref('执行结果')
const batchResult = ref<BatchResult | null>(null)

// 执行详情
const execDetailDrawer = ref(false)
const execDetail = ref<ExecutionDetail | null>(null)
const execDetailLoading = ref(false)

let pollTimer: ReturnType<typeof setInterval> | null = null

function findNode(nodes: CodeModuleTreeNode[], id: number): CodeModuleTreeNode | null {
  for (const n of nodes) {
    if (n.id === id) return n
    const hit = findNode(n.children || [], id)
    if (hit) return hit
  }
  return null
}

function onSelectionChange(selection: CodeCaseListItem[]) {
  selectedIds.value = selection.map(item => item.id)
}

async function loadTree() {
  try {
    tree.value = await codeModuleApi.getTree(currentProjectId.value)
  } catch {
    // 拦截器已提示
  }
}

async function loadStats() {
  try {
    stats.value = await codeCaseApi.stats(currentProjectId.value)
  } catch {
    // 拦截器已提示
  }
}

async function loadCases() {
  listLoading.value = true
  try {
    const res = await codeCaseApi.list({
      page: page.value,
      page_size: pageSize.value,
      module_id: selectedModuleId.value,
      include_children: true,
      level: filterLevel.value || undefined,
      keyword: keyword.value || undefined,
      project_id: currentProjectId.value,
    })
    cases.value = res.items
    total.value = res.total
    // 清空选择（新的一页数据）
    await nextTick()
    if (tableRef.value) {
      tableRef.value.clearSelection()
    }
  } finally {
    listLoading.value = false
  }
}

async function refreshAll() {
  await Promise.all([loadTree(), loadStats(), loadCases()])
}

async function scanCode() {
  scanning.value = true
  try {
    const r = await codeCaseApi.scan(currentProjectId.value)
    const parts = [
      `扫描 ${r.scanned_files} 个文件`,
      `${r.scanned_cases} 个用例`,
      `新增 ${r.created}`,
      `更新 ${r.updated}`,
    ]
    if (r.restored) parts.push(`恢复 ${r.restored}`)
    if (r.deleted) parts.push(`失效 ${r.deleted}`)
    if (r.skipped) parts.push(`跳过其他项目 ${r.skipped}`)
    if (r.modules_created) parts.push(`新增模块 ${r.modules_created}`)
    ElMessage.success(parts.join('，'))
    if (r.errors?.length) {
      ElMessageBox.alert(r.errors.join('\n'), '扫描告警', { type: 'warning' })
    }
    page.value = 1
    await refreshAll()
  } finally {
    scanning.value = false
  }
}

function onNodeClick(data: CodeModuleTreeNode) {
  selectedModuleId.value = data.id
  page.value = 1
  loadCases()
}

function selectAllCases() {
  selectedModuleId.value = null
  page.value = 1
  loadCases()
}

function openModuleDialog(parentId: number | null) {
  moduleForm.id = null
  moduleForm.name = ''
  moduleForm.parent_id = parentId
  moduleDialog.value = true
}

function openRenameDialog(data: CodeModuleTreeNode) {
  moduleForm.id = data.id
  moduleForm.name = data.name
  moduleForm.parent_id = data.parent_id
  moduleDialog.value = true
}

async function saveModule() {
  if (!moduleForm.name.trim()) {
    ElMessage.warning('请输入模块名称')
    return
  }
  moduleSaving.value = true
  try {
    if (moduleForm.id) {
      await codeModuleApi.update(moduleForm.id, { name: moduleForm.name.trim() })
      ElMessage.success('模块已更新')
    } else {
      const created = await codeModuleApi.create({
        name: moduleForm.name.trim(),
        parent_id: moduleForm.parent_id,
      })
      // 新模块还没有用例，开着「仅显示有用例的层级」会被直接剪掉。
      // 选中它，让 pruneEmpty 的选中例外把它留在树上，否则会像创建失败。
      if (created?.id) {
        selectedModuleId.value = created.id
        page.value = 1
      }
      ElMessage.success('模块已创建')
    }
    moduleDialog.value = false
    await refreshAll()
  } finally {
    moduleSaving.value = false
  }
}

async function deleteModule(data: CodeModuleTreeNode) {
  const hasChildren = (data.children?.length || 0) > 0
  const hasCases = data.total_case_count > 0
  const warn = hasChildren || hasCases
    ? `该模块下有 ${data.children?.length || 0} 个子模块、${data.total_case_count} 个用例，将一并删除层级（用例本身保留但解除归属）。`
    : '确定删除该模块层级？'
  try {
    await ElMessageBox.confirm(warn, `删除模块「${data.name}」`, {
      type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await codeModuleApi.delete(data.id, warn !== '确定删除该模块层级？')
    ElMessage.success('模块已删除')
    if (selectedModuleId.value === data.id) selectedModuleId.value = null
    await refreshAll()
  } catch {
    // 拦截器已提示
  }
}

async function openDetail(row: CodeCaseListItem) {
  try {
    detail.value = await codeCaseApi.get(row.id)
    detailDrawer.value = true
  } catch {
    // 拦截器已提示
  }
}

async function executeSingle(row: CodeCaseListItem) {
  executing.value = true
  try {
    const result = await codeCaseApi.execute({ case_ids: [row.id] })
    openResultDrawer(result)
    startPolling(result.summary.batch_id)
  } catch {
    // 拦截器已提示
  } finally {
    executing.value = false
  }
}

async function executeBatch() {
  if (selectedIds.value.length === 0) return
  executing.value = true
  try {
    const result = await codeCaseApi.execute({ case_ids: selectedIds.value })
    openResultDrawer(result)
    startPolling(result.summary.batch_id)
  } catch {
    // 拦截器已提示
  } finally {
    executing.value = false
  }
}

function openResultDrawer(result: BatchResult) {
  batchResult.value = result
  resultDrawerTitle.value = `执行结果 (${result.summary.total} 个用例)`
  resultDrawer.value = true
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

function startPolling(batchId: string) {
  stopPolling()
  resultLoading.value = false

  const poll = async () => {
    try {
      const r = await codeCaseApi.getBatch(batchId)
      batchResult.value = r
      if (r.summary.finished) {
        stopPolling()
        resultLoading.value = false
        ElMessage.success(`执行完成：通过 ${r.summary.passed} / 失败 ${r.summary.failed + r.summary.error}`)
        // 刷新列表数据
        await loadCases()
        await loadStats()
      }
    } catch {
      // 静默忽略，下次轮询再试
    }
  }

  // 先立即拉一次
  poll()
  // 每 2 秒轮询
  pollTimer = setInterval(poll, 2000)
}

async function viewExecutionDetail(execId: number) {
  execDetailLoading.value = true
  execDetailDrawer.value = true
  execDetail.value = null
  try {
    execDetail.value = await codeCaseApi.getExecution(execId)
  } catch {
    // 拦截器已提示
    execDetailDrawer.value = false
  } finally {
    execDetailLoading.value = false
  }
}

function isErrorStatus(status: string) {
  return status === 'failed' || status === 'error' || status === 'timeout'
}

function formatDuration(ms: number) {
  if (ms < 1000) return `${ms}ms`
  const s = ms / 1000
  if (s < 60) return `${s.toFixed(1)}s`
  const m = Math.floor(s / 60)
  const sec = Math.round(s % 60)
  return `${m}m ${sec}s`
}

watch(currentProjectId, (newId, oldId) => {
  if (newId !== oldId) {
    refreshAll()
  }
})

onMounted(refreshAll)
</script>

<style scoped>
.cc-view { display: flex; flex-direction: column; height: 100%; gap: 12px; }

.cc-page-head { display: flex; justify-content: space-between; align-items: flex-start; }
.cc-page-head h1 { display: flex; align-items: center; gap: 8px; margin: 0; font-size: 20px; }
.cc-page-head p { margin: 4px 0 0; color: var(--el-text-color-secondary); font-size: 13px; }

.cc-stats {
  display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
  padding: 10px 14px; background: var(--el-fill-color-light);
  border-radius: 6px; font-size: 13px;
}
.stats-label { color: var(--el-text-color-secondary); }
.stats-total { color: var(--el-color-primary); font-size: 16px; margin: 0 2px; }
.stats-sep { width: 1px; height: 14px; background: var(--el-border-color); margin: 0 8px; }
.stats-note { margin-left: auto; color: var(--el-text-color-placeholder); font-size: 12px; }
.pri { margin-left: 8px; font-size: 12px; padding: 1px 5px; border-radius: 3px; }
.pri-p0 { color: var(--el-color-danger); background: var(--el-color-danger-light-9); }
.pri-p1 { color: var(--el-color-warning); background: var(--el-color-warning-light-9); }
.pri-p2 { color: var(--el-color-primary); background: var(--el-color-primary-light-9); }
.pri-p3 { color: var(--el-color-info); background: var(--el-color-info-light-9); }

.cc-layout { display: flex; gap: 12px; flex: 1; min-height: 0; }

.cc-tree-panel {
  width: 280px; flex-shrink: 0; display: flex; flex-direction: column;
  border: 1px solid var(--el-border-color-lighter); border-radius: 6px;
  background: var(--el-bg-color); overflow: hidden;
}
.panel-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 10px 12px; border-bottom: 1px solid var(--el-border-color-lighter);
}
.panel-title { font-weight: 600; font-size: 14px; }
.panel-search { padding: 8px 10px 4px; }
.panel-filter {
  display: flex; align-items: center; gap: 6px;
  padding: 0 10px 8px; border-bottom: 1px solid var(--el-border-color-lighter);
}
.hidden-hint {
  font-size: 11px; color: var(--el-text-color-secondary);
  background: var(--el-fill-color); padding: 0 5px; border-radius: 8px; cursor: help;
}
.tree-container { flex: 1; overflow-y: auto; padding: 6px 6px 10px; }

.all-case-row {
  display: flex; align-items: center; gap: 6px; width: 100%;
  padding: 7px 10px; margin-bottom: 4px; border: none; border-radius: 4px;
  background: transparent; cursor: pointer; font-size: 13px; text-align: left;
  color: var(--el-text-color-primary);
}
.all-case-row:hover { background: var(--el-fill-color-light); }
.all-case-row.active { background: var(--el-color-primary-light-9); color: var(--el-color-primary); }
.all-case-row b { margin-left: auto; font-weight: 600; }

.tree-node { display: flex; align-items: center; gap: 6px; width: 100%; padding-right: 4px; }
.node-icon { color: var(--el-color-warning); flex-shrink: 0; }
.node-label { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.node-count {
  font-size: 11px; color: var(--el-text-color-secondary);
  background: var(--el-fill-color); padding: 0 5px; border-radius: 8px;
}
.node-actions { display: none; }
.tree-node:hover .node-actions { display: flex; }
.empty-tree { padding: 20px 0; text-align: center; }

.cc-main {
  flex: 1; min-width: 0; display: flex; flex-direction: column;
  border: 1px solid var(--el-border-color-lighter); border-radius: 6px;
  background: var(--el-bg-color); overflow: hidden;
}
.cc-toolbar {
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  padding: 10px 12px; border-bottom: 1px solid var(--el-border-color-lighter);
}
.toolbar-left { display: flex; align-items: center; gap: 10px; }
.toolbar-right { display: flex; gap: 8px; }
.module-breadcrumb {
  display: flex; align-items: center; gap: 6px;
  font-size: 13px; font-weight: 500; color: var(--el-text-color-primary);
}
.selected-tag { font-size: 12px; }
.cc-content { flex: 1; overflow: auto; display: flex; flex-direction: column; }
.cc-pager { padding: 10px 12px; display: flex; justify-content: flex-end; }
.module-path { color: var(--el-text-color-secondary); font-size: 12px; }
.parent-hint { color: var(--el-text-color-secondary); font-size: 13px; }
.last-run { font-size: 12px; color: var(--el-text-color-secondary); }
.text-placeholder { color: var(--el-text-color-placeholder); font-size: 12px; }

.cc-detail { display: flex; flex-direction: column; gap: 12px; }
.code-block-title { font-weight: 600; font-size: 13px; }
.code-block {
  margin: 0; padding: 12px; border-radius: 6px; overflow: auto;
  background: var(--el-fill-color-darker); font-size: 12px; line-height: 1.6;
  font-family: Consolas, Monaco, 'Courier New', monospace;
  max-height: 460px; white-space: pre-wrap; word-break: break-all;
}
.ms-gap { margin-left: 8px; color: var(--el-text-color-secondary); font-size: 12px; }

/* 批次结果 */
.batch-result { display: flex; flex-direction: column; gap: 16px; }
.batch-summary {
  display: flex; gap: 16px; align-items: center;
  padding: 16px; background: var(--el-fill-color-light); border-radius: 8px;
}
.summary-item { display: flex; flex-direction: column; align-items: center; min-width: 80px; }
.summary-value { font-size: 24px; font-weight: 700; }
.summary-label { font-size: 12px; color: var(--el-text-color-secondary); margin-top: 2px; }
.summary-item.total .summary-value { color: var(--el-color-primary); }
.summary-item.passed .summary-value { color: var(--el-color-success); }
.summary-item.failed .summary-value { color: var(--el-color-danger); }
.summary-item.rate .summary-value { color: var(--el-color-warning); }
.summary-item.status-indicator { margin-left: auto; }
.batch-progress { margin-top: 8px; }
.result-table { flex: 1; }

/* 执行详情 */
.exec-detail { display: flex; flex-direction: column; gap: 16px; }
.detail-section { display: flex; flex-direction: column; gap: 8px; }
.section-title { font-weight: 600; font-size: 13px; display: flex; align-items: center; gap: 8px; }
.message-box {
  padding: 10px 12px; border-radius: 6px; font-size: 13px;
  background: var(--el-fill-color); color: var(--el-text-color-primary);
}
.message-error {
  background: var(--el-color-danger-light-9);
  color: var(--el-color-danger);
}
.log-block {
  margin: 0; padding: 12px; border-radius: 6px; overflow: auto;
  background: #1e1e1e; color: #d4d4d4;
  font-size: 12px; line-height: 1.6;
  font-family: Consolas, Monaco, 'Courier New', monospace;
  max-height: 300px; white-space: pre-wrap; word-break: break-all;
}
.traceback-block {
  margin: 0; padding: 12px; border-radius: 6px; overflow: auto;
  background: #2d1b1b; color: #ff6b6b;
  font-size: 12px; line-height: 1.5;
  font-family: Consolas, Monaco, 'Courier New', monospace;
  max-height: 200px; white-space: pre-wrap; word-break: break-all;
}
</style>
