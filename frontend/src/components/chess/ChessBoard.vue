<script setup lang="ts">
import { Chessground } from 'chessground'
import type { Api as ChessgroundApi } from 'chessground/api'
import type { Config as ChessgroundConfig } from 'chessground/config'
import type { Key } from 'chessground/types'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import {
  buildPositions,
  materialSummary,
  positionFen,
  type Color,
} from './chess'

const props = withDefaults(defineProps<{
  fen?: string | null
  moves?: string[]
  sanMoves?: string[]
  modelValue?: number
  orientation?: Color
  controls?: boolean
  coordinates?: boolean
  compact?: boolean
  label?: string
}>(), {
  fen: 'startpos',
  moves: () => [],
  sanMoves: () => [],
  orientation: 'white',
  controls: true,
  coordinates: true,
  compact: false,
  label: 'Chess game viewer',
})

const emit = defineEmits<{
  'update:modelValue': [ply: number]
  position: [value: { ply: number; fen: string }]
}>()

const viewer = ref<HTMLElement | null>(null)
const board = ref<HTMLElement | null>(null)
let ground: ChessgroundApi | null = null
const selectedPly = ref(clampPly(props.modelValue ?? props.moves.length))

const positions = computed(() => buildPositions(props.fen, props.moves))
const position = computed(() => positions.value[clampPly(selectedPly.value)]!)
const currentFen = computed(() => positionFen(position.value))
const material = computed(() => materialSummary(position.value))
const lastMove = computed(() => selectedPly.value > 0 ? props.moves[selectedPly.value - 1] ?? '' : '')
const status = computed(() => {
  if (!props.moves.length) return 'Start position'
  if (selectedPly.value === 0) return `Start position, 0 of ${props.moves.length} moves`
  const san = props.sanMoves[selectedPly.value - 1]
  return `Ply ${selectedPly.value} of ${props.moves.length}${san ? `, ${san}` : ''}`
})

const positionDescription = computed(() => {
  const side = position.value.turn === 'w' ? 'White' : 'Black'
  return `${status.value}. ${side} to move. ${material.value.label}.`
})

watch(() => props.modelValue, (next) => {
  if (next !== undefined && next !== selectedPly.value) selectedPly.value = clampPly(next)
})

let previousFen = props.fen
let previousMoveCount = props.moves.length
watch(() => `${props.fen || ''}\u0000${props.moves.join(' ')}`, () => {
  const followedLatest = selectedPly.value >= previousMoveCount
  if (props.fen !== previousFen || followedLatest) selectPly(props.moves.length)
  else selectPly(selectedPly.value)
  previousFen = props.fen
  previousMoveCount = props.moves.length
})

watch([selectedPly, currentFen], () => {
  emit('position', { ply: selectedPly.value, fen: currentFen.value })
}, { immediate: true })

watch([currentFen, lastMove, () => props.orientation, () => props.coordinates], renderBoard)

onMounted(() => {
  if (board.value) {
    ground = Chessground(board.value, {
      viewOnly: true,
      coordinates: props.coordinates,
      animation: { enabled: !props.compact, duration: 150 },
      drawable: { enabled: false },
    })
    renderBoard()
  }
  if (props.controls) document.addEventListener('keydown', handleKey)
})

onBeforeUnmount(() => {
  document.removeEventListener('keydown', handleKey)
  ground?.destroy()
  ground = null
})

function clampPly(ply: number): number {
  const numeric = Number.isFinite(ply) ? Math.trunc(ply) : 0
  return Math.max(0, Math.min(props.moves.length, numeric))
}

function selectPly(ply: number): void {
  const next = clampPly(ply)
  if (next === selectedPly.value) return
  selectedPly.value = next
  emit('update:modelValue', next)
}

function renderBoard(): void {
  if (!ground) return
  const move = lastMove.value
  const config: ChessgroundConfig = {
    fen: currentFen.value,
    orientation: props.orientation,
    coordinates: props.coordinates,
  }
  if (/^[a-h][1-8][a-h][1-8]/.test(move)) {
    config.lastMove = [move.slice(0, 2) as Key, move.slice(2, 4) as Key]
  }
  ground.set(config)
}

function handleKey(event: KeyboardEvent): void {
  const target = event.target as HTMLElement | null
  if (target instanceof Element && target.closest('input, textarea, select, [contenteditable="true"]')) return
  if (event.key === 'ArrowLeft') {
    event.preventDefault()
    selectPly(selectedPly.value - 1)
  } else if (event.key === 'ArrowRight') {
    event.preventDefault()
    selectPly(selectedPly.value + 1)
  } else if (event.key === 'Home') {
    event.preventDefault()
    selectPly(0)
  } else if (event.key === 'End') {
    event.preventDefault()
    selectPly(props.moves.length)
  }
}

