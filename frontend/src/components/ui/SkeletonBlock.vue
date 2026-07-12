<script setup lang="ts">
withDefaults(
  defineProps<{
    width?: string;
    height?: string;
    radius?: string;
  }>(),
  { width: "100%", height: "1rem", radius: "var(--radius-sm)" },
);
</script>

<template>
  <span class="skeleton-block" :style="{ width, height, borderRadius: radius }" aria-hidden="true" />
</template>

<style scoped>
.skeleton-block {
  display: block;
  max-width: 100%;
  background: linear-gradient(
    90deg,
    var(--color-surface-sunken) 0%,
    var(--color-surface-hover) 48%,
    var(--color-surface-sunken) 100%
  );
  background-size: 220% 100%;
  animation: shimmer 1.4s ease-in-out infinite;
}

@keyframes shimmer {
  to {
    background-position-x: -220%;
  }
}
</style>
