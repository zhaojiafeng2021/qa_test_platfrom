<!-- 累积覆盖：每个服务的当前轮次账本 + 来源拆分 + 需回归方法 + 合并历史 -->
<template>
  <el-card class="ledger-card" shadow="never" v-loading="loading">
    <template #header>
      <div class="card-head">
        <span>累积覆盖</span>
        <el-button
          v-if="canRun && hasActive"
          size="small"
          :disabled="running"
          @click="newRound()"
        >全部服务开始新一轮</el-button>
      </div>
    </template>

    <el-empty v-if="!loading && services.length === 0" description="尚未采集，完成首次采集后生成累积账本" :image-size="60" />

    <el-tabs v-else v-model="activeService" class="svc-tabs">
      <el-tab-pane v-for="s in services" :key="s.service_name" :name="s.service_name" :label="s.service_name">
        <el-alert
          v-if="s.branch_mismatch"
          type="warning"
          :closable="false"
          show-icon
          :title="`任务分支已改为 ${task.branch}，下次采集将开始新一轮，当前账本（${s.active?.branch}）只读保留`"
          class="block"
        />
        <el-empty v-if="s.rounds.length === 0" description="该服务尚无账本" :image-size="48" />
      </el-tab-pane>
    </el-tabs>

    <template v-if="ledger">
      <div class="ledger-head">
        <el-select v-model="selectedLedgerId" size="small" class="round-select">
          <el-option
            v-for="r in currentService?.rounds ?? []"
            :key="r.id"
            :value="r.id"
            :label="`第 ${r.round_no} 轮 · ${r.branch}${r.is_active ? '（当前）' : '（只读）'}`"
          />
        </el-select>
        <span class="meta">head <code>{{ shortSha(ledger.head_commit) }}</code></span>
        <span class="meta">更新于 {{ formatTime(ledger.updated_at) }}</span>
        <div class="spacer" />
        <el-button link type="primary" size="small" @click="emit('view-code', ledger.id)">查看累积代码</el-button>
        <el-button
          v-if="canRun && ledger.is_active"
          link
          type="danger"
          size="small"
          :disabled="running"
          @click="newRound(ledger.service_name)"
        >开始新一轮</el-button>
      </div>

      <div class="metrics">
        <div class="metric">
          <div class="label">全量行覆盖</div>
          <div class="value" :style="{ color: rateColor(ledger.line_rate, ledger.lines_total) }">{{ fmtPct(ledger.line_rate, ledger.lines_total) }}</div>
          <div class="sub">{{ ledger.lines_covered ?? 0 }} / {{ ledger.lines_total ?? 0 }} 行</div>
        </div>
        <div class="metric">
          <div class="label">分支覆盖</div>
          <div class="value" :style="{ color: rateColor(ledger.branch_rate, ledger.branches_total) }">{{ fmtPct(ledger.branch_rate, ledger.branches_total) }}</div>
          <div class="sub">{{ ledger.branches_covered ?? 0 }} / {{ ledger.branches_total ?? 0 }}</div>
        </div>
        <div v-if="task.diff_base_branch" class="metric">
          <div class="label">增量覆盖（vs {{ task.diff_base_branch }}）</div>
          <template v-if="diff">
            <div class="value" :style="{ color: rateColor(diff.line_rate, diff.lines_total) }">{{ fmtPct(diff.line_rate, diff.lines_total) }}</div>
            <div class="sub">
              {{ diff.lines_total ? `${diff.lines_covered} / ${diff.lines_total} 行，其中继承 ${diff.lines_inherited}` : '无 Java 代码变更' }}
              <el-button v-if="diff.lines_total" link type="primary" size="small" @click="emit('view-code', ledger.id)">查看</el-button>
            </div>
          </template>
          <div v-else-if="diffError" class="sub error">{{ diffError }}</div>
          <div v-else class="sub">计算中…</div>
        </div>
        <div class="metric sources">
          <div class="label">已覆盖行来源</div>
          <div class="source-bar">
            <span
              v-for="b in sourceBars"
              :key="b.key"
              :class="['seg', b.key]"
              :style="{ width: `${b.pct}%` }"
              :title="`${b.label} ${b.lines} 行（${b.pct.toFixed(1)}%）`"
            />
          </div>
          <div class="source-legend">
            <span v-for="b in sourceBars" :key="b.key" class="item">
              <span :class="['dot', b.key]" />{{ b.label }} {{ b.lines }}
            </span>
          </div>
        </div>
      </div>

      <el-alert
        v-if="latestMismatch.length"
        type="warning"
        :closable="false"
        show-icon
        class="block"
        :title="`最近一次采集有 ${latestMismatch.length} 个类的 exec 与编译 class 不一致，这些类的覆盖未计入`"
      >
        <div class="class-list">{{ latestMismatch.join('\n') }}</div>
      </el-alert>

      <el-tabs v-model="detailTab" class="detail-tabs">
        <el-tab-pane name="regression">
          <template #label>
            需回归方法
            <el-badge v-if="pendingRegression" :value="pendingRegression" type="danger" class="tab-badge" />
          </template>
          <el-table :data="events?.regression_methods ?? []" size="small" max-height="360" empty-text="没有因代码变更被清零的方法">
            <el-table-column label="方法" min-width="320">
              <template #default="{ row }">
                <el-button link type="primary" class="method-link" @click="emit('view-code', ledger!.id, row.file_path, row.start ?? undefined, row.end ?? undefined)">
                  {{ methodLabel(row.key) }}
                </el-button>
                <div class="method-path">{{ row.file_path }}<template v-if="row.start">:{{ row.start }}</template></div>
              </template>
            </el-table-column>
            <el-table-column label="清零于" width="110">
              <template #default="{ row }"><code>{{ shortSha(row.reset_at_commit) }}</code></template>
            </el-table-column>
            <el-table-column label="覆盖" width="110">
              <template #default="{ row }">{{ row.covered_lines }} / {{ row.executable_lines }}</template>
            </el-table-column>
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag v-if="row.recovered" type="success" size="small">已回归</el-tag>
                <el-tag v-else type="danger" size="small">待回归</el-tag>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane label="合并历史" name="history">
          <el-timeline v-if="events?.events.length" class="timeline">
            <el-timeline-item
              v-for="e in events.events"
              :key="e.id"
              :timestamp="formatTime(e.created_at)"
              :type="directionType(e.direction)"
              placement="top"
            >
              <div class="event-row">
                <el-tag size="small" :type="directionType(e.direction)" effect="light">{{ directionText(e) }}</el-tag>
                <el-tag v-if="e.source" size="small" effect="plain">{{ e.source === 'runtime' ? '运行时' : '单测' }}</el-tag>
                <span class="commits">
                  <template v-if="e.from_commit && e.from_commit !== e.to_commit"><code>{{ shortSha(e.from_commit) }}</code> → </template>
                  <code>{{ shortSha(e.to_commit) }}</code>
                </span>
                <span v-if="e.line_rate_after !== null && e.line_rate_after !== undefined" class="rate-change">
                  {{ e.line_rate_before !== null && e.line_rate_before !== undefined ? `${e.line_rate_before}%` : '—' }} → {{ e.line_rate_after }}%
                  <span v-if="rateDelta(e) !== null" :class="['delta', rateDelta(e)! >= 0 ? 'up' : 'down']">
                    {{ rateDelta(e)! >= 0 ? '+' : '' }}{{ rateDelta(e) }}
                  </span>
                </span>
              </div>
              <div v-if="e.direction !== 'new_round'" class="event-stats">
                保留 {{ e.methods_kept }} · 清零 {{ e.methods_reset }} · 删除 {{ e.methods_removed }} · 新增 {{ e.methods_added }}
                <span v-if="e.mismatch_classes_json?.length" class="warn">· class 不一致 {{ e.mismatch_classes_json.length }}</span>
              </div>
            </el-timeline-item>
          </el-timeline>
          <el-empty v-else description="暂无合并记录" :image-size="48" />
        </el-tab-pane>
      </el-tabs>
    </template>
  </el-card>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getLedgerDiffCoverage, getLedgerEvents, getTaskLedgers, startLedgerNewRound } from '@/api/coverage'
