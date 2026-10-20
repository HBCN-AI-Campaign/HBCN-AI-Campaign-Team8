import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const apiTarget = process.env.HBCN_API_TARGET || 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      // 前端 /api 代理到 FastAPI，避免跨域
      '/api': {
        target: apiTarget,
        changeOrigin: true,
      },
      // 样本 PDF 原件（供「定位原文」预览）
      '/pdf': {
        target: apiTarget,
        changeOrigin: true,
      },
      // 经办人上传的真实 PDF（落盘后按批次目录预览）
      '/uploads': {
        target: apiTarget,
        changeOrigin: true,
      },
    },
  },
})
