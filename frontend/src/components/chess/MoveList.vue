<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'

import { parseFen } from './chess'

interface MoveCell {
  ply: number
  label: string
}

interface MoveRow {
  number: number
  white?: MoveCell
  black?: MoveCell
}

const props = withDefaults(defineProps<{
  moves?: string[]
  uciMoves?: string[]
  fen?: string | null
  modelValue?: number
  title?: string
}>(), {
  moves: () => [],
  uciMoves: () => [],
  fen: 'startpos',
  modelValue: 0,
  title: 'Moves',
})

const emit = defineEmits<{
  'update:modelValue': [ply: number]
}>()

const list = ref<HTMLElement | null>(null)
const rows = computed<MoveRow[]>(() => {
  const start = parseFen(props.fen)
  const result: MoveRow[] = []
  let number = start.fullmove
  let side = start.turn

  props.moves.forEach((san, index) => {
    const cell: MoveCell = {
      ply: index + 1,
      label: san || props.uciMoves[index] || `Move ${index + 1}`,
    }
    if (side === 'w') {
      result.push({ number, white: cell })
      side = 'b'
    } else {
      const row = result[result.length - 1]
      if (row && row.number === number && !row.black) row.black = cell
      else result.push({ number, black: cell })
      side = 'w'
      number += 1
    }
  })
  return result
})

const textAlternative = computed(() => rows.value.map((row) => {
  const white = row.white?.label || '...'
  return `${row.number}. ${white}${row.black ? ` ${row.black.label}` : ''}`
}).join(' '))

watch(() => props.modelValue, async () => {
  await nextTick()
  scrollCurrentMoveIntoView()
})

function scrollCurrentMoveIntoView(): void {
  const container = list.value
  const currentMove = container?.querySelector<HTMLElement>('[aria-current="step"]')
  if (!container || !currentMove) return

  const containerRect = container.getBoundingClientRect()
  const currentMoveRect = currentMove.getBoundingClientRect()
  if (currentMoveRect.top < containerRect.top) {
    container.scrollTop -= containerRect.top - currentMoveRect.top
  } else if (currentMoveRect.bottom > containerRect.bottom) {
    container.scrollTop += currentMoveRect.bottom - containerRect.bottom
  }
}
</script>

<template>
  <section class="move-list" aria-labelledby="move-list-title">
    <header class="move-list__header">
      <h2 id="move-list-title">{{ title }}</h2>
      <span>{{ moves.length }} plies</span>
    </header>
    <div v-if="rows.length" ref="list" class="move-list__scroll" tabindex="0">
      <ol class="move-list__rows">
        <li v-for="row in rows" :key="`${row.number}-${row.white?.ply || row.black?.ply}`" class="move-row">
          <span class="move-number">{{ row.number }}.</span>
          <button
            v-if="row.white"
            type="button"
            :aria-label="`Move ${row.number}, White, ${row.white.label}`"
            :aria-current="modelValue === row.white.ply ? 'step' : undefined"
            @click="emit('update:modelValue', row.white.ply)"
          >{{ row.white.label }}</button>
          <span v-else class="move-placeholder">...</span>
          <button
            v-if="row.black"
            type="button"
            :aria-label="`Move ${row.number}, Black, ${row.black.label}`"
            :aria-current="modelValue === row.black.ply ? 'step' : undefined"
            @click="emit('update:modelValue', row.black.ply)"
          >{{ row.black.label }}</button>
          <span v-else class="move-placeholder"></span>
        </li>
      </ol>
    </div>
    <p v-else class="move-list__empty">No moves.</p>
    <p class="sr-only">{{ textAlternative || 'No moves recorded.' }}</p>
  </section>
</template>

<style scoped>
.move-list {
  display: flex;
  min-height: 0;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid var(--color-border, #d5dbe1);
  border-radius: var(--radius-md, 0.5rem);
  background: var(--color-surface, #fff);
}

.move-list__header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--space-sm, 0.5rem);
  padding: var(--space-sm, 0.5rem) var(--space-md, 1rem);
  border-block-end: 1px solid var(--color-border, #d5dbe1);
}

.move-list__header h2 {
  margin: 0;
  font-size: 0.95rem;
}

.move-list__header span {
  color: var(--color-text-muted, #607080);
  font-size: 0.75rem;
}

.move-list__scroll {
  min-height: 6rem;
  flex: 1;
  overflow: auto;
  scrollbar-gutter: stable;
}

.move-list__scroll:focus-visible {
  outline: 2px solid var(--color-accent, #2f78c4);
  outline-offset: -2px;
}

.move-list__rows {
  margin: 0;
  padding: 0.35rem;
  list-style: none;
}

.move-row {
  display: grid;
  grid-template-columns: 2.25rem repeat(2, minmax(0, 1fr));
  align-items: center;
  min-height: 2rem;
  border-radius: var(--radius-sm, 0.35rem);
}

.move-row:nth-child(odd) {
  background: color-mix(in srgb, var(--color-text, #17202a) 3.5%, transparent);
}

.move-number {
  padding-inline: 0.4rem;
  color: var(--color-text-muted, #607080);
  font-size: 0.72rem;
  font-variant-numeric: tabular-nums;
  text-align: end;
}

.move-row button {
  overflow: hidden;
  padding: 0.35rem 0.5rem;
  border: 0;
  border-radius: var(--radius-sm, 0.35rem);
  background: transparent;
  color: var(--color-text, #17202a);
  font: inherit;
  font-size: 0.85rem;
  font-weight: 600;
  text-align: start;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: pointer;
}

.move-row button:hover {
  color: var(--color-accent, #2f78c4);
  background: color-mix(in srgb, var(--color-accent, #2f78c4) 9%, transparent);
}

.move-row button[aria-current='step'] {
  background: var(--color-primary, var(--color-accent, #2f78c4));
  color: var(--color-on-primary, var(--color-on-accent, #fff));
}

.move-row button:focus-visible {
  outline: 2px solid var(--color-accent, #2f78c4);
  outline-offset: -2px;
}

.move-placeholder {
  min-height: 1px;
  padding-inline: 0.5rem;
  color: var(--color-text-muted, #607080);
}

.move-list__empty {
  display: grid;
  min-height: 7rem;
  margin: 0;
  padding: var(--space-md, 1rem);
  place-items: center;
  color: var(--color-text-muted, #607080);
  font-size: 0.85rem;
  text-align: center;
}
</style>
