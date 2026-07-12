<script setup lang="ts">
import { computed } from 'vue'

import ChessBoard from '@/components/chess/ChessBoard.vue'

import type { EngineAnalysis, Identifier } from './types'
import { formatNodes, formatNps } from './format'

const props = withDefaults(defineProps<{
  side: 'white' | 'black'
  name?: string
  engineId?: Identifier | null
  clock?: string
  analysis?: EngineAnalysis | null
  positionFen?: string | null
  active?: boolean
}>(), {
  name: '',
  engineId: null,
  clock: '--:--',
  analysis: null,
  positionFen: 'startpos',
  active: false,
})

const title = computed(() => props.name || (props.side === 'white' ? 'White' : 'Black'))
const info = computed(() => props.analysis?.info || props.analysis?.pv || 'No analysis recorded')
const pvMoves = computed(() => (props.analysis?.pv || '')
  .split(/\s+/)
  .map((move) => move.toLowerCase())
  .filter((move) => /^[a-h][1-8][a-h][1-8][qrbn]?$/.test(move)))
const pvRootFen = computed(() => props.analysis?.root_fen || props.positionFen || 'startpos')
</script>

<template>
  <article class="engine-panel" :class="[`engine-panel--${side}`, { 'engine-panel--active': active }]">
    <header>
      <div>
        <span>{{ side }}</span>
        <strong>
          <RouterLink v-if="engineId !== null" :to="`/engines/${engineId}`">{{ title }}</RouterLink>
          <template v-else>{{ title }}</template>
        </strong>
      </div>
      <time :aria-label="`${title} clock, ${clock}`">{{ clock }}</time>
    </header>

    <div class="engine-panel__body">
      <div class="engine-panel__details">
        <div class="evaluation">
          <span>Evaluation</span>
          <strong>{{ analysis?.eval ?? '-' }}</strong>
        </div>

        <dl class="engine-stats">
          <div><dt>Depth</dt><dd>{{ analysis?.depth ?? '-' }}</dd></div>
          <div><dt>Nodes</dt><dd>{{ formatNodes(analysis?.nodes) }}</dd></div>
          <div><dt>NPS</dt><dd>{{ formatNps(analysis?.nps) }}</dd></div>
        </dl>

        <div class="analysis-line">
          <span>{{ analysis?.pv ? 'Principal variation' : 'Engine info' }}</span>
          <p :title="info">{{ analysis?.pv || info }}</p>
        </div>
      </div>

      <div class="pv-preview">
        <span>PV position</span>
        <ChessBoard
          :fen="pvRootFen"
          :moves="pvMoves"
          :orientation="side"
          :controls="false"
          :coordinates="false"
          compact
          :label="`${title} principal variation final position`"
        />
      </div>
    </div>
  </article>
</template>

<style scoped>
.engine-panel {
  --side-color: #05070a;
  --side-name: var(--color-text, #17202a);
  position: relative;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  gap: 0.75rem;
  height: 100%;
  min-height: 17rem;
  min-width: 0;
  overflow: hidden;
  padding: var(--space-md, 1rem);
  border: 1px solid var(--color-border, #d5dbe1);
  border-inline-start: 4px solid var(--side-color);
  border-radius: var(--radius-md, 0.5rem);
  background: var(--color-surface-raised, var(--color-surface, #fff));
}

.engine-panel--white {
  --side-color: #f7f8fa;
}

.engine-panel::before {
  position: absolute;
  inset-block: 0;
  inset-inline-start: 0;
  width: 4px;
  background: var(--side-color);
  content: '';
}

.engine-panel--active {
  border-color: var(--color-border-strong, #99a8bb);
  border-inline-start-color: var(--side-color);
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--side-color) 22%, var(--color-border-strong, #99a8bb));
}

.engine-panel header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
}

.engine-panel header > div {
  display: flex;
  min-width: 0;
  flex-direction: column;
}

.engine-panel header span,
.evaluation span,
.analysis-line span,
.engine-stats dt {
  color: var(--color-text-muted, #607080);
  font-size: 0.62rem;
  font-weight: 750;
  letter-spacing: 0.045em;
  text-transform: uppercase;
}

.engine-panel header strong {
  overflow: hidden;
  color: var(--side-name);
  font-size: 0.9rem;
  font-weight: 800;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.engine-panel header a {
  color: inherit;
  text-decoration: none;
}

.engine-panel header a:hover {
  color: var(--color-text, #17202a);
  text-decoration: underline;
  text-underline-offset: 0.16em;
}

.engine-panel time {
  font-size: clamp(1.2rem, 2vw, 1.65rem);
  font-weight: 760;
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.015em;
  white-space: nowrap;
}

.engine-panel__body {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(8.5rem, 10rem);
  align-items: center;
  gap: 1rem;
  min-height: 0;
}

.engine-panel__details {
  display: grid;
  grid-template-rows: auto auto minmax(3.3rem, 1fr);
  align-self: stretch;
  gap: 0.75rem;
  min-width: 0;
  min-height: 0;
}

.evaluation {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.62rem 0.7rem;
  border-radius: var(--radius-sm, 0.35rem);
  background: color-mix(in srgb, var(--color-text, #17202a) 4.5%, transparent);
}

.evaluation strong {
  font-size: 1.35rem;
  font-variant-numeric: tabular-nums;
}

.engine-stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin: 0;
}

.engine-stats div {
  min-width: 0;
  padding-inline: 0.55rem;
  border-inline-start: 1px solid var(--color-border, #d5dbe1);
}

.engine-stats div:first-child {
  padding-inline-start: 0;
  border-inline-start: 0;
}

.engine-stats dd {
  overflow: hidden;
  margin: 0.16rem 0 0;
  font-size: 0.78rem;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.analysis-line {
  overflow-y: auto;
  min-width: 0;
  min-height: 0;
}

.analysis-line p {
  margin: 0.25rem 0 0;
  color: var(--color-text-muted, #607080);
  font-family: var(--font-mono, ui-monospace, monospace);
  font-size: 0.68rem;
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.pv-preview {
  display: grid;
  align-content: center;
  gap: 0.35rem;
  min-width: 0;
}

.pv-preview > span {
  color: var(--color-text-muted, #607080);
  font-size: 0.58rem;
  font-weight: 750;
  letter-spacing: 0.045em;
  text-align: center;
  text-transform: uppercase;
}

.pv-preview :deep(.board-mount) {
  border-color: color-mix(in srgb, var(--side-color) 62%, var(--color-border, #d5dbe1));
}

@media (max-width: 40rem) {
  .engine-panel__body {
    grid-template-columns: minmax(0, 1fr) minmax(7.5rem, 9rem);
  }
}
</style>
