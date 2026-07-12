<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  state: 'connecting' | 'live' | 'reconnecting' | 'closed'
}>()

const label = computed(() => ({
  connecting: 'Connecting',
  live: 'Synced',
  reconnecting: 'Reconnecting',
  closed: 'Offline',
})[props.state])
</script>

<template>
  <span class="stream-indicator" :class="`stream-indicator--${state}`" role="status" aria-live="polite">
    <span aria-hidden="true"></span>{{ label }}
  </span>
</template>

<style scoped>
.stream-indicator {
  --stream-color: var(--color-text-muted, #607080);
  display: inline-flex;
  align-items: center;
  gap: 0.42rem;
  color: var(--stream-color);
  font-size: 0.72rem;
  font-weight: 700;
  white-space: nowrap;
}

.stream-indicator > span {
  width: 0.5rem;
  height: 0.5rem;
  border-radius: 50%;
  background: currentColor;
}

.stream-indicator--live { --stream-color: var(--color-success, #16794b); }
.stream-indicator--connecting,
.stream-indicator--reconnecting { --stream-color: var(--color-warning, #9a6700); }
</style>
