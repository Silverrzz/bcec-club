<script setup lang="ts">
import type { IconName } from "@/types/icons";
import AppIcon from "./AppIcon.vue";

withDefaults(
  defineProps<{
    title: string;
    message?: string;
    icon?: IconName;
    compact?: boolean;
  }>(),
  { icon: "archive" },
);
</script>

<template>
  <div class="empty-state" :class="{ 'empty-state--compact': compact }">
    <span class="empty-state__icon" aria-hidden="true"><AppIcon :name="icon" :size="compact ? 20 : 26" /></span>
    <div class="empty-state__copy">
      <h2>{{ title }}</h2>
      <p v-if="message">{{ message }}</p>
    </div>
    <div v-if="$slots.actions" class="empty-state__actions"><slot name="actions" /></div>
  </div>
</template>

<style scoped>
.empty-state {
  min-height: 12rem;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: var(--space-4);
  border: 1px dashed var(--color-border-strong);
  border-radius: var(--radius-lg);
  background: color-mix(in srgb, var(--color-surface) 65%, transparent);
  padding: var(--space-8);
  text-align: center;
}

.empty-state--compact {
  min-height: 0;
  padding: var(--space-5);
}

.empty-state__icon {
  width: 3rem;
  height: 3rem;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: var(--color-surface-sunken);
  color: var(--color-text-muted);
}

.empty-state--compact .empty-state__icon {
  width: 2.5rem;
  height: 2.5rem;
}

.empty-state__copy {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.empty-state__copy h2 {
  font-size: 1rem;
}

.empty-state__copy p {
  max-width: 32rem;
  color: var(--color-text-muted);
  font-size: 0.875rem;
}

.empty-state__actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: var(--space-3);
}
</style>
