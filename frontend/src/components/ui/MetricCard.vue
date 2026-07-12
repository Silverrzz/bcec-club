<script setup lang="ts">
import type { IconName } from "@/types/icons";
import AppIcon from "./AppIcon.vue";

defineProps<{
  label: string;
  value: string | number;
  icon?: IconName;
  detail?: string;
}>();
</script>

<template>
  <div class="metric-card">
    <span v-if="icon" class="metric-card__icon"><AppIcon :name="icon" :size="20" /></span>
    <div class="metric-card__copy">
      <span class="metric-card__label">{{ label }}</span>
      <strong class="metric-card__value">{{ value }}</strong>
      <span v-if="detail" class="metric-card__detail">{{ detail }}</span>
    </div>
  </div>
</template>

<style scoped>
.metric-card {
  min-width: 0;
  display: flex;
  align-items: flex-start;
  gap: var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-surface);
  box-shadow: var(--shadow-xs);
  padding: var(--space-5);
}

.metric-card__icon {
  width: 2.5rem;
  height: 2.5rem;
  display: grid;
  flex: 0 0 auto;
  place-items: center;
  border-radius: var(--radius-md);
  background: var(--color-accent-soft);
  color: var(--color-accent);
}

.metric-card__copy {
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.metric-card__label,
.metric-card__detail {
  color: var(--color-text-muted);
  font-size: 0.8125rem;
}

.metric-card__value {
  overflow: hidden;
  color: var(--color-text);
  font-size: 1.5rem;
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.025em;
  line-height: 1.3;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
