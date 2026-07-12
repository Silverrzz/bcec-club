<script setup lang="ts">
defineProps<{
  title: string;
  description?: string;
  eyebrow?: string;
}>();
</script>

<template>
  <header class="page-header">
    <div class="page-header__copy">
      <p v-if="eyebrow" class="page-header__eyebrow">{{ eyebrow }}</p>
      <h1>{{ title }}</h1>
      <p v-if="description" class="page-header__description">{{ description }}</p>
      <slot name="meta" />
    </div>
    <div v-if="$slots.actions" class="page-header__actions">
      <slot name="actions" />
    </div>
  </header>
</template>

<style scoped>
.page-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--space-6);
}

.page-header__copy {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.page-header__eyebrow {
  color: var(--color-accent);
  font-size: 0.75rem;
  font-weight: 720;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.page-header__description {
  max-width: 46rem;
  color: var(--color-text-muted);
  font-size: 0.9375rem;
  text-wrap: pretty;
}

.page-header__actions {
  display: flex;
  flex: 0 0 auto;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: var(--space-3);
}

@media (max-width: 38rem) {
  .page-header {
    align-items: stretch;
    flex-direction: column;
    gap: var(--space-4);
  }

  .page-header__actions {
    justify-content: flex-start;
  }
}
</style>
