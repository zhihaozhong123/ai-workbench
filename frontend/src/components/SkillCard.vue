<template>
  <div class="skill-card" :class="{ failed: skill.is_failed }">
    <div class="skill-card-head">
      <div class="skill-card-logo" :class="{ inst: skill.is_installed && !skill.is_failed }">
        {{ skill.emoji || '🧩' }}
      </div>
      <div class="skill-card-meta">
        <div class="skill-card-name">
          {{ skill.name || skill.slug }}
          <span v-if="skill.is_installed && !skill.is_failed" class="skill-installed-tag">已安装</span>
          <span v-else-if="skill.is_failed" class="skill-failed-tag">安装失败</span>
        </div>
        <div class="skill-card-slug">@{{ skill.slug }}</div>
      </div>
      <span class="skill-card-cat">{{ skill.category || '通用' }}</span>
    </div>

    <p class="skill-card-desc">{{ skill.description || '该技能暂无简介' }}</p>

    <div v-if="skill.is_failed && skill.failed_error" class="skill-failed-msg" :title="skill.failed_error">
      {{ skill.failed_error }}
    </div>

    <div class="skill-card-foot">
      <div class="skill-card-info">
        <span class="skill-card-ver">v{{ skill.version }}</span>
        <span class="skill-card-count">{{ skill.install_count || 0 }} 人安装</span>
      </div>

      <div class="skill-card-actions">
        <button
          v-if="busy"
          class="skill-btn loading"
          disabled
        >{{ busyText }}</button>

        <template v-else-if="skill.is_failed">
          <button class="skill-btn primary" @click="$emit('install', skill)">重试安装</button>
        </template>

        <template v-else-if="skill.is_installed && skill.upgradable">
          <button class="skill-btn ghost" @click="$emit('open', skill)">打开任务</button>
          <button class="skill-btn ghost danger" @click="$emit('uninstall', skill)">卸载</button>
          <button class="skill-btn primary" data-tooltip="有新版本可用" @click="$emit('install', skill)">升级</button>
        </template>

        <template v-else-if="skill.is_installed">
          <button class="skill-btn ghost" @click="$emit('uninstall', skill)">卸载</button>
          <button class="skill-btn primary" @click="$emit('open', skill)">打开任务</button>
        </template>

        <button v-else class="skill-btn primary" @click="$emit('install', skill)">安装</button>
      </div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  skill: { type: Object, required: true },
  busy: { type: Boolean, default: false },
  busyText: { type: String, default: '处理中…' },
})
defineEmits(['install', 'uninstall', 'open'])
</script>

<style scoped>
.skill-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  background: #fff;
  border: 1px solid #e7eaf0;
  border-radius: 14px;
  padding: 16px;
  transition: box-shadow 0.18s, transform 0.18s, border-color 0.18s;
}
.skill-card:hover {
  box-shadow: 0 10px 26px rgba(31, 45, 85, 0.09);
  transform: translateY(-2px);
  border-color: #d4dcff;
}
.skill-card.failed {
  border-color: #fecaca;
  background: #fffafa;
}
.skill-card-head {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}
.skill-card-logo {
  width: 46px;
  height: 46px;
  flex-shrink: 0;
  border-radius: 12px;
  background: linear-gradient(135deg, #eef2ff, #eef7ff);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 23px;
}
.skill-card-logo.inst {
  background: linear-gradient(135deg, #2563eb, #7c5cff);
  box-shadow: 0 6px 14px rgba(37, 99, 235, 0.25);
}
.skill-card-meta {
  flex: 1;
  min-width: 0;
}
.skill-card-name {
  font-size: 14.5px;
  font-weight: 600;
  color: #1f2937;
  display: flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
  overflow: hidden;
}
.skill-installed-tag {
  font-size: 10px;
  font-weight: 500;
  color: #fff;
  background: #10b981;
  border-radius: 999px;
  padding: 1px 8px;
  flex-shrink: 0;
}
.skill-failed-tag {
  font-size: 10px;
  font-weight: 500;
  color: #fff;
  background: #ef4444;
  border-radius: 999px;
  padding: 1px 8px;
  flex-shrink: 0;
}
.skill-card-slug {
  font-size: 11.5px;
  color: #9ca3af;
  margin-top: 2px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
.skill-card-cat {
  flex-shrink: 0;
  font-size: 11px;
  color: #2563eb;
  background: #eef3ff;
  padding: 2px 9px;
  border-radius: 999px;
}
.skill-card-desc {
  margin: 0;
  font-size: 12.5px;
  color: #6b7280;
  line-height: 1.6;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  min-height: 40px;
}
.skill-failed-msg {
  font-size: 11px;
  color: #dc2626;
  background: #fef2f2;
  border: 1px solid #fde2e2;
  border-radius: 8px;
  padding: 5px 9px;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.skill-card-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.skill-card-info {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11.5px;
  color: #9ca3af;
}
.skill-card-ver {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  background: #f1f3f8;
  color: #4b5563;
  padding: 1px 7px;
  border-radius: 6px;
}
.skill-card-actions {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  justify-content: flex-end;
}
.skill-btn {
  border: none;
  border-radius: 8px;
  font-size: 12.5px;
  padding: 6px 13px;
  cursor: pointer;
  transition: background 0.15s, opacity 0.15s;
}
.skill-btn.primary {
  background: #2563eb;
  color: #fff;
  font-weight: 600;
}
.skill-btn.primary:hover {
  background: #1d4ed8;
}
.skill-btn.loading {
  background: #eaf0fe;
  color: #2563eb;
  cursor: default;
}
.skill-btn.ghost {
  background: #f1f3f8;
  color: #4b5563;
}
.skill-btn.ghost:hover {
  background: #e5e9f2;
}
.skill-btn.ghost.danger {
  color: #ef4444;
  background: #fef1f1;
}
.skill-btn.ghost.danger:hover {
  background: #fde2e2;
}
</style>
