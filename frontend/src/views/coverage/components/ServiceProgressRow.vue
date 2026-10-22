<!-- 单服务进度行 -->
<template>
  <div class="service-row" :class="{ failed: report.status === 'failed' }">
    <div class="row-head">
      <div class="svc-name">
        <span class="name">{{ report.service_name }}</span>
        <el-tag :type="statusTagType" size="small" effect="light">{{ statusText }}</el-tag>
        <el-tag v-if="report.stage" size="small" effect="plain" type="info">{{ stageText }}</el-tag>
      </div>
      <div class="svc-actions">
        <el-button
          v-if="report.status === 'completed' && !diffBase"
          link
          type="primary"
          size="small"
          @click="$emit('view-code', report)"
        >查看代码</el-button>
        <el-button
          v-if="report.status === 'failed'"
          link
          type="danger"
          size="small"
          @click="$emit('view-log', report)"
        >查看日志</el-button>
      </div>
    </div>

    <div class="row-body">
      <el-progress
        :percentage="report.progress || 0"
        :status="progressStatus"
        :stroke-width="10"
        class="svc-progress"
      />
      <!-- 迭代任务（配置了 diffBase）不展示全量覆盖率，只看下方增量 -->
      <CoverageRing
        v-if="report.status === 'completed' && !diffBase"
        :line-rate="report.line_rate"
        :branch-rate="report.branch_rate"
        :lines-covered="report.lines_covered"
        :lines-total="report.lines_total"
        :branches-covered="report.branches_covered"
        :branches-total="report.branches_total"
        :size="64"
        :stroke-width="6"
      />
    </div>

    <div v-if="report.status === 'completed' && diffBase" class="diff-block">
      <span class="diff-label">本次迭代增量覆盖（vs {{ diffBase }}）</span>
      <template v-if="diff">
        <span class="diff-rate" :style="{ color: rateColor(diff.line_rate, diff.lines_total) }">
          {{ diff.lines_total ? `${diff.line_rate}%` : '—' }}
        </span>
        <span class="diff-stats">
          {{ diff.lines_total ? `已覆盖 ${diff.lines_covered} / 变更可执行行 ${diff.lines_total}` : '无 Java 代码变更' }}
          · merge-base {{ diff.merge_base.slice(0, 8) }}
        </span>
        <el-button
          v-if="diff.lines_total"
          link
          type="primary"
          size="small"
          @click="$emit('view-diff', report)"
        >查看增量代码</el-button>
      </template>
      <span v-else-if="diffError" class="diff-error">{{ diffError }}</span>
      <el-button link type="primary" size="small" :loading="diffLoading" @click="loadDiff">
        {{ diff || diffError ? '重新计算' : '计算' }}
      </el-button>
    </div>

    <div v-if="report.stage_detail" class="stage-detail">{{ report.stage_detail }}</div>
    <div v-if="report.error_message" class="error-msg">
      <el-icon><WarningFilled /></el-icon>
      <span>{{ report.error_message }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { WarningFilled } from '@element-plus/icons-vue'
import { getReportDiffCoverage } from '@/api/coverage'
import type { DiffCoverage, JavaCoverageReport } from '@/types/coverage'
import CoverageRing from './CoverageRing.vue'

interface Props {
  report: JavaCoverageReport
  /** 任务配置的 diff 基准分支，为空时不展示增量覆盖 */
  diffBase?: string | null
}
const props = defineProps<Props>()

defineEmits<{
  (e: 'view-code', report: JavaCoverageReport): void
  (e: 'view-log', report: JavaCoverageReport): void
  (e: 'view-diff', report: JavaCoverageReport): void
}>()

// 增量覆盖需要后端 git fetch，按需计算而不是随进度自动拉取
const diff = ref<DiffCoverage | null>(null)
const diffError = ref('')
const diffLoading = ref(false)

async function loadDiff(): Promise<void> {
  diffLoading.value = true
  diffError.value = ''
  try {
    diff.value = await getReportDiffCoverage(props.report.id)
  } catch (e: any) {
    diff.value = null
    diffError.value = e?.response?.data?.message || e?.message || '计算失败'
  } finally {
    diffLoading.value = false
  }
}

// 报告完成后自动计算一次；切换报告时重置
watch(
  () => [props.report.id, props.report.status, props.diffBase] as const,
  ([id, status, base], old) => {
    if (old && old[0] !== id) {
      diff.value = null
      diffError.value = ''
    }
    if (status === 'completed' && base && !diff.value && !diffError.value && !diffLoading.value) {
      loadDiff()
    }
  },
  { immediate: true },
)

function rateColor(rate: number, total: number): string {
  if (!total) return 'var(--el-text-color-placeholder)'
  if (rate >= 80) return 'var(--el-color-success)'
  if (rate >= 60) return 'var(--el-color-warning)'
  return 'var(--el-color-danger)'
}

const statusText = computed(() => {
  switch (props.report.status) {
    case 'queued': return '排队中'
    case 'running': return '运行中'
    case 'completed': return '已完成'
    case 'failed': return '失败'
    case 'skipped': return '已跳过'
    case 'cancelled': return '已取消'
    default: return props.report.status
  }
})

const statusTagType = computed(() => {
  switch (props.report.status) {
    case 'completed': return 'success'
    case 'failed': return 'danger'
    case 'running': return 'primary'
    case 'cancelled': return 'info'
    default: return 'info'
  }
})

const progressStatus = computed(() => {
  if (props.report.status === 'failed') return 'exception'
  if (props.report.status === 'completed') return 'success'
  return undefined
})

const stageText = computed(() => {
  switch (props.report.stage) {
    case 'pending': return '待处理'
    case 'clone': return '克隆代码'
    case 'build': return '编译'
    case 'test': return '执行测试'
    case 'report': return '生成报告'
    case 'done': return '完成'
    default: return props.report.stage
  }
})
</script>

<style scoped>
.service-row {
  padding: 12px 16px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  background: var(--el-bg-color);
}
.service-row.failed {
  border-color: var(--el-color-danger-light-7);
  background: var(--el-color-danger-light-9);
}
.row-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.svc-name {
  display: flex;
  align-items: center;
  gap: 8px;
}
.svc-name .name {
  font-weight: 600;
  font-size: 14px;
}
.row-body {
  display: flex;
  align-items: center;
  gap: 16px;
}
.svc-progress {
  flex: 1;
}
.diff-block {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed var(--el-border-color-lighter);
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
  flex-wrap: wrap;
}
.diff-label {
  color: var(--el-text-color-secondary);
}
.diff-rate {
  font-size: 16px;
  font-weight: 600;
}
.diff-stats {
  color: var(--el-text-color-regular);
}
.diff-error {
  color: var(--el-color-danger);
}
.stage-detail {
  margin-top: 6px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.error-msg {
  margin-top: 6px;
  font-size: 12px;
  color: var(--el-color-danger);
  display: flex;
  align-items: center;
  gap: 4px;
}
</style>
