<script setup lang="ts">
import { computed } from 'vue'

import { statusLabel } from './format'

const props = defineProps<{
  status?: string | null
}>()

const tone = computed(() => {
  const status = props.status?.toLowerCase() || ''
  if (['live', 'running', 'connected', 'ready', 'finished'].includes(status)) return 'positive'
  if (['scheduled', 'pending', 'assigned', 'minted'].includes(status)) return 'neutral'
  if (['paused', 'building', 'reconnecting'].includes(status)) return 'warning'
  if (['aborted', 'abandoned', 'failed', 'revoked', 'offline'].includes(status)) return 'negative'
  return 'neutral'
})
</script>

<template>
  <span class="status-pill" :class="`status-pill--${tone}`">
    <span class="status-pill__dot" aria-hidden="true"></span>
    {{ statusLabel(status) }}
  </span>
</template>

<style scoped>
.status-pill {
  --status-color: var(--color-text-muted, #607080);
  display: inline-flex;
  min-height: 1.65rem;
  align-items: center;
  gap: 0.38rem;
  padding-inline: 0.58rem;
  border: 1px solid color-mix(in srgb, var(--status-color) 28%, transparent);
  border-radius: 999px;
  background: color-mix(in srgb, var(--status-color) 9%, var(--color-surface, #fff));
  color: color-mix(in srgb, var(--status-color) 88%, var(--color-text, #17202a));
  font-size: 0.69rem;
  font-weight: 750;
  letter-spacing: 0.025em;
  line-height: 1;
  white-space: nowrap;
}

.status-pill--positive { --status-color: var(--color-success, #16794b); }
.status-pill--warning { --status-color: var(--color-warning, #9a6700); }
.status-pill--negative { --status-color: var(--color-danger, #b42318); }

.status-pill__dot {
  width: 0.42rem;
  height: 0.42rem;
  border-radius: 50%;
  background: currentColor;
}

@media (forced-colors: active) {
  .status-pill { border-color: currentColor; }
}
</style>

