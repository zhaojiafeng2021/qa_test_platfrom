<!-- 代码源（远程 Git 仓库）管理弹窗 -->
<template>
  <el-dialog v-model="visible" title="代码源管理" width="760px" :close-on-click-modal="false">
    <el-table :data="repos" v-loading="loading" empty-text="暂无代码源" size="small">
      <el-table-column prop="name" label="名称" width="160" />
      <el-table-column prop="repo_url" label="仓库地址" min-width="260" show-overflow-tooltip />
      <el-table-column prop="default_branch" label="默认分支" width="110" />
      <el-table-column label="操作" width="160" align="center">
        <template #default="{ row }">
          <el-button link type="primary" size="small" @click="testConnection(row as CodeRepository)">测试连接</el-button>
          <el-button link type="primary" size="small" @click="edit(row as CodeRepository)">编辑</el-button>
          <el-button link type="danger" size="small" @click="remove(row as CodeRepository)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-divider content-position="left">{{ editingId ? '编辑代码源' : '接入新代码源' }}</el-divider>
    <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
      <el-form-item label="名称" prop="name">
        <el-input v-model="form.name" maxlength="100" placeholder="例：test_java_project" />
      </el-form-item>
      <el-form-item label="仓库地址" prop="repo_url">
        <el-input v-model="form.repo_url" placeholder="https://github.com/org/repo.git" />
      </el-form-item>
      <el-form-item label="默认分支">
        <el-input v-model="form.default_branch" placeholder="main（下拉时置顶）" />
      </el-form-item>
      <el-form-item label="说明">
        <el-input v-model="form.description" maxlength="500" />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" :loading="saving" @click="submit">{{ editingId ? '保存' : '接入' }}</el-button>
        <el-button v-if="editingId" @click="resetForm">取消编辑</el-button>
      </el-form-item>
    </el-form>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { createCodeRepo, deleteCodeRepo, listCodeRepos, listRepoBranches, updateCodeRepo } from '@/api/coverage'
import type { CodeRepository } from '@/types/coverage'

const props = defineProps<{ modelValue: boolean; projectId: number }>()
const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void
  (e: 'changed'): void
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const repos = ref<CodeRepository[]>([])
const loading = ref(false)
const saving = ref(false)
const editingId = ref<number | null>(null)
const formRef = ref<FormInstance>()
const form = reactive({ name: '', repo_url: '', default_branch: '', description: '' })

const rules: FormRules = {
  name: [{ required: true, message: '请输入名称', trigger: 'blur' }],
  repo_url: [
    { required: true, message: '请输入仓库地址', trigger: 'blur' },
    { pattern: /^(https?:\/\/|ssh:\/\/|git@)\S+$/, message: '需为 https://、ssh:// 或 git@ 开头', trigger: 'blur' },
  ],
}

async function load(): Promise<void> {
  loading.value = true
  try {
    repos.value = await listCodeRepos(props.projectId)
  } finally {
    loading.value = false
  }
}

watch(visible, (v) => { if (v) load() }, { immediate: true })

function resetForm(): void {
  editingId.value = null
  Object.assign(form, { name: '', repo_url: '', default_branch: '', description: '' })
  formRef.value?.clearValidate()
}

function edit(row: CodeRepository): void {
  editingId.value = row.id
  Object.assign(form, {
    name: row.name,
    repo_url: row.repo_url,
    default_branch: row.default_branch || '',
    description: row.description || '',
  })
}

async function submit(): Promise<void> {
  await formRef.value?.validate()
  saving.value = true
  try {
    const payload = {
      name: form.name.trim(),
      repo_url: form.repo_url.trim(),
      default_branch: form.default_branch.trim() || undefined,
      description: form.description.trim() || undefined,
    }
    if (editingId.value) await updateCodeRepo(props.projectId, editingId.value, payload)
    else await createCodeRepo(props.projectId, payload)
    ElMessage.success(editingId.value ? '已保存' : '已接入')
    resetForm()
    await load()
    emit('changed')
  } finally {
    saving.value = false
  }
}

async function testConnection(row: CodeRepository): Promise<void> {
  const branches = await listRepoBranches(props.projectId, row.id)
  ElMessage.success(`连接成功，共 ${branches.length} 个分支`)
}

async function remove(row: CodeRepository): Promise<void> {
  try {
    await ElMessageBox.confirm(`确认删除代码源「${row.name}」？已创建的任务不受影响。`, '删除确认', { type: 'warning' })
  } catch {
    return
  }
  await deleteCodeRepo(props.projectId, row.id)
  if (editingId.value === row.id) resetForm()
  await load()
  emit('changed')
}
</script>
