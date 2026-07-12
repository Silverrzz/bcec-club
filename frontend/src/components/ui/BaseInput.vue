<script setup lang="ts">
import { computed, useAttrs, useId } from "vue";

import AppIcon from "./AppIcon.vue";
import FormField from "./FormField.vue";
import type { IconName } from "@/types/icons";

defineOptions({ inheritAttrs: false });

const props = withDefaults(
  defineProps<{
    modelValue?: string | number | null;
    id?: string;
    label?: string;
    type?: string;
    hint?: string;
    error?: string | readonly string[] | null;
    required?: boolean;
    optional?: boolean;
    icon?: IconName;
    suffix?: string;
  }>(),
  { type: "text" },
);

const emit = defineEmits<{
  "update:modelValue": [value: string | number | null];
}>();

const attrs = useAttrs();
const generatedId = useId();
const inputId = computed(() => props.id ?? `input-${generatedId}`);

interface FormFieldBindings {
  id: string;
  label?: string;
  hint?: string;
  error?: string | readonly string[] | null;
  required?: boolean;
  optional?: boolean;
}

const formFieldBindings = computed<FormFieldBindings>(() => {
  const bindings: FormFieldBindings = { id: inputId.value };
  if (props.label !== undefined) bindings.label = props.label;
  if (props.hint !== undefined) bindings.hint = props.hint;
  if (props.error !== undefined) bindings.error = props.error;
  if (props.required !== undefined) bindings.required = props.required;
  if (props.optional !== undefined) bindings.optional = props.optional;
  return bindings;
});

function update(event: Event): void {
  const input = event.target as HTMLInputElement;
  if (props.type === "number") emit("update:modelValue", input.value === "" ? null : input.valueAsNumber);
  else emit("update:modelValue", input.value);
}
</script>

<template>
  <FormField
    v-bind="formFieldBindings"
  >
    <template v-if="$slots.label" #label><slot name="label" /></template>
    <template #default="field">
      <div class="input-shell" :class="{ 'input-shell--error': field.invalid }">
        <AppIcon v-if="icon" class="input-shell__icon" :name="icon" :size="18" />
        <input
          :id="inputId"
          class="base-input"
          :class="{ 'base-input--icon': icon, 'base-input--suffix': suffix }"
          :type="type"
          :value="modelValue ?? ''"
          :required="required"
          :aria-invalid="field.invalid || undefined"
          :aria-describedby="field.describedBy"
          v-bind="attrs"
          @input="update"
        />
        <span v-if="suffix" class="input-shell__suffix">{{ suffix }}</span>
      </div>
    </template>
  </FormField>
</template>

<style scoped>
.input-shell {
  position: relative;
  display: flex;
  align-items: center;
}

.input-shell__icon {
  position: absolute;
  z-index: 1;
  left: var(--space-3);
  color: var(--color-text-muted);
  pointer-events: none;
}

.input-shell__suffix {
  position: absolute;
  right: var(--space-3);
  color: var(--color-text-muted);
  font-size: 0.875rem;
  pointer-events: none;
}

.base-input {
  width: 100%;
  min-width: 0;
  min-height: var(--control-height);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-md);
  background: var(--color-surface-raised);
  padding: 0.6rem 0.75rem;
  color: var(--color-text);
  line-height: 1.35;
  transition:
    border-color var(--transition-fast),
    box-shadow var(--transition-fast),
    background-color var(--transition-fast);
}

.base-input--icon {
  padding-left: 2.5rem;
}

.base-input--suffix {
  padding-right: 3rem;
}

.base-input:hover:not(:disabled) {
  border-color: color-mix(in srgb, var(--color-border-strong) 70%, var(--color-text));
}

.base-input:focus {
  border-color: var(--color-focus);
  outline: 0;
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--color-focus) 20%, transparent);
}

.base-input:disabled {
  cursor: not-allowed;
  opacity: 0.62;
  background: var(--color-surface-sunken);
}

.input-shell--error .base-input {
  border-color: var(--color-danger);
}
</style>
