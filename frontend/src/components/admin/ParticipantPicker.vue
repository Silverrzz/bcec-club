<script setup lang="ts">
import { computed, ref } from 'vue'
import type { Engine } from './types'

const props = defineProps<{ modelValue: number[]; engines: Engine[] }>()
const emit = defineEmits<{ 'update:modelValue': [value: number[]] }>()

const query = ref('')
const visibleEngines = computed(() => {
  const needle = query.value.trim().toLocaleLowerCase()
  if (!needle) return props.engines
  return props.engines.filter((engine) => `${engine.name} ${engine.author ?? ''} ${engine.version ?? ''}`.toLocaleLowerCase().includes(needle))
})
const selected = computed(() => new Set(props.modelValue))

function toggle(engineId: number): void {
  const next = new Set(props.modelValue)
  if (next.has(engineId)) next.delete(engineId)
  else next.add(engineId)
  emit('update:modelValue', [...next])
}

function selectVisible(): void {
  emit('update:modelValue', [...new Set([...props.modelValue, ...visibleEngines.value.map((engine) => engine.id)])])
}

function clear(): void {
  emit('update:modelValue', [])
}
</script>

<template>
  <div class="participant-picker">
    <div class="participant-picker__toolbar">
      <label class="participant-search">
        <span class="sr-only">Search engines</span>
        <svg aria-hidden="true" viewBox="0 0 24 24"><circle cx="11" cy="11" r="6.5" /><path d="m16 16 4 4" /></svg>
        <input v-model="query" class="input" type="search" placeholder="Search by engine, author, or version">
      </label>
      <span class="participant-picker__count" aria-live="polite">{{ modelValue.length }} selected</span>
      <button v-if="visibleEngines.length" class="button button--ghost button--small" type="button" @click="selectVisible">Select visible</button>
      <button v-if="modelValue.length" class="button button--ghost button--small" type="button" @click="clear">Clear</button>
    </div>

    <div v-if="visibleEngines.length" class="participant-grid" role="group" aria-label="Tournament participants">
      <label v-for="engine in visibleEngines" :key="engine.id" class="participant-card" :class="{ 'participant-card--selected': selected.has(engine.id) }">
        <input type="checkbox" :checked="selected.has(engine.id)" @change="toggle(engine.id)">
        <span class="participant-card__body">
          <strong>{{ engine.name }}</strong>
          <span v-if="engine.author || engine.version">{{ [engine.author, engine.version].filter(Boolean).join(' · ') }}</span>
        </span>
        <svg class="participant-card__check" aria-hidden="true" viewBox="0 0 24 24"><path d="m5 12 4.2 4L19 6.5" /></svg>
      </label>
    </div>
    <p v-else class="participant-picker__empty">No engines match “{{ query }}”.</p>
  </div>
</template>

<style scoped>
.participant-picker { display: grid; gap: .8rem; }
.participant-picker__toolbar { align-items: center; display: flex; flex-wrap: wrap; gap: .55rem; }
.participant-search { flex: 1 1 18rem; position: relative; }
.participant-search svg { fill: none; height: 1rem; left: .75rem; pointer-events: none; position: absolute; stroke: var(--color-text-muted, #64748b); stroke-linecap: round; stroke-width: 1.8; top: 50%; transform: translateY(-50%); width: 1rem; }
.participant-search .input { padding-left: 2.25rem; width: 100%; }
.participant-picker__count { color: var(--color-text-muted, #64748b); font-size: .82rem; font-weight: 600; white-space: nowrap; }
.participant-grid { display: grid; gap: .55rem; grid-template-columns: repeat(auto-fill, minmax(min(100%, 14rem), 1fr)); max-height: 23rem; overflow: auto; padding: .1rem; }
.participant-card { align-items: center; background: var(--color-surface, #fff); border: 1px solid var(--color-border, #d9e0ea); border-radius: var(--radius-md, .6rem); cursor: pointer; display: flex; gap: .65rem; min-width: 0; padding: .72rem .8rem; transition: border-color 120ms ease, background 120ms ease, box-shadow 120ms ease; }
.participant-card:hover { border-color: color-mix(in srgb, var(--color-accent, #315fcc) 45%, var(--color-border, #d9e0ea)); }
.participant-card:focus-within { box-shadow: 0 0 0 3px color-mix(in srgb, var(--color-accent, #315fcc) 20%, transparent); }
.participant-card--selected { background: color-mix(in srgb, var(--color-accent, #315fcc) 7%, var(--color-surface, #fff)); border-color: var(--color-accent, #315fcc); }
.participant-card input { height: 1rem; margin: 0; width: 1rem; }
.participant-card__body { display: grid; flex: 1 1 auto; min-width: 0; }
.participant-card__body strong, .participant-card__body span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.participant-card__body span { color: var(--color-text-muted, #64748b); font-size: .76rem; margin-top: .14rem; }
.participant-card__check { fill: none; height: 1rem; opacity: 0; stroke: var(--color-accent, #315fcc); stroke-linecap: round; stroke-linejoin: round; stroke-width: 2.2; width: 1rem; }
.participant-card--selected .participant-card__check { opacity: 1; }
.participant-picker__empty { color: var(--color-text-muted, #64748b); margin: .5rem 0; text-align: center; }
</style>
