import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: { host: '127.0.0.1', proxy: { '/api/v1': { target: 'http://127.0.0.1:18729', changeOrigin: false } } },
  build: { target: 'es2022', sourcemap: false, rollupOptions: { output: { manualChunks: { charts: ['echarts/core', 'echarts/charts', 'echarts/components', 'echarts/renderers'] } } } },
})
