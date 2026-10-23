<template>
  <div class="coverage-code-page">
    <div class="page-head">
      <div class="title-row">
        <el-button link :icon="ArrowLeft" @click="goBack">返回</el-button>
        <h1 v-if="isLedger">累积覆盖 · Ledger #{{ ledgerId }}</h1>
        <h1 v-else>行级覆盖 · Report #{{ reportId }}</h1>
        <el-tag v-if="isIteration" size="small" effect="plain">迭代增量</el-tag>
        <span v-if="isIteration && diff" class="diff-summary">
          {{ task?.branch }} vs {{ diff.base_branch }} ·
          <b :style="{ color: diff.lines_total ? diffRateColor(diff.line_rate) : undefined }">
            {{ diff.lines_total ? `${diff.line_rate}%` : '—' }}
          </b>
          （{{ diff.lines_covered }} / {{ diff.lines_total }} 行<template v-if="isLedger">，继承 {{ (diff as LedgerDiffCoverage).lines_inherited }}</template>）
        </span>
      </div>
      <div class="legend">
        <span v-if="isIteration" class="legend-item"><span class="swatch changed" />本次迭代变更行</span>
        <span class="legend-item"><span class="swatch covered" />{{ isLedger ? '实测覆盖' : '已覆盖' }}</span>
        <span v-if="isLedger" class="legend-item"><span class="swatch inherited" />仅继承覆盖</span>
        <span class="legend-item"><span class="swatch missed" />未覆盖</span>
        <span class="legend-item"><span class="swatch partial" />部分覆盖</span>
        <span class="legend-item"><span class="swatch unknown" />无数据</span>
      </div>
    </div>

    <div class="code-layout">
      <div class="file-tree" v-loading="filesLoading">
        <el-input v-model="fileFilter" placeholder="搜索文件" :prefix-icon="Search" clearable size="small" class="file-filter" />
        <el-scrollbar class="file-scroll">
          <div
            v-for="f in filteredFiles"
            :key="f.file_path"
            :class="['file-item', { active: f.file_path === selectedPath }]"
            role="button"
            tabindex="0"
            @click="selectFile(f.file_path)"
            @keydown.enter="selectFile(f.file_path)"
            @keydown.space.prevent="selectFile(f.file_path)"
          >
            <div class="file-name">{{ basename(f.file_path) }}</div>
            <div class="file-path">{{ dirname(f.file_path) }}</div>
            <div v-if="isIteration && diffFiles[f.file_path]" class="file-rate" :style="{ color: diffRateColor(diffFiles[f.file_path].line_rate) }">
              {{ diffFiles[f.file_path].line_rate }}%
              <span class="file-rate-sub">{{ diffFiles[f.file_path].changed_lines_covered }}/{{ diffFiles[f.file_path].changed_lines_total }}</span>
            </div>
            <div v-else class="file-rate" :style="{ color: rateColor(f.line_rate) }">{{ fmtRate(f.line_rate) }}</div>
          </div>
          <el-empty
            v-if="filteredFiles.length === 0"
            :description="isIteration ? (diffError || '本次迭代无变更的 Java 文件') : '无文件'"
            :image-size="48"
          />
        </el-scrollbar>
      </div>

      <div class="code-area" v-loading="contentLoading">
        <template v-if="fileContent">
          <div class="code-head">
            <span class="path">{{ fileContent.file_path }}</span>
          </div>
          <el-alert
            v-if="!fileContent.source_available"
            type="info"
            :closable="false"
            show-icon
            :title="isLedger ? '账本 head commit 对应的报告没有源码快照，仅显示行级覆盖标记。' : '该报告没有源码快照（早期采集或快照上传失败），仅显示行级覆盖标记。重新触发采集后可查看源码。'"
          />
          <el-scrollbar ref="codeScroll" class="code-scroll">
            <div class="code-table">
              <div
                v-for="(line, idx) in sourceLines"
                :key="idx"
                :data-line="idx + 1"
                :class="[
                  'code-line',
                  lineStatus(idx + 1),
                  {
                    changed: changedLineSet.has(idx + 1),
                    dimmed: isIteration && !changedLineSet.has(idx + 1),
                    focused: focusRange && idx + 1 >= focusRange[0] && idx + 1 <= focusRange[1],
                  },
                ]"
              >
                <span class="line-no">{{ idx + 1 }}</span>
                <span class="line-marker" :title="markerTooltip(idx + 1)">{{ markerChar(idx + 1) }}</span>
                <span class="line-code">{{ line }}<span v-if="lineStatus(idx + 1) === 'inherited'" class="inherit-badge" :title="markerTooltip(idx + 1)">继承</span></span>
              </div>
            </div>
          </el-scrollbar>
        </template>
        <el-empty v-else description="请选择左侧文件查看覆盖情况" :image-size="80" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import type { ScrollbarInstance } from 'element-plus'
