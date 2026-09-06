<template>
  <div class="ph-page">
    <div class="ph-card">
      <div class="ph-icon">{{ meta.emoji }}</div>
      <h2 class="ph-title">{{ meta.label }}</h2>
      <p class="ph-desc">{{ meta.desc }}</p>
      <div class="ph-soon">功能开发中，敬请期待</div>
      <button class="ph-back" @click="go('/tasks')">返回对话任务</button>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()

const MODULES = {
  data: { label: '数据管理', emoji: '🗂', desc: '统一管理工作台中的数据与文档资产。' },
  'task-center': { label: '任务中心', emoji: '📋', desc: '查看各 Agent 的运行任务与执行记录。' },
  schedule: { label: '定时任务', emoji: '⏰', desc: '创建定时触发的自动化任务与技能编排。' },
  models: { label: '模型管理', emoji: '🧠', desc: '配置模型接入（DeepSeek 等）与调用偏好。' },
  channels: { label: '频道管理', emoji: '📡', desc: '管理消息通知频道与推送渠道。' },
  plugins: { label: '插件管理', emoji: '🔌', desc: '管理平台插件与扩展能力。' },
  more: { label: '更多', emoji: '✨', desc: '更多扩展模块将在这里汇集。' },
}

const key = computed(() => String(route.params.key || 'more'))
const meta = computed(() => MODULES[key.value] || MODULES.more)

function go(path) {
  router.push(path)
}
</script>

<style scoped>
.ph-page {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f5f6f8;
  min-height: 0;
  overflow-y: auto;
  padding: 40px 20px;
}
.ph-card {
  text-align: center;
  background: #fff;
  border: 1px solid #e7eaf0;
  border-radius: 20px;
  padding: 52px 64px;
  box-shadow: 0 10px 32px rgba(30, 40, 80, 0.06);
  max-width: 440px;
}
.ph-icon {
  font-size: 52px;
}
.ph-title {
  margin: 14px 0 8px;
  font-size: 19px;
  color: #1f2937;
  font-weight: 600;
}
.ph-desc {
  margin: 0 0 18px;
  font-size: 13px;
  color: #6b7280;
}
.ph-soon {
  display: inline-block;
  font-size: 12px;
  color: #2563eb;
  background: #eaf0fe;
  padding: 5px 14px;
  border-radius: 999px;
  margin-bottom: 26px;
}
.ph-back {
  display: block;
  margin: 0 auto;
  padding: 9px 22px;
  border: none;
  border-radius: 9px;
  background: #2563eb;
  color: #fff;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.15s;
}
.ph-back:hover {
  background: #1d4ed8;
}
</style>
