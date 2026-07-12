<script setup lang="ts">
withDefaults(defineProps<{
  kind: 'loading' | 'error' | 'empty'
  title?: string
  message?: string
  actionLabel?: string
  compact?: boolean
}>(), {
  title: '',
  message: '',
  actionLabel: '',
  compact: false,
})

defineEmits<{
  action: []
}>()
</script>

<template>
  <section
    class="content-state"
    :class="[`content-state--${kind}`, { 'content-state--compact': compact }]"
    :role="kind === 'error' ? 'alert' : 'status'"
    :aria-live="kind === 'loading' ? 'polite' : undefined"
    :aria-busy="kind === 'loading' || undefined"
  >
    <span v-if="kind === 'loading'" class="content-state__spinner" aria-hidden="true"></span>
    <span v-else class="content-state__icon" aria-hidden="true">{{ kind === 'error' ? '!' : '○' }}</span>
    <div>
      <h2>{{ title || (kind === 'loading' ? 'Loading' : kind === 'error' ? 'Unable to load this page' : 'Nothing here yet') }}</h2>
      <p v-if="message">{{ message }}</p>
    </div>
    <button v-if="actionLabel" type="button" @click="$emit('action')">{{ actionLabel }}</button>
  </section>
</template>

<style scoped>
.content-state {
  display: grid;
  min-height: clamp(16rem, 48vh, 28rem);
  place-content: center;
  justify-items: center;
  gap: var(--space-md, 1rem);
  padding: var(--space-xl, 2rem);
  border: 1px solid var(--color-border, #d5dbe1);
  border-radius: var(--radius-lg, 0.75rem);
  background: var(--color-surface, #fff);
  text-align: center;
}

.content-state--compact {
  min-height: 9rem;
  padding: var(--space-lg, 1.5rem);
}

.content-state__spinner {
  width: 2rem;
  height: 2rem;
  border: 3px solid color-mix(in srgb, var(--color-accent, #2f78c4) 22%, transparent);
  border-block-start-color: var(--color-accent, #2f78c4);
  border-radius: 50%;
  animation: spin 0.75s linear infinite;
}

.content-state__icon {
  display: grid;
  width: 2.25rem;
  height: 2.25rem;
  place-items: center;
  border: 2px solid currentColor;
  border-radius: 50%;
  color: var(--color-text-muted, #607080);
  font-weight: 800;
}

.content-state--error .content-state__icon {
  color: var(--color-danger, #b42318);
}

.content-state h2,
.content-state p {
  margin: 0;
}

.content-state h2 {
  font-size: 1rem;
}

.content-state p {
  max-width: 34rem;
  margin-block-start: 0.35rem;
  color: var(--color-text-muted, #607080);
  font-size: 0.88rem;
}

.content-state button {
  min-height: 2.5rem;
  padding-inline: 1rem;
  border: 0;
  border-radius: var(--radius-sm, 0.35rem);
  background: var(--color-primary, var(--color-accent, #2f78c4));
  color: var(--color-on-primary, var(--color-on-accent, #fff));
  font: inherit;
  font-weight: 700;
  cursor: pointer;
}

.content-state button:focus-visible {
  outline: 2px solid var(--color-accent, #2f78c4);
  outline-offset: 3px;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

@media (prefers-reduced-motion: reduce) {
  .content-state__spinner { animation-duration: 1.8s; }
}
</style>
