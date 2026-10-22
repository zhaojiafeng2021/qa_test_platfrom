<!-- 新建/编辑覆盖率任务弹窗 -->
<template>
  <el-dialog
    v-model="visible"
    :title="isEdit ? '编辑覆盖率任务' : '新建覆盖率任务'"
    width="640px"
    :close-on-click-modal="false"
    @closed="handleClosed"
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="120px">
      <el-form-item label="任务名称" prop="name">
        <el-input v-model="form.name" placeholder="例：订单服务 - master 覆盖率" maxlength="64" />
      </el-form-item>

      <el-form-item label="代码源" prop="repo_url">
        <div v-if="projectId" class="repo-row">
          <el-select
            v-model="form.repo_id"
            placeholder="选择已接入的代码源"
            clearable
            filterable
            class="repo-select"
            :loading="reposLoading"
            @change="onRepoChange"
          >
            <el-option v-for="r in repos" :key="r.id" :label="r.name" :value="r.id">
              <span>{{ r.name }}</span>
              <span class="opt-sub">{{ r.repo_url }}</span>
            </el-option>
          </el-select>
          <el-button link type="primary" @click="manageVisible = true">管理代码源</el-button>
        </div>
        <el-input
          v-if="!form.repo_id"
          v-model="form.repo_url"
          placeholder="未选择代码源时手动填写：https://git.example.com/group/repo.git"
          class="repo-manual"
        />
        <div v-else class="hint repo-url-hint">{{ selectedRepo?.repo_url }}</div>
      </el-form-item>

      <el-form-item label="目标分支" prop="branch">
        <el-select
          v-if="form.repo_id"
          v-model="form.branch"
          filterable
          placeholder="选择分支"
          class="full-width"
          :loading="branchesLoading"
        >
          <el-option v-for="b in branches" :key="b.name" :label="b.name" :value="b.name">
            <span>{{ b.name }}</span>
            <span class="opt-sub">{{ b.commit_sha.slice(0, 8) }}</span>
          </el-option>
        </el-select>
        <el-input v-else v-model="form.branch" placeholder="master" />
      </el-form-item>

      <el-form-item label="Diff 基准分支">
        <el-input v-model="form.diff_base_branch" placeholder="留空则使用 master（二期生效）" />
      </el-form-item>

      <el-form-item label="采集模式">
        <el-radio-group v-model="form.collection_mode">
          <el-radio value="unittest">单元测试</el-radio>
          <el-radio value="runtime">运行时 (tcpserver dump)</el-radio>
        </el-radio-group>
      </el-form-item>

      <template v-if="isRuntime">
        <el-form-item label="Agent 地址" prop="runtime_host">
          <el-input v-model="form.runtime_host" placeholder="默认 agent 地址，如 10.0.1.100（服务可单独覆盖）" class="rt-host-input" />
          <el-input-number v-model="form.runtime_port" :min="1" :max="65535" controls-position="right" class="rt-port-input" />
        </el-form-item>
        <el-form-item label="Dump 后重置">
          <el-switch v-model="form.runtime_reset" />
          <span class="hint">开启后每次采集只统计上次 dump 以来的覆盖</span>
        </el-form-item>
        <el-alert type="info" :closable="false" class="rt-tip">
          被测应用需以 <code>-javaagent:jacocoagent.jar=output=tcpserver,address=*,port={{ form.runtime_port }}</code> 启动，
          且部署的代码须与目标分支一致，否则覆盖数据无法匹配。
        </el-alert>
      </template>

      <el-form-item label="服务列表" prop="services">
        <div class="svc-list">
          <el-select
            v-if="form.repo_id"
            v-model="selectedServicePaths"
            multiple
            filterable
            placeholder="选择分支后自动发现含 pom.xml / build.gradle 的服务"
            class="full-width svc-select"
            :loading="servicesLoading"
            :disabled="!form.branch"
          >
            <el-option v-for="s in discoveredServices" :key="s.path" :label="s.name" :value="s.path">
              <span>{{ s.name }}</span>
              <span class="opt-sub">{{ s.path }} · {{ s.build_tool }}</span>
            </el-option>
          </el-select>
          <!-- 代码源模式：服务名/路径来自自动发现，只读；仍可配置模块与服务级 agent -->
          <div v-for="(svc, idx) in form.services" :key="svc.path || idx" class="svc-item">
            <el-input v-model="svc.name" placeholder="服务名 (必填)" class="svc-name-input" :disabled="!!form.repo_id" />
            <el-input v-model="svc.module" placeholder="模块 (可选)" class="svc-module-input" />
            <el-input
              v-model="svc.path"
              placeholder="相对路径，如 services/order (必填)"
              class="svc-path-input"
              :disabled="!!form.repo_id"
            />
            <template v-if="isRuntime">
              <el-input v-model="svc.agent_host" placeholder="agent 地址 (可选)" class="svc-host-input" />
              <el-input v-model.number="svc.agent_port" placeholder="端口" class="svc-port-input" />
            </template>
            <el-button
              v-if="!form.repo_id"
              link
              type="danger"
              :icon="Delete"
              :disabled="form.services.length <= 1"
              @click="removeService(idx)"
            />
          </div>
          <el-button v-if="!form.repo_id" link type="primary" :icon="Plus" @click="addService">添加服务</el-button>
        </div>
      </el-form-item>

      <el-form-item label="Cron 表达式">
        <el-input v-model="form.cron_expr" placeholder="二期生效，可留空" />
      </el-form-item>

      <el-form-item label="行覆盖阈值">
        <el-input-number v-model="form.threshold_line_rate" :min="0" :max="1" :step="0.05" :precision="2" />
        <span class="hint">0-1，二期生效</span>
      </el-form-item>

      <el-form-item label="分支覆盖阈值">
        <el-input-number v-model="form.threshold_branch_rate" :min="0" :max="1" :step="0.05" :precision="2" />
      </el-form-item>

      <el-form-item label="关联需求">
        <el-input v-model="form.requirement_ref" placeholder="需求 ID / 链接（二期生效）" />
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="handleSubmit">{{ isEdit ? '保存' : '创建' }}</el-button>
    </template>

    <CodeRepoManageDialog
      v-if="projectId"
      v-model="manageVisible"
      :project-id="projectId"
      append-to-body
      @changed="loadRepos"
    />
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { Delete, Plus } from '@element-plus/icons-vue'
import type { FormInstance, FormRules } from 'element-plus'
import { listCodeRepos, listRepoBranches, listRepoServices } from '@/api/coverage'
import type {
  CodeRepository,
  CollectionMode,
  CoverageTask,
  CoverageTaskCreatePayload,
  RepoBranch,
  RepoService,
  ServiceRef,
} from '@/types/coverage'
import CodeRepoManageDialog from './CodeRepoManageDialog.vue'

