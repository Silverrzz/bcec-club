<script setup lang="ts">
import { computed } from 'vue'
import { humanize } from './format'

const props = defineProps<{ status?: string | null; label?: string }>()

const tone = computed(() => {
  const status = props.status?.toLowerCase() ?? ''
  if (['ready', 'running', 'connected', 'applied', 'active', 'finished', 'complete'].includes(status)) return 'positive'
  if (['scheduled', 'building', 'busy', 'pending', 'minted', 'requested'].includes(status)) return 'info'
  if (['paused', 'idle', 'offline', 'draft', 'expired'].includes(status)) return 'neutral'
  if (['failed', 'aborted', 'revoked', 'error', 'disconnected'].includes(status)) return 'danger'
  return 'neutral'
})
</script>

<template>
  <span class="status-badge" :class="`status-badge--${tone}`">
    <span class="status-badge__dot" aria-hidden="true" />
    {{ label ?? humanize(status) }}
  </span>
</template>

<style scoped>
.status-badge {
  align-items: center;
  background: var(--badge-bg, color-mix(in srgb, currentColor 10%, transparent));
  border: 1px solid color-mix(in srgb, currentColor 25%, transparent);
  border-radius: 999px;
  color: var(--badge-color, var(--color-text-muted, #475569));
  display: inline-flex;
  font-size: .75rem;
  font-weight: 650;
  gap: .4rem;
  line-height: 1;
  padding: .35rem .55rem;
  white-space: nowrap;
}
.status-badge__dot { background: currentColor; border-radius: 50%; height: .42rem; width: .42rem; }
.status-badge--positive { --badge-color: var(--color-success, #15803d); }
.status-badge--info { --badge-color: var(--color-accent, #315fcc); }
.status-badge--danger { --badge-color: var(--color-danger, #b42318); }
.status-badge--neutral { --badge-color: var(--color-text-muted, #64748b); }
</style>
