<script setup lang="ts">
import { computed } from "vue";

import AppIcon from "./AppIcon.vue";
import type { FeedbackTone } from "@/types/ui";
import type { IconName } from "@/types/icons";

const props = withDefaults(
  defineProps<{
    tone?: Exclude<FeedbackTone, "neutral">;
    title?: string;
  }>(),
  { tone: "info" },
);

const icon = computed<IconName>(() => {
  if (props.tone === "success") return "check-circle";
  if (props.tone === "danger") return "alert-circle";
  if (props.tone === "warning") return "alert-circle";
  return "info";
});
</script>

<template>
  <div class="base-alert" :class="`base-alert--${tone}`" :role="tone === 'danger' ? 'alert' : 'status'">
    <AppIcon class="base-alert__icon" :name="icon" :size="19" />
    <div class="base-alert__copy">
      <strong v-if="title">{{ title }}</strong>
      <div class="base-alert__body"><slot /></div>
    </div>
  </div>
</template>

<style scoped>
.base-alert {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  border: 1px solid transparent;
  border-radius: var(--radius-md);
  padding: var(--space-4);
  font-size: 0.875rem;
}

.base-alert--info {
  border-color: color-mix(in srgb, var(--color-info) 25%, transparent);
  background: var(--color-info-soft);
  color: var(--color-info);
}

.base-alert--success {
  border-color: color-mix(in srgb, var(--color-success) 25%, transparent);
  background: var(--color-success-soft);
  color: var(--color-success);
}

.base-alert--warning {
  border-color: color-mix(in srgb, var(--color-warning) 25%, transparent);
  background: var(--color-warning-soft);
  color: var(--color-warning);
}

.base-alert--danger {
  border-color: color-mix(in srgb, var(--color-danger) 25%, transparent);
  background: var(--color-danger-soft);
  color: var(--color-danger);
}

.base-alert__icon {
  flex: 0 0 auto;
  margin-top: 0.08rem;
}

.base-alert__copy {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.base-alert__body {
  color: var(--color-text-secondary);
}
</style>
