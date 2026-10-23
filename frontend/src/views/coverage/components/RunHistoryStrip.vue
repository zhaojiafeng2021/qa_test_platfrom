<!-- 历史 run 横向滚动条 -->
<template>
  <div class="run-strip">
    <div
      v-for="run in runs"
      :key="run.id"
      :class="['run-card', statusClass(run.overall_status), { active: run.id === currentRunId }]"
      @click="$emit('select', run)"
    >
      <div class="run-head">
        <span class="run-id">#{{ run.id }}</span>
        <span class="trigger">{{ triggerText(run.trigger_type) }}</span>
      </div>
      <div class="run-status">{{ statusText(run.overall_status) }}</div>
      <div class="run-progress">
        <span class="done">{{ run.services_completed }}</span>
        <span class="sep">/</span>
        <span class="total">{{ run.services_total }}</span>
        <span v-if="run.services_failed" class="failed">({{ run.services_failed }} 失败)</span>
      </div>
      <div class="run-time">{{ formatTime(run.finished_at || run.started_at || run.created_at) }}</div>
    </div>
    <div v-if="runs.length === 0" class="empty">暂无历史记录</div>
  </div>
</template>

<script setup lang="ts">
import type { JavaCoverageRun, RunStatus, TriggerType } from '@/types/coverage'
import { formatTime } from '@/utils/format'

interface Props {
  runs: JavaCoverageRun[]
  currentRunId?: number
}
defineProps<Props>()

defineEmits<{
  (e: 'select', run: JavaCoverageRun): void
}>()

function statusClass(s: RunStatus): string {
  return `st-${s}`
}

function statusText(s: RunStatus): string {
  switch (s) {
    case 'queued': return '排队中'
    case 'running': return '运行中'
    case 'completed': return '成功'
    case 'failed': return '失败'
    case 'cancelled': return '已取消'
    case 'partial': return '部分成功'
    default: return s
  }
}

function triggerText(t: TriggerType): string {
  switch (t) {
    case 'manual': return '手动'
    case 'cron': return '定时'
    case 'retry': return '重试'
    default: return t
  }
}
</script>

<style scoped>
.run-strip {
  display: flex;
  gap: 8px;
  overflow-x: auto;
  padding: 4px 0;
}
.run-card {
  flex: 0 0 auto;
  min-width: 140px;
  padding: 8px 10px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  background: var(--el-bg-color);
  cursor: pointer;
  transition: all 0.15s;
  font-size: 12px;
}
.run-card:hover {
  border-color: var(--el-color-primary-light-5);
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08);
}
.run-card.active {
  border-color: var(--el-color-primary);
  box-shadow: 0 0 0 1px var(--el-color-primary-light-7);
}
.run-head {
  display: flex;
  justify-content: space-between;
  color: var(--el-text-color-secondary);
  margin-bottom: 4px;
}
.run-id {
  font-weight: 600;
}
.run-status {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 4px;
}
.st-completed .run-status { color: var(--el-color-success); }
.st-failed .run-status { color: var(--el-color-danger); }
.st-running .run-status { color: var(--el-color-primary); }
.st-partial .run-status { color: var(--el-color-warning); }
.st-cancelled .run-status { color: var(--el-text-color-secondary); }
.st-queued .run-status { color: var(--el-text-color-secondary); }
.run-progress {
  color: var(--el-text-color-regular);
  margin-bottom: 4px;
}
.run-progress .failed {
  color: var(--el-color-danger);
  margin-left: 4px;
}
.run-time {
  color: var(--el-text-color-secondary);
  font-size: 11px;
}
.empty {
  padding: 12px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
</style>
