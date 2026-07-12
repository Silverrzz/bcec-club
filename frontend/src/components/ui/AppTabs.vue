<script setup lang="ts">
import { nextTick } from "vue";
import type { TabItem } from "@/types/ui";

const props = defineProps<{
  modelValue: string;
  tabs: readonly TabItem[];
  label: string;
}>();

const emit = defineEmits<{
  "update:modelValue": [value: string];
}>();

function select(value: string): void {
  const tab = props.tabs.find((item) => item.value === value);
  if (!tab?.disabled) emit("update:modelValue", value);
}

async function move(event: KeyboardEvent, index: number): Promise<void> {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
  event.preventDefault();
  const enabled = props.tabs.filter((item) => !item.disabled);
  const current = enabled.findIndex((item) => item.value === props.tabs[index]?.value);
  let next = current;
  if (event.key === "Home") next = 0;
  else if (event.key === "End") next = enabled.length - 1;
  else if (event.key === "ArrowLeft") next = (current - 1 + enabled.length) % enabled.length;
  else next = (current + 1) % enabled.length;
  const tab = enabled[next];
  if (!tab) return;
  select(tab.value);
  await nextTick();
  document.getElementById(`tab-${tab.value}`)?.focus();
}
</script>

<template>
  <div class="app-tabs" role="tablist" :aria-label="label">
    <button
      v-for="(tab, index) in tabs"
      :id="`tab-${tab.value}`"
      :key="tab.value"
      class="app-tabs__tab"
      :class="{ 'app-tabs__tab--active': modelValue === tab.value }"
      type="button"
      role="tab"
      :aria-selected="modelValue === tab.value"
      :aria-controls="`panel-${tab.value}`"
      :tabindex="modelValue === tab.value ? 0 : -1"
      :disabled="tab.disabled"
      @click="select(tab.value)"
      @keydown="move($event, index)"
    >
      <span>{{ tab.label }}</span>
      <span v-if="tab.count !== undefined" class="app-tabs__count">{{ tab.count }}</span>
    </button>
  </div>
</template>

<style scoped>
.app-tabs {
  display: flex;
  gap: var(--space-1);
  overflow-x: auto;
  border-bottom: 1px solid var(--color-border);
  scrollbar-width: none;
}

.app-tabs::-webkit-scrollbar {
  display: none;
}

.app-tabs__tab {
  position: relative;
  min-height: 2.75rem;
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  gap: var(--space-2);
  border-radius: var(--radius-sm) var(--radius-sm) 0 0;
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
  padding: 0.65rem var(--space-3);
  font-size: 0.875rem;
  font-weight: 620;
}

.app-tabs__tab::after {
  content: "";
  position: absolute;
  right: var(--space-2);
  bottom: -1px;
  left: var(--space-2);
  height: 2px;
  border-radius: 2px 2px 0 0;
  background: transparent;
}

.app-tabs__tab:hover:not(:disabled) {
  background: var(--color-surface-hover);
  color: var(--color-text);
}

.app-tabs__tab--active {
  color: var(--color-accent);
}

.app-tabs__tab--active::after {
  background: var(--color-accent);
}

.app-tabs__tab:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.app-tabs__count {
  min-width: 1.25rem;
  border-radius: var(--radius-round);
  background: var(--color-surface-sunken);
  padding: 0.08rem 0.38rem;
  color: var(--color-text-muted);
  font-size: 0.6875rem;
  text-align: center;
}
</style>
