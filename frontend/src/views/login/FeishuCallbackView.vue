<template>
  <div class="callback-view">
    <el-icon class="loading-icon" :size="40"><Loading /></el-icon>
    <p>{{ message }}</p>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Loading } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { authApi } from '@/api/auth'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const message = ref('正在登录，请稍候...')

onMounted(async () => {
  // 后端回调重定向到此页面，携带 access_token / refresh_token / redirect
  const accessToken = route.query.access_token as string | undefined
  const refreshToken = route.query.refresh_token as string | undefined
  const redirect = route.query.redirect as string | undefined
  const error = route.query.error as string | undefined

  if (error) {
    message.value = '飞书登录失败'
    ElMessage.error('飞书登录失败，请重试')
    setTimeout(() => router.replace('/login'), 1500)
    return
  }

  if (!accessToken || !refreshToken) {
    message.value = '登录参数缺失'
    ElMessage.error('登录参数缺失')
    setTimeout(() => router.replace('/login'), 1500)
    return
  }

  try {
    authStore.setTokens(accessToken, refreshToken)
    const me = await authApi.getMe()
    authStore.setUser(me)
    ElMessage.success('登录成功')

    // 如果有 redirect 参数，跳转到指定路径；否则跳转到项目列表
    if (redirect) {
      router.replace(redirect)
    } else {
      router.replace('/projects')
    }
  } catch (e) {
    console.error('飞书登录回调失败:', e)
    message.value = '获取用户信息失败'
    ElMessage.error('获取用户信息失败，请重试')
    setTimeout(() => router.replace('/login'), 1500)
  }
})
</script>

<style scoped>
.callback-view {
  width: 100%;
  height: 100vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
  color: #64748b;
}

.loading-icon {
  animation: rotate 1s linear infinite;
}

@keyframes rotate {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}
</style>
