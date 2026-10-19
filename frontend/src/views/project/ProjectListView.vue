<template>
  <div class="project-hub">
    <header class="hub-topbar">
      <div class="hub-brand">
        <span class="brand-mark"><el-icon><DataAnalysis /></el-icon></span>
        <span><b>测试平台</b><small>项目中心</small></span>
      </div>
      <div class="hub-meta">选择一个项目进入测试工作台</div>
    </header>

    <main class="hub-main">
      <div class="page-head">
        <div>
          <h1><el-icon><Grid /></el-icon>项目列表</h1>
          <p>集中管理测试资产、环境与项目成员</p>
        </div>
        <div class="actions">
          <el-button type="primary" @click="openCreateDialog">
            <el-icon><Plus /></el-icon>创建项目
          </el-button>
        </div>
      </div>

      <section class="project-panel" v-loading="loading">
        <div class="project-toolbar">
          <div class="toolbar-title">
            <b>我的项目</b><span>{{ filteredProjects.length }} / {{ projects.length }}</span>
          </div>
          <div class="toolbar-filters">
            <el-input v-model="keyword" clearable :prefix-icon="Search" placeholder="搜索项目名称或代码" />
            <el-select v-model="statusFilter" class="status-filter">
              <el-option label="全部状态" value="" />
              <el-option label="活跃" value="active" />
              <el-option label="已归档" value="archived" />
            </el-select>
            <el-tooltip content="刷新项目">
              <el-button :icon="Refresh" @click="loadProjects" />
            </el-tooltip>
          </div>
        </div>

        <el-table :data="filteredProjects" row-key="id" class="project-table">
          <el-table-column label="项目" min-width="270">
            <template #default="{ row }">
              <button class="project-cell" type="button" @click="handleEnter(row as Project)">
                <span class="project-mark" :style="{ background: row.color || '#3B7BF5' }">
                  {{ row.name.charAt(0) }}
                </span>
                <span class="project-copy">
                  <b>{{ row.name }}</b>
                  <small>{{ row.code }}</small>
                </span>
              </button>
            </template>
          </el-table-column>
          <el-table-column prop="description" label="描述" min-width="260" show-overflow-tooltip>
            <template #default="{ row }"><span class="description">{{ row.description || '暂无项目描述' }}</span></template>
          </el-table-column>
          <el-table-column prop="status" label="状态" width="110">
            <template #default="{ row }">
              <span v-if="row.status === 'active'" class="status-dot st-pass">活跃</span>
              <span v-else-if="row.status === 'archived'" class="status-dot st-skip">已归档</span>
              <span v-else class="status-dot st-fail">已删除</span>
            </template>
          </el-table-column>
          <el-table-column label="最近更新" width="180">
            <template #default="{ row }"><span class="date-text">{{ formatDate(row.updated_at || row.created_at) }}</span></template>
          </el-table-column>
          <el-table-column label="操作" width="310" fixed="right" align="right">
            <template #default="{ row }">
              <el-button type="primary" size="small" @click="handleEnter(row as Project)">
                进入<el-icon class="button-tail"><ArrowRight /></el-icon>
              </el-button>
              <el-button size="small" :icon="Edit" @click="handleEdit(row as Project)">编辑</el-button>
              <el-button size="small" :icon="User" @click="handleMembers(row as Project)">成员</el-button>
              <el-tooltip content="删除项目">
                <el-button
                  v-if="row.status === 'active' && authStore.user?.is_superuser"
                  size="small"
                  type="danger"
                  plain
                  :icon="Delete"
                  aria-label="删除项目"
                  @click="handleDelete(row as Project)"
                />
              </el-tooltip>
            </template>
          </el-table-column>
          <template #empty>
            <el-empty description="没有匹配的项目" :image-size="72" />
          </template>
        </el-table>
      </section>
    </main>

    <el-dialog
      v-model="showCreateDialog"
      :title="editingProject ? '编辑项目' : '创建项目'"
      width="min(640px, calc(100vw - 28px))"
      @closed="resetForm"
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-width="110px">
        <el-form-item label="项目代码" prop="code">
          <el-input v-model="form.code" placeholder="例如 qa-platform" :disabled="!!editingProject" />
        </el-form-item>
        <el-form-item label="项目名称" prop="name">
          <el-input v-model="form.name" placeholder="项目显示名称" />
        </el-form-item>
        <el-form-item label="项目描述" prop="description">
          <el-input v-model="form.description" type="textarea" :rows="3" placeholder="项目简介" />
        </el-form-item>
        <el-form-item label="项目图标" prop="icon">
          <el-input v-model="form.icon" placeholder="可选的图标名称" />
        </el-form-item>
        <el-form-item label="标识颜色" prop="color">
          <el-color-picker v-model="form.color" />
        </el-form-item>

        <!-- 公开项目开关（仅超级管理员编辑时可见） -->
        <el-form-item v-if="editingProject && authStore.user?.is_superuser" label="公开项目">
          <el-switch v-model="form.is_public" />
          <div class="form-tip">开启后，所有用户都可以查看此项目（只读权限）</div>
        </el-form-item>

        <!-- Grafana 监控配置（编辑项目时显示） -->
        <template v-if="editingProject">
          <el-divider content-position="left">Grafana 监控配置（可选）</el-divider>
          <el-form-item label="Grafana URL">
            <el-input v-model="form.grafana_url" placeholder="http://grafana.tec-develop.com" />
            <div class="form-tip">Grafana 服务地址</div>
          </el-form-item>
          <el-form-item label="Service Token">
            <el-input v-model="form.grafana_token" type="password" placeholder="glsa_xxxxxxxxxxxxx" show-password />
            <div class="form-tip">Service Account Token（用于查询 Prometheus 指标）</div>
          </el-form-item>
          <el-form-item label="数据源 UID">
            <el-input v-model="form.grafana_datasource_uid" placeholder="prometheus-uid" />
            <div class="form-tip">Prometheus 数据源的唯一标识符</div>
          </el-form-item>
          <el-form-item label="集群名称">
            <el-input v-model="form.grafana_cluster" placeholder="hwgz-share-cce" />
            <div class="form-tip">K8s 集群名称（可选）</div>
          </el-form-item>
        </template>
      </el-form>
      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSubmit">确定</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showMembersDialog" title="项目成员" width="min(820px, calc(100vw - 28px))">
      <div v-if="currentProject" class="members-dialog">
        <div class="dialog-context">
          <span class="project-mark small" :style="{ background: currentProject.color || '#3B7BF5' }">{{ currentProject.name.charAt(0) }}</span>
          <span><b>{{ currentProject.name }}</b><small>{{ currentProject.code }}</small></span>
          <el-button type="primary" size="small" :icon="Plus" @click="showAddMemberDialog = true">添加成员</el-button>
        </div>
        <el-table :data="members" v-loading="loadingMembers">
          <el-table-column label="成员" min-width="200">
            <template #default="{ row }">
              <div class="member-cell"><span class="member-avatar">{{ (row.full_name || row.username || String(row.user_id)).charAt(0) }}</span><span><b>{{ row.full_name || row.username || `用户 ${row.user_id}` }}</b><small>{{ row.email || `ID: ${row.user_id}` }}</small></span></div>
            </template>
          </el-table-column>
          <el-table-column label="角色" width="120">
            <template #default="{ row }">
              <el-tag v-if="row.role === 'owner'" type="danger">负责人</el-tag>
              <el-tag v-else-if="row.role === 'admin'" type="warning">管理员</el-tag>
              <el-tag v-else-if="row.role === 'member'">成员</el-tag>
              <el-tag v-else type="info">只读</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="加入时间" width="180">
            <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="170" align="right">
            <template #default="{ row }">
              <el-button v-if="row.role !== 'owner'" link type="primary" size="small" @click="handleChangeRole(row as Member)">修改角色</el-button>
              <el-button v-if="row.role !== 'owner'" link type="danger" size="small" @click="handleRemoveMember(row as Member)">移除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </el-dialog>

    <el-dialog v-model="showAddMemberDialog" title="添加成员" width="min(400px, calc(100vw - 28px))" append-to-body>
      <el-form :model="memberForm" label-width="72px">
        <el-form-item label="用户ID"><el-input v-model.number="memberForm.user_id" placeholder="输入用户ID" /></el-form-item>
        <el-form-item label="角色">
          <el-select v-model="memberForm.role" style="width:100%">
            <el-option label="管理员" value="admin" />
            <el-option label="成员" value="member" />
            <el-option label="只读" value="viewer" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showAddMemberDialog = false">取消</el-button>
        <el-button type="primary" :loading="addingMember" @click="handleAddMember">添加</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowRight, DataAnalysis, Delete, Edit, Grid, Plus, Refresh, Search, User } from '@element-plus/icons-vue'
