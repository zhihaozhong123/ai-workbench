import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import './assets/style.css'

// 桌面端（Tauri WebView）禁用默认右键菜单（避免出现 Back/Reload 等导航选项）
if (typeof window !== 'undefined' && (window.__TAURI_INTERNALS__ || window.__TAURI__)) {
  document.addEventListener('contextmenu', (e) => e.preventDefault())
}

createApp(App).use(createPinia()).use(router).mount('#app')
