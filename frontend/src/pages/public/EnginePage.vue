<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import { api } from '@/api/client'
import ContentState from '@/components/public/ContentState.vue'
import GameTable from '@/components/public/GameTable.vue'
import { errorMessage } from '@/components/public/format'
import type { EngineRecord, GameRecord } from '@/components/public/types'

interface EngineRecordSummary {
  wins: number
  draws: number
  losses: number
  games: number
}

interface EngineResponse {
  engine: EngineRecord
  games: GameRecord[]
  engines: Record<string, string>
  record: EngineRecordSummary
}

const route = useRoute()
const data = ref<EngineResponse | null>(null)
const loading = ref(true)
const loadError = ref('')
let controller: AbortController | null = null

const engineId = computed(() => String(route.params.id || ''))
const scorePercent = computed(() => {
  if (!data.value?.record.games) return 0
  return Math.round(((data.value.record.wins + data.value.record.draws * 0.5) / data.value.record.games) * 100)
})
const uciOptions = computed(() => Object.entries(data.value?.engine.uci_options || {}))

watch(engineId, load, { immediate: true })
onBeforeUnmount(() => controller?.abort())

async function load(): Promise<void> {
  controller?.abort()
  controller = new AbortController()
  loading.value = true
  loadError.value = ''
  data.value = null
  try {
    data.value = await api.get<EngineResponse>(`/api/engines/${encodeURIComponent(engineId.value)}`, { signal: controller.signal })
  } catch (error) {
    if ((error as { name?: string })?.name !== 'AbortError') {
      loadError.value = errorMessage(error, 'This engine could not be loaded.')
    }
  } finally {
    loading.value = false
  }
}

</script>

<template>
  <div class="page-container engine-page">
    <ContentState v-if="loading" kind="loading" title="Loading engine" />
    <ContentState v-else-if="loadError" kind="error" :message="loadError" action-label="Try again" @action="load" />

    <template v-else-if="data">
      <header class="engine-heading">
        <div>
          <RouterLink class="back-link" to="/ratings">Back to ratings</RouterLink>
          <h1>{{ data.engine.name }}</h1>
          <p v-if="data.engine.author">By {{ data.engine.author }}</p>
        </div>

        <dl class="record-stats" aria-label="Game record">
          <div><dt>Wins</dt><dd>{{ data.record.wins }}</dd></div>
          <div><dt>Draws</dt><dd>{{ data.record.draws }}</dd></div>
          <div><dt>Losses</dt><dd>{{ data.record.losses }}</dd></div>
          <div><dt>Score</dt><dd>{{ scorePercent }}%</dd></div>
        </dl>
      </header>

      <div class="engine-layout">
        <section class="panel build-panel" aria-labelledby="build-title">
          <header>
            <div>
              <h2 id="build-title">Version artifact</h2>
            </div>
          </header>
          <dl class="build-details">
            <div><dt>Version</dt><dd>{{ data.engine.version || '-' }}</dd></div>
            <div><dt>Binary</dt><dd><code>{{ data.engine.binary_filename || '-' }}</code></dd></div>
            <div class="detail-wide"><dt>SHA-256</dt><dd><code :title="data.engine.binary_sha256 || undefined">{{ data.engine.binary_sha256 || '-' }}</code></dd></div>
            <div><dt>Size</dt><dd>{{ data.engine.binary_size ? `${data.engine.binary_size.toLocaleString()} bytes` : '-' }}</dd></div>
          </dl>
        </section>

        <section class="panel options-panel" aria-labelledby="options-title">
          <header>
            <div>
              <h2 id="options-title">UCI options</h2>
            </div>
            <span>{{ uciOptions.length }}</span>
          </header>
          <dl v-if="uciOptions.length" class="option-list">
            <div v-for="([name, value]) in uciOptions" :key="name">
              <dt>{{ name }}</dt>
              <dd><code>{{ String(value) }}</code></dd>
            </div>
          </dl>
          <p v-else class="panel-empty">No custom UCI options.</p>
        </section>
      </div>

      <section class="panel games-panel" aria-labelledby="engine-games-title">
        <header>
          <div>
            <h2 id="engine-games-title">Recent games</h2>
            <p>{{ data.record.games }} completed game{{ data.record.games === 1 ? '' : 's' }} in the recorded result.</p>
          </div>
        </header>
        <GameTable v-if="data.games.length" :games="data.games" :engines="data.engines" :show-round="false" caption="Recent games for this engine" />
        <ContentState v-else kind="empty" compact title="No games yet" />
      </section>
    </template>
  </div>