import type { FormInstance, FormRules } from 'element-plus'
import * as projectApi from '@/api/project'
import { useAuthStore } from '@/stores/auth'
import { formatDateTimeShort } from '@/utils/datetime'

interface Project {
  id: number
  code: string
  name: string
  description?: string
  icon?: string
  color?: string
  status: string
  created_at: string
  updated_at: string
  grafana_config_json?: {
    url?: string
    token?: string
    datasource_uid?: string
    cluster?: string
  } | null
}

interface Member {
  user_id: number
  role: string
  created_at: string
  username?: string
  email?: string
  full_name?: string
}

const router = useRouter()
const authStore = useAuthStore()
const loading = ref(false)
const projects = ref<Project[]>([])
const keyword = ref('')
const statusFilter = ref('')
const filteredProjects = computed(() => {
  const query = keyword.value.trim().toLowerCase()
  return projects.value.filter(project => {
    const matchesStatus = !statusFilter.value || project.status === statusFilter.value
    const matchesKeyword = !query || project.name.toLowerCase().includes(query) || project.code.toLowerCase().includes(query)
    return matchesStatus && matchesKeyword
  })
})

const showCreateDialog = ref(false)
const formRef = ref<FormInstance>()
const submitting = ref(false)
const editingProject = ref<Project | null>(null)
const form = ref({
  code: '',
  name: '',
  description: '',
  icon: '',
  color: '#3B7BF5',
  is_public: false,
  grafana_url: '',
  grafana_token: '',
  grafana_datasource_uid: '',
  grafana_cluster: ''
})
const rules: FormRules = {
  code: [
    { required: true, message: '请输入项目代码', trigger: 'blur' },
    { pattern: /^[a-zA-Z][a-zA-Z0-9_-]*$/, message: '以字母开头，仅支持字母、数字、下划线和连字符', trigger: 'blur' },
  ],
  name: [{ required: true, message: '请输入项目名称', trigger: 'blur' }],
}

