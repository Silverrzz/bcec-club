<script setup lang="ts">
import { computed, useAttrs, useId } from "vue";

import AppIcon from "./AppIcon.vue";
import FormField from "./FormField.vue";
import type { SelectOption } from "@/types/ui";

defineOptions({ inheritAttrs: false });

const props = defineProps<{
  modelValue?: string | number | null;
  options: readonly SelectOption[];
  id?: string;
  label?: string;
  placeholder?: string;
  hint?: string;
  error?: string | readonly string[] | null;
  required?: boolean;
  optional?: boolean;
}>();

const emit = defineEmits<{
  "update:modelValue": [value: string | number | null];
}>();

const attrs = useAttrs();
const generatedId = useId();
const selectId = computed(() => props.id ?? `select-${generatedId}`);

interface FormFieldBindings {
  id: string;
  label?: string;
  hint?: string;
  error?: string | readonly string[] | null;
  required?: boolean;
  optional?: boolean;
}

const formFieldBindings = computed<FormFieldBindings>(() => {
  const bindings: FormFieldBindings = { id: selectId.value };
  if (props.label !== undefined) bindings.label = props.label;
  if (props.hint !== undefined) bindings.hint = props.hint;
  if (props.error !== undefined) bindings.error = props.error;
  if (props.required !== undefined) bindings.required = props.required;
  if (props.optional !== undefined) bindings.optional = props.optional;
  return bindings;
});

function update(event: Event): void {
  const value = (event.target as HTMLSelectElement).value;
  if (value === "") {
    emit("update:modelValue", null);
    return;
  }
  const option = props.options.find((item) => String(item.value) === value);
  emit("update:modelValue", option?.value ?? value);
}
</script>

<template>
  <FormField
    v-bind="formFieldBindings"
  >
    <template v-if="$slots.label" #label><slot name="label" /></template>
    <template #default="field">
      <div class="select-shell" :class="{ 'select-shell--error': field.invalid }">
        <select
          :id="selectId"
          class="base-select"
          :value="modelValue ?? ''"
          :required="required"
          :aria-invalid="field.invalid || undefined"
          :aria-describedby="field.describedBy"
          v-bind="attrs"
          @change="update"
        >
          <option v-if="placeholder" value="" :disabled="required">{{ placeholder }}</option>
          <option v-for="option in options" :key="option.value" :value="option.value" :disabled="option.disabled">
            {{ option.label }}
          </option>
        </select>
        <AppIcon class="select-shell__icon" name="chevron-down" :size="17" />
      </div>
    </template>
  </FormField>
</template>

<style scoped>
.select-shell {
  position: relative;
}

.base-select {
  width: 100%;
  min-width: 0;
  min-height: var(--control-height);
  appearance: none;
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-md);
  background: var(--color-surface-raised);
  padding: 0.6rem 2.5rem 0.6rem 0.75rem;
  color: var(--color-text);
  line-height: 1.35;
  transition:
    border-color var(--transition-fast),
    box-shadow var(--transition-fast);
}

.select-shell__icon {
  position: absolute;
  top: 50%;
  right: var(--space-3);
  color: var(--color-text-muted);
  pointer-events: none;
  transform: translateY(-50%);
}

.base-select:hover:not(:disabled) {
  border-color: color-mix(in srgb, var(--color-border-strong) 70%, var(--color-text));
}

.base-select:focus {
  border-color: var(--color-focus);
  outline: 0;
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--color-focus) 20%, transparent);
}

.base-select:disabled {
  cursor: not-allowed;
  opacity: 0.62;
  background: var(--color-surface-sunken);
}

.select-shell--error .base-select {
  border-color: var(--color-danger);
}
</style>
