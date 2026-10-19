<template>
  <div class="permission-view">
    <div class="page-head">
      <h1>🔐 权限管理 (RBAC v2)</h1>
    </div>

    <el-tabs v-model="activeTab" class="permission-tabs">
      <!-- 角色管理 -->
      <el-tab-pane label="角色管理" name="roles">
        <div class="toolbar">
          <el-button type="primary" @click="openRoleDialog()">+ 新建角色</el-button>
          <span class="hint">加法继承: 有效权限 = 父角色有效权限 ∪ 当前角色直接权限</span>
        </div>
        <el-table :data="roles" v-loading="loading" stripe>
          <el-table-column prop="name" label="角色名称" min-width="140" />
          <el-table-column prop="code" label="标识" min-width="140" />
          <el-table-column label="继承自" min-width="120">
            <template #default="{ row }">{{ row.parent_role_name || '—' }}</template>
          </el-table-column>
          <el-table-column label="有效权限" width="90">
            <template #default="{ row }">{{ row.permission_codes?.length ?? 0 }}</template>
          </el-table-column>
          <el-table-column prop="member_count" label="成员" width="80" />
          <el-table-column label="类型" width="90">
            <template #default="{ row }">
              <el-tag :type="row.is_builtin ? 'info' : 'success'" size="small">
                {{ row.is_builtin ? '内置' : '自定义' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="160" fixed="right">
            <template #default="{ row }">
              <el-button
                link type="primary" size="small"
                @click="openRoleDialog(row as Role)"
              >编辑</el-button>
              <el-button
                link type="danger" size="small"
                :disabled="row.is_builtin"
                @click="handleDeleteRole(row as Role)"
              >删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- 功能权限矩阵 -->
      <el-tab-pane label="功能权限矩阵" name="permissions">
        <el-alert
          type="info" :closable="false" style="margin-bottom: 16px"
          title="展示各角色的有效权限（含继承）。编辑角色的直接权限请在“角色管理”中操作。"
        />
        <el-table :data="permissionMatrix" v-loading="loading" stripe max-height="560">
          <el-table-column prop="name" label="权限" min-width="180" fixed="left">
            <template #default="{ row }">
              <div>{{ row.name }}</div>
              <div class="code-hint">{{ row.code }}</div>
            </template>
          </el-table-column>
          <el-table-column
            v-for="role in customAndBuiltinRoles"
            :key="role.id"
            :label="role.name"
            width="110"
            align="center"
          >
            <template #default="{ row }">
              <el-icon v-if="roleHasPermission(role, row.code)" color="#67C23A"><Select /></el-icon>
              <span v-else class="muted">—</span>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- 数据权限 -->
      <el-tab-pane label="数据权限" name="data-policies">
        <el-table :data="dataPolicies" v-loading="loading" stripe>
          <el-table-column prop="resource_type" label="资源类型" min-width="160" />
          <el-table-column label="可见范围" min-width="140">
            <template #default="{ row }">
              <el-tag size="small">{{ scopeLabel(row.visibility_scope) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="指定成员数" width="110">
            <template #default="{ row }">{{ row.member_ids?.length ?? 0 }}</template>
          </el-table-column>
          <el-table-column label="操作" width="100" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="openPolicyDialog(row as DataPolicy)">配置</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- 成员管理 -->
      <el-tab-pane label="成员管理" name="members">
        <div class="toolbar">
          <el-button type="primary" @click="openMemberDialog()">+ 邀请成员</el-button>
        </div>
        <el-table :data="members" v-loading="loading" stripe>
          <el-table-column prop="username" label="用户名" min-width="140" />
          <el-table-column prop="full_name" label="姓名" min-width="120" />
          <el-table-column prop="email" label="邮箱" min-width="180" />
          <el-table-column label="角色" min-width="180">
            <template #default="{ row }">
              <div v-if="row.role_names && row.role_names.length > 0" style="display: flex; gap: 6px; flex-wrap: wrap">
                <el-tag v-for="(name, idx) in row.role_names" :key="idx" size="small">{{ name }}</el-tag>
              </div>
              <el-tag v-else size="small">{{ row.role_name }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="Owner" width="80">
            <template #default="{ row }">
              <el-tag v-if="row.is_project_owner" type="warning" size="small">Owner</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="180" fixed="right">
            <template #default="{ row }">
              <el-button
                link type="primary" size="small"
                :disabled="row.is_project_owner"
                @click="openAssignDialog(row as ProjectMember)"
              >改角色</el-button>
              <el-button
                link type="danger" size="small"
                :disabled="row.is_project_owner"
                @click="handleRemoveMember(row as ProjectMember)"
              >移除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- 审计日志 -->
      <el-tab-pane label="审计日志" name="audit">
        <div class="toolbar">
          <el-input v-model="auditActionFilter" placeholder="按操作筛选" clearable style="width: 220px" @clear="loadAudit" @keyup.enter="loadAudit" />
          <el-button @click="loadAudit">查询</el-button>
        </div>
        <el-table :data="auditLogs" v-loading="loading" stripe>
          <el-table-column prop="created_at" label="时间" min-width="170" />
          <el-table-column prop="username" label="操作者" min-width="120">
            <template #default="{ row }">{{ row.full_name || row.username || '系统' }}</template>
          </el-table-column>
          <el-table-column prop="action" label="操作" min-width="180" />
          <el-table-column prop="resource_type" label="资源类型" min-width="140" />
          <el-table-column prop="resource_id" label="资源ID" min-width="100" />
        </el-table>
        <el-pagination
          v-model:current-page="auditPage"
          :page-size="auditPageSize"
          :total="auditTotal"
          layout="prev, pager, next, total"
          style="margin-top: 16px; justify-content: flex-end"
          @current-change="loadAudit"
        />
      </el-tab-pane>
    </el-tabs>

    <RoleFormDialog
      v-model="showRoleDialog"
      :role="editingRole"
      :roles="roles"
      :permissions="permissions"
      :project-id="projectId ?? 0"
      @success="onRoleSaved"
    />
    <MemberInviteDialog
      v-model="showMemberDialog"
      :roles="assignableRoles"
      :project-id="projectId ?? 0"
      @success="onMemberSaved"
    />
    <MemberRoleDialog
      v-model="showAssignDialog"
      :member="editingMember"
      :roles="assignableRoles"
      :project-id="projectId ?? 0"
      @success="onMemberSaved"
    />
    <DataPolicyDialog
      v-model="showPolicyDialog"
      :policy="editingPolicy"
      :members="members"
      :project-id="projectId ?? 0"
      @success="onPolicySaved"
    />
  </div>
</template>
<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Select } from '@element-plus/icons-vue'
import { useProjectStore } from '@/stores/project'
import { permissionApi } from '@/api/permission'
import type {
  Role,
  Permission,
  DataPolicy,
  ProjectMember,
  AuditLog,
} from '@/types/permission'
import RoleFormDialog from './components/RoleFormDialog.vue'
import MemberInviteDialog from './components/MemberInviteDialog.vue'
import MemberRoleDialog from './components/MemberRoleDialog.vue'
import DataPolicyDialog from './components/DataPolicyDialog.vue'

const projectStore = useProjectStore()
const projectId = computed(() => projectStore.currentProjectId)

const activeTab = ref('roles')
const loading = ref(false)

const roles = ref<Role[]>([])
const permissions = ref<Permission[]>([])
const dataPolicies = ref<DataPolicy[]>([])
const members = ref<ProjectMember[]>([])
const auditLogs = ref<AuditLog[]>([])

const auditPage = ref(1)
const auditPageSize = ref(20)
const auditTotal = ref(0)
const auditActionFilter = ref('')

// Dialog state
const showRoleDialog = ref(false)
const editingRole = ref<Role | null>(null)
const showMemberDialog = ref(false)
const showAssignDialog = ref(false)
const editingMember = ref<ProjectMember | null>(null)
const showPolicyDialog = ref(false)
const editingPolicy = ref<DataPolicy | null>(null)

const customAndBuiltinRoles = computed(() => roles.value)
const assignableRoles = computed(() => roles.value)

const permissionMatrix = computed(() => permissions.value)

const roleHasPermission = (role: Role, code: string): boolean =>
  (role.permission_codes || []).includes(code)

const scopeLabel = (scope: string): string => {
  const map: Record<string, string> = {
    all: '全部可见',
    owner: '仅负责人',
    members: '指定成员',
  }
  return map[scope] || scope
}

const loadCoreData = async () => {
  if (!projectId.value) return
  loading.value = true
  try {
    const [catalog, roleList, policies, memberList] = await Promise.all([
      permissionApi.getCatalog(projectId.value),
      permissionApi.listRoles(projectId.value),
      permissionApi.listDataPolicies(projectId.value),
      permissionApi.listMembers(projectId.value),
    ])
    permissions.value = catalog
    roles.value = roleList
    dataPolicies.value = policies
    members.value = memberList
  } catch (err) {
    ElMessage.error('加载权限数据失败')
  } finally {
    loading.value = false
  }
}

const loadAudit = async () => {
  if (!projectId.value) return
  loading.value = true
  try {
    const page = await permissionApi.listAuditLogs(projectId.value, {
      page: auditPage.value,
      page_size: auditPageSize.value,
      action: auditActionFilter.value || undefined,
    })
    auditLogs.value = page.items
    auditTotal.value = page.total
  } catch (err) {
    ElMessage.error('加载审计日志失败')
  } finally {
    loading.value = false
  }
}

// Role handlers
const openRoleDialog = (role?: Role) => {
  editingRole.value = role || null
  showRoleDialog.value = true
}
const handleDeleteRole = async (role: Role) => {
  try {
    await ElMessageBox.confirm(`确认删除角色「${role.name}」？`, '删除确认', { type: 'warning' })
    await permissionApi.deleteRole(projectId.value!, role.id)
    ElMessage.success('角色已删除')
    loadCoreData()
  } catch (err: any) {
    if (err !== 'cancel') ElMessage.error(err?.message || '删除失败')
  }
}
const onRoleSaved = () => {
  showRoleDialog.value = false
  loadCoreData()
}

// Member handlers
const openMemberDialog = () => {
  showMemberDialog.value = true
}
const openAssignDialog = (member: ProjectMember) => {
  editingMember.value = member
  showAssignDialog.value = true
}
const handleRemoveMember = async (member: ProjectMember) => {
  try {
    await ElMessageBox.confirm(`确认移除成员「${member.username}」？`, '移除确认', { type: 'warning' })
    await permissionApi.removeMember(projectId.value!, member.user_id)
    ElMessage.success('成员已移除')
    loadCoreData()
  } catch (err: any) {
    if (err !== 'cancel') ElMessage.error(err?.message || '移除失败')
  }
}
const onMemberSaved = () => {
  showMemberDialog.value = false
  showAssignDialog.value = false
  loadCoreData()
}

// Data policy handlers
const openPolicyDialog = (policy: DataPolicy) => {
  editingPolicy.value = policy
  showPolicyDialog.value = true
}
const onPolicySaved = () => {
  showPolicyDialog.value = false
  loadCoreData()
}

watch(projectId, (val) => {
  if (val) {
    loadCoreData()
    loadAudit()
  }
})
watch(activeTab, (tab) => {
  if (tab === 'audit') loadAudit()
})

onMounted(() => {
  if (projectId.value) loadCoreData()
})
</script>

<style scoped>
.permission-view {
  padding: 20px;
}
.page-head {
  margin-bottom: 20px;
}
.page-head h1 {
  font-size: 24px;
  margin: 0;
}
.permission-tabs {
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
.code-hint {
  color: #909399;
  font-size: 12px;
}
.muted {
  color: #c0c4cc;
}
</style>