const showMembersDialog = ref(false)
const showAddMemberDialog = ref(false)
const currentProject = ref<Project | null>(null)
const members = ref<Member[]>([])
const loadingMembers = ref(false)
const addingMember = ref(false)
const memberForm = ref({ user_id: undefined as number | undefined, role: 'member' })

async function loadProjects() {
  loading.value = true
  try {
    projects.value = await projectApi.getProjects() as Project[]
  } catch {
    ElMessage.error('加载项目列表失败')
  } finally {
    loading.value = false
  }
}

function openCreateDialog() {
  resetForm()
  showCreateDialog.value = true
}

async function handleSubmit() {
  if (!formRef.value) return
  await formRef.value.validate(async valid => {
    if (!valid) return
    submitting.value = true
    try {
      const payload: any = {
        name: form.value.name,
        description: form.value.description,
        icon: form.value.icon,
        color: form.value.color
      }

      // 编辑时添加 is_public 和 Grafana 配置
      if (editingProject.value) {
        // 添加公开项目开关（仅超级管理员可修改）
        if (authStore.user?.is_superuser) {
          payload.is_public = form.value.is_public
        }

        // 如果任何一个字段有值，则构造配置对象
        const hasGrafanaConfig = form.value.grafana_url || form.value.grafana_token || form.value.grafana_datasource_uid || form.value.grafana_cluster

        if (hasGrafanaConfig) {
          payload.grafana_config_json = {
            url: form.value.grafana_url || undefined,
            token: form.value.grafana_token || undefined,
            datasource_uid: form.value.grafana_datasource_uid || undefined,
            cluster: form.value.grafana_cluster || undefined
          }
        } else {
          // 所有字段都为空，则清空配置
          payload.grafana_config_json = null
        }
      }

      if (editingProject.value) {
        await projectApi.updateProject(editingProject.value.id, payload)
        ElMessage.success('项目更新成功')
      } else {
        payload.code = form.value.code
        await projectApi.createProject(payload)
        ElMessage.success('项目创建成功')
      }
      showCreateDialog.value = false
      await loadProjects()
    } catch (error) {
      console.error('提交失败', error)
      ElMessage.error(editingProject.value ? '更新失败' : '创建失败')
    } finally {
      submitting.value = false
    }
  })
}

