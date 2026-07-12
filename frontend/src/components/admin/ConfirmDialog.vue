<script setup lang="ts">
import { nextTick, ref } from 'vue'

const dialog = ref<HTMLDialogElement>()
const title = ref('Confirm action')
const description = ref('')
const confirmLabel = ref('Confirm')
const tone = ref<'default' | 'danger'>('default')
let resolver: ((value: boolean) => void) | null = null

async function open(options: {
  title: string
  description: string
  confirmLabel?: string
  tone?: 'default' | 'danger'
}): Promise<boolean> {
  if (dialog.value?.open) finish(false)
  title.value = options.title
  description.value = options.description
  confirmLabel.value = options.confirmLabel ?? 'Confirm'
  tone.value = options.tone ?? 'default'
  await nextTick()
  dialog.value?.showModal()
  return new Promise<boolean>((resolve) => { resolver = resolve })
}

function finish(value: boolean): void {
  dialog.value?.close()
  resolver?.(value)
  resolver = null
}

function onCancel(event: Event): void {
  event.preventDefault()
  finish(false)
}

defineExpose({ open })
</script>

<template>
  <dialog ref="dialog" class="confirm-dialog" aria-labelledby="confirm-title" aria-describedby="confirm-description" @cancel="onCancel" @click.self="finish(false)">
    <form method="dialog" class="confirm-dialog__surface" @submit.prevent="finish(true)">
      <span class="confirm-dialog__icon" :class="{ 'confirm-dialog__icon--danger': tone === 'danger' }" aria-hidden="true">
        <svg viewBox="0 0 24 24"><path d="M12 8v4m0 4h.01M10.3 3.8 2.6 17.1A2 2 0 0 0 4.3 20h15.4a2 2 0 0 0 1.7-2.9L13.7 3.8a2 2 0 0 0-3.4 0Z" /></svg>
      </span>
      <div class="confirm-dialog__copy">
        <h2 id="confirm-title">{{ title }}</h2>
        <p id="confirm-description">{{ description }}</p>
      </div>
      <div class="confirm-dialog__actions">
        <button class="button button--ghost" type="button" @click="finish(false)">Cancel</button>
        <button class="button" :class="tone === 'danger' ? 'button--danger' : 'button--primary'" type="submit">{{ confirmLabel }}</button>
      </div>
    </form>
  </dialog>
</template>

<style scoped>
.confirm-dialog { background: transparent; border: 0; color: inherit; max-width: min(92vw, 30rem); padding: 0; width: 100%; }
.confirm-dialog::backdrop { background: rgb(10 18 30 / .58); backdrop-filter: blur(2px); }
.confirm-dialog__surface { background: var(--color-surface, #fff); border: 1px solid var(--color-border, #d9e0ea); border-radius: var(--radius-lg, .8rem); box-shadow: 0 1.5rem 4rem rgb(8 15 30 / .25); display: grid; gap: .75rem 1rem; grid-template-columns: auto 1fr; padding: 1.2rem; }
.confirm-dialog__icon { align-items: center; background: color-mix(in srgb, var(--color-accent, #315fcc) 10%, transparent); border-radius: 50%; color: var(--color-accent, #315fcc); display: flex; height: 2.2rem; justify-content: center; width: 2.2rem; }
.confirm-dialog__icon--danger { background: color-mix(in srgb, var(--color-danger, #b42318) 10%, transparent); color: var(--color-danger, #b42318); }
.confirm-dialog__icon svg { fill: none; height: 1.15rem; stroke: currentColor; stroke-linecap: round; stroke-linejoin: round; stroke-width: 1.8; width: 1.15rem; }
.confirm-dialog__copy h2 { font-size: 1rem; margin: .1rem 0 0; }
.confirm-dialog__copy p { color: var(--color-text-muted, #64748b); font-size: .86rem; line-height: 1.5; margin: .35rem 0 0; }
.confirm-dialog__actions { display: flex; gap: .6rem; grid-column: 1 / -1; justify-content: flex-end; margin-top: .5rem; }
</style>