import { ArrowLeft, Search } from '@element-plus/icons-vue'
import {
  getCoverageTask,
  getLedgerDiffCoverage,
  getLedgerFile,
  getReportDiffCoverage,
  getReportFileContent,
  listLedgerFiles,
  listReportFiles,
} from '@/api/coverage'
import { useProjectStore } from '@/stores/project'
import type {
  CoverageTask,
  DiffCoverage,
  DiffCoverageFile,
  FileContentWithCoverage,
  FileCoverageSummary,
  LedgerDiffCoverage,
  LedgerFileContent,
  LineCoverage,
  LineCoverStatus,
  LineSource,
} from '@/types/coverage'

const route = useRoute()
const router = useRouter()
const projectStore = useProjectStore()
const reportId = computed(() => Number(route.params.reportId))
// 账本模式：同一页面展示累积覆盖，行级数据带来源 sources
const isLedger = computed(() => route.name === 'CoverageLedgerCode')
const ledgerId = computed(() => Number(route.params.ledgerId))

const files = ref<FileCoverageSummary[]>([])
const filesLoading = ref(false)
const fileFilter = ref('')

const fileContent = ref<FileContentWithCoverage | LedgerFileContent | null>(null)
const contentLoading = ref(false)
const selectedPath = ref('')
const codeScroll = ref<ScrollbarInstance | null>(null)

// 从需回归方法跳转过来时高亮方法行范围
const focusPath = typeof route.query.path === 'string' ? route.query.path : ''
const focusRange = ref<[number, number] | null>(null)

function readFocusRange(): [number, number] | null {
  const start = Number(route.query.line)
  if (!Number.isFinite(start) || start <= 0) return null
  const end = Number(route.query.end)
  return [start, Number.isFinite(end) && end >= start ? end : start]
}

// 配置了 diff_base_branch 的任务即迭代任务：只展示本次迭代变更代码的覆盖情况，
// 不展示非本次迭代代码（避免存量代码的覆盖率干扰迭代评估）
const task = ref<CoverageTask | null>(null)
const isIteration = computed(() => !!task.value?.diff_base_branch)
const diff = ref<DiffCoverage | null>(null)
const diffError = ref('')
const diffFiles = computed<Record<string, DiffCoverageFile>>(() => diff.value?.files ?? {})

const filteredFiles = computed(() => {
  const kw = fileFilter.value.trim().toLowerCase()
  let list = files.value
  if (isIteration.value) {
    // 只列有可执行变更行的文件，按增量覆盖率升序（最差的排前面）
    list = list
      .filter((f) => diffFiles.value[f.file_path])
      .sort((a, b) => diffFiles.value[a.file_path].line_rate - diffFiles.value[b.file_path].line_rate)
  }
  if (!kw) return list
  return list.filter((f) => f.file_path.toLowerCase().includes(kw))
})

const changedLineSet = computed<Set<number>>(() => {
  if (!isIteration.value || !selectedPath.value) return new Set()
  const df = diffFiles.value[selectedPath.value]
  return new Set(df?.changed_lines.map((l) => l.line_no) ?? [])
})

async function loadDiff(): Promise<void> {
  try {
    const pid = projectStore.currentProjectId
    diff.value = isLedger.value
      ? (pid ? await getLedgerDiffCoverage(pid, ledgerId.value) : null)
      : await getReportDiffCoverage(reportId.value)
  } catch (e: any) {
    diffError.value = e?.response?.data?.message || e?.message || '增量覆盖率计算失败'
  }
}

const sourceLines = computed(() => {
  const fc = fileContent.value
  if (!fc) return []
  if (fc.source_available) return fc.source.replace(/\r\n?/g, '\n').split('\n')
  // 无源码快照（历史报告）：按最大覆盖行号生成空行，仅展示覆盖标记
  const maxLine = fc.line_coverage.reduce((m, lc) => Math.max(m, lc.line_no), 0)
  return Array.from({ length: maxLine }, () => '')
})

const lineCoverageMap = computed<Map<number, LineCoverage & { sources?: LineSource[] }>>(() => {
  const m = new Map<number, LineCoverage & { sources?: LineSource[] }>()
  for (const lc of fileContent.value?.line_coverage ?? []) {
    m.set(lc.line_no, lc)
  }
  return m
})

