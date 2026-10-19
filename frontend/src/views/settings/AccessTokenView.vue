<template>
  <div class="token-view">
    <div class="page-head">
      <div>
        <h1><el-icon><Key /></el-icon>访问令牌</h1>
        <p>个人访问令牌（PAT）用于 CI/CD 流水线等自动化场景调用平台接口，等同于你的账号身份。请妥善保管。</p>
      </div>
      <div class="actions">
        <el-button type="primary" :icon="Plus" @click="openCreate">新建令牌</el-button>
      </div>
    </div>

    <el-table :data="tokens" v-loading="loading" empty-text="暂无令牌">
      <el-table-column prop="name" label="名称" min-width="160" />
      <el-table-column label="令牌前缀" min-width="140">
        <template #default="{ row }">
          <code>{{ row.token_prefix }}…</code>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag v-if="!row.is_active" type="info">已吊销</el-tag>
          <el-tag v-else-if="isExpired(row)" type="danger">已过期</el-tag>
          <el-tag v-else type="success">有效</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="有效期" min-width="180">
        <template #default="{ row }">
          <span v-if="row.expires_at">{{ formatTime(row.expires_at) }}</span>
          <el-tag v-else type="warning" effect="plain">永不过期</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="最近使用" min-width="180">
        <template #default="{ row }">
          {{ row.last_used_at ? formatTime(row.last_used_at) : '从未使用' }}
        </template>
      </el-table-column>
      <el-table-column label="创建时间" min-width="180">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="100" fixed="right">
        <template #default="{ row }">
          <el-popconfirm title="吊销后使用该令牌的调用将立即失效，确定吊销？" @confirm="revoke(row)">
            <template #reference>
              <el-button type="danger" link :disabled="!row.is_active">吊销</el-button>
            </template>
          </el-popconfirm>
        </template>
      </el-table-column>
    </el-table>

    <!-- 创建对话框 -->
    <el-dialog v-model="createVisible" title="新建访问令牌" width="480px">
      <el-form :model="form" label-width="90px">
        <el-form-item label="名称" required>
          <el-input v-model="form.name" placeholder="用途标识，如 CICD-流水线门禁" maxlength="100" />
        </el-form-item>
        <el-form-item label="有效期">
          <el-select v-model="form.expires_option" style="width: 100%">
            <el-option label="永不过期" value="never" />
            <el-option label="30 天" :value="30" />
            <el-option label="90 天" :value="90" />
            <el-option label="180 天" :value="180" />
            <el-option label="365 天" :value="365" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="submitCreate">创建</el-button>
      </template>
    </el-dialog>

    <!-- 明文展示对话框 -->
    <el-dialog v-model="resultVisible" title="令牌创建成功" width="560px" :close-on-click-modal="false">
      <el-alert type="warning" :closable="false" show-icon
        title="令牌明文仅显示这一次，关闭后无法再次查看，请立即复制保存。" style="margin-bottom: 16px" />
      <div class="token-plain">
        <code>{{ createdToken?.token }}</code>
        <el-button :icon="CopyDocument" @click="copyToken">复制</el-button>
      </div>
      <template #footer>
        <el-button type="primary" @click="resultVisible = false">我已保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Key, Plus, CopyDocument } from '@element-plus/icons-vue'
import { authApi, type ApiTokenInfo, type ApiTokenCreateResult } from '@/api/auth'

const loading = ref(false)
const tokens = ref<ApiTokenInfo[]>([])

const createVisible = ref(false)
const creating = ref(false)
const form = ref<{ name: string; expires_option: string | number }>({ name: '', expires_option: 'never' })

const resultVisible = ref(false)
const createdToken = ref<ApiTokenCreateResult | null>(null)

function formatTime(t?: string | null): string {
  if (!t) return '-'
  return new Date(t).toLocaleString('zh-CN', { hour12: false })
}

function isExpired(row: ApiTokenInfo): boolean {
  return !!row.expires_at && new Date(row.expires_at).getTime() < Date.now()
}

async function loadTokens() {
  loading.value = true
  try {
    tokens.value = await authApi.listApiTokens()
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
}

function openCreate() {
  form.value = { name: '', expires_option: 'never' }
  createVisible.value = true
}

async function submitCreate() {
  if (!form.value.name.trim()) {
    ElMessage.warning('请输入令牌名称')
    return
  }
  creating.value = true
  try {
    const expires_in_days = form.value.expires_option === 'never'
      ? null
      : Number(form.value.expires_option)
    createdToken.value = await authApi.createApiToken({
      name: form.value.name.trim(),
      expires_in_days,
    })
    createVisible.value = false
    resultVisible.value = true
    await loadTokens()
  } catch (e) {
    console.error(e)
  } finally {
    creating.value = false
  }
}

async function copyToken() {
  if (!createdToken.value) return
  try {
    await navigator.clipboard.writeText(createdToken.value.token)
    ElMessage.success('已复制到剪贴板')
  } catch {
    ElMessage.warning('复制失败，请手动选择复制')
  }
}

async function revoke(row: ApiTokenInfo) {
  try {
    await authApi.revokeApiToken(row.id)
    ElMessage.success('令牌已吊销')
    await loadTokens()
  } catch (e) {
    console.error(e)
  }
}

onMounted(loadTokens)
</script>

<style scoped>
.token-view { padding: 24px; }
.page-head { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 20px; }
.page-head h1 { display: flex; align-items: center; gap: 8px; font-size: 20px; margin: 0 0 6px; }
.page-head p { color: var(--txt3, #909399); font-size: 13px; margin: 0; max-width: 720px; }
.token-plain { display: flex; align-items: center; gap: 12px; background: var(--primary-bg, #f5f7fa); padding: 12px; border-radius: 6px; }
.token-plain code { flex: 1; word-break: break-all; font-size: 13px; }
</style>
