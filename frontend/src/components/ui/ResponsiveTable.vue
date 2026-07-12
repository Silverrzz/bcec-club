<script setup lang="ts">
withDefaults(
  defineProps<{
    caption?: string;
    minWidth?: string;
    stickyHeader?: boolean;
    compact?: boolean;
  }>(),
  { minWidth: "42rem" },
);
</script>

<template>
  <div class="table-frame" :class="{ 'table-frame--sticky': stickyHeader, 'table-frame--compact': compact }">
    <table class="responsive-table" :style="{ minWidth }">
      <caption v-if="caption" class="sr-only">{{ caption }}</caption>
      <slot />
    </table>
  </div>
</template>

<style scoped>
.table-frame {
  width: 100%;
  overflow: auto;
  overscroll-behavior-inline: contain;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-surface);
  box-shadow: var(--shadow-xs);
  scrollbar-width: thin;
}

.responsive-table {
  width: 100%;
  color: var(--color-text-secondary);
  font-size: 0.875rem;
  text-align: left;
}

.responsive-table :deep(th),
.responsive-table :deep(td) {
  padding: 0.8rem var(--space-4);
  border-bottom: 1px solid var(--color-border);
  vertical-align: middle;
}

.responsive-table :deep(th) {
  background: var(--color-surface-sunken);
  color: var(--color-text-muted);
  font-size: 0.75rem;
  font-weight: 690;
  letter-spacing: 0.035em;
  text-transform: uppercase;
  white-space: nowrap;
}

.table-frame--sticky .responsive-table :deep(thead th) {
  position: sticky;
  z-index: 1;
  top: 0;
}

.responsive-table :deep(tbody tr:last-child td) {
  border-bottom: 0;
}

.responsive-table :deep(tbody tr) {
  transition: background-color var(--transition-fast);
}

.responsive-table :deep(tbody tr:hover) {
  background: var(--color-surface-hover);
}

.responsive-table :deep(a) {
  color: var(--color-link);
  font-weight: 600;
}

.responsive-table :deep(.cell-primary) {
  color: var(--color-text);
  font-weight: 610;
}

.responsive-table :deep(.cell-actions) {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
  white-space: nowrap;
}

.responsive-table :deep(.cell-number) {
  font-variant-numeric: tabular-nums;
  text-align: right;
}

.table-frame--compact .responsive-table :deep(th),
.table-frame--compact .responsive-table :deep(td) {
  padding: 0.6rem var(--space-3);
}

@media (max-width: 42rem) {
  .table-frame {
    border-radius: var(--radius-md);
  }
}
</style>