interface Props {
  modelValue: boolean
  task?: CoverageTask | null
  /** 传入后启用代码源下拉（仓库 / 分支 / 服务） */
  projectId?: number | null
}
const props = defineProps<Props>()

const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void
  (e: 'submit', payload: CoverageTaskCreatePayload, isEdit: boolean): void
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const isEdit = computed(() => !!props.task)
const saving = ref(false)
const formRef = ref<FormInstance>()

interface FormState {
  name: string
  repo_id?: number
  repo_url: string
  branch: string
  diff_base_branch: string
  cron_expr: string
  requirement_ref: string
  threshold_line_rate?: number
  threshold_branch_rate?: number
  collection_mode: CollectionMode
  runtime_host: string
  runtime_port: number
  runtime_reset: boolean
  services: ServiceRef[]
}

const form = reactive<FormState>({
  name: '',
  repo_id: undefined,
  repo_url: '',
  branch: 'master',
  diff_base_branch: '',
  cron_expr: '',
  requirement_ref: '',
  threshold_line_rate: undefined,
  threshold_branch_rate: undefined,
  collection_mode: 'unittest',
  runtime_host: '',
  runtime_port: 6300,
  runtime_reset: false,
  services: [{ name: '', module: '', path: '' }],
})

const isRuntime = computed(() => form.collection_mode === 'runtime')