function handleEnter(project: Project) {
  router.push(`/${project.code}/dashboard`)
}

function handleEdit(project: Project) {
  editingProject.value = project

  // 解析 Grafana 配置
  const grafanaConfig = project.grafana_config_json || {}

  form.value = {
    code: project.code,
    name: project.name,
    description: project.description || '',
    icon: project.icon || '',
    color: project.color || '#3B7BF5',
    is_public: project.is_public || false,
    grafana_url: grafanaConfig.url || '',
    grafana_token: grafanaConfig.token || '',
    grafana_datasource_uid: grafanaConfig.datasource_uid || '',
    grafana_cluster: grafanaConfig.cluster || ''
  }
  showCreateDialog.value = true
}

async function handleDelete(project: Project) {
  try {
    await ElMessageBox.confirm(`确定要删除项目「${project.name}」吗？`, '删除确认', { type: 'warning', confirmButtonText: '确定', cancelButtonText: '取消' })
    await projectApi.deleteProject(project.id)
    ElMessage.success('项目已删除')
    await loadProjects()
  } catch (error) {
    if (error !== 'cancel') ElMessage.error('删除失败')
  }
}

async function handleMembers(project: Project) {
  currentProject.value = project
  showMembersDialog.value = true
  await loadMembers(project.id)
}

async function loadMembers(projectId: number) {
  loadingMembers.value = true
  try {
    members.value = await projectApi.getProjectMembers(projectId) as Member[]
  } catch {
    ElMessage.error('加载成员列表失败')
  } finally {
    loadingMembers.value = false
  }
}

async function handleAddMember() {
  if (!currentProject.value || !memberForm.value.user_id) return ElMessage.warning('请输入用户ID')
  addingMember.value = true
  try {
    await projectApi.addProjectMember(currentProject.value.id, { user_id: memberForm.value.user_id, role: memberForm.value.role })
    ElMessage.success('成员添加成功')
    showAddMemberDialog.value = false
    memberForm.value = { user_id: undefined, role: 'member' }
    await loadMembers(currentProject.value.id)
  } catch {
    ElMessage.error('添加成员失败')
  } finally {
    addingMember.value = false
  }
}

async function handleChangeRole(member: Member) {
  if (!currentProject.value) return
  try {
    const { value } = await ElMessageBox.prompt('输入 admin、member 或 viewer', '修改角色', {
      confirmButtonText: '确定', cancelButtonText: '取消', inputPattern: /^(admin|member|viewer)$/, inputErrorMessage: '角色格式不正确',
    })
    await projectApi.updateMemberRole(currentProject.value.id, member.user_id, { role: value })
    ElMessage.success('角色修改成功')
    await loadMembers(currentProject.value.id)
  } catch (error) {
    if (error !== 'cancel') ElMessage.error('修改角色失败')
  }
}

async function handleRemoveMember(member: Member) {
  if (!currentProject.value) return
  try {
    await ElMessageBox.confirm('确定要移除该成员吗？', '移除确认', { type: 'warning', confirmButtonText: '确定', cancelButtonText: '取消' })
    await projectApi.removeMember(currentProject.value.id, member.user_id)
    ElMessage.success('成员已移除')
    await loadMembers(currentProject.value.id)
  } catch (error) {
    if (error !== 'cancel') ElMessage.error('移除成员失败')
  }
}

function resetForm() {
  editingProject.value = null
  form.value = {
    code: '',
    name: '',
    description: '',
    icon: '',
    color: '#3B7BF5',
    is_public: false,
    grafana_url: '',
    grafana_token: '',
    grafana_datasource_uid: '',
    grafana_cluster: ''
  }
  formRef.value?.resetFields()
}

function formatDate(date: string) {
  return formatDateTimeShort(date)
}

