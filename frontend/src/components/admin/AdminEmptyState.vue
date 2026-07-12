<script setup lang="ts">
defineProps<{ title: string; description?: string }>()
</script>

<template>
  <div class="empty-state">
    <span class="empty-state__icon" aria-hidden="true">
      <svg viewBox="0 0 24 24"><path d="M4 7.5h16v11H4zM8 7.5V5.8A1.8 1.8 0 0 1 9.8 4h4.4A1.8 1.8 0 0 1 16 5.8v1.7M4 12h5l1.2 2h3.6l1.2-2h5" /></svg>
    </span>
    <strong>{{ title }}</strong>
    <p v-if="description">{{ description }}</p>
    <div v-if="$slots.default" class="empty-state__actions"><slot /></div>
  </div>
</template>

<style scoped>
.empty-state { align-items: center; color: var(--color-text-muted, #64748b); display: flex; flex-direction: column; justify-content: center; min-height: 13rem; padding: 2rem; text-align: center; }
.empty-state strong { color: var(--color-text, #172033); font-size: 1rem; }
.empty-state p { margin: .45rem 0 0; max-width: 48ch; }
.empty-state__icon { align-items: center; background: var(--color-surface-subtle, #f1f5f9); border-radius: 50%; display: flex; height: 2.8rem; justify-content: center; margin-bottom: .8rem; width: 2.8rem; }
.empty-state__icon svg { fill: none; height: 1.45rem; stroke: currentColor; stroke-linecap: round; stroke-linejoin: round; stroke-width: 1.6; width: 1.45rem; }
.empty-state__actions { margin-top: 1rem; }
</style>
