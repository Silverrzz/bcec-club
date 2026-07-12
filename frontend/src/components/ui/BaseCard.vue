<script setup lang="ts">
withDefaults(
  defineProps<{
    padding?: "none" | "small" | "medium" | "large";
    interactive?: boolean;
  }>(),
  { padding: "medium" },
);
</script>

<template>
  <section class="base-card" :class="[`base-card--${padding}`, { 'base-card--interactive': interactive }]">
    <slot />
  </section>
</template>

<style scoped>
.base-card {
  min-width: 0;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-surface);
  box-shadow: var(--shadow-xs);
}

.base-card--small {
  padding: var(--space-4);
}

.base-card--medium {
  padding: clamp(var(--space-4), 2vw, var(--space-6));
}

.base-card--large {
  padding: clamp(var(--space-5), 3vw, var(--space-8));
}

.base-card--interactive {
  transition:
    border-color var(--transition-fast),
    box-shadow var(--transition-fast),
    transform var(--transition-fast);
}

.base-card--interactive:hover {
  border-color: var(--color-border-strong);
  box-shadow: var(--shadow-sm);
  transform: translateY(-1px);
}
</style>
