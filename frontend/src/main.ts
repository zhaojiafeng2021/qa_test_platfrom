import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'

import App from './App.vue'
import router from './router'
import './styles/theme.css'
import './styles/index.css'
import './styles/components.css'
import { setupGlobalChunkErrorHandler } from './utils/chunk-error-handler'

// 初始化全局 chunk 错误处理（捕获非路由级别的错误）
setupGlobalChunkErrorHandler()

const app = createApp(App)

// 注册Element Plus图标
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

app.use(createPinia())
app.use(router)
app.use(ElementPlus)

app.mount('#app')
