<template>
  <button
    type="button"
    class="task-card"
    :class="{ active, failed: skill.status === 'failed' }"
    :data-tooltip="skill.status === 'failed' ? skill.error || '安装失败，请重试' : `进入「${skill.name || skill.slug}」专属对话`"
    @click="$emit('open', skill)"
  >
    <span class="task-emoji">{{ skill.emoji || '🧩' }}</span>
    <span class="task-meta">
      <span class="task-name">{{ skill.name || skill.slug }}</span>
      <span class="task-slug">{{ skill.slug }}</span>
    </span>
    <span v-if="skill.status === 'failed'" class="task-badge fail">异常</span>
    <span class="task-go">›</span>
  </button>
</template>

<script setup>
defineProps({
  skill: { type: Object, required: true },
  active: { type: Boolean, default: false },
})
defineEmits(['open'])
</script>

<style scoped>
.task-card {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 8px 10px;
  border: 1px solid transparent;
  border-radius: 11px;
  background: transparent;
  text-align: left;
  transition: background 0.15s, border-color 0.15s, box-shadow 0.15s, transform 0.12s;
}
.task-card:hover {
  background: #f3f5f9;
  border-color: #e7eaf0;
}
.task-card.active {
  background: #eaf0fe;
  border-color: #d7e2ff;
}
.task-card.active:hover {
  background: #e3ebfd;
}
.task-emoji {
  width: 30px;
  height: 30px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 9px;
  background: linear-gradient(135deg, #f0f4ff, #eef7ff);
  font-size: 16px;
}
.task-card.active .task-emoji {
  background: linear-gradient(135deg, #2563eb, #7c5cff);
  box-shadow: 0 4px 10px rgba(37, 99, 235, 0.25);
}
.task-meta {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.task-name {
  font-size: 12.5px;
  font-weight: 600;
  color: #1f2937;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.task-card.active .task-name {
  color: #1d4ed8;
}
.task-slug {
  font-size: 10.5px;
  color: #9ca3af;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.task-badge.fail {
  font-size: 10px;
  color: #ef4444;
  background: #fef1f1;
  border-radius: 999px;
  padding: 1px 7px;
  flex-shrink: 0;
}
.task-go {
  color: #c3c9d3;
  font-size: 16px;
  flex-shrink: 0;
  transition: color 0.15s, transform 0.12s;
}
.task-card:hover .task-go {
  color: #2563eb;
  transform: translateX(2px);
}
</style>
