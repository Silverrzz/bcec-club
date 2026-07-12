<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import type { MoveRecord, OpeningRecord } from '@/components/public/types'

import ChessBoard from './ChessBoard.vue'
import type { Color } from './chess'

const props = withDefaults(defineProps<{
  opening?: OpeningRecord | null
  moves?: MoveRecord[]
  modelValue?: number
  label?: string
}>(), {
  opening: null,
  moves: () => [],
  label: 'Chess game viewer',
})

const emit = defineEmits<{
  'update:modelValue': [ply: number]
  position: [value: { ply: number; fen: string }]
}>()

const orientation = ref<Color>('white')
const ply = ref(props.modelValue ?? props.moves.length)
const currentFen = ref(props.opening?.fen || 'startpos')
const copied = ref('')
let copyTimer: number | undefined

const uciMoves = computed(() => props.moves.map((move) => move.uci).filter(Boolean))
const sanMoves = computed(() => props.moves.map((move) => move.san || move.uci))
const opening = computed<OpeningRecord>(() => props.opening || { name: 'Start position', fen: 'startpos' })
const hasOpeningName = computed(() => {
  const name = opening.value.name.trim().toLowerCase()
  return Boolean(name) && name !== '?' && name !== 'opening'
})

watch(() => props.modelValue, (value) => {
  if (value !== undefined) ply.value = value
})

watch(() => props.moves.length, (length, previousLength) => {
  if (props.modelValue === undefined && ply.value >= previousLength) ply.value = length
})

function selectPly(value: number): void {
  ply.value = value
  emit('update:modelValue', value)
}

function flipBoard(): void {
  orientation.value = orientation.value === 'white' ? 'black' : 'white'
}

async function copy(value: string, label: string): Promise<void> {
  try {
    if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(value)
    else fallbackCopy(value)
    copied.value = `${label} copied`
  } catch {
    copied.value = `Could not copy ${label.toLowerCase()}`
  }
  window.clearTimeout(copyTimer)
  copyTimer = window.setTimeout(() => { copied.value = '' }, 2200)
}

function fallbackCopy(value: string): void {
  const textarea = document.createElement('textarea')
  textarea.value = value
  textarea.style.position = 'fixed'
  textarea.style.opacity = '0'
  document.body.append(textarea)
  textarea.select()
  document.execCommand('copy')
  textarea.remove()
}
</script>

<template>
  <div class="viewer-shell">
    <ChessBoard
      :fen="opening.fen"
      :moves="uciMoves"
      :san-moves="sanMoves"
      :model-value="ply"
      :orientation="orientation"
      :label="label"
      @update:model-value="selectPly"
      @position="currentFen = $event.fen; emit('position', $event)"
    />

    <div class="viewer-meta" :class="{ 'viewer-meta--without-opening': !hasOpeningName }">
      <button
        v-if="hasOpeningName"
        class="viewer-meta__copy viewer-meta__copy--opening"
        type="button"
        :title="`Copy opening${opening.fen === 'startpos' ? '' : ' and starting FEN'}`"
        @click="copy(opening.fen === 'startpos' ? opening.name : `${opening.name} | ${opening.fen}`, 'Opening')"
      >
        <span>Opening</span>
        <strong>{{ opening.name }}</strong>
      </button>
      <button class="viewer-meta__copy viewer-meta__copy--fen" type="button" title="Copy current FEN" @click="copy(currentFen, 'FEN')">
        <span>Current FEN</span>
        <code>{{ currentFen }}</code>
      </button>
      <button class="viewer-meta__flip" type="button" :aria-label="`Flip board, ${orientation} is currently at the bottom`" @click="flipBoard">
        Flip
      </button>
    </div>
    <p class="copy-status" aria-live="polite">{{ copied }}</p>
  </div>
</template>

<style scoped>
.viewer-shell {
  position: relative;
  min-width: 0;
}

.viewer-meta {
  display: grid;
  grid-template-columns: minmax(8rem, 0.65fr) minmax(0, 1.35fr) auto;
  gap: var(--space-xs, 0.35rem);
  margin-block-start: var(--space-sm, 0.5rem);
}

.viewer-meta--without-opening {
  grid-template-columns: minmax(0, 1fr) auto;
}

.viewer-meta button {
  min-width: 0;
  border: 1px solid var(--color-border, #d5dbe1);
  border-radius: var(--radius-sm, 0.35rem);
  background: var(--color-surface, #fff);
  color: var(--color-text, #17202a);
  font: inherit;
  cursor: pointer;
}

.viewer-meta button:hover {
  border-color: var(--color-accent, #2f78c4);
}

.viewer-meta button:focus-visible {
  outline: 2px solid var(--color-accent, #2f78c4);
  outline-offset: 2px;
}

.viewer-meta__copy {
  display: flex;
  min-height: 3rem;
  flex-direction: column;
  align-items: flex-start;
  justify-content: center;
  padding: 0.45rem 0.65rem;
  text-align: start;
}

.viewer-meta__copy span {
  color: var(--color-text-muted, #607080);
  font-size: 0.65rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.viewer-meta__copy strong,
.viewer-meta__copy code {
  display: block;
  width: 100%;
  overflow: hidden;
  font-size: 0.75rem;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.viewer-meta__copy code {
  color: inherit;
}

.viewer-meta__flip {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  justify-content: center;
  padding-inline: 0.7rem;
  font-size: 0.78rem;
  font-weight: 650;
}

.viewer-meta__flip span {
  font-size: 1.1rem;
}

.copy-status {
  position: absolute;
  inset-block-end: -1.2rem;
  inset-inline-end: 0;
  min-height: 1rem;
  margin: 0;
  color: var(--color-text-muted, #607080);
  font-size: 0.7rem;
}

@media (max-width: 32rem) {
  .viewer-meta {
    grid-template-columns: minmax(0, 1fr) auto;
  }

  .viewer-meta__copy--fen {
    grid-column: 1 / -1;
    grid-row: 2;
  }

  .viewer-meta--without-opening .viewer-meta__copy--fen {
    grid-column: 1;
    grid-row: 1;
  }
}
</style>
