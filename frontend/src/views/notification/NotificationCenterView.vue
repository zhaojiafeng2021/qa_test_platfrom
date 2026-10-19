<template>
  <div class="notification-view">
    <div class="page-head">
      <h1>🔔 飞书通知中心</h1>
    </div>

    <el-tabs v-model="activeTab" class="notification-tabs">
      <!-- 通知规则 -->
      <el-tab-pane label="通知规则" name="rules">
        <div class="toolbar">
          <el-button type="primary" @click="openRuleDialog()">+ 新建规则</el-button>
          <span class="hint">配置何时向哪些人发送哪种消息</span>
        </div>
        <el-table :data="rules" v-loading="loading" stripe>
          <el-table-column prop="name" label="规则名称" min-width="160" />
          <el-table-column label="触发事件" min-width="140">
            <template #default="{ row }">{{ getEventName(row.event_type) }}</template>
          </el-table-column>
          <el-table-column prop="channel_name" label="通知渠道" min-width="140" />
          <el-table-column label="接收人" min-width="120">
            <template #default="{ row }">{{ getRecipientLabel(row.recipient_type) }}</template>
          </el-table-column>
          <el-table-column label="状态" width="80">
            <template #default="{ row }">
              <el-switch v-model="row.enabled" @change="handleToggleRuleEnabled(row as NotificationRule)" />
            </template>
          </el-table-column>
          <el-table-column label="操作" width="160" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="openRuleDialog(row as NotificationRule)">编辑</el-button>
              <el-button link type="danger" size="small" @click="handleDeleteRule(row as NotificationRule)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- 消息模板 -->
      <el-tab-pane label="消息模板" name="templates">
        <el-alert type="info" :closable="false" style="margin-bottom: 16px">
          消息模板由系统预定义。每种模板适配特定事件类型，采用固定的飞书卡片风格。
        </el-alert>
        <el-table :data="templates" v-loading="loading" stripe>
          <el-table-column prop="name" label="模板名称" min-width="160" />
          <el-table-column prop="code" label="标识" min-width="160" />
          <el-table-column label="适用事件" min-width="220">
            <template #default="{ row }">{{ row.event_types?.join(', ') }}</template>
          </el-table-column>
          <el-table-column label="风格" width="100">
            <template #default="{ row }">
              <el-tag :type="getToneType(row.tone) as any" size="small">{{ row.tone }}</el-tag>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- Webhook配置 -->
      <el-tab-pane label="Webhook配置" name="channels">
        <div class="toolbar">
          <el-button type="primary" @click="openChannelDialog()">+ 新建渠道</el-button>
          <span class="hint">配置飞书群机器人 Webhook</span>
        </div>
        <el-table :data="channels" v-loading="loading" stripe>
          <el-table-column prop="name" label="渠道名称" min-width="160" />
          <el-table-column prop="webhook_masked" label="Webhook地址" min-width="220" />
          <el-table-column label="最近测试" width="100">
            <template #default="{ row }">
              <el-tag
                v-if="row.last_test_status"
                :type="row.last_test_status === 'success' ? 'success' : 'danger'"
                size="small"
              >
                {{ row.last_test_status }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="最近触发" width="170">
            <template #default="{ row }">{{ row.last_triggered_at || '—' }}</template>
          </el-table-column>
          <el-table-column label="状态" width="80">
            <template #default="{ row }">
              <el-switch v-model="row.enabled" @change="handleToggleChannelEnabled(row as NotificationChannel)" />
            </template>
          </el-table-column>
          <el-table-column label="操作" width="220" fixed="right">
            <template #default="{ row }">
              <el-button link type="success" size="small" @click="handleTestChannel(row as NotificationChannel)">测试</el-button>
              <el-button link type="primary" size="small" @click="openChannelDialog(row as NotificationChannel)">编辑</el-button>
              <el-button link type="danger" size="small" @click="handleDeleteChannel(row as NotificationChannel)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- 发送历史 -->
      <el-tab-pane label="发送历史" name="history">
        <div class="toolbar">
          <el-select v-model="historyEventFilter" placeholder="事件类型" clearable style="width: 180px" @change="loadHistory">
            <el-option
              v-for="evt in events"
              :key="evt.code"
              :label="evt.name"
              :value="evt.code"
            />
          </el-select>
          <el-select v-model="historyStatusFilter" placeholder="状态" clearable style="width: 120px" @change="loadHistory">
            <el-option label="已发送" value="sent" />
            <el-option label="失败" value="failed" />
            <el-option label="跳过" value="skipped" />
          </el-select>
        </div>
        <el-table :data="deliveries" v-loading="loading" stripe>
          <el-table-column label="创建时间" min-width="170">
            <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column prop="rule_name" label="规则" min-width="140" />
          <el-table-column prop="message_summary" label="消息摘要" min-width="200" show-overflow-tooltip />
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="getStatusType(row.status) as any" size="small">{{ getStatusLabel(row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="attempt_count" label="尝试" width="70" />
          <el-table-column label="错误信息" min-width="180" show-overflow-tooltip>
            <template #default="{ row }">{{ row.error_message || '—' }}</template>
          </el-table-column>
        </el-table>
        <el-pagination
          v-model:current-page="historyPage"
          :page-size="historyPageSize"
          :total="historyTotal"
          layout="prev, pager, next, total"
          style="margin-top: 16px; justify-content: flex-end"
          @current-change="loadHistory"
        />
      </el-tab-pane>
    </el-tabs>

    <ChannelFormDialog
      v-model="showChannelDialog"
      :channel="editingChannel"
      :project-id="projectId ?? 0"
      @success="onChannelSaved"
    />
    <RuleFormDialog
      v-model="showRuleDialog"
      :rule="editingRule"
      :channels="channels"
      :events="events"
      :templates="templates"
      :project-id="projectId ?? 0"
      :project-members="projectMembers"
      @success="onRuleSaved"
    />
  </div>
</template>
<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useProjectStore } from '@/stores/project'
import { notificationApi } from '@/api/notification'
import { projectApi } from '@/api/project'
import type {
  NotificationChannel,
  NotificationRule,
  NotificationDelivery,
  EventCatalog,
  TemplateCatalog,
} from '@/types/notification'
import ChannelFormDialog from './components/ChannelFormDialog.vue'
import RuleFormDialog from './components/RuleFormDialog.vue'

const projectStore = useProjectStore()
const projectId = computed(() => projectStore.currentProjectId)

const activeTab = ref('rules')
const loading = ref(false)

const channels = ref<NotificationChannel[]>([])
const rules = ref<NotificationRule[]>([])
const deliveries = ref<NotificationDelivery[]>([])
const events = ref<EventCatalog[]>([])
const templates = ref<TemplateCatalog[]>([])
const projectMembers = ref<any[]>([])

const historyPage = ref(1)
const historyPageSize = ref(20)
const historyTotal = ref(0)
const historyEventFilter = ref('')
const historyStatusFilter = ref('')

const showChannelDialog = ref(false)
const editingChannel = ref<NotificationChannel | null>(null)
const showRuleDialog = ref(false)
const editingRule = ref<NotificationRule | null>(null)

const getEventName = (code: string): string =>
  events.value.find((e) => e.code === code)?.name || code

const getRecipientLabel = (type: string): string => {
  const map: Record<string, string> = {
    all_members: '全体成员',
    project_admins: '项目管理员',
    event_owner: '事件负责人',
    affected_member: '受影响成员',
    custom: '指定成员',
  }
  return map[type] || type
}

const getToneType = (tone: string): string => {
  const map: Record<string, string> = {
    success: 'success',
    danger: 'danger',
    warning: 'warning',
    info: 'info',
  }
  return map[tone] || 'info'
}

const getStatusType = (status: string): string => {
  const map: Record<string, string> = {
    sent: 'success',
    pending: 'info',
    sending: 'primary',
    retrying: 'warning',
    failed: 'danger',
    skipped: 'info',
  }
  return map[status] || 'info'
}

const getStatusLabel = (status: string): string => {
  const map: Record<string, string> = {
    sent: '已发送',
    pending: '待发送',
    sending: '发送中',
    retrying: '重试中',
    failed: '失败',
    skipped: '已跳过',
  }
  return map[status] || status
}

const formatDateTime = (dateStr: string): string => {
  if (!dateStr) return '—'
  const date = new Date(dateStr)
  // 检查是否为有效日期
  if (isNaN(date.getTime())) return dateStr

  // 格式化为本地时间：YYYY-MM-DD HH:mm:ss
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  const hours = String(date.getHours()).padStart(2, '0')
  const minutes = String(date.getMinutes()).padStart(2, '0')
  const seconds = String(date.getSeconds()).padStart(2, '0')

  return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`
}

const loadCoreData = async () => {
  if (!projectId.value) return
  loading.value = true
  try {
    const [catalog, channelList, ruleList, memberPage] = await Promise.all([
      notificationApi.getCatalog(projectId.value),
      notificationApi.listChannels(projectId.value),
      notificationApi.listRules(projectId.value),
      projectApi.listMembers(projectId.value),
    ])
    events.value = catalog.events
    templates.value = catalog.templates
    channels.value = channelList
    rules.value = ruleList
    projectMembers.value = memberPage.items || []
  } catch (err) {
    ElMessage.error('加载通知数据失败')
  } finally {
    loading.value = false
  }
}

const loadHistory = async () => {
  if (!projectId.value) return
  loading.value = true
  try {
    const page = await notificationApi.listDeliveries(projectId.value, {
      page: historyPage.value,
      page_size: historyPageSize.value,
      event_type: historyEventFilter.value || undefined,
      status: historyStatusFilter.value || undefined,
    })
    deliveries.value = page.items
    historyTotal.value = page.total
  } catch (err) {
    ElMessage.error('加载发送历史失败')
  } finally {
    loading.value = false
  }
}

// Channel handlers
const openChannelDialog = (channel?: NotificationChannel) => {
  editingChannel.value = channel || null
  showChannelDialog.value = true
}

const handleToggleChannelEnabled = async (channel: NotificationChannel) => {
  try {
    await notificationApi.updateChannel(projectId.value!, channel.id, {
      enabled: channel.enabled,
    })
    ElMessage.success(`已${channel.enabled ? '启用' : '停用'}渠道`)
  } catch (err: any) {
    channel.enabled = !channel.enabled
    ElMessage.error(err?.message || '更新失败')
  }
}

const handleTestChannel = async (channel: NotificationChannel) => {
  try {
    await ElMessageBox.confirm(
      '确认向此渠道发送一条测试消息？消息会实际发送到飞书群。',
      '测试发送',
      { type: 'warning' }
    )
    const result = await notificationApi.testChannel(projectId.value!, channel.id, {
      message: '这是一条测试消息',
    })
    if (result.success) {
      ElMessage.success('测试发送成功')
      loadCoreData()
    } else {
      ElMessage.error(`测试失败: ${result.error || '未知错误'}`)
    }
  } catch (err: any) {
    if (err !== 'cancel') ElMessage.error(err?.message || '测试失败')
  }
}

const handleDeleteChannel = async (channel: NotificationChannel) => {
  try {
    await ElMessageBox.confirm(`确认删除渠道「${channel.name}」？`, '删除确认', { type: 'warning' })
    await notificationApi.deleteChannel(projectId.value!, channel.id)
    ElMessage.success('渠道已删除')
    loadCoreData()
  } catch (err: any) {
    if (err !== 'cancel') ElMessage.error(err?.message || '删除失败')
  }
}

const onChannelSaved = () => {
  showChannelDialog.value = false
  loadCoreData()
}

// Rule handlers
const openRuleDialog = (rule?: NotificationRule) => {
  editingRule.value = rule || null
  showRuleDialog.value = true
}

const handleToggleRuleEnabled = async (rule: NotificationRule) => {
  try {
    await notificationApi.updateRule(projectId.value!, rule.id, {
      enabled: rule.enabled,
    })
    ElMessage.success(`已${rule.enabled ? '启用' : '停用'}规则`)
  } catch (err: any) {
    rule.enabled = !rule.enabled
    ElMessage.error(err?.message || '更新失败')
  }
}

const handleDeleteRule = async (rule: NotificationRule) => {
  try {
    await ElMessageBox.confirm(`确认删除规则「${rule.name}」？`, '删除确认', { type: 'warning' })
    await notificationApi.deleteRule(projectId.value!, rule.id)
    ElMessage.success('规则已删除')
    loadCoreData()
  } catch (err: any) {
    if (err !== 'cancel') ElMessage.error(err?.message || '删除失败')
  }
}

const onRuleSaved = () => {
  showRuleDialog.value = false
  loadCoreData()
}

watch(projectId, (val) => {
  if (val) loadCoreData()
})
watch(activeTab, (tab) => {
  if (tab === 'history') loadHistory()
})

onMounted(() => {
  if (projectId.value) loadCoreData()
})
</script>

<style scoped>
.notification-view {
  padding: 20px;
}
.page-head {
  margin-bottom: 20px;
}
.page-head h1 {
  font-size: 24px;
  margin: 0;
}
.notification-tabs {
  background: white;
  padding: 20px;
  border-radius: 4px;
}
.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}
.toolbar .hint {
  color: #909399;
  font-size: 13px;
}
</style>
