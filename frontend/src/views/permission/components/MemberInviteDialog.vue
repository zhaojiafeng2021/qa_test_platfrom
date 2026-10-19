<template>
  <el-dialog
    :model-value="modelValue"
    title="邀请成员"
    width="560px"
    @update:model-value="$emit('update:modelValue', $event)"
    @close="handleClose"
  >
    <el-form label-width="90px">
      <el-form-item label="选择用户">
        <el-select
          v-model="selectedUserId"
          filterable
          remote
          reserve-keyword
          placeholder="输入用户名/姓名/邮箱搜索"
          :remote-method="searchUsers"
          :loading="searching"
          style="width: 100%"
        >
          <el-option
            v-for="u in availableUsers"
            :key="u.id"
            :label="userLabel(u)"
            :value="u.id"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="分配角色">
        <el-select v-model="selectedRoleId" placeholder="选择角色" style="width: 100%">
          <el-option v-for="r in roles" :key="r.id" :label="r.name" :value="r.id" />
        </el-select>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="handleClose">取消</el-button>
      <el-button type="primary" :loading="saving" :disabled="!canSubmit" @click="handleSubmit">邀请</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { permissionApi } from '@/api/permission'
import type { Role, AvailableUser } from '@/types/permission'

const props = defineProps<{
  modelValue: boolean
  roles: Role[]
  projectId: number
}>()
const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void
  (e: 'success'): void
}>()

const searching = ref(false)
const saving = ref(false)
const availableUsers = ref<AvailableUser[]>([])
const selectedUserId = ref<number | undefined>(undefined)
const selectedRoleId = ref<number | undefined>(undefined)

const canSubmit = computed(() => !!selectedUserId.value && !!selectedRoleId.value)

const userLabel = (u: AvailableUser): string =>
  `${u.full_name || u.username}（${u.email}）`

const searchUsers = async (query: string) => {
  if (!props.projectId) return
  searching.value = true
  try {
    availableUsers.value = await permissionApi.searchAvailableUsers(props.projectId, query || undefined)
  } catch (err) {
    ElMessage.error('搜索用户失败')
  } finally {
    searching.value = false
  }
}

watch(
  () => props.modelValue,
  (open) => {
    if (open) {
      selectedUserId.value = undefined
      selectedRoleId.value = undefined
      availableUsers.value = []
      searchUsers('')
    }
  }
)

const handleClose = () => emit('update:modelValue', false)

const handleSubmit = async () => {
  if (!canSubmit.value) return
  saving.value = true
  try {
    await permissionApi.addMember(props.projectId, {
      user_id: selectedUserId.value!,
      role_id: selectedRoleId.value!,
    })
    ElMessage.success('成员已邀请')
    emit('success')
  } catch (err: any) {
    ElMessage.error(err?.message || '邀请失败')
  } finally {
    saving.value = false
  }
}
</script>