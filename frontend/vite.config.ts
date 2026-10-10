import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig(({ mode }) => ({
  plugins: [vue()],
  server: {
    host: '127.0.0.1', port: 5173, strictPort: true,
    proxy: { '/api/v1': { target: loadEnv(mode, '.', 'GRADHEAT_').GRADHEAT_DEV_API_URL || 'http://127.0.0.1:18731', changeOrigin: false } },
  },
  build: { target: 'es2022', sourcemap: false, rollupOptions: { output: { manualChunks: { charts: ['echarts/core', 'echarts/charts', 'echarts/components', 'echarts/renderers'] } } } },
}))