import { formatTime } from '@/utils/format'
import type {
  CoverageLedger,
  CoverageLedgerEvent,
  CoverageTask,
  LedgerDiffCoverage,
  LedgerDirection,
  LedgerEvents,
  ServiceLedgers,
} from '@/types/coverage'

const props = defineProps<{
  projectId: number
  task: CoverageTask
  canRun: boolean
  /** 采集进行中不允许开新一轮（后端同样 409） */
  running: boolean
}>()

const emit = defineEmits<{
  (e: 'view-code', ledgerId: number, path?: string, line?: number, end?: number): void
}>()

const loading = ref(false)
const services = ref<ServiceLedgers[]>([])
const activeService = ref('')
const selectedLedgerId = ref<number | null>(null)
const detailTab = ref<'regression' | 'history'>('regression')

const events = ref<LedgerEvents | null>(null)
const diff = ref<LedgerDiffCoverage | null>(null)
const diffError = ref('')

const currentService = computed(() => services.value.find((s) => s.service_name === activeService.value))
const ledger = computed<CoverageLedger | null>(
  () => currentService.value?.rounds.find((r) => r.id === selectedLedgerId.value) ?? null,
)
const hasActive = computed(() => services.value.some((s) => s.active))

const mismatchServices = computed(() => services.value.filter((s) => s.branch_mismatch).map((s) => s.service_name))

