import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vitest/config'
import { loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
  // .env 里的变量不会自动进 process.env，需要 loadEnv 显式读取
  const env = loadEnv(mode, process.cwd(), '')
  return {
  plugins: [
    vue(),
    AutoImport({
      imports: ['vue', 'vue-router', 'pinia'],
      resolvers: [ElementPlusResolver()],
      dts: 'src/types/auto-imports.d.ts',
    }),
    Components({
      resolvers: [ElementPlusResolver()],
      dts: 'src/types/components.d.ts',
    }),
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  test: {
    environment: 'node',
  },
  server: {
    port: 5273,
    host: '0.0.0.0',
    proxy: {
      '/api': {
        target: env.VITE_PROXY_TARGET || process.env.VITE_PROXY_TARGET || 'http://localhost:8100',
        changeOrigin: true,
      }
    }
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    chunkSizeWarningLimit: 1000,
    rollupOptions: {
      output: {
        // 更细粒度的 chunk 分割，减少单个 chunk 变化对整体的影响
        manualChunks(id) {
          // 第三方库单独打包
          if (id.includes('node_modules')) {
            // axios 单独分包（避免与 view-login 循环依赖）
            if (id.includes('axios')) {
              return 'vendor-axios'
            }
            // Element Plus 单独分包（体积大，变化少）
            if (id.includes('element-plus')) {
              return 'vendor-element-plus'
            }
            // Vue 全家桶
            if (id.includes('vue') || id.includes('pinia') || id.includes('@vue')) {
              return 'vendor-vue'
            }
            // 其他第三方库
            return 'vendor'
          }
          // 业务代码按模块分包
          if (id.includes('/src/views/')) {
            const match = id.match(/\/views\/([^/]+)\//)
            if (match) {
              return `view-${match[1]}`
            }
          }
        },
        // 文件名使用 contenthash，确保内容变化时文件名才变
        entryFileNames: 'assets/[name]-[hash].js',
        chunkFileNames: 'assets/[name]-[hash].js',
        assetFileNames: 'assets/[name]-[hash].[ext]'
      }
    }
  }
  }
})