const SOURCE_TEXT: Record<LineSource, string> = { unittest: '单测', runtime: '运行时', inherited: '继承' }

function lineStatus(lineNo: number): LineCoverStatus | 'inherited' | 'none' {
  // 迭代任务下非变更行不着色
  if (isIteration.value && !changedLineSet.value.has(lineNo)) return 'none'
  const lc = lineCoverageMap.value.get(lineNo)
  if (!lc) return 'none'
  // 账本中仅靠继承得到的覆盖：浅绿 + 角标，与实测覆盖区分
  if (lc.status === 'covered' && lc.sources?.length === 1 && lc.sources[0] === 'inherited') return 'inherited'
  return lc.status
}

function markerChar(lineNo: number): string {
  const s = lineStatus(lineNo)
  if (s === 'covered' || s === 'missed') return '●'
  if (s === 'inherited') return '○'
  if (s === 'partial') return '◐'
  return ''
}

function markerTooltip(lineNo: number): string {
  if (lineStatus(lineNo) === 'none') return ''
  const lc = lineCoverageMap.value.get(lineNo)
  if (!lc) return ''
  const base = `ci=${lc.covered_instructions} mi=${lc.missed_instructions} cb=${lc.covered_branches} mb=${lc.missed_branches}`
  if (!lc.sources?.length) return base
  return `来源：${lc.sources.map((s) => SOURCE_TEXT[s]).join(' + ')}\n${base}`
}

function basename(p: string): string {
  const parts = p.split('/')
  return parts[parts.length - 1] || p
}

function dirname(p: string): string {
  const parts = p.split('/')
  return parts.slice(0, -1).join('/')
}

function fmtRate(v?: number): string {
  if (v === undefined || v === null) return '—'
  return `${Math.round((v > 1 ? v : v * 100) * 10) / 10}%`
}

function rateColor(v?: number): string {
  if (v === undefined || v === null) return 'var(--el-text-color-placeholder)'
  const p = (v > 1 ? v : v * 100)
  if (p >= 80) return 'var(--el-color-success)'
  if (p >= 60) return 'var(--el-color-warning)'
  return 'var(--el-color-danger)'
}

// 增量覆盖率固定为 0-100，不走 fmtRate/rateColor 的 0-1 兼容判断
function diffRateColor(p: number): string {
  if (p >= 80) return 'var(--el-color-success)'
  if (p >= 60) return 'var(--el-color-warning)'
  return 'var(--el-color-danger)'
}

async function selectFile(path: string): Promise<void> {
  if (selectedPath.value === path) return
  selectedPath.value = path
  contentLoading.value = true
  fileContent.value = null
  try {
    const pid = projectStore.currentProjectId
    if (isLedger.value) {
      if (!pid) return
      fileContent.value = await getLedgerFile(pid, ledgerId.value, path)
    } else {
      fileContent.value = await getReportFileContent(reportId.value, path)
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.message || e?.response?.data?.detail || '加载文件失败')
    selectedPath.value = ''
  } finally {
    contentLoading.value = false
  }
}

async function scrollToFocus(): Promise<void> {
  const range = focusRange.value
  if (!range) return
  await nextTick()
  const wrap = codeScroll.value?.wrapRef
  const el = wrap?.querySelector<HTMLElement>(`[data-line="${range[0]}"]`)
  if (wrap && el) codeScroll.value?.setScrollTop(Math.max(0, el.offsetTop - wrap.clientHeight / 3))
}

function goBack(): void {
  router.push({ name: 'CoverageDetail', params: { taskId: Number(route.params.taskId) } })
}

onMounted(async () => {
  filesLoading.value = true
  try {
    const pid = projectStore.currentProjectId
    const [fileList, t] = await Promise.all([
      isLedger.value
        ? (pid ? listLedgerFiles(pid, ledgerId.value) : Promise.resolve([]))
        : listReportFiles(reportId.value),
      pid ? getCoverageTask(pid, Number(route.params.taskId)) : Promise.resolve(null),
    ])
    files.value = fileList
    task.value = t
    if (isIteration.value) await loadDiff()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.message || e?.response?.data?.detail || '加载文件列表失败')
  } finally {
    filesLoading.value = false
  }
  // 指定了文件（来自需回归方法）时直接打开，即使它不在迭代变更文件中
  if (focusPath && files.value.some((f) => f.file_path === focusPath)) {
    focusRange.value = readFocusRange()
    await selectFile(focusPath)
    await scrollToFocus()
    return
  }
  const first = filteredFiles.value[0]
  if (first) await selectFile(first.file_path)
})
</script>

