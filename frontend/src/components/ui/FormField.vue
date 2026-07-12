<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{
  id: string;
  label?: string;
  hint?: string;
  error?: string | readonly string[] | null;
  required?: boolean;
  optional?: boolean;
}>();

const message = computed(() => (Array.isArray(props.error) ? props.error.join(" ") : props.error));
</script>

<template>
  <div class="form-field" :class="{ 'form-field--error': message }">
    <div v-if="label || $slots.label" class="form-field__heading">
      <label class="form-field__label" :for="id">
        <slot name="label">{{ label }}</slot>
        <span v-if="required" aria-hidden="true" class="form-field__required">*</span>
      </label>
      <span v-if="optional && !required" class="form-field__optional">Optional</span>
    </div>
    <slot :described-by="message ? `${id}-error` : hint ? `${id}-hint` : undefined" :invalid="Boolean(message)" />
    <p v-if="message" :id="`${id}-error`" class="form-field__message form-field__message--error" role="alert">
      {{ message }}
    </p>
    <p v-else-if="hint" :id="`${id}-hint`" class="form-field__message">{{ hint }}</p>
  </div>
</template>

<style scoped>
.form-field {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.form-field__heading {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--space-3);
}

.form-field__label {
  color: var(--color-text);
  font-size: 0.875rem;
  font-weight: 640;
}

.form-field__required {
  margin-left: var(--space-1);
  color: var(--color-danger);
}

.form-field__optional,
.form-field__message {
  color: var(--color-text-muted);
  font-size: 0.8125rem;
}

.form-field__message {
  line-height: 1.4;
}

.form-field__message--error {
  color: var(--color-danger);
}
</style>
