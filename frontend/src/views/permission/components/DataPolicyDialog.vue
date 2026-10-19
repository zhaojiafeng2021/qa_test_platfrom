<template>
  <el-dialog
    :model-value="modelValue"
    title="配置数据权限"
    width="560px"
    @update:model-value="$emit('update:modelValue', $event)"
    @close="handleClose"
  >
    <el-form label-width="110px">
      <el-form-item label="资源类型">
        <span>{{ resourceLabel }}</span>
      </el-form-item>
      <el-form-item label="可见范围">
        <el-radio-group v-model="form.visibility_scope">
          <el-radio value="all">全部可见（项目内所有成员）</el-radio>
          <el-radio value="owner">仅负责人（资源的 owner 字段对应的用户）</el-radio>
          <el-radio value="members">指定成员（下方勾选）</el-radio>
        </el-radio-group>
      </el-form-item>
      <el-form-item v-if="form.visibility_scope === 'members'" label="指定成员">
        <el-select
          v-model="form.member_ids"
          multiple
          filterable
          placeholder="选择成员"
          style="width: 100%"
        >
          <el-option
            v-for="m in members"
            :key="m.user_id"
            :label="m.full_name || m.username"
            :value="m.user_id"
          />
        </el-select>
        <div class="tip">至少选择一名成员</div>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="handleClose">取消</el-button>
      <el-button type="primary" :loading="saving" :disabled="!canSubmit" @click="handleSubmit">保存</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { permissionApi } from '@/api/permission'
import type { DataPolicy, ProjectMember } from '@/types/permission'

const props = defineProps<{
  modelValue: boolean
  policy: DataPolicy | null
  members: ProjectMember[]
  projectId: number
}>()
const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void
  (e: 'success'): void
}>()

const saving = ref(false)
const form = ref<{ visibility_scope: 'all' | 'owner' | 'members'; member_ids: number[] }>({
  visibility_scope: 'all',
  member_ids: [],
})

const resourceLabel = computed(() => {
  const map: Record<string, string> = {
    automation_case: '自动化用例',
    manual_case: '手工用例',
    test_plan: '测试计划',
    environment: '测试环境',
    api_catalog: 'API接口',
  }
  return map[props.policy?.resource_type || ''] || props.policy?.resource_type || ''
})

const canSubmit = computed(() => {
  if (form.value.visibility_scope === 'members') {
    return form.value.member_ids.length > 0
  }
  return true
})

watch(
  () => props.modelValue,
  (open) => {
    if (open && props.policy) {
      form.value = {
        visibility_scope: props.policy.visibility_scope,
        member_ids: [...(props.policy.member_ids || [])],
      }
    }
  }
)

const handleClose = () => emit('update:modelValue', false)

const handleSubmit = async () => {
  if (!canSubmit.value || !props.policy) return
  saving.value = true
  try {
    await permissionApi.updateDataPolicy(props.projectId, props.policy.resource_type, {
      visibility_scope: form.value.visibility_scope,
      member_ids: form.value.member_ids,
    })
    ElMessage.success('数据权限已更新')
    emit('success')
  } catch (err: any) {
    ElMessage.error(err?.message || '更新失败')
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.tip {
  color: #909399;
  font-size: 12px;
  margin-top: 4px;
}
</style>