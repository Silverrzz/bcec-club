<script setup lang="ts">
withDefaults(defineProps<{ size?: number; label?: string }>(), {
  size: 18,
  label: "Loading",
});
</script>

<template>
  <span class="spinner" role="status" :aria-label="label" :style="{ width: `${size}px`, height: `${size}px` }" />
</template>

<style scoped>
.spinner {
  display: inline-block;
  flex: 0 0 auto;
  border: 2px solid color-mix(in srgb, currentColor 24%, transparent);
  border-top-color: currentColor;
  border-radius: 50%;
  animation: spin 700ms linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

@media (prefers-reduced-motion: reduce) {
  .spinner {
    animation-duration: 1400ms !important;
  }
}
</style>
