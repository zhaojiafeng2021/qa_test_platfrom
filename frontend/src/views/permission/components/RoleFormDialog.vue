<template>
  <el-dialog
    :model-value="modelValue"
    :title="dialogTitle"
    width="720px"
    @update:model-value="$emit('update:modelValue', $event)"
    @close="handleClose"
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="100px">
      <el-alert
        v-if="isBuiltin"
        type="warning"
        :closable="false"
        show-icon
        title="内置角色为全局共享，修改权限将影响所有项目。仅可调整权限和描述，名称/标识/父角色不可更改。"
        style="margin-bottom: 16px"
      />
      <el-form-item label="角色名称" prop="name">
        <el-input v-model="form.name" placeholder="如：测试主管" maxlength="100" :disabled="isBuiltin" />
      </el-form-item>
      <el-form-item label="角色标识" prop="code">
        <el-input
          v-model="form.code"
          placeholder="留空自动生成（小写字母/数字/下划线）"
          :disabled="isEdit"
        />
      </el-form-item>
      <el-form-item label="继承父角色">
        <el-select v-model="form.parent_role_id" placeholder="无（不继承）" clearable style="width: 100%" :disabled="isBuiltin">
          <el-option
            v-for="r in parentCandidates"
            :key="r.id"
            :label="r.name"
            :value="r.id"
          />
        </el-select>
        <div class="tip">加法继承：本角色有效权限 = 父角色有效权限 ∪ 下方勾选的直接权限。本期不支持撤销父角色权限。</div>
      </el-form-item>
      <el-form-item label="描述">
        <el-input v-model="form.description" type="textarea" :rows="2" maxlength="500" />
      </el-form-item>
      <el-form-item label="直接权限">
        <div class="perm-groups">
          <div v-for="(perms, moduleName) in groupedPermissions" :key="moduleName" class="perm-group">
            <div class="perm-group-head">
              <el-checkbox
                :model-value="isModuleAllChecked(perms)"
                :indeterminate="isModuleIndeterminate(perms)"
                @change="toggleModule(perms, $event)"
              >
                {{ moduleName }}
              </el-checkbox>
            </div>
            <el-checkbox-group v-model="selectedCodes" class="perm-items">
              <el-checkbox
                v-for="p in perms"
                :key="p.code"
                :value="p.code"
              >
                {{ p.name }}
                <el-tag v-if="inheritedCodes.includes(p.code)" size="small" type="info">继承</el-tag>
              </el-checkbox>
            </el-checkbox-group>
          </div>
        </div>
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
import { permissionApi } from '@/api/permission'
import type { Role, Permission, RoleCreate, RoleUpdate } from '@/types/permission'

const props = defineProps<{
  modelValue: boolean
  role: Role | null
  roles: Role[]
  permissions: Permission[]
  projectId: number
}>()
const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void
  (e: 'success'): void
}>()

const formRef = ref<FormInstance>()
const saving = ref(false)
const selectedCodes = ref<string[]>([])

const form = ref<{ name: string; code: string; parent_role_id?: number; description: string }>({
  name: '',
  code: '',
  parent_role_id: undefined,
  description: '',
})

const isEdit = computed(() => !!props.role)
const isBuiltin = computed(() => props.role?.is_builtin ?? false)
const dialogTitle = computed(() =>
  isBuiltin.value ? '编辑内置角色权限' : isEdit.value ? '编辑角色' : '新建角色'
)

const rules: FormRules = {
  name: [{ required: true, min: 2, max: 100, message: '请输入2-100字角色名称', trigger: 'blur' }],
}

// Exclude self and descendants to prevent inheritance cycles
const parentCandidates = computed(() => {
  if (!props.role) return props.roles
  const descendantIds = collectDescendants(props.role.id)
  return props.roles.filter((r) => r.id !== props.role!.id && !descendantIds.has(r.id))
})

const collectDescendants = (rootId: number): Set<number> => {
  const result = new Set<number>()
  const walk = (parentId: number) => {
    for (const r of props.roles) {
      if (r.parent_role_id === parentId && !result.has(r.id)) {
        result.add(r.id)
        walk(r.id)
      }
    }
  }
  walk(rootId)
  return result
}

const groupedPermissions = computed(() => {
  const groups: Record<string, Permission[]> = {}
  for (const p of props.permissions ?? []) {
    if (!groups[p.module]) groups[p.module] = []
    groups[p.module].push(p)
  }
  return groups
})

// Inherited codes from selected parent role (read-only display)
const inheritedCodes = computed(() => {
  if (!form.value.parent_role_id) return []
  const parent = props.roles.find((r) => r.id === form.value.parent_role_id)
  return parent?.permission_codes || []
})

const isModuleAllChecked = (perms: Permission[]): boolean =>
  perms.every((p) => selectedCodes.value.includes(p.code))
const isModuleIndeterminate = (perms: Permission[]): boolean => {
  const checked = perms.filter((p) => selectedCodes.value.includes(p.code)).length
  return checked > 0 && checked < perms.length
}
const toggleModule = (perms: Permission[], checked: any) => {
  const codes = perms.map((p) => p.code)
  if (checked) {
    selectedCodes.value = Array.from(new Set([...selectedCodes.value, ...codes]))
  } else {
    selectedCodes.value = selectedCodes.value.filter((c) => !codes.includes(c))
  }
}

watch(
  () => props.modelValue,
  (open) => {
    if (open) {
      if (props.role) {
        form.value = {
          name: props.role.name,
          code: props.role.code,
          parent_role_id: props.role.parent_role_id ?? undefined,
          description: props.role.description || '',
        }
        selectedCodes.value = [...(props.role.direct_permission_codes || [])]
      } else {
        form.value = { name: '', code: '', parent_role_id: undefined, description: '' }
        selectedCodes.value = []
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
      if (isEdit.value && props.role) {
        // 内置角色只允许修改 description 和 permission_codes
        const payload: RoleUpdate = props.role.is_builtin
          ? {
              description: form.value.description,
              permission_codes: selectedCodes.value,
            }
          : {
              name: form.value.name,
              description: form.value.description,
              parent_role_id: form.value.parent_role_id,
              permission_codes: selectedCodes.value,
            }
        await permissionApi.updateRole(props.projectId, props.role.id, payload)
        ElMessage.success('角色已更新')
      } else {
        const payload: RoleCreate = {
          name: form.value.name,
          code: form.value.code || undefined,
          description: form.value.description || undefined,
          parent_role_id: form.value.parent_role_id || undefined,
          permission_codes: selectedCodes.value,
        }
        await permissionApi.createRole(props.projectId, payload)
        ElMessage.success('角色已创建')
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
  line-height: 1.5;
  margin-top: 4px;
}
.perm-groups {
  width: 100%;
  max-height: 320px;
  overflow-y: auto;
  border: 1px solid #ebeef5;
  border-radius: 4px;
  padding: 8px 12px;
}
.perm-group {
  padding: 8px 0;
  border-bottom: 1px dashed #ebeef5;
}
.perm-group:last-child {
  border-bottom: none;
}
.perm-group-head {
  font-weight: 600;
  margin-bottom: 6px;
}
.perm-items {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 20px;
  padding-left: 20px;
}
</style>