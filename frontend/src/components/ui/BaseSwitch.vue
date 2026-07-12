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
const switchId = computed(() => props.id ?? `switch-${generatedId}`);
</script>

<template>
  <label class="switch-row" :class="{ 'switch-row--disabled': disabled }" :for="switchId">
    <span class="switch-row__copy">
      <span class="switch-row__label">{{ label }}</span>
      <span v-if="description" :id="`${switchId}-description`" class="switch-row__description">{{ description }}</span>
    </span>
    <input
      :id="switchId"
      class="switch-row__input"
      type="checkbox"
      role="switch"
      :checked="modelValue"
      :disabled="disabled"
      :aria-describedby="description ? `${switchId}-description` : undefined"
      @change="emit('update:modelValue', ($event.target as HTMLInputElement).checked)"
    />
    <span class="switch-row__track" aria-hidden="true"><span class="switch-row__thumb" /></span>
  </label>
</template>

<style scoped>
.switch-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-5);
  cursor: pointer;
}

.switch-row__copy {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.switch-row__label {
  color: var(--color-text);
  font-size: 0.875rem;
  font-weight: 600;
}

.switch-row__description {
  color: var(--color-text-muted);
  font-size: 0.8125rem;
  line-height: 1.4;
}

.switch-row__input {
  position: absolute;
  width: 1px;
  height: 1px;
  opacity: 0;
}

.switch-row__track {
  width: 2.5rem;
  height: 1.5rem;
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-round);
  background: var(--color-surface-sunken);
  padding: 0.15rem;
  transition:
    background-color var(--transition-fast),
    border-color var(--transition-fast),
    box-shadow var(--transition-fast);
}

.switch-row__thumb {
  width: 1.05rem;
  height: 1.05rem;
  border-radius: 50%;
  background: var(--color-text-muted);
  box-shadow: var(--shadow-xs);
  transition:
    transform var(--transition-base),
    background-color var(--transition-fast);
}

.switch-row__input:checked + .switch-row__track {
  border-color: var(--color-accent);
  background: var(--color-accent);
}

.switch-row__input:checked + .switch-row__track .switch-row__thumb {
  background: var(--color-on-accent);
  transform: translateX(1rem);
}

.switch-row__input:focus-visible + .switch-row__track {
  outline: 3px solid color-mix(in srgb, var(--color-focus) 78%, transparent);
  outline-offset: 2px;
}

.switch-row--disabled {
  cursor: not-allowed;
  opacity: 0.58;
}
</style>