<style scoped>
.coverage-code-page {
  padding: 20px;
  display: flex;
  flex-direction: column;
  height: 100%;
}
.page-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.title-row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.title-row h1 {
  font-size: 18px;
  font-weight: 600;
  margin: 0;
}
.legend {
  display: flex;
  gap: 16px;
  font-size: 12px;
  color: var(--el-text-color-regular);
}
.legend-item {
  display: flex;
  align-items: center;
  gap: 4px;
}
.swatch {
  display: inline-block;
  width: 12px;
  height: 12px;
  border-radius: 2px;
}
.swatch.covered { background: rgba(103, 194, 58, 0.25); border-left: 3px solid #67c23a; }
.swatch.missed { background: rgba(245, 108, 108, 0.25); border-left: 3px solid #f56c6c; }
.swatch.partial { background: rgba(230, 162, 60, 0.25); border-left: 3px solid #e6a23c; }
.swatch.changed { background: transparent; border-left: 3px solid var(--el-color-primary); }
.diff-summary {
  font-size: 13px;
  color: var(--el-text-color-regular);
}
.file-rate-sub {
  margin-left: 4px;
  font-size: 11px;
  color: var(--el-text-color-secondary);
}
.code-line.changed { box-shadow: inset 3px 0 0 var(--el-color-primary); }
.code-line.dimmed { opacity: 0.45; }
.swatch.unknown { background: var(--el-fill-color); border-left: 3px solid var(--el-border-color); }

.code-layout {
  display: grid;
  grid-template-columns: 300px 1fr;
  gap: 12px;
  flex: 1;
  min-height: 0;
}
.file-tree {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  background: var(--el-bg-color);
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.file-filter {
  padding: 8px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.file-scroll {
  flex: 1;
}
.file-item {
  padding: 8px 12px;
  border-bottom: 1px solid var(--el-border-color-extra-light);
  cursor: pointer;
  position: relative;
}
.file-item:hover { background: var(--el-fill-color-light); }
.file-item.active { background: var(--el-color-primary-light-9); }
.file-name {
  font-size: 13px;
  font-weight: 500;
  font-family: 'JetBrains Mono', 'Consolas', monospace;
}
.file-path {
  font-size: 11px;
  color: var(--el-text-color-secondary);
  font-family: 'JetBrains Mono', 'Consolas', monospace;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.file-rate {
  position: absolute;
  right: 12px;
  top: 8px;
  font-size: 12px;
  font-weight: 600;
}
.code-area {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  background: var(--el-bg-color);
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.code-head {
  padding: 8px 12px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  font-family: 'JetBrains Mono', 'Consolas', monospace;
  font-size: 12px;
  color: var(--el-text-color-regular);
}
.code-scroll {
  flex: 1;
}
.code-table {
  font-family: 'JetBrains Mono', 'Consolas', monospace;
  font-size: 12px;
  line-height: 1.55;
  padding: 8px 0;
}
.code-line {
  display: grid;
  grid-template-columns: 56px 20px 1fr;
  align-items: center;
  padding: 0 8px;
  white-space: pre;
}
.code-line .line-no {
  color: var(--el-text-color-placeholder);
  text-align: right;
  padding-right: 12px;
  user-select: none;
}
.code-line .line-marker {
  color: var(--el-text-color-placeholder);
  user-select: none;
  text-align: center;
}
.code-line.covered { background: rgba(103, 194, 58, 0.12); }
.code-line.covered .line-marker { color: var(--el-color-success); }
.code-line.missed { background: rgba(245, 108, 108, 0.15); }
.code-line.missed .line-marker { color: var(--el-color-danger); }
.code-line.partial { background: rgba(230, 162, 60, 0.15); }
.code-line.partial .line-marker { color: var(--el-color-warning); }
/* 仅继承覆盖：浅绿 + 角标，区分于实测覆盖 */
.code-line.inherited { background: rgba(103, 194, 58, 0.05); }
.code-line.inherited .line-marker { color: #95d475; }
.code-line.focused { outline: 1px dashed var(--el-color-primary); outline-offset: -1px; }
.inherit-badge {
  margin-left: 8px;
  padding: 0 4px;
  font-size: 10px;
  line-height: 14px;
  border-radius: 3px;
  color: #529b2e;
  background: rgba(149, 212, 117, 0.25);
  user-select: none;
}
.swatch.inherited { background: rgba(103, 194, 58, 0.08); border-left: 3px solid #b3e19d; }
</style>
