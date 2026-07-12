<script setup lang="ts">
import BaseSpinner from "./BaseSpinner.vue";

withDefaults(
  defineProps<{
    label?: string;
    compact?: boolean;
  }>(),
  { label: "Loading" },
);
</script>

<template>
  <div class="loading-state" :class="{ 'loading-state--compact': compact }" role="status" aria-live="polite">
    <BaseSpinner :size="compact ? 18 : 26" :label="label" />
    <span>{{ label }}</span>
  </div>
</template>

<style scoped>
.loading-state {
  min-height: 12rem;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-3);
  color: var(--color-text-muted);
  font-size: 0.875rem;
}

.loading-state--compact {
  min-height: 4rem;
}
</style>