</template>

<style scoped>
.engine-page {
  display: grid;
  gap: var(--space-xl, 2rem);
  padding-block: clamp(1.2rem, 2.5vw, 2.25rem) 3rem;
}

.engine-heading {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: var(--space-xl, 2rem);
  padding-block-end: var(--space-xl, 2rem);
  border-block-end: 1px solid var(--color-border, #d5dbe1);
}

.engine-heading h1,
.engine-heading p,
.record-stats,
.panel h2,
.panel p,
.panel dl {
  margin: 0;
}

.back-link {
  display: inline-block;
  margin-block-end: 1rem;
  color: var(--color-text-muted, #607080);
  font-size: 0.75rem;
  font-weight: 700;
  text-decoration: none;
}

.back-link:hover { color: var(--color-accent, #2f78c4); }

.engine-heading h1 {
  margin-block-start: 0.2rem;
  font-size: clamp(2rem, 5vw, 3.6rem);
  letter-spacing: -0.04em;
  line-height: 1;
}

.engine-heading > div > p {
  margin-block-start: 0.5rem;
  color: var(--color-text-muted, #607080);
}

.source-link {
  display: inline-block;
  margin-block-start: 0.75rem;
  color: var(--color-accent, #2f78c4);
  font-size: 0.76rem;
  font-weight: 700;
  text-decoration: none;
}

.source-link:hover { text-decoration: underline; text-underline-offset: 0.18em; }

.record-stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(5rem, 1fr));
  gap: 1px;
  overflow: hidden;
  border: 1px solid var(--color-border, #d5dbe1);
  border-radius: var(--radius-md, 0.5rem);
  background: var(--color-border, #d5dbe1);
}

.record-stats div {
  min-width: 5rem;
  padding: 0.75rem 0.9rem;
  background: var(--color-surface, #fff);
}

.record-stats dt,
.build-details dt,
.option-list dt {
  color: var(--color-text-muted, #607080);
  font-size: 0.62rem;
  font-weight: 750;
  letter-spacing: 0.045em;
  text-transform: uppercase;
}

.record-stats dd {
  margin: 0.18rem 0 0;
  font-size: 1.25rem;
  font-weight: 800;
  font-variant-numeric: tabular-nums;
}

.engine-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(17rem, 0.65fr);
  gap: var(--space-md, 1rem);
  align-items: start;
}

.panel {
  overflow: hidden;
  padding: 0;
}

.panel > header {
  display: flex;
  align-items: start;
  justify-content: space-between;
  gap: 1rem;
  padding: var(--space-md, 1rem);
  border-block-end: 1px solid var(--color-border, #d5dbe1);
}

.panel h2 { font-size: 1rem; }
.panel header p { margin-block-start: 0.2rem; color: var(--color-text-muted, #607080); font-size: 0.72rem; }
.options-panel header > span { color: var(--color-text-muted, #607080); font-size: 0.72rem; }

.build-details {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 1px;
  background: var(--color-border, #d5dbe1);
}

.build-details div {
  min-width: 0;
  padding: 1rem;
  background: var(--color-surface, #fff);
}

.build-details .detail-wide { grid-column: span 3; }
.build-details dd,
.option-list dd { margin: 0.25rem 0 0; overflow-wrap: anywhere; }
.build-details code,
.option-list code { color: inherit; font-size: 0.76rem; }

.option-list {
  display: grid;
  max-height: 21rem;
  overflow: auto;
  padding: 0.3rem 1rem;
}

.option-list div {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 1rem;
  padding-block: 0.65rem;
  border-block-end: 1px solid var(--color-border, #d5dbe1);
}

.option-list div:last-child { border-block-end: 0; }
.option-list dd { text-align: end; }
.panel-empty { padding: 2.5rem 1rem; color: var(--color-text-muted, #607080); font-size: 0.8rem; text-align: center; }

@media (max-width: 62rem) {
  .engine-heading { align-items: stretch; flex-direction: column; }
  .record-stats { align-self: stretch; }
  .record-stats div { min-width: 0; }
  .engine-layout { grid-template-columns: 1fr; }
}

@media (max-width: 38rem) {
  .record-stats { grid-template-columns: repeat(2, 1fr); }
  .build-details { grid-template-columns: 1fr 1fr; }
  .build-details .detail-wide { grid-column: span 2; }
}
</style>
