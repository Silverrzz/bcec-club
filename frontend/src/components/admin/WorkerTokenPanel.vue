<script setup lang="ts">
import { ref } from 'vue'
import { formatDate } from './format'

withDefaults(defineProps<{
  token: string
  expiresAt: string
  startCommand?: string
  title?: string
  warning?: string
}>(), {
  title: 'One-time worker credential',
  warning: 'Store this credential now. It is held only in this page and cannot be recovered after you leave or refresh.',
})
const copied = ref<'token' | 'command' | ''>('')

async function copy(value: string, kind: 'token' | 'command'): Promise<void> {
  await navigator.clipboard.writeText(value)
  copied.value = kind
  window.setTimeout(() => { if (copied.value === kind) copied.value = '' }, 1800)
}
</script>

<template>
  <section class="token-panel" aria-labelledby="worker-token-title">
    <div class="token-panel__icon" aria-hidden="true">
      <svg viewBox="0 0 24 24"><circle cx="8.5" cy="12" r="3.5" /><path d="M12 12h9m-3 0v3m-3-3v2" /></svg>
    </div>
    <div class="token-panel__body">
      <div class="token-panel__heading">
        <div><h2 id="worker-token-title">{{ title }}</h2><p>Expires {{ formatDate(expiresAt) }}</p></div>
        <span>Shown once</span>
      </div>
      <div class="secret-row">
        <code>{{ token }}</code>
        <button class="button button--secondary button--small" type="button" @click="copy(token, 'token')">{{ copied === 'token' ? 'Copied' : 'Copy token' }}</button>
      </div>
      <div v-if="startCommand" class="command-row">
        <span>Start command</span>
        <code>{{ startCommand }}</code>
        <button class="button button--secondary button--small" type="button" @click="copy(startCommand, 'command')">{{ copied === 'command' ? 'Copied' : 'Copy command' }}</button>
      </div>
      <p class="token-panel__warning">{{ warning }}</p>
    </div>
  </section>
</template>

<style scoped>
.token-panel { background: color-mix(in srgb, var(--color-accent, #315fcc) 7%, var(--color-surface, #fff)); border: 1px solid color-mix(in srgb, var(--color-accent, #315fcc) 30%, var(--color-border, #d9e0ea)); border-radius: var(--radius-lg, .8rem); display: grid; gap: .9rem; grid-template-columns: auto minmax(0, 1fr); padding: 1rem; }
.token-panel__icon { align-items: center; background: var(--color-primary, #2d63bf); border-radius: 50%; color: var(--color-on-primary, #fff); display: flex; height: 2.2rem; justify-content: center; width: 2.2rem; }
.token-panel__icon svg { fill: none; height: 1.2rem; stroke: currentColor; stroke-linecap: round; stroke-linejoin: round; stroke-width: 1.8; width: 1.2rem; }
.token-panel__body { display: grid; gap: .75rem; min-width: 0; }
.token-panel__heading { align-items: flex-start; display: flex; gap: 1rem; justify-content: space-between; }
.token-panel h2 { font-size: .95rem; margin: 0; }
.token-panel__heading p { color: var(--color-text-muted, #64748b); font-size: .75rem; margin: .2rem 0 0; }
.token-panel__heading > span { background: var(--color-primary, #2d63bf); border-radius: 999px; color: var(--color-on-primary, #fff); font-size: .65rem; font-weight: 700; padding: .3rem .5rem; text-transform: uppercase; white-space: nowrap; }
.secret-row, .command-row { align-items: center; background: var(--color-surface, #fff); border: 1px solid var(--color-border, #d9e0ea); border-radius: var(--radius-md, .6rem); display: grid; gap: .55rem; grid-template-columns: minmax(0, 1fr) auto; padding: .55rem; }
.secret-row code, .command-row code { font-size: .7rem; overflow: auto; padding: .2rem; white-space: nowrap; }
.command-row > span { color: var(--color-text-muted, #64748b); font-size: .68rem; font-weight: 650; grid-column: 1 / -1; text-transform: uppercase; }
.token-panel__warning { color: var(--color-text-muted, #64748b); font-size: .73rem; line-height: 1.45; margin: 0; }
@media (max-width: 34rem) {
  .token-panel { grid-template-columns: 1fr; }
  .secret-row, .command-row { grid-template-columns: 1fr; }
  .secret-row .button, .command-row .button { justify-self: start; }
}
</style>