onMounted(loadProjects)
</script>

<style scoped>
.project-hub { min-height: 100vh; background: var(--bg); color: var(--txt); }
.hub-topbar { height: 56px; display: flex; align-items: center; padding: 0 max(24px, calc((100vw - 1280px) / 2)); background: var(--sidebar); color: #fff; border-bottom: 1px solid rgba(255,255,255,.08); }
.hub-brand { display: flex; align-items: center; gap: 10px; }
.brand-mark { width: 30px; height: 30px; display: grid; place-items: center; border-radius: 7px; background: var(--primary); font-size: 17px; }
.hub-brand > span:last-child { display: flex; align-items: baseline; gap: 10px; }
.hub-brand b { font-size: 15px; }
.hub-brand small { color: #8EA1BC; font-size: 11px; }
.hub-meta { margin-left: auto; color: #8EA1BC; font-size: 11px; }
.hub-main { width: min(1280px, calc(100% - 48px)); margin: 0 auto; padding: 28px 0 48px; }
.page-head h1 { margin: 0; }
.page-head p { margin: 6px 0 0; color: var(--txt2); font-size: 12px; }
.project-panel { overflow: hidden; background: #fff; border: 1px solid var(--line); border-radius: var(--r2); box-shadow: var(--shadow); }
.project-toolbar { min-height: 58px; padding: 10px 14px 10px 18px; display: flex; align-items: center; justify-content: space-between; gap: 16px; border-bottom: 1px solid var(--line); }
.toolbar-title { display: flex; align-items: center; gap: 8px; font-size: 14px; }
.toolbar-title span { padding: 2px 8px; border-radius: 10px; background: var(--line2); color: var(--txt3); font-size: 11px; }
.toolbar-filters { display: flex; align-items: center; gap: 8px; }
.toolbar-filters .el-input { width: 240px; }
.status-filter { width: 116px; }
.project-cell { min-width: 0; display: flex; align-items: center; gap: 11px; padding: 0; border: 0; background: transparent; cursor: pointer; text-align: left; }
.project-mark { width: 36px; height: 36px; display: grid; place-items: center; flex: 0 0 36px; border-radius: 7px; color: #fff; font-weight: 700; }
.project-mark.small { width: 30px; height: 30px; flex-basis: 30px; }
.project-copy, .member-cell > span:last-child, .dialog-context > span:nth-child(2) { min-width: 0; display: flex; flex-direction: column; }
.project-copy b { overflow: hidden; text-overflow: ellipsis; color: var(--txt); font-size: 13px; }
.project-copy small, .member-cell small, .dialog-context small { margin-top: 3px; color: var(--txt3); font-size: 11px; }
.project-cell:hover b { color: var(--primary); }
.description, .date-text { color: var(--txt2); font-size: 12px; }
.button-tail { margin-left: 4px; }
.dialog-context { display: flex; align-items: center; gap: 10px; padding-bottom: 14px; }
.dialog-context .el-button { margin-left: auto; }
.member-cell { display: flex; align-items: center; gap: 9px; }
.member-avatar { width: 28px; height: 28px; display: grid; place-items: center; flex: 0 0 28px; border-radius: 50%; background: var(--primary-bg); color: var(--primary); font-size: 11px; font-weight: 700; }
.member-cell b { font-size: 12px; }
:deep(.project-table .el-table__cell) { padding: 11px 0; }
:deep(.project-table th.el-table__cell) { padding: 9px 0; background: #F8FAFC; color: var(--txt2); font-size: 11px; }
:deep(.project-table .el-table__row:hover > td.el-table__cell) { background: #FAFCFF; }
@media (max-width: 760px) {
  .hub-topbar { padding: 0 14px; }
  .hub-meta { display: none; }
  .hub-main { width: calc(100% - 28px); padding-top: 18px; }
  .page-head { align-items: flex-start; }
  .project-toolbar { align-items: stretch; flex-direction: column; }
  .toolbar-filters { flex-wrap: wrap; }
  .toolbar-filters .el-input { flex: 1 1 190px; width: auto; }
  .status-filter { flex: 1 1 100px; }
}

.form-tip {
  font-size: 12px;
  color: #999;
  line-height: 1.5;
  margin-top: 4px;
}
</style>