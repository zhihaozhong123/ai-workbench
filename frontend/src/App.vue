<template>
  <!-- 未登录：整页渲染（登录/注册）；已登录：主工作台壳（一级侧栏 + 内容区） -->
  <div v-if="authed" class="wb-shell">
    <AppSidebar />
    <main class="wb-main">
      <router-view v-slot="{ Component }">
        <transition name="wb-fade" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>
    </main>
  </div>
  <router-view v-else />

  <!-- 启动检查：发现新版本横幅浮层（顶部居中、不遮罩；自动检查开关见系统设置-更新） -->
  <transition name="upd-slide">
    <div v-if="authed && updateInfo" class="upd-banner" role="status" aria-live="polite">
      <div class="upd-banner-inner">
        <span class="upd-banner-icon" aria-hidden="true">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="10" />
            <line x1="12" y1="8" x2="12" y2="12" />
            <line x1="12" y1="16" x2="12.01" y2="16" />
          </svg>
        </span>
        <span class="upd-banner-text">
          发现新版本 <strong>v{{ updateInfo.latest_version }}</strong>
        </span>
        <button v-if="updateInfo.download_url" class="upd-banner-cta" @click="goDownload">去更新</button>
        <button v-else class="upd-banner-cta" @click="dismissUpdate">知道了</button>
        <button class="upd-banner-close" title="关闭" aria-label="关闭" @click="dismissUpdate">×</button>
      </div>
    </div>
  </transition>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import AppSidebar from '@/components/AppSidebar.vue'
import { checkUpdate } from '@/api/update'
import { openExternal } from '@/utils/external'

const auth = useAuthStore()
onMounted(() => auth.hydrate())
const authed = computed(() => !!auth.accessToken)

// ---- 启动自动检查更新（仅当设置里开启「自动检查更新」）----
const updateInfo = ref(null)
let checkedThisSession = false

function goDownload() {
  if (!updateInfo.value?.download_url) return
  openExternal(updateInfo.value.download_url)
}

function dismissUpdate() {
  if (updateInfo.value) {
    localStorage.setItem('wb.updateDismissedV', updateInfo.value.latest_version)
  }
  updateInfo.value = null
}

async function autoCheckOnStart() {
  if (checkedThisSession) return
  checkedThisSession = true
  if (localStorage.getItem('wb.autoCheck') !== '1') return
  try {
    const { data } = await checkUpdate()
    if (!data || !data.has_update) return
    const latest = data.latest_version || ''
    if (latest && localStorage.getItem('wb.updateDismissedV') === latest) return
    updateInfo.value = {
      current_version: data.current_version || '',
      latest_version: latest,
      notes: data.notes || '',
      download_url: data.download_url || '',
    }
  } catch (e) {
    // 更新服务未接入 / 网络异常：静默，不打断使用
    console.warn('启动自动检查更新失败', e?.response?.status || e?.message)
  }
}

watch(
  authed,
  (v) => {
    if (v) setTimeout(autoCheckOnStart, 900)
  },
  { immediate: true },
)
</script>

<style>
/* ============ 智作台 · 全局工作台壳 ============ */
.wb-shell {
  display: flex;
  height: 100%;
  width: 100%;
  overflow: hidden;
}
.wb-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  background: #f5f6f8;
  overflow: hidden;
}
.wb-fade-enter-active,
.wb-fade-leave-active {
  transition: opacity 0.16s ease, transform 0.16s ease;
}
.wb-fade-enter-from {
  opacity: 0;
  transform: translateY(4px);
}
.wb-fade-leave-to {
  opacity: 0;
}

/* ============ 启动「发现新版本」横幅浮层（顶部居中、不遮罩）============ */
.upd-banner {
  position: fixed;
  top: 18px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 500;
  pointer-events: none;
}
.upd-banner-inner {
  pointer-events: auto;
  display: flex;
  align-items: center;
  gap: 10px;
  background: #fff;
  border: 1px solid #e7eaf0;
  border-radius: 999px;
  padding: 6px 8px 6px 14px;
  box-shadow: 0 12px 36px rgba(17, 24, 39, 0.16);
}
.upd-banner-icon {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: #2563eb;
  color: #fff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.upd-banner-text {
  font-size: 13.5px;
  color: #1f2937;
  white-space: nowrap;
}
.upd-banner-text strong {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  color: #2563eb;
  font-weight: 600;
  margin-left: 2px;
}
.upd-banner-cta {
  background: #2563eb;
  color: #fff;
  border: none;
  border-radius: 999px;
  padding: 6px 16px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s;
  flex-shrink: 0;
}
.upd-banner-cta:hover {
  background: #1d4ed8;
}
.upd-banner-close {
  background: transparent;
  border: none;
  color: #9ca3af;
  font-size: 18px;
  cursor: pointer;
  padding: 0 8px;
  line-height: 1;
  border-radius: 6px;
  height: 28px;
  flex-shrink: 0;
}
.upd-banner-close:hover {
  color: #4b5563;
  background: #f1f3f8;
}
.upd-slide-enter-active,
.upd-slide-leave-active {
  transition: opacity 0.22s ease, transform 0.22s ease;
}
.upd-slide-enter-from,
.upd-slide-leave-to {
  opacity: 0;
  transform: translate(-50%, -10px);
}
</style>