const rules: FormRules = {
  name: [{ required: true, message: '请输入任务名称', trigger: 'blur' }],
  repo_url: [
    {
      validator: (_r, _v, cb) =>
        form.repo_id || form.repo_url.trim() ? cb() : cb(new Error('请选择代码源或填写 Git 仓库地址')),
      trigger: 'blur',
    },
  ],
  branch: [{ required: true, message: '请选择或输入目标分支', trigger: 'change' }],
  services: [
    {
      validator: (_r, value: ServiceRef[], cb) => {
        if (!value || value.length === 0) return cb(new Error('至少添加一个服务'))
        for (const s of value) {
          if (!s.name?.trim()) return cb(new Error('服务名不能为空'))
          if (!s.path?.trim()) return cb(new Error('服务路径不能为空'))
          if (isRuntime.value && !s.agent_host?.trim() && !form.runtime_host.trim()) {
            return cb(new Error(`服务 ${s.name} 未配置 agent 地址（填写默认 Agent 地址或服务级地址）`))
          }
        }
        cb()
      },
      trigger: 'blur',
    },
  ],
}

watch(
  () => props.task,
  (t) => {
    if (t) {
      form.name = t.name
      form.repo_id = t.repo_id ?? undefined
      form.repo_url = t.repo_url
      form.branch = t.branch
      form.diff_base_branch = t.diff_base_branch || ''
      form.cron_expr = t.cron_expr || ''
      form.requirement_ref = t.requirement_ref || ''
      form.threshold_line_rate = t.threshold_line_rate
      form.threshold_branch_rate = t.threshold_branch_rate
      form.collection_mode = t.collection_mode || 'unittest'
      form.runtime_host = t.runtime_config?.host || ''
      form.runtime_port = t.runtime_config?.port || 6300
      form.runtime_reset = !!t.runtime_config?.reset
      form.services = t.services?.length ? t.services.map((s) => ({ ...s })) : [{ name: '', module: '', path: '' }]
    } else {
      resetForm()
    }
  },
  { immediate: true },
)

function resetForm(): void {
  form.name = ''
  form.repo_id = undefined
  form.repo_url = ''
  form.branch = 'master'
  form.diff_base_branch = ''
  form.cron_expr = ''
  form.requirement_ref = ''
  form.threshold_line_rate = undefined
  form.threshold_branch_rate = undefined
  form.collection_mode = 'unittest'
  form.runtime_host = ''
  form.runtime_port = 6300
  form.runtime_reset = false
  form.services = [{ name: '', module: '', path: '' }]
}

// ─── 代码源：下拉选择仓库 / 分支 / 服务 ───

const manageVisible = ref(false)
const repos = ref<CodeRepository[]>([])
const branches = ref<RepoBranch[]>([])
const discoveredServices = ref<RepoService[]>([])
const reposLoading = ref(false)
const branchesLoading = ref(false)
const servicesLoading = ref(false)
// 丢弃过期请求结果（快速切换仓库/分支时）
let branchSeq = 0
let serviceSeq = 0

const selectedRepo = computed(() => repos.value.find((r) => r.id === form.repo_id))

async function loadRepos(): Promise<void> {
  if (!props.projectId) return
  reposLoading.value = true
  try {
    repos.value = await listCodeRepos(props.projectId)
    // 新建任务时默认选中第一个代码源，省去手动输入
    if (!isEdit.value && !form.repo_id && !form.repo_url && repos.value.length) {
      form.repo_id = repos.value[0].id
      onRepoChange()
    }
  } finally {
    reposLoading.value = false
  }
}

async function loadBranches(): Promise<void> {
  const repoId = form.repo_id
  if (!props.projectId || !repoId) return
  const seq = ++branchSeq
  branchesLoading.value = true
  try {
    const list = await listRepoBranches(props.projectId, repoId)
    if (seq !== branchSeq) return
    branches.value = list
    if (!list.some((b) => b.name === form.branch)) {
      const def = selectedRepo.value?.default_branch
      form.branch = list.find((b) => b.name === def)?.name ?? list[0]?.name ?? ''
    }
  } finally {
    if (seq === branchSeq) branchesLoading.value = false
  }
}

