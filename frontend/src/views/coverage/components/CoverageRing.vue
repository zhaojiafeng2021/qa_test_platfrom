<!-- 覆盖率环形图：双环（行覆盖 + 分支覆盖） -->
<template>
  <div class="coverage-ring">
    <div class="ring-item">
      <el-progress
        type="circle"
        :percentage="pct(lineRate)"
        :width="size"
        :stroke-width="strokeWidth"
        :color="colorFor(lineRate)"
      >
        <template #default>
          <div class="ring-label">
            <div class="ring-value">{{ pct(lineRate) }}%</div>
            <div class="ring-name">行覆盖</div>
          </div>
        </template>
      </el-progress>
      <div v-if="showNumbers" class="ring-num">{{ covered(linesCovered) }}/{{ covered(linesTotal) }}</div>
    </div>
    <div v-if="branchRate !== undefined && branchRate !== null" class="ring-item">
      <el-progress
        type="circle"
        :percentage="pct(branchRate)"
        :width="size"
        :stroke-width="strokeWidth"
        :color="colorFor(branchRate)"
      >
        <template #default>
          <div class="ring-label">
            <div class="ring-value">{{ pct(branchRate) }}%</div>
            <div class="ring-name">分支</div>
          </div>
        </template>
      </el-progress>
      <div v-if="showNumbers" class="ring-num">{{ covered(branchesCovered) }}/{{ covered(branchesTotal) }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
interface Props {
  lineRate?: number
  branchRate?: number
  linesCovered?: number
  linesTotal?: number
  branchesCovered?: number
  branchesTotal?: number
  size?: number
  strokeWidth?: number
  showNumbers?: boolean
}

withDefaults(defineProps<Props>(), {
  size: 88,
  strokeWidth: 8,
  showNumbers: true,
})

function pct(v?: number): number {
  if (v === undefined || v === null || Number.isNaN(v)) return 0
  // 后端约定为 0-1 之间的小数；防御性处理 0-100
  const val = v > 1 ? v : v * 100
  return Math.max(0, Math.min(100, Math.round(val * 10) / 10))
}

function covered(v?: number): string {
  return v === undefined || v === null ? '—' : String(v)
}

function colorFor(v?: number): string {
  const p = pct(v)
  if (p >= 80) return '#67c23a'
  if (p >= 60) return '#e6a23c'
  if (p > 0) return '#f56c6c'
  return '#c0c4cc'
}
</script>

<style scoped>
.coverage-ring {
  display: inline-flex;
  gap: 16px;
  align-items: center;
}
.ring-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}
.ring-label {
  text-align: center;
  line-height: 1.1;
}
.ring-value {
  font-size: 16px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}
.ring-name {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-top: 2px;
}
.ring-num {
  font-size: 11px;
  color: var(--el-text-color-secondary);
}
</style>
