import { createRouter, createWebHistory } from 'vue-router'
import LoginView from '@/views/LoginView.vue'
import ChatView from '@/views/ChatView.vue'
import SkillMarketView from '@/views/SkillMarketView.vue'
import SettingsView from '@/views/SettingsView.vue'
import PlaceholderView from '@/views/PlaceholderView.vue'
import { useAuthStore } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/tasks' },
    { path: '/login', name: 'login', component: LoginView, meta: { public: true } },
    { path: '/tasks', name: 'tasks', component: ChatView },
    { path: '/market', name: 'market', component: SkillMarketView },
    { path: '/settings', name: 'settings', component: SettingsView },
    { path: '/placeholder/:key', name: 'placeholder', component: PlaceholderView },
    { path: '/:pathMatch(.*)*', redirect: '/tasks' },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (!auth.hydrated) {
    try {
      await auth.hydrate()
    } catch {
      /* hydrate 失败按未登录处理 */
    }
  }
  if (to.meta.public) {
    return auth.accessToken ? '/tasks' : true
  }
  if (!auth.accessToken) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  return true
})

export default router
