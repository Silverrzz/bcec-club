<script setup lang="ts">
defineProps<{ message?: string | null; tone?: 'error' | 'info' }>()
</script>

<template>
  <div v-if="message" class="inline-feedback" :class="`inline-feedback--${tone ?? 'error'}`" :role="tone === 'info' ? 'status' : 'alert'">
    <svg aria-hidden="true" viewBox="0 0 24 24">
      <path d="M12 8v4m0 4h.01M10.3 3.8 2.6 17.1A2 2 0 0 0 4.3 20h15.4a2 2 0 0 0 1.7-2.9L13.7 3.8a2 2 0 0 0-3.4 0Z" />
    </svg>
    <span>{{ message }}</span>
  </div>
</template>

<style scoped>
.inline-feedback {
  align-items: flex-start;
  background: color-mix(in srgb, var(--feedback-color) 9%, transparent);
  border: 1px solid color-mix(in srgb, var(--feedback-color) 28%, transparent);
  border-radius: var(--radius-md, .6rem);
  color: var(--feedback-color);
  display: flex;
  font-size: .9rem;
  gap: .65rem;
  padding: .8rem .9rem;
}
.inline-feedback svg { fill: none; flex: 0 0 auto; height: 1.15rem; stroke: currentColor; stroke-linecap: round; stroke-width: 1.8; width: 1.15rem; }
.inline-feedback--error { --feedback-color: var(--color-danger, #b42318); }
.inline-feedback--info { --feedback-color: var(--color-accent, #315fcc); }
</style>
