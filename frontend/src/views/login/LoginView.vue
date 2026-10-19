<template>
  <div class="login-view">
    <section class="brand-panel" aria-label="QA 测试平台">
      <div class="brand-mark"><el-icon><DataAnalysis /></el-icon></div>
      <div class="brand-copy">
        <span class="brand-kicker">QUALITY ENGINEERING</span>
        <h1>QA 测试平台</h1>
        <p>让测试资产、自动化编排与执行结果保持在同一个工作空间。</p>
      </div>
      <div class="brand-grid" aria-hidden="true">
        <span v-for="index in 20" :key="index" />
      </div>
      <div class="brand-meta">QA PLATFORM · 2026</div>
    </section>

    <main class="login-panel">
      <div class="login-box">
        <div class="mobile-brand">
          <span class="mobile-mark"><el-icon><DataAnalysis /></el-icon></span>
          <b>QA 测试平台</b>
        </div>
        <div class="login-header">
          <h2>登录工作台</h2>
          <p>使用平台账号继续</p>
        </div>

        <el-form ref="formRef" :model="loginForm" :rules="rules" class="login-form" label-position="top">
          <el-form-item label="用户名" prop="username">
            <el-input
              v-model="loginForm.username"
              placeholder="请输入用户名"
              size="large"
              :prefix-icon="User"
              autocomplete="username"
            />
          </el-form-item>
          <el-form-item label="密码" prop="password">
            <el-input
              v-model="loginForm.password"
              type="password"
              placeholder="请输入密码"
              size="large"
              :prefix-icon="Lock"
              autocomplete="current-password"
              show-password
              @keyup.enter="handleLogin"
            />
          </el-form-item>
          <el-form-item class="submit-item">
            <el-button type="primary" size="large" :loading="loading" @click="handleLogin">
              登录
            </el-button>
          </el-form-item>
        </el-form>

        <div class="login-divider"><span>其他方式</span></div>
        <el-button class="feishu-button" size="large" :loading="feishuLoading" @click="handleFeishuLogin">
          使用飞书登录
        </el-button>
        <p class="login-footer">© 2026 QA Platform</p>
      </div>
    </main>
  </div>
</template>
<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { DataAnalysis, Lock, User } from '@element-plus/icons-vue'
import type { FormInstance, FormRules } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { authApi } from '@/api/auth'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

const formRef = ref<FormInstance>()
const loading = ref(false)
const feishuLoading = ref(false)

const loginForm = reactive({
  username: '',
  password: ''
})

const rules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }]
}

const redirectAfterLogin = async () => {
  // 清除旧的项目缓存，确保切换账号后重新加载
  const { useProjectStore } = await import('@/stores/project')
  const projectStore = useProjectStore()
  projectStore.clearCurrentProject()

  // 拉取当前用户信息（含权限）
  const me = await authApi.getMe()
  authStore.setUser(me)

  const redirect = route.query.redirect as string | undefined
  if (redirect) {
    router.push(redirect)
  } else {
    // 默认跳转到项目列表
    router.push('/projects')
  }
}

const handleLogin = async () => {
  if (!formRef.value) return

  await formRef.value.validate(async (valid) => {
    if (valid) {
      loading.value = true
      try {
        const result = await authApi.login(loginForm)
        authStore.setTokens(result.access_token, result.refresh_token)
        ElMessage.success('登录成功')
        await redirectAfterLogin()
      } catch (error) {
        // 错误提示已由响应拦截器统一处理
      } finally {
        loading.value = false
      }
    }
  })
}

