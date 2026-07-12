<script setup lang="ts">
import AppIcon from "@/components/ui/AppIcon.vue";
import BaseButton from "@/components/ui/BaseButton.vue";
</script>

<template>
  <div class="page-container not-found">
    <div class="not-found__mark" aria-hidden="true"><AppIcon name="search" :size="28" /></div>
    <p class="not-found__code">404</p>
    <h1>Page not found</h1>
    <BaseButton variant="primary" to="/">
      <template #icon><AppIcon name="home" :size="17" /></template>
      Go to the home page
    </BaseButton>
  </div>
</template>

<style scoped>
.not-found {
  min-height: min(30rem, 60vh);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: var(--space-3);
  text-align: center;
}

.not-found__mark {
  width: 3.5rem;
  height: 3.5rem;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: var(--color-accent-soft);
  color: var(--color-accent);
}

.not-found__code {
  color: var(--color-text-faint);
  font-size: 0.75rem;
  font-weight: 720;
  letter-spacing: 0.12em;
}

.not-found > p:not(.not-found__code) {
  max-width: 30rem;
  color: var(--color-text-muted);
}

.not-found :deep(.base-button) {
  margin-top: var(--space-3);
}
</style>
