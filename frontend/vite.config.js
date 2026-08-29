import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8001', changeOrigin: true },
      '/health': { target: 'http://127.0.0.1:8001', changeOrigin: true },
    },
  },
  build: {
    // R-10：生产构建代码分割（按供应商拆分 chunk，消除超大主包）
    rollupOptions: {
      output: {
        manualChunks: {
          'vue-vendor': ['vue', 'vue-router', 'pinia', 'axios'],
          'element-plus': ['element-plus'],
          'echarts': ['echarts'],
        },
      },
    },
    chunkSizeWarningLimit: 1400,
  },
})