async function loadServices(): Promise<void> {
  const repoId = form.repo_id
  const branch = form.branch
  if (!props.projectId || !repoId || !branch) return
  const seq = ++serviceSeq
  servicesLoading.value = true
  try {
    const list = await listRepoServices(props.projectId, repoId, branch)
    if (seq !== serviceSeq) return
    discoveredServices.value = list
  } finally {
    if (seq === serviceSeq) servicesLoading.value = false
  }
}

/** 用户切换代码源：清空分支与服务，重新拉取 */
function onRepoChange(): void {
  branches.value = []
  discoveredServices.value = []
  form.branch = ''
  form.services = form.repo_id ? [] : [{ name: '', module: '', path: '' }]
}

/** 多选框与 form.services 双向同步；保留已选服务上配置的模块 / agent */
const selectedServicePaths = computed<string[]>({
  get: () => form.services.filter((s) => s.path).map((s) => s.path),
  set: (paths) => {
    form.services = paths.map((p) => {
      const existing = form.services.find((s) => s.path === p)
      if (existing) return existing
      const found = discoveredServices.value.find((s) => s.path === p)
      return { name: found?.name ?? p, module: '', path: p }
    })
  },
})

watch(
  () => [visible.value, props.projectId] as const,
  ([v]) => { if (v) loadRepos() },
  { immediate: true },
)
watch(() => form.repo_id, () => loadBranches(), { immediate: true })
watch(() => [form.repo_id, form.branch] as const, ([, branch], old) => {
  // 用户切换分支时清掉旧分支的服务选择
  if (old && old[0] === form.repo_id && old[1] && old[1] !== branch) form.services = []
  discoveredServices.value = []
  loadServices()
}, { immediate: true })

function addService(): void {
  form.services.push({ name: '', module: '', path: '' })
}

function removeService(idx: number): void {
  form.services.splice(idx, 1)
}

async function handleSubmit(): Promise<void> {
  if (!formRef.value) return
  await formRef.value.validate()
  saving.value = true
  try {
    const payload: CoverageTaskCreatePayload = {
      name: form.name.trim(),
      repo_id: form.repo_id,
      // 选了代码源时由后端按代码源回填仓库地址
      repo_url: form.repo_id ? undefined : form.repo_url.trim(),
      branch: form.branch.trim() || 'master',
      diff_base_branch: form.diff_base_branch.trim() || undefined,
      cron_expr: form.cron_expr.trim() || undefined,
      requirement_ref: form.requirement_ref.trim() || undefined,
      threshold_line_rate: form.threshold_line_rate,
      threshold_branch_rate: form.threshold_branch_rate,
      collection_mode: form.collection_mode,
      runtime_config: isRuntime.value
        ? { host: form.runtime_host.trim() || undefined, port: form.runtime_port, reset: form.runtime_reset }
        : undefined,
      services: form.services.map((s) => ({
        name: s.name.trim(),
        module: s.module?.trim() || undefined,
        path: s.path.trim(),
        ...(isRuntime.value
          ? { agent_host: s.agent_host?.trim() || undefined, agent_port: s.agent_port || undefined }
          : {}),
      })),
    }
    emit('submit', payload, isEdit.value)
    visible.value = false
  } finally {
    saving.value = false
  }
}

function handleClosed(): void {
  if (!isEdit.value) resetForm()
}
</script>

<style scoped>
.repo-row {
  width: 100%;
  display: flex;
  gap: 8px;
  align-items: center;
}
.repo-select { flex: 1; }
.repo-manual { margin-top: 8px; }
.repo-url-hint { margin-left: 0; }
.full-width { width: 100%; }
.opt-sub {
  float: right;
  margin-left: 12px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.svc-list {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.svc-item {
  display: flex;
  gap: 6px;
  align-items: center;
}
.svc-name-input { width: 140px; }
.svc-module-input { width: 120px; }
.svc-path-input { flex: 1; }
.svc-host-input { width: 130px; }
.svc-port-input { width: 70px; }
.rt-host-input { flex: 1; margin-right: 8px; }
.rt-port-input { width: 120px; }
.rt-tip { margin: -6px 0 16px 120px; width: auto; }
.rt-tip code { font-size: 12px; }
.hint {
  margin-left: 8px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
</style>
