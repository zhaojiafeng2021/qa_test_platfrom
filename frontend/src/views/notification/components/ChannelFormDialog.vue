<template>
  <el-dialog
    :model-value="modelValue"
    :title="isEdit ? '编辑渠道' : '新建渠道'"
    width="560px"
    @update:model-value="$emit('update:modelValue', $event)"
    @close="handleClose"
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="110px">
      <el-form-item label="渠道名称" prop="name">
        <el-input v-model="form.name" placeholder="如：QA 值班群" maxlength="100" />
      </el-form-item>
      <el-form-item label="Webhook地址" prop="webhook_url">
        <el-input
          v-model="form.webhook_url"
          type="textarea"
          :rows="2"
          :placeholder="isEdit ? '留空则不修改现有地址' : 'https://open.feishu.cn/open-apis/bot/v2/hook/...'"
        />
        <div class="tip">飞书群机器人 Webhook 地址。仅支持 open.feishu.cn 官方 Webhook。</div>
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
import type { NotificationChannel, ChannelCreate, ChannelUpdate } from '@/types/notification'

const props = defineProps<{
  modelValue: boolean
  channel: NotificationChannel | null
  projectId: number
}>()
const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void
  (e: 'success'): void
}>()

const formRef = ref<FormInstance>()
const saving = ref(false)
const form = ref<{ name: string; webhook_url: string; enabled: boolean }>({
  name: '',
  webhook_url: '',
  enabled: true,
})

const isEdit = computed(() => !!props.channel)

const rules = computed<FormRules>(() => ({
  name: [{ required: true, min: 2, max: 100, message: '请输入2-100字渠道名称', trigger: 'blur' }],
  webhook_url: isEdit.value
    ? []
    : [{ required: true, min: 20, message: '请输入有效的 Webhook 地址', trigger: 'blur' }],
}))

watch(
  () => props.modelValue,
  (open) => {
    if (open) {
      if (props.channel) {
        form.value = {
          name: props.channel.name,
          webhook_url: '',
          enabled: props.channel.enabled,
        }
      } else {
        form.value = { name: '', webhook_url: '', enabled: true }
      }
    }
  }
)

const handleClose = () => emit('update:modelValue', false)

const handleSubmit = async () => {
  if (!formRef.value) return
  await formRef.value.validate(async (valid) => {
    if (!valid) return
    saving.value = true
    try {
      if (isEdit.value && props.channel) {
        const payload: ChannelUpdate = {
          name: form.value.name,
          enabled: form.value.enabled,
        }
        if (form.value.webhook_url) payload.webhook_url = form.value.webhook_url
        await notificationApi.updateChannel(props.projectId, props.channel.id, payload)
        ElMessage.success('渠道已更新')
      } else {
        const payload: ChannelCreate = {
          name: form.value.name,
          webhook_url: form.value.webhook_url,
          enabled: form.value.enabled,
        }
        await notificationApi.createChannel(props.projectId, payload)
        ElMessage.success('渠道已创建')
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
</style>