const handleFeishuLogin = async () => {
  feishuLoading.value = true
  try {
    // 获取当前页面的 redirect 参数（如果有）
    const redirect = route.query.redirect as string | undefined

    // 调用后端获取授权 URL，传递 redirect 参数，加 _t 防缓存
    const params: Record<string, string> = { _t: String(Date.now()) }
    if (redirect) params.redirect = redirect
    const { authorization_url } = await authApi.getFeishuAuthUrl(params)

    // 跳转到飞书授权页面
    window.location.href = authorization_url
  } catch (error) {
    // 错误提示已由响应拦截器统一处理
    feishuLoading.value = false
  }
}
</script>
<style scoped>
.login-view { min-height: 100vh; display: grid; grid-template-columns: minmax(360px, 46%) 1fr; background: #fff; }
.brand-panel { position: relative; min-height: 100vh; padding: 48px 56px; overflow: hidden; display: flex; flex-direction: column; background: var(--sidebar); color: #fff; }
.brand-mark { width: 42px; height: 42px; display: grid; place-items: center; border-radius: 8px; background: var(--primary); font-size: 22px; }
.brand-copy { position: relative; z-index: 1; max-width: 520px; margin: auto 0; }
.brand-kicker { color: #7691B8; font-size: 11px; font-weight: 700; letter-spacing: 2px; }
.brand-copy h1 { margin: 16px 0 14px; font-size: 38px; line-height: 1.2; letter-spacing: 0; }
.brand-copy p { max-width: 440px; margin: 0; color: #AFC0D8; font-size: 15px; line-height: 1.8; }
.brand-grid { position: absolute; right: -80px; bottom: 70px; width: 420px; display: grid; grid-template-columns: repeat(5, 58px); gap: 12px; transform: rotate(-8deg); opacity: .3; }
.brand-grid span { aspect-ratio: 1; border: 1px solid #43618A; border-radius: 6px; background: rgba(59,123,245,.08); }
.brand-grid span:nth-child(3n) { background: rgba(59,123,245,.32); border-color: #3B7BF5; }
.brand-meta { position: relative; z-index: 1; margin-top: auto; color: #526C91; font-size: 10px; letter-spacing: 1.5px; }
.login-panel { min-height: 100vh; display: grid; place-items: center; padding: 40px; }
.login-box { width: min(100%, 380px); }
.mobile-brand { display: none; }
.login-header { margin-bottom: 30px; }
.login-header h2 { margin: 0; color: var(--txt); font-size: 24px; letter-spacing: 0; }
.login-header p { margin: 8px 0 0; color: var(--txt3); font-size: 13px; }
.login-form :deep(.el-form-item__label) { padding-bottom: 7px; color: var(--txt2); font-size: 12px; font-weight: 600; }
.login-form :deep(.el-input__wrapper) { min-height: 44px; border-radius: var(--r); box-shadow: 0 0 0 1px var(--line) inset; }
.login-form :deep(.el-input__wrapper.is-focus) { box-shadow: 0 0 0 1px var(--primary) inset; }
.submit-item { margin-top: 8px; margin-bottom: 0; }
.submit-item :deep(.el-form-item__content), .submit-item .el-button { width: 100%; }
.submit-item .el-button { min-height: 44px; }
.login-divider { display: flex; align-items: center; gap: 12px; margin: 24px 0 16px; color: var(--txt3); font-size: 11px; }
.login-divider::before, .login-divider::after { content: ''; height: 1px; flex: 1; background: var(--line); }
.feishu-button { width: 100%; min-height: 44px; }
.login-footer { margin: 28px 0 0; text-align: center; color: var(--txt3); font-size: 10px; }
@media (max-width: 840px) {
  .login-view { display: block; }
  .brand-panel { display: none; }
  .login-panel { padding: 28px 20px; background: var(--bg); }
  .login-box { padding: 28px 24px; border: 1px solid var(--line); border-radius: var(--r2); background: #fff; box-shadow: var(--shadow); }
  .mobile-brand { display: flex; align-items: center; gap: 9px; margin-bottom: 34px; color: var(--txt); font-size: 14px; }
  .mobile-mark { width: 30px; height: 30px; display: grid; place-items: center; border-radius: 6px; background: var(--primary); color: #fff; }
}
</style>