const pendingRegression = computed(() => events.value?.regression_methods.filter((m) => !m.recovered).length ?? 0)

// 最近一次真实采集（跳过 new_round 标记事件）的 class 不一致列表
const latestMismatch = computed<string[]>(() => {
  const e = events.value?.events.find((x) => x.direction !== 'new_round')
  return e?.mismatch_classes_json ?? []
})

// 一行可能同时有多个来源，各段按占 lines_total 的比例画，不相加到 100%
const sourceBars = computed(() => {
  const l = ledger.value
  const total = l?.lines_total || 0
  const st = l?.source_stats
  const items = [
    { key: 'unittest', label: '单测', lines: st?.unittest_lines ?? 0 },
    { key: 'runtime', label: '运行时', lines: st?.runtime_lines ?? 0 },
    { key: 'inherited', label: '继承', lines: st?.inherited_lines ?? 0 },
  ]
  return items.map((i) => ({ ...i, pct: total ? (i.lines * 100) / total : 0 }))
})

function shortSha(s?: string | null): string {
  return s ? s.slice(0, 8) : '—'
}

function fmtPct(v?: number | null, total?: number | null): string {
  if (!total || v === null || v === undefined) return '—'
  return `${v}%`
}

function rateColor(v?: number | null, total?: number | null): string {
  if (!total || v === null || v === undefined) return 'var(--el-text-color-placeholder)'
  if (v >= 80) return 'var(--el-color-success)'
  if (v >= 60) return 'var(--el-color-warning)'
  return 'var(--el-color-danger)'
}

function rateDelta(e: CoverageLedgerEvent): number | null {
  if (e.line_rate_before === null || e.line_rate_before === undefined) return null
  if (e.line_rate_after === null || e.line_rate_after === undefined) return null
  return Math.round((e.line_rate_after - e.line_rate_before) * 100) / 100
}

function methodLabel(key: string): string {
  // com.foo.OrderService#create(String) → OrderService#create(String)
  const [cls, rest] = key.split('#')
  const simple = cls.split('.').pop() || cls
  return rest ? `${simple}#${rest}` : simple
}

function directionText(e: CoverageLedgerEvent): string {
  switch (e.direction) {
    case 'init': return '首次采集'
    case 'same': return '同版本合并'
    case 'forward': return '代码前进'
    case 'backward': return '代码回退'
    case 'diverged': return '分叉合并'
    case 'new_round': return e.reason === 'branch_switch' ? '切换分支 · 新一轮' : '手动开始新一轮'
    default: return e.direction
  }
}

function directionType(d: LedgerDirection): 'primary' | 'success' | 'warning' | 'danger' | 'info' {
  switch (d) {
    case 'forward': return 'primary'
    case 'same': return 'success'
    case 'backward':
    case 'diverged': return 'warning'
    case 'new_round': return 'danger'
    default: return 'info'
  }
}

async function load(): Promise<void> {
  loading.value = true
  try {
    services.value = await getTaskLedgers(props.projectId, props.task.id)
    if (!services.value.some((s) => s.service_name === activeService.value)) {
      activeService.value = services.value[0]?.service_name ?? ''
    }
    pickDefaultLedger(true)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.message || '加载累积覆盖失败')
  } finally {
    loading.value = false
  }
}

