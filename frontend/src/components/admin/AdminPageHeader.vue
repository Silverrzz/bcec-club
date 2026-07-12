<script setup lang="ts">
defineProps<{
  title: string
  description?: string
}>()
</script>

<template>
  <header class="admin-page-header">
    <div class="admin-page-header__copy">
      <h1>{{ title }}</h1>
      <p v-if="description" class="admin-page-header__description">{{ description }}</p>
    </div>
    <div v-if="$slots.actions" class="admin-page-header__actions">
      <slot name="actions" />
    </div>
  </header>
</template>

<style scoped>
.admin-page-header {
  align-items: flex-start;
  display: flex;
  gap: var(--space-5, 1.25rem);
  justify-content: space-between;
  min-width: 0;
}

.admin-page-header__copy { min-width: 0; }
.admin-page-header h1 { margin: 0; text-wrap: balance; }

.admin-page-header__description {
  color: var(--color-text-muted, #64748b);
  margin: .45rem 0 0;
  max-width: 70ch;
}

.admin-page-header__actions {
  align-items: center;
  display: flex;
  flex: 0 0 auto;
  flex-wrap: wrap;
  gap: .65rem;
  justify-content: flex-end;
}

@media (max-width: 42rem) {
  .admin-page-header { align-items: stretch; flex-direction: column; }
  .admin-page-header__actions { justify-content: flex-start; }
}
</style>
