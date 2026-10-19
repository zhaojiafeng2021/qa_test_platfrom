<template>
  <div class="schedule-page" v-loading="loading">
    <div class="page-head">
      <h1><el-icon><Timer /></el-icon>定时任务</h1>
      <el-button type="primary" :icon="Plus" @click="openEditor()">新建定时任务</el-button>
    </div>

    <section class="table-panel">
      <div class="table-toolbar"><h3>任务列表</h3><el-button :icon="Refresh" circle @click="load" /></div>
      <el-table :data="schedules" empty-text="暂无定时任务">
        <el-table-column prop="name" label="任务名称" min-width="180"><template #default="scope"><b>{{ scope.row.name }}</b></template></el-table-column>
        <el-table-column label="Cron 表达式" min-width="150"><template #default="scope"><code>{{ scope.row.cron_expression }}</code></template></el-table-column>
        <el-table-column label="关联计划" min-width="190"><template #default="scope">{{ planName(scope.row.plan_id) }}</template></el-table-column>
        <el-table-column label="下次执行" min-width="180"><template #default="scope">{{ formatTime(scope.row.next_run_at) }}</template></el-table-column>
        <el-table-column label="状态" width="110"><template #default="scope"><el-tag :type="scope.row.enabled ? 'success' : 'info'" size="small">{{ scope.row.enabled ? '已启用' : '已停用' }}</el-tag></template></el-table-column>
        <el-table-column label="操作" width="190" fixed="right"><template #default="scope">
          <el-button link type="primary" @click="toggle(scope.row as Schedule)">{{ scope.row.enabled ? '停用' : '启用' }}</el-button>
          <el-button link @click="openEditor(scope.row as Schedule)">编辑</el-button>
          <el-popconfirm title="确认删除该定时任务？" @confirm="remove(scope.row as Schedule)"><template #reference><el-button link type="danger">删除</el-button></template></el-popconfirm>
        </template></el-table-column>
      </el-table>
    </section>

    <el-dialog v-model="editorVisible" title="定时任务配置" width="620px">
      <el-form label-position="top">
        <div class="form-grid">
          <el-form-item label="任务名称"><el-input v-model="form.name" placeholder="例如：每日凌晨回归" /></el-form-item>
          <el-form-item label="关联计划"><el-select v-model="form.plan_id" filterable placeholder="选择测试计划"><el-option v-for="plan in plans" :key="plan.id" :label="plan.name" :value="plan.id" /></el-select></el-form-item>
        </div>
        <div class="form-grid">
          <el-form-item label="Cron 表达式"><el-input v-model="form.cron_expression" placeholder="0 2 * * *" /></el-form-item>
          <el-form-item label="时区"><el-select v-model="form.timezone" filterable allow-create><el-option v-for="zone in timezones" :key="zone" :label="zone" :value="zone" /></el-select></el-form-item>
        </div>
        <el-form-item><el-switch v-model="form.enabled" active-text="启用定时任务" /></el-form-item>
        <el-alert title="Cron 使用五段格式：分钟 小时 日期 月份 星期" type="info" :closable="false" show-icon />
      </el-form>
      <template #footer><el-button @click="editorVisible=false">取消</el-button><el-button type="primary" :loading="saving" @click="save">保存</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { Plus, Refresh, Timer } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useProjectStore } from '@/stores/project'
import * as api from '@/api/test-plan'
import type { Schedule, TestPlan } from '@/types/test-plan'
import { parseUTC } from '@/utils/datetime'

const store = useProjectStore()
const projectId = computed(() => store.currentProjectId)
const loading = ref(false)
const saving = ref(false)
const schedules = ref<Schedule[]>([])
const plans = ref<TestPlan[]>([])
const editorVisible = ref(false)
const editingId = ref<number>()
const timezones = ['Asia/Shanghai', 'UTC', 'Asia/Tokyo', 'Europe/London', 'America/New_York']
const form = reactive({ name: '', plan_id: undefined as number | undefined, cron_expression: '0 2 * * *', timezone: 'Asia/Shanghai', enabled: true })

watch(projectId, id => { if (id) load() }, { immediate: true })

async function load() {
  if (!projectId.value) return
  loading.value = true
  try {
    const [scheduleList, planPage] = await Promise.all([api.listSchedules(projectId.value), api.listPlans(projectId.value, { page_size: 100 })])
    schedules.value = scheduleList
    plans.value = planPage.items
  } finally {
    loading.value = false
  }
}

function openEditor(schedule?: Schedule) {
  editingId.value = schedule?.id
  Object.assign(form, {
    name: schedule?.name || '',
    plan_id: schedule?.plan_id,
    cron_expression: schedule?.cron_expression || '0 2 * * *',
    timezone: schedule?.timezone || 'Asia/Shanghai',
    enabled: schedule?.enabled ?? true,
  })
  editorVisible.value = true
}

async function save() {
  if (!projectId.value || !form.plan_id) return ElMessage.warning('请选择关联计划')
  if (!form.name.trim() || !form.cron_expression.trim()) return ElMessage.warning('请填写任务名称和 Cron 表达式')
  saving.value = true
  try {
    const payload = { plan_id: form.plan_id, name: form.name.trim(), cron_expression: form.cron_expression.trim(), timezone: form.timezone, enabled: form.enabled }
    if (editingId.value) await api.updateSchedule(projectId.value, editingId.value, payload)
    else await api.createSchedule(projectId.value, form.plan_id, payload)
    editorVisible.value = false
    await load()
    ElMessage.success('定时任务已保存')
  } finally {
    saving.value = false
  }
}

async function toggle(schedule: Schedule) {
  if (!projectId.value) return
  await api.updateSchedule(projectId.value, schedule.id, { enabled: !schedule.enabled })
  await load()
}

async function remove(schedule: Schedule) {
  if (!projectId.value) return
  await api.deleteSchedule(projectId.value, schedule.id)
  await load()
  ElMessage.success('定时任务已删除')
}

const planName = (id: number) => plans.value.find(plan => plan.id === id)?.name || `计划 #${id}`
const formatTime = (value?: string) => value ? new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(parseUTC(value)) : '--'
</script>

<style scoped>
.page-head h1 { display: flex; align-items: center; gap: 8px; }
.table-panel { background: #fff; border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }
.table-toolbar { height: 52px; padding: 0 16px; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid var(--line); }
.table-toolbar h3 { margin: 0; font-size: 14px; }
code { padding: 3px 7px; border-radius: 5px; background: var(--line2); color: var(--txt2); }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.form-grid :deep(.el-select) { width: 100%; }
@media (max-width: 760px) { .form-grid { grid-template-columns: 1fr; gap: 0; } }
</style>
