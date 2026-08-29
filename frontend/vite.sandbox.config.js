import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 沙箱专用配置：禁用依赖预构建（esbuild 子进程被沙箱拦截），SFC 编译走纯 JS 的 @vue/compiler-sfc
export default defineConfig({
  plugins: [vue()],
  optimizeDeps: { disabled: true },
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8001', changeOrigin: true },
      '/health': { target: 'http://127.0.0.1:8001', changeOrigin: true },
    },
  },
})
