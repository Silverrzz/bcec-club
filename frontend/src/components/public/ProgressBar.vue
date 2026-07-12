<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  value?: number
  label?: string
  hideLabel?: boolean
}>(), {
  value: 0,
  label: 'Progress',
  hideLabel: false,
})

const percentage = computed(() => Math.max(0, Math.min(100, Math.round(Number(props.value) || 0))))
</script>

<template>
  <div class="progress-wrap">
    <div v-if="!hideLabel" class="progress-label">
      <span>{{ label }}</span>
      <span>{{ percentage }}%</span>
    </div>
    <div class="progress-track" role="progressbar" :aria-label="label" aria-valuemin="0" aria-valuemax="100" :aria-valuenow="percentage">
      <span :style="{ width: `${percentage}%` }"></span>
    </div>
  </div>
</template>

<style scoped>
.progress-label {
  display: flex;
  justify-content: space-between;
  gap: var(--space-sm, 0.5rem);
  margin-block-end: 0.35rem;
  color: var(--color-text-muted, #607080);
  font-size: 0.72rem;
}

.progress-track {
  height: 0.34rem;
  overflow: hidden;
  border-radius: 999px;
  background: color-mix(in srgb, var(--color-text, #17202a) 9%, transparent);
}

.progress-track span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--color-accent, #2f78c4);
  transition: width 180ms ease;
}

@media (prefers-reduced-motion: reduce) {
  .progress-track span { transition: none; }
}
</style>
