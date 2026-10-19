<template>
  <el-dialog
    :model-value="modelValue"
    :title="isEdit ? '编辑规则' : '新建规则'"
    width="640px"
    @update:model-value="$emit('update:modelValue', $event)"
    @close="handleClose"
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="110px">
      <el-form-item label="规则名称" prop="name">
        <el-input v-model="form.name" placeholder="如：执行失败告警" maxlength="200" />
      </el-form-item>
      <el-form-item label="触发事件" prop="event_type">
        <el-select v-model="form.event_type" placeholder="选择事件" style="width: 100%" @change="onEventChange">
          <el-option v-for="e in events" :key="e.code" :label="e.name" :value="e.code">
            <span>{{ e.name }}</span>
            <span class="opt-hint">{{ e.description }}</span>
          </el-option>
        </el-select>
      </el-form-item>
      <el-form-item label="消息模板" prop="template_code">
        <el-select v-model="form.template_code" placeholder="选择模板" style="width: 100%">
          <el-option
            v-for="t in compatibleTemplates"
            :key="t.code"
            :label="t.name"
            :value="t.code"
          />
        </el-select>
        <div v-if="form.event_type && compatibleTemplates.length === 0" class="tip warn">
          当前事件无匹配模板，将使用默认模板
        </div>
      </el-form-item>
      <el-form-item label="通知渠道" prop="channel_id">
        <el-select v-model="form.channel_id" placeholder="选择渠道" style="width: 100%">
          <el-option
            v-for="c in enabledChannels"
            :key="c.id"
            :label="c.name"
            :value="c.id"
          />
        </el-select>
        <div v-if="enabledChannels.length === 0" class="tip warn">
          无可用渠道，请先在 Webhook 配置中创建并启用渠道
        </div>
      </el-form-item>
      <el-form-item label="接收人" prop="recipient_type">
        <el-select v-model="form.recipient_type" placeholder="选择接收人范围" style="width: 100%">
          <el-option label="全体成员" value="all_members" />
          <el-option label="项目管理员" value="project_admins" />
          <el-option label="事件负责人" value="event_owner" />
          <el-option label="受影响成员" value="affected_member" />
          <el-option label="指定成员" value="custom" />
        </el-select>
        <div class="tip">未绑定飞书身份的接收人会被自动跳过。若最终无有效接收人，通知将被跳过。</div>
      </el-form-item>
      <el-form-item v-if="form.recipient_type === 'custom'" label="指定成员">
        <el-select
          v-model="customUserIds"
          multiple
          filterable
          placeholder="选择项目成员"
          style="width: 100%"
        >
          <el-option
            v-for="member in projectMembers"
            :key="member.user_id"
            :label="member.full_name || member.username"
            :value="member.user_id"
          >
            <span>{{ member.full_name || member.username }}</span>
            <span v-if="member.full_name" class="opt-hint">{{ member.username }}</span>
          </el-option>
        </el-select>
        <div class="tip">选择需要接收通知的项目成员</div>
      </el-form-item>
      <el-form-item label="启用">
        <el-switch v-model="form.enabled" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="handleClose">取消</el-button>
      <el-button type="primary" :loading="saving" @click="handleSubmit">保存</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { notificationApi } from '@/api/notification'
import type {
  NotificationChannel,
  NotificationRule,
  EventCatalog,
  TemplateCatalog,
  RuleCreate,
  RuleUpdate,
} from '@/types/notification'

const props = defineProps<{
  modelValue: boolean
  rule: NotificationRule | null
  channels: NotificationChannel[]
  events: EventCatalog[]
  templates: TemplateCatalog[]
  projectId: number
  projectMembers?: any[]  // 添加项目成员参数
}>()
const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void
  (e: 'success'): void
}>()

const formRef = ref<FormInstance>()
const saving = ref(false)
const customUserIds = ref<number[]>([])  // 改为数组存储用户ID

const form = ref<{
  name: string
  event_type: string
  template_code: string
  channel_id?: number
  recipient_type: string
  enabled: boolean
}>({
  name: '',
  event_type: '',
  template_code: '',
  channel_id: undefined,
  recipient_type: 'all_members',
  enabled: true,
})

const isEdit = computed(() => !!props.rule)

const enabledChannels = computed(() => props.channels.filter((c) => c.enabled))

const compatibleTemplates = computed(() =>
  props.templates.filter((t) => t.event_types.includes(form.value.event_type))
)

const rules: FormRules = {
  name: [{ required: true, min: 2, max: 200, message: '请输入2-200字规则名称', trigger: 'blur' }],
  event_type: [{ required: true, message: '请选择触发事件', trigger: 'change' }],
  channel_id: [{ required: true, message: '请选择通知渠道', trigger: 'change' }],
  recipient_type: [{ required: true, message: '请选择接收人', trigger: 'change' }],
}

const onEventChange = () => {
  // Auto-select first compatible template
  if (compatibleTemplates.value.length > 0) {
    form.value.template_code = compatibleTemplates.value[0].code
  }
}

watch(
  () => props.modelValue,
  (open) => {
    if (open) {
      if (props.rule) {
        form.value = {
          name: props.rule.name,
          event_type: props.rule.event_type,
          template_code: props.rule.template_code || '',
          channel_id: props.rule.channel_id,
          recipient_type: props.rule.recipient_type || 'all_members',
          enabled: props.rule.enabled,
        }
        const ids = props.rule.recipient_config?.member_ids
        customUserIds.value = Array.isArray(ids) ? ids : []
      } else {
        form.value = {
          name: '',
          event_type: '',
          template_code: '',
          channel_id: undefined,
          recipient_type: 'all_members',
          enabled: true,
        }
        customUserIds.value = []
      }
    }
  }
)

const handleClose = () => emit('update:modelValue', false)

const buildRecipientConfig = (): Record<string, any> => {
  if (form.value.recipient_type === 'custom') {
    return { member_ids: customUserIds.value }
  }
  return {}
}

const handleSubmit = async () => {
  if (!formRef.value) return
  await formRef.value.validate(async (valid) => {
    if (!valid) return
    saving.value = true
    try {
      if (isEdit.value && props.rule) {
        const payload: RuleUpdate = {
          name: form.value.name,
          event_type: form.value.event_type,
          channel_id: form.value.channel_id,
          template_code: form.value.template_code || undefined,
          recipient_type: form.value.recipient_type,
          recipient_config: buildRecipientConfig(),
          enabled: form.value.enabled,
        }
        await notificationApi.updateRule(props.projectId, props.rule.id, payload)
        ElMessage.success('规则已更新')
      } else {
        const payload: RuleCreate = {
          name: form.value.name,
          event_type: form.value.event_type,
          channel_id: form.value.channel_id!,
          template_code: form.value.template_code || undefined,
          recipient_type: form.value.recipient_type,
          recipient_config: buildRecipientConfig(),
          enabled: form.value.enabled,
        }
        await notificationApi.createRule(props.projectId, payload)
        ElMessage.success('规则已创建')
      }
      emit('success')
    } catch (err: any) {
      ElMessage.error(err?.message || '保存失败')
    } finally {
      saving.value = false
    }
  })
}
</script>

<style scoped>
.tip {
  color: #909399;
  font-size: 12px;
  margin-top: 4px;
}
.tip.warn {
  color: #e6a23c;
}
.opt-hint {
  color: #909399;
  font-size: 12px;
  margin-left: 8px;
}
</style>