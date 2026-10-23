<!-- 触发采集：选择来源 + 从分支提交列表中选 commit（不支持手填） -->
<template>
  <el-dialog :model-value="modelValue" title="触发采集" width="640px" @update:model-value="emit('update:modelValue', $event)" @open="onOpen">
    <el-form label-width="88px">
      <el-form-item label="采集来源">
        <el-radio-group v-model="source">
          <el-radio-button value="unittest">单元测试</el-radio-button>
          <el-radio-button value="runtime" :disabled="!runtimeAvailable">运行时</el-radio-button>
        </el-radio-group>
        <div v-if="!runtimeAvailable" class="hint">任务未配置运行时 agent，只能采集单测覆盖</div>
      </el-form-item>

      <el-form-item label="Commit">
        <template v-if="task.repo_id">
          <el-select
            v-model="commitSha"
            filterable
            :filter-method="onFilter"
            :loading="commitsLoading"
            placeholder="选择分支上的提交"
            class="commit-select"
            @visible-change="(v: boolean) => v && (keyword = '')"
          >
            <el-option v-for="c in filteredCommits" :key="c.sha" :value="c.sha" :label="optionLabel(c)">
              <div class="commit-opt">
                <span class="sha">{{ c.short_sha }}</span>
                <span class="subject">{{ c.subject }}</span>
                <span class="meta">{{ c.author }} · {{ formatTime(c.committed_at) }}</span>
              </div>
            </el-option>
          </el-select>
          <div class="hint">
            {{ source === 'runtime' ? '请选择当前部署到环境中的版本，平台会按该 commit 编译 class 以匹配 exec' : '默认分支最新提交' }}
            · 分支 {{ task.branch }}
          </div>
          <div v-if="commitsError" class="error">{{ commitsError }}</div>
        </template>
        <span v-else class="hint">任务未关联代码源，将采集分支 {{ task.branch }} 的最新提交</span>
      </el-form-item>
    </el-form>

    <el-alert
      v-if="mismatchServices.length"
      type="warning"
      :closable="false"
      show-icon
      :title="`任务分支已变更为 ${task.branch}，本次采集将开始新一轮，旧数据只读保留`"
      :description="`涉及服务：${mismatchServices.join('、')}`"
    />

    <template #footer>
      <el-button @click="emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :loading="submitting" :disabled="!canSubmit" @click="submit">触发</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { listRepoCommits } from '@/api/coverage'
import { formatTime } from '@/utils/format'
import type { CollectionMode, CoverageTask, RepoCommit, TriggerPayload } from '@/types/coverage'

const props = defineProps<{
  modelValue: boolean
  task: CoverageTask
  projectId: number
  /** branch_mismatch 的服务：本次采集会自动开新一轮 */
  mismatchServices: string[]
  submitting?: boolean
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void
  (e: 'confirm', payload: TriggerPayload): void
}>()

const source = ref<CollectionMode>('unittest')
const commits = ref<RepoCommit[]>([])
const commitsLoading = ref(false)
const commitsError = ref('')
const commitSha = ref('')
const keyword = ref('')

const runtimeAvailable = computed(() => {
  const t = props.task
  return !!t.runtime_config?.host || (t.services.length > 0 && t.services.every((s) => !!s.agent_host))
})

// 只在已加载的列表里筛选：按 sha 前缀或提交说明
const filteredCommits = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  if (!kw) return commits.value
  return commits.value.filter((c) => c.sha.startsWith(kw) || c.subject.toLowerCase().includes(kw))
})

const canSubmit = computed(() => !props.task.repo_id || (!!commitSha.value && !commitsLoading.value))

function onFilter(v: string): void {
  keyword.value = v
}

function optionLabel(c: RepoCommit): string {
  return `${c.short_sha} · ${formatTime(c.committed_at)} · ${c.author} · ${c.subject}`
}

async function loadCommits(): Promise<void> {
  if (!props.task.repo_id) return
  commitsLoading.value = true
  commitsError.value = ''
  commits.value = []
  commitSha.value = ''
  try {
    commits.value = await listRepoCommits(props.projectId, props.task.repo_id, props.task.branch)
    commitSha.value = commits.value[0]?.sha ?? ''
    if (!commits.value.length) commitsError.value = '该分支没有可选的提交'
  } catch (e: any) {
    commitsError.value = e?.response?.data?.message || e?.message || '加载提交列表失败'
  } finally {
    commitsLoading.value = false
  }
}

function onOpen(): void {
  source.value = props.task.collection_mode === 'runtime' && runtimeAvailable.value ? 'runtime' : 'unittest'
  keyword.value = ''
  void loadCommits()
}

function submit(): void {
  const payload: TriggerPayload = { source: source.value }
  // commitSha 只可能来自下拉列表
  if (props.task.repo_id && commits.value.some((c) => c.sha === commitSha.value)) {
    payload.commit_sha = commitSha.value
  }
  emit('confirm', payload)
}
</script>

<style scoped>
.commit-select { width: 100%; }
.commit-opt {
  display: flex;
  gap: 8px;
  align-items: baseline;
  overflow: hidden;
}
.commit-opt .sha {
  font-family: 'JetBrains Mono', 'Consolas', monospace;
  color: var(--el-color-primary);
  flex-shrink: 0;
}
.commit-opt .subject {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.commit-opt .meta {
  flex-shrink: 0;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.hint {
  width: 100%;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
  margin-top: 4px;
}
.error {
  width: 100%;
  font-size: 12px;
  color: var(--el-color-danger);
}
</style>