/** 切换服务或刷新后：保留仍存在的选择，否则选当前轮次 */
function pickDefaultLedger(keep: boolean): void {
  const s = currentService.value
  if (keep && s?.rounds.some((r) => r.id === selectedLedgerId.value)) {
    void loadLedgerDetail()
    return
  }
  selectedLedgerId.value = s?.active?.id ?? s?.rounds[0]?.id ?? null
}

async function loadLedgerDetail(): Promise<void> {
  const id = selectedLedgerId.value
  events.value = null
  diff.value = null
  diffError.value = ''
  if (!id) return
  try {
    const ev = await getLedgerEvents(props.projectId, id)
    if (selectedLedgerId.value === id) events.value = ev
  } catch {
    // 全局拦截器已提示
  }
  if (!props.task.diff_base_branch) return
  try {
    const d = await getLedgerDiffCoverage(props.projectId, id)
    if (selectedLedgerId.value === id) diff.value = d
  } catch (e: any) {
    if (selectedLedgerId.value === id) diffError.value = e?.response?.data?.message || e?.message || '增量覆盖率计算失败'
  }
}

async function newRound(serviceName?: string): Promise<void> {
  const target = serviceName ? `服务 ${serviceName}` : '全部服务'
  try {
    await ElMessageBox.confirm(
      `${target}的当前账本将关闭并只读保留，下次采集从零开始累积。确认开始新一轮？`,
      '开始新一轮',
      { type: 'warning', confirmButtonText: '开始新一轮' },
    )
  } catch {
    return
  }
  try {
    const res = await startLedgerNewRound(props.projectId, props.task.id, serviceName)
    ElMessage.success(res.closed_services.length ? `已关闭：${res.closed_services.join('、')}，下次采集生效` : '没有需要关闭的账本')
    await load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.message || '操作失败')
  }
}

watch(activeService, () => pickDefaultLedger(false))
watch(selectedLedgerId, () => void loadLedgerDetail())
watch(() => props.task.id, () => void load(), { immediate: true })

defineExpose({ reload: load, mismatchServices })
</script>

<style scoped>
.ledger-card { margin-bottom: 16px; }
.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.svc-tabs :deep(.el-tabs__header) { margin-bottom: 8px; }
.block { margin-bottom: 12px; }
.ledger-head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
  font-size: 12px;
}
.round-select { width: 240px; }
.meta { color: var(--el-text-color-secondary); }
.spacer { flex: 1; }
code {
  font-family: 'JetBrains Mono', 'Consolas', monospace;
  font-size: 12px;
}
.metrics {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
  margin-bottom: 12px;
}
.metric {
  padding: 10px 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
}
.metric.sources { grid-column: span 2; min-width: 0; }
.metric .label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.metric .value {
  font-size: 22px;
  font-weight: 600;
  margin: 4px 0 2px;
}
.metric .sub {
  font-size: 12px;
  color: var(--el-text-color-regular);
}
.metric .sub.error { color: var(--el-color-danger); }
.source-bar {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin: 10px 0 8px;
}
.source-bar .seg {
  display: block;
  height: 8px;
  border-radius: 4px;
  min-width: 2px;
}
.seg.unittest, .dot.unittest { background: #67c23a; }
.seg.runtime, .dot.runtime { background: #409eff; }
.seg.inherited, .dot.inherited { background: #b3e19d; }
.source-legend {
  display: flex;
  gap: 16px;
  font-size: 12px;
  color: var(--el-text-color-regular);
}
.source-legend .item {
  display: flex;
  align-items: center;
  gap: 4px;
}
.dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.class-list {
  white-space: pre-wrap;
  font-family: 'JetBrains Mono', 'Consolas', monospace;
  font-size: 12px;
  max-height: 120px;
  overflow: auto;
}
.tab-badge { margin-left: 4px; }
.method-link {
  font-family: 'JetBrains Mono', 'Consolas', monospace;
  font-size: 12px;
}
.method-path {
  font-size: 11px;
  color: var(--el-text-color-secondary);
  font-family: 'JetBrains Mono', 'Consolas', monospace;
}
.timeline {
  max-height: 400px;
  overflow: auto;
  padding: 4px 4px 0;
}
.event-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 13px;
}
.rate-change { color: var(--el-text-color-regular); }
.delta.up { color: var(--el-color-success); margin-left: 4px; }
.delta.down { color: var(--el-color-danger); margin-left: 4px; }
.event-stats {
  margin-top: 4px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.event-stats .warn { color: var(--el-color-warning); }
</style>
