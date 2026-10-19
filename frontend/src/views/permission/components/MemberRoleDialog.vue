<template>
  <el-dialog
    :model-value="modelValue"
    title="修改成员角色"
    width="520px"
    @update:model-value="$emit('update:modelValue', $event)"
    @close="handleClose"
  >
    <el-form label-width="90px">
      <el-form-item label="成员">
        <span>{{ member?.full_name || member?.username }}</span>
      </el-form-item>
      <el-form-item label="当前角色">
        <div v-if="member?.role_names && member.role_names.length > 0" style="display: flex; gap: 6px; flex-wrap: wrap">
          <el-tag v-for="(name, idx) in member.role_names" :key="idx" size="small">{{ name }}</el-tag>
        </div>
        <el-tag v-else>{{ member?.role_name }}</el-tag>
      </el-form-item>
      <el-form-item label="新角色">
        <el-select
          v-model="selectedRoleIds"
          multiple
          collapse-tags
          collapse-tags-tooltip
          placeholder="选择角色（可多选）"
          style="width: 100%"
        >
          <el-option v-for="r in roles" :key="r.id" :label="r.name" :value="r.id" />
        </el-select>
      </el-form-item>
      <el-alert
        type="info"
        :closable="false"
        show-icon
        style="margin-top: 8px"
      >
        <template #title>
          <span style="font-size: 12px">多角色权限取并集。例如：角色A有 case:read，角色B有 api:read，则该成员同时拥有两项权限。</span>
        </template>
      </el-alert>
    </el-form>
    <template #footer>
      <el-button @click="handleClose">取消</el-button>
      <el-button type="primary" :loading="saving" :disabled="selectedRoleIds.length === 0" @click="handleSubmit">保存</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { permissionApi } from '@/api/permission'
import type { Role, ProjectMember } from '@/types/permission'

const props = defineProps<{
  modelValue: boolean
  member: ProjectMember | null
  roles: Role[]
  projectId: number
}>()
const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void
  (e: 'success'): void
}>()

const saving = ref(false)
const selectedRoleIds = ref<number[]>([])

watch(
  () => props.modelValue,
  (open) => {
    if (open && props.member) {
      // 优先使用多角色字段，fallback 到单角色
      if (props.member.role_ids && props.member.role_ids.length > 0) {
        selectedRoleIds.value = [...props.member.role_ids]
      } else if (props.member.role_id) {
        selectedRoleIds.value = [props.member.role_id]
      } else {
        selectedRoleIds.value = []
      }
    }
  }
)

const handleClose = () => emit('update:modelValue', false)

const handleSubmit = async () => {
  if (selectedRoleIds.value.length === 0 || !props.member) return
  saving.value = true
  try {
    await permissionApi.assignMemberRole(props.projectId, props.member.user_id, {
      role_ids: selectedRoleIds.value,
    })
    ElMessage.success('角色已更新')
    emit('update:modelValue', false)
    emit('success')
  } catch (err: any) {
    ElMessage.error(err?.message || '更新失败')
  } finally {
    saving.value = false
  }
}
</script>