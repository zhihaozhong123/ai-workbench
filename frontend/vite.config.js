import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

// 前端后端地址通过 src/config.js 读取 VITE_API_BASE（默认 http://127.0.0.1:8000），
// 因此这里不再需要 dev 代理（Tauri 窗口与独立 dev 都直连后端，地址可配置）。
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
  },
})
