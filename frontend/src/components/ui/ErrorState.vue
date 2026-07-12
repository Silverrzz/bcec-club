<script setup lang="ts">
import { computed } from "vue";

import { ApiError } from "@/api/client";
import AppIcon from "./AppIcon.vue";
import BaseButton from "./BaseButton.vue";

const props = withDefaults(
  defineProps<{
    title?: string;
    message?: string;
    error?: unknown;
    retryLabel?: string;
    retry?: boolean;
    compact?: boolean;
  }>(),
  {
    title: "Unable to load this content",
    retryLabel: "Try again",
    retry: true,
  },
);

defineEmits<{ retry: [] }>();

const detail = computed(() => {
  if (props.message) return props.message;
  if (props.error instanceof ApiError || props.error instanceof Error) return props.error.message;
  if (typeof props.error === "string") return props.error;
  return "The request could not be completed. Please try again.";
});
</script>

<template>
  <div class="error-state" :class="{ 'error-state--compact': compact }" role="alert">
    <span class="error-state__icon"><AppIcon name="alert-circle" :size="compact ? 20 : 24" /></span>
    <div class="error-state__copy">
      <h2>{{ title }}</h2>
      <p>{{ detail }}</p>
    </div>
    <BaseButton v-if="retry" size="small" @click="$emit('retry')">
      <template #icon><AppIcon name="refresh" :size="16" /></template>
      {{ retryLabel }}
    </BaseButton>
  </div>
</template>

<style scoped>
.error-state {
  min-height: 12rem;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: var(--space-4);
  border: 1px solid color-mix(in srgb, var(--color-danger) 26%, var(--color-border));
  border-radius: var(--radius-lg);
  background: var(--color-danger-soft);
  padding: var(--space-8);
  text-align: center;
}

.error-state--compact {
  min-height: 0;
  align-items: flex-start;
  flex-direction: row;
  justify-content: flex-start;
  padding: var(--space-4);
  text-align: left;
}

.error-state__icon {
  color: var(--color-danger);
}

.error-state__copy {
  display: flex;
  flex: 0 1 auto;
  flex-direction: column;
  gap: var(--space-1);
}

.error-state__copy h2 {
  font-size: 1rem;
}

.error-state__copy p {
  max-width: 35rem;
  color: var(--color-text-secondary);
  font-size: 0.875rem;
}

.error-state--compact :deep(.base-button) {
  margin-left: auto;
}

@media (max-width: 32rem) {
  .error-state--compact {
    flex-wrap: wrap;
  }
}
</style>