async function focusBoard(): Promise<void> {
  await nextTick()
  viewer.value?.focus()
}

defineExpose({ selectPly, focusBoard })
</script>

<template>
  <section
    ref="viewer"
    class="chess-viewer"
    :class="{ 'chess-viewer--compact': compact }"
    :aria-label="label"
    :tabindex="controls ? 0 : undefined"
  >
    <div ref="board" class="board-mount" role="img" :aria-label="`${label}, ${positionDescription}`"></div>

    <div v-if="controls" class="board-controls">
      <div class="board-controls__buttons" role="group" aria-label="Replay controls">
        <button type="button" :disabled="selectedPly === 0" title="First position (Home)" aria-label="First position" @click="selectPly(0)">
          <span aria-hidden="true">|&lt;</span>
        </button>
        <button type="button" :disabled="selectedPly === 0" title="Previous move (Left arrow)" aria-label="Previous move" @click="selectPly(selectedPly - 1)">
          <span aria-hidden="true">&lt;</span>
        </button>
        <button type="button" :disabled="selectedPly === moves.length" title="Next move (Right arrow)" aria-label="Next move" @click="selectPly(selectedPly + 1)">
          <span aria-hidden="true">&gt;</span>
        </button>
        <button type="button" :disabled="selectedPly === moves.length" title="Latest position (End)" aria-label="Latest position" @click="selectPly(moves.length)">
          <span aria-hidden="true">&gt;|</span>
        </button>
      </div>
      <p class="board-controls__status" aria-live="polite">{{ status }}</p>
      <p class="material" :title="`White ${material.white}, Black ${material.black}`">{{ material.label }}</p>
    </div>

    <p class="sr-only">{{ positionDescription }}</p>
  </section>
</template>

<style scoped>
.chess-viewer {
  width: 100%;
  min-width: 0;
  border-radius: var(--radius-lg, 0.75rem);
  outline: none;
}

.chess-viewer:focus-visible {
  outline: none;
}

.chess-viewer:focus-visible .board-controls__status {
  color: var(--color-text, #17202a);
  font-weight: 650;
}

.board-mount {
  width: 100%;
  aspect-ratio: 1;
  box-sizing: border-box;
  overflow: hidden;
  border: 1px solid color-mix(in srgb, var(--color-text, #17202a) 28%, transparent);
  border-radius: var(--radius-md, 0.5rem);
  background: #b58863;
  box-shadow: 0 0.75rem 2.5rem color-mix(in srgb, #000 14%, transparent);
}

.board-controls {
  display: grid;
  grid-template-columns: auto minmax(7rem, 1fr) auto;
  align-items: center;
  gap: var(--space-sm, 0.5rem);
  padding-block-start: var(--space-sm, 0.5rem);
}

.board-controls__buttons {
  display: flex;
  gap: 0.25rem;
}

.board-controls button {
  display: grid;
  width: 2.25rem;
  height: 2.25rem;
  place-items: center;
  border: 1px solid var(--color-border, #ccd3da);
  border-radius: var(--radius-sm, 0.35rem);
  background: var(--color-surface, #fff);
  color: var(--color-text, #17202a);
  font: inherit;
  font-size: 1.25rem;
  line-height: 1;
  cursor: pointer;
}

.board-controls button:hover:not(:disabled) {
  border-color: var(--color-accent, #2f78c4);
  color: var(--color-accent, #2f78c4);
}

.board-controls button:focus-visible {
  outline: 2px solid var(--color-accent, #2f78c4);
  outline-offset: 2px;
}

.board-controls button:disabled {
  opacity: 0.42;
  cursor: not-allowed;
}

.board-controls__status,
.material {
  margin: 0;
  color: var(--color-text-muted, #607080);
  font-size: 0.82rem;
}

.board-controls__status {
  text-align: center;
}

.material {
  white-space: nowrap;
}

.chess-viewer--compact .board-mount {
  border-radius: var(--radius-sm, 0.35rem);
  box-shadow: none;
}

@media (max-width: 36rem) {
  .board-controls {
    grid-template-columns: 1fr auto;
  }

  .board-controls__status {
    grid-column: 1 / -1;
    grid-row: 2;
    text-align: start;
  }
}

@media (forced-colors: active) {
  .board-mount {
    border: 1px solid CanvasText;
  }
}
</style>
