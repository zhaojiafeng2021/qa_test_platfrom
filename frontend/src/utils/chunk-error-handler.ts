/**
 * Chunk 加载失败检测与自动恢复
 * 解决 SPA 版本更新后旧页面加载新 chunk 失败的问题
 */

const CHUNK_RELOAD_KEY = 'chunk_reload_ts'
const CHUNK_RELOAD_ATTEMPT_KEY = 'chunk_reload_attempt'
const CHUNK_RELOAD_WINDOW_MS = 10_000  // 10秒窗口期
const MAX_RELOAD_ATTEMPTS = 3  // 最大重试次数

/**
 * 检测是否为 chunk 加载错误
 */
export function isChunkLoadError(error: unknown): boolean {
  const msg = (error as { message?: string })?.message || String(error || '')
  const isChunkError = (
    msg.includes('Failed to fetch dynamically imported module') ||
    msg.includes('Importing a module script failed') ||
    msg.includes('error loading dynamically imported module') ||
    msg.includes('Unable to preload CSS') ||
    msg.includes('dynamically imported module')
  )

  if (isChunkError) {
    console.warn('[Chunk Load Error]', msg, error)
  }
  return isChunkError
}

/**
 * 刷新页面以加载新版本
 */
export function reloadForChunkError(target: string): boolean {
  const now = Date.now()
  const lastReload = Number(sessionStorage.getItem(CHUNK_RELOAD_KEY) || '0')
  const attempts = Number(sessionStorage.getItem(CHUNK_RELOAD_ATTEMPT_KEY) || '0')

  // 窗口期内检查重试次数
  if (now - lastReload < CHUNK_RELOAD_WINDOW_MS) {
    if (attempts >= MAX_RELOAD_ATTEMPTS) {
      console.error('[Chunk Reload] 超过最大重试次数，请手动刷新页面或联系管理员')
      alert('页面版本已更新，但自动刷新失败。请手动刷新页面（Ctrl+F5 或 Cmd+Shift+R）')
      return false
    }
    sessionStorage.setItem(CHUNK_RELOAD_ATTEMPT_KEY, String(attempts + 1))
  } else {
    // 超出窗口期，重置计数器
    sessionStorage.setItem(CHUNK_RELOAD_ATTEMPT_KEY, '1')
  }

  sessionStorage.setItem(CHUNK_RELOAD_KEY, String(now))

  console.log(`[Chunk Reload] 尝试刷新 (${attempts + 1}/${MAX_RELOAD_ATTEMPTS}): ${target}`)

  // 强制刷新：绕过所有缓存
  const sep = target.includes('?') ? '&' : '?'
  window.location.replace(`${target}${sep}_r=${now}`)
  return true
}

/**
 * 清除刷新计数器（导航成功后调用）
 */
export function clearChunkReloadCounter() {
  sessionStorage.removeItem(CHUNK_RELOAD_KEY)
  sessionStorage.removeItem(CHUNK_RELOAD_ATTEMPT_KEY)
}

/**
 * 初始化全局错误处理
 * 捕获非路由级别的 chunk 加载错误
 */
export function setupGlobalChunkErrorHandler() {
  // 捕获 window.onerror
  window.addEventListener('error', (event) => {
    if (isChunkLoadError(event.error) || isChunkLoadError(event.message)) {
      event.preventDefault()  // 阻止默认错误提示
      console.warn('[Global] 检测到 chunk 加载错误，准备刷新')
      reloadForChunkError(window.location.pathname + window.location.search)
    }
  })

  // 捕获未处理的 Promise rejection
  window.addEventListener('unhandledrejection', (event) => {
    if (isChunkLoadError(event.reason)) {
      event.preventDefault()
      console.warn('[Global] 检测到 Promise rejection chunk 错误，准备刷新')
      reloadForChunkError(window.location.pathname + window.location.search)
    }
  })
}
