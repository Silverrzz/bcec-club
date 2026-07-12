<script setup lang="ts">
import type { FeedbackTone } from "@/types/ui";

withDefaults(
  defineProps<{
    tone?: FeedbackTone;
    dot?: boolean;
    pulse?: boolean;
  }>(),
  { tone: "neutral" },
);
</script>

<template>
  <span class="status-badge" :class="[`status-badge--${tone}`]">
    <span v-if="dot" class="status-badge__dot" :class="{ 'status-badge__dot--pulse': pulse }" aria-hidden="true" />
    <slot />
  </span>
</template>

<style scoped>
.status-badge {
  width: fit-content;
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  border: 1px solid transparent;
  border-radius: var(--radius-round);
  padding: 0.22rem 0.55rem;
  font-size: 0.75rem;
  font-weight: 680;
  line-height: 1.25;
  white-space: nowrap;
}

.status-badge--neutral {
  border-color: var(--color-border);
  background: var(--color-surface-sunken);
  color: var(--color-text-secondary);
}

.status-badge--info {
  background: var(--color-info-soft);
  color: var(--color-info);
}

.status-badge--success {
  background: var(--color-success-soft);
  color: var(--color-success);
}

.status-badge--warning {
  background: var(--color-warning-soft);
  color: var(--color-warning);
}

.status-badge--danger {
  background: var(--color-danger-soft);
  color: var(--color-danger);
}

.status-badge__dot {
  width: 0.42rem;
  height: 0.42rem;
  border-radius: 50%;
  background: currentColor;
}

.status-badge__dot--pulse {
  animation: status-pulse 1.8s ease-out infinite;
}

@keyframes status-pulse {
  0%,
  100% {
    box-shadow: 0 0 0 0 color-mix(in srgb, currentColor 0%, transparent);
  }
  40% {
    box-shadow: 0 0 0 0.25rem color-mix(in srgb, currentColor 15%, transparent);
  }
}
</style>
