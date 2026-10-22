import axios, { type AxiosInstance, type AxiosRequestConfig, type AxiosResponse } from 'axios'
import { ElMessage } from 'element-plus'

const baseURL = import.meta.env.VITE_API_BASE_URL || '/api/v1'

// 防止多个 401 响应同时触发跳转
let isRedirectingToLogin = false

// 创建axios实例
const http: AxiosInstance = axios.create({
  baseURL,
  timeout: 120000
})
// 注意：不要在此处硬编码 Content-Type。
// axios 会为普通对象 body 自动设置 application/json，
// 为 FormData 自动设置 multipart/form-data 并附带 boundary。
// 若硬编码 application/json，会覆盖 FormData 的 boundary，导致文件上传后端解析不到 file 字段（422）。

// 请求拦截器
http.interceptors.request.use(
  (config) => {
    // 添加token
    const token = localStorage.getItem('access_token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    // 统一防缓存：所有 GET 请求追加时间戳并禁用缓存，
    // 避免增删改后重新拉取列表时命中浏览器/nginx/CDN 缓存返回旧数据。
    if ((config.method || '').toLowerCase() === 'get') {
      config.params = { ...(config.params || {}), _t: Date.now() }
      config.headers['Cache-Control'] = 'no-cache'
      config.headers['Pragma'] = 'no-cache'
    }
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// 响应拦截器
http.interceptors.response.use(
  (response: AxiosResponse) => {
    const { data } = response

    // 统一响应格式 { code, message, data, request_id }
    if (data.code === 0) {
      return data.data
    } else {
      ElMessage.error(data.message || '请求失败')
      return Promise.reject(new Error(data.message || '请求失败'))
    }
  },
  (error) => {
    // 调用方传 { silent: true } 时自行展示错误（401 跳转仍保留）
    const silent = (error.config as { silent?: boolean } | undefined)?.silent
    if (silent && error.response?.status !== 401) {
      return Promise.reject(error)
    }
    if (error.response) {
      const { status, data } = error.response

      switch (status) {
        case 401:
          if (!isRedirectingToLogin) {
            isRedirectingToLogin = true
            ElMessage.error('登录已过期，请重新登录')
            localStorage.removeItem('access_token')
            localStorage.removeItem('refresh_token')
            const currentPath = window.location.pathname + window.location.search
            window.location.href = `/login?redirect=${encodeURIComponent(currentPath)}`
          }
          break
        case 403:
          ElMessage.error(data.message || '权限不足')
          break
        case 404:
          ElMessage.error(data.message || '资源不存在')
          break
        case 409:
          // 版本冲突等，由业务层处理，不弹全局提示
          break
        case 422:
          ElMessage.error(data.message || '参数验证失败')
          break
        case 500:
          ElMessage.error(data.message || '服务器错误')
          break
        default:
          ElMessage.error(data.message || '请求失败')
      }
    } else if (error.request) {
      ElMessage.error('网络错误，请检查网络连接')
    } else {
      ElMessage.error(error.message || '请求配置错误')
    }

    return Promise.reject(error)
  }
)

export default http
