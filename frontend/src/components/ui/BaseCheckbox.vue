<script setup lang="ts">
import { computed, useId } from "vue";

const props = defineProps<{
  modelValue: boolean;
  id?: string;
  label: string;
  description?: string;
  disabled?: boolean;
}>();

const emit = defineEmits<{
  "update:modelValue": [value: boolean];
}>();

const generatedId = useId();
const checkboxId = computed(() => props.id ?? `checkbox-${generatedId}`);
</script>

<template>
  <label class="checkbox" :class="{ 'checkbox--disabled': disabled }" :for="checkboxId">
    <input
      :id="checkboxId"
      class="checkbox__input"
      type="checkbox"
      :checked="modelValue"
      :disabled="disabled"
      :aria-describedby="description ? `${checkboxId}-description` : undefined"
      @change="emit('update:modelValue', ($event.target as HTMLInputElement).checked)"
    />
    <span class="checkbox__box" aria-hidden="true">
      <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
        <path d="m3 8 3 3 7-7" />
      </svg>
    </span>
    <span class="checkbox__copy">
      <span class="checkbox__label">{{ label }}</span>
      <span v-if="description" :id="`${checkboxId}-description`" class="checkbox__description">{{ description }}</span>
    </span>
  </label>
</template>

<style scoped>
.checkbox {
  display: inline-flex;
  align-items: flex-start;
  gap: var(--space-3);
  cursor: pointer;
}

.checkbox__input {
  position: absolute;
  width: 1px;
  height: 1px;
  opacity: 0;
}

.checkbox__box {
  width: 1.125rem;
  height: 1.125rem;
  display: grid;
  flex: 0 0 auto;
  place-items: center;
  margin-top: 0.12rem;
  border: 1px solid var(--color-border-strong);
  border-radius: 0.3rem;
  background: var(--color-surface-raised);
  color: transparent;
  transition:
    background-color var(--transition-fast),
    border-color var(--transition-fast),
    box-shadow var(--transition-fast);
}

.checkbox__box svg {
  width: 0.8rem;
  height: 0.8rem;
}

.checkbox__input:checked + .checkbox__box {
  border-color: var(--color-accent);
  background: var(--color-accent);
  color: var(--color-on-accent);
}

.checkbox__input:focus-visible + .checkbox__box {
  outline: 3px solid color-mix(in srgb, var(--color-focus) 78%, transparent);
  outline-offset: 2px;
}

.checkbox__copy {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.checkbox__label {
  color: var(--color-text);
  font-size: 0.875rem;
  font-weight: 600;
}

.checkbox__description {
  color: var(--color-text-muted);
  font-size: 0.8125rem;
  line-height: 1.4;
}

.checkbox--disabled {
  cursor: not-allowed;
  opacity: 0.58;
}
</style>
