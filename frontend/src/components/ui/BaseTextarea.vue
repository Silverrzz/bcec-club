<script setup lang="ts">
import { computed, useAttrs, useId } from "vue";

import FormField from "./FormField.vue";

defineOptions({ inheritAttrs: false });

const props = withDefaults(
  defineProps<{
    modelValue?: string | null;
    id?: string;
    label?: string;
    hint?: string;
    error?: string | readonly string[] | null;
    required?: boolean;
    optional?: boolean;
    rows?: number;
  }>(),
  { rows: 4 },
);

const emit = defineEmits<{
  "update:modelValue": [value: string];
}>();

const attrs = useAttrs();
const generatedId = useId();
const textareaId = computed(() => props.id ?? `textarea-${generatedId}`);

interface FormFieldBindings {
  id: string;
  label?: string;
  hint?: string;
  error?: string | readonly string[] | null;
  required?: boolean;
  optional?: boolean;
}

const formFieldBindings = computed<FormFieldBindings>(() => {
  const bindings: FormFieldBindings = { id: textareaId.value };
  if (props.label !== undefined) bindings.label = props.label;
  if (props.hint !== undefined) bindings.hint = props.hint;
  if (props.error !== undefined) bindings.error = props.error;
  if (props.required !== undefined) bindings.required = props.required;
  if (props.optional !== undefined) bindings.optional = props.optional;
  return bindings;
});
</script>

<template>
  <FormField
    v-bind="formFieldBindings"
  >
    <template v-if="$slots.label" #label><slot name="label" /></template>
    <template #default="field">
      <textarea
        :id="textareaId"
        class="base-textarea"
        :class="{ 'base-textarea--error': field.invalid }"
        :value="modelValue ?? ''"
        :rows="rows"
        :required="required"
        :aria-invalid="field.invalid || undefined"
        :aria-describedby="field.describedBy"
        v-bind="attrs"
        @input="emit('update:modelValue', ($event.target as HTMLTextAreaElement).value)"
      />
    </template>
  </FormField>
</template>

<style scoped>
.base-textarea {
  width: 100%;
  min-width: 0;
  resize: vertical;
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-md);
  background: var(--color-surface-raised);
  padding: 0.7rem 0.75rem;
  color: var(--color-text);
  line-height: 1.5;
  transition:
    border-color var(--transition-fast),
    box-shadow var(--transition-fast);
}

.base-textarea:hover:not(:disabled) {
  border-color: color-mix(in srgb, var(--color-border-strong) 70%, var(--color-text));
}

.base-textarea:focus {
  border-color: var(--color-focus);
  outline: 0;
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--color-focus) 20%, transparent);
}

.base-textarea--error {
  border-color: var(--color-danger);
}

.base-textarea:disabled {
  cursor: not-allowed;
  opacity: 0.62;
  background: var(--color-surface-sunken);
}
</style>
