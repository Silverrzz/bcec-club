<script setup lang="ts">
import { computed } from "vue";

import AppIcon from "./AppIcon.vue";
import BaseButton from "./BaseButton.vue";

const props = defineProps<{
  page: number;
  pageSize: number;
  total: number;
  label?: string;
}>();

const emit = defineEmits<{
  "update:page": [page: number];
}>();

const pageCount = computed(() => Math.max(1, Math.ceil(props.total / props.pageSize)));
const start = computed(() => (props.total ? (props.page - 1) * props.pageSize + 1 : 0));
const end = computed(() => Math.min(props.total, props.page * props.pageSize));
</script>

<template>
  <nav class="pagination" :aria-label="label ?? 'Pagination'">
    <p class="pagination__summary">{{ start }} to {{ end }} of {{ total }}</p>
    <div class="pagination__actions">
      <BaseButton size="small" icon-only :disabled="page <= 1" aria-label="Previous page" @click="emit('update:page', page - 1)">
        <template #icon><AppIcon name="chevron-left" :size="16" /></template>
        Previous page
      </BaseButton>
      <span class="pagination__page">Page {{ page }} of {{ pageCount }}</span>
      <BaseButton size="small" icon-only :disabled="page >= pageCount" aria-label="Next page" @click="emit('update:page', page + 1)">
        <template #icon><AppIcon name="chevron-right" :size="16" /></template>
        Next page
      </BaseButton>
    </div>
  </nav>
</template>

<style scoped>
.pagination {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  color: var(--color-text-muted);
  font-size: 0.8125rem;
}

.pagination__actions {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.pagination__page {
  min-width: 6rem;
  text-align: center;
}

@media (max-width: 32rem) {
  .pagination {
    align-items: stretch;
    flex-direction: column;
  }

  .pagination__actions {
    justify-content: space-between;
  }
}
</style>
