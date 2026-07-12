<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { api } from '@/api/client'
import ContentState from '@/components/public/ContentState.vue'
import GameTable from '@/components/public/GameTable.vue'
import TournamentCard from '@/components/public/TournamentCard.vue'
import { engineName, errorMessage, tournamentName } from '@/components/public/format'
import type { GameRecord, TournamentSummary } from '@/components/public/types'

interface ArchiveResponse {
  tournaments: TournamentSummary[]
  games: GameRecord[]
  engines: Record<string, string>
}

const route = useRoute()
const router = useRouter()
const data = ref<ArchiveResponse | null>(null)
const loading = ref(true)
const loadError = ref('')
let controller: AbortController | null = null

const search = computed({
  get: () => queryValue(route.query.q),
  set: (value: string) => updateQuery('q', value.trim() || undefined),
})
const status = computed({
  get: () => queryValue(route.query.status) || 'all',
  set: (value: string) => updateQuery('status', value === 'all' ? undefined : value),
})
const tournamentNames = computed(() => Object.fromEntries(
  (data.value?.tournaments || []).map((item) => [String(item.record.id), item.record.name]),
))
const filteredTournaments = computed(() => {
  const term = search.value.toLocaleLowerCase()
  return (data.value?.tournaments || []).filter((item) => {
    if (item.record.status === 'draft') return false
    if (status.value !== 'all' && item.record.status !== status.value) return false
    return !term || [item.record.name, item.format, item.time_control, ...(item.participant_names || [])]
      .some((value) => value?.toLocaleLowerCase().includes(term))
  })
})
const filteredGames = computed(() => {
  const term = search.value.toLocaleLowerCase()
  if (!term) return data.value?.games || []
  return (data.value?.games || []).filter((game) => [
    tournamentName(tournamentNames.value, game.tournament_id),
    engineName(data.value?.engines, game.white_engine_id, game.white_name),
    engineName(data.value?.engines, game.black_engine_id, game.black_name),
    game.result || '',
  ].some((value) => value.toLocaleLowerCase().includes(term)))
})
const completedGames = computed(() => (data.value?.tournaments || []).reduce((sum, item) => sum + (item.summary.finished || 0), 0))

onMounted(load)
onBeforeUnmount(() => controller?.abort())

async function load(): Promise<void> {
  controller?.abort()
  controller = new AbortController()
  loading.value = true
  loadError.value = ''
  try {
    data.value = await api.get<ArchiveResponse>('/api/archive', { signal: controller.signal })
  } catch (error) {
    if ((error as { name?: string })?.name !== 'AbortError') {
      loadError.value = errorMessage(error, 'The archive could not be loaded.')
    }
  } finally {
    loading.value = false
  }
}

function queryValue(value: unknown): string {
  return Array.isArray(value) ? String(value[0] || '') : typeof value === 'string' ? value : ''
}

function updateQuery(key: string, value?: string): void {
  const query = { ...route.query }
  if (value) query[key] = value
  else delete query[key]
  void router.replace({ query })
}

function clearFilters(): void {
  void router.replace({ query: {} })
}
</script>

<template>
  <div class="page-container archive-page">
    <ContentState v-if="loading" kind="loading" title="Loading archive" />
    <ContentState v-else-if="loadError" kind="error" :message="loadError" action-label="Try again" @action="load" />

    <template v-else-if="data">
      <header class="archive-heading">
        <div>
          <h1>Archive</h1>
        </div>
        <dl aria-label="Archive summary">
          <div><dt>Tournaments</dt><dd>{{ data.tournaments.length }}</dd></div>
          <div><dt>Finished games</dt><dd>{{ completedGames.toLocaleString() }}</dd></div>
        </dl>
      </header>

      <form v-if="data.tournaments.length || data.games.length" class="archive-filters" role="search" @submit.prevent>
        <label>
          <span>Search archive</span>
          <input v-model="search" type="search" name="q" placeholder="Tournament or engine">
        </label>
        <label>
          <span>Tournament result</span>
          <select v-model="status" name="status">
            <option value="all">Finished and aborted</option>
            <option value="finished">Finished</option>
            <option value="aborted">Aborted</option>
          </select>
        </label>
      </form>

      <section v-if="data.tournaments.length" class="archive-section" aria-labelledby="archive-tournaments-title">
        <div class="section-heading">
          <div>
            <h2 id="archive-tournaments-title">Tournaments</h2>
            <p>{{ filteredTournaments.length }} archived event{{ filteredTournaments.length === 1 ? '' : 's' }} shown</p>
          </div>
        </div>
        <div v-if="filteredTournaments.length" class="archive-grid">
          <TournamentCard v-for="item in filteredTournaments" :key="item.record.id" :item="item" compact />
        </div>
        <ContentState v-else kind="empty" compact title="No matching tournaments" action-label="Clear filters" @action="clearFilters" />
      </section>

      <section class="panel games-section" aria-labelledby="archive-games-title">
        <header>
          <div>
            <h2 id="archive-games-title">Latest finished games</h2>
            <p>{{ filteredGames.length }} result{{ filteredGames.length === 1 ? '' : 's' }} shown</p>
          </div>
        </header>
        <GameTable
          v-if="filteredGames.length"
          :games="filteredGames"
          :engines="data.engines"
          :tournament-names="tournamentNames"
          :show-tournament="true"
          :show-round="false"
          caption="Archived finished games"
        />
        <ContentState v-else kind="empty" compact title="No finished games found" />
      </section>
    </template>
  </div>
</template>

<style scoped>
.archive-page {
  display: grid;
  gap: var(--space-xl, 2rem);
  padding-block: clamp(1.2rem, 2.5vw, 2.25rem) 3rem;
}

.archive-heading {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: var(--space-xl, 2rem);
  padding-block-end: var(--space-lg, 1.5rem);
  border-block-end: 1px solid var(--color-border, #d5dbe1);
}

.archive-heading h1,
.archive-heading p,
.archive-heading dl,
.section-heading h2,
.section-heading p,
.games-section h2,
.games-section p {
  margin: 0;
}

.archive-heading h1 {
  font-size: clamp(2rem, 5vw, 3.5rem);
  letter-spacing: -0.04em;
  line-height: 1;
}

.archive-heading dl {
  display: flex;
  gap: 1px;
  overflow: hidden;
  border: 1px solid var(--color-border, #d5dbe1);
  border-radius: var(--radius-md, 0.5rem);
  background: var(--color-border, #d5dbe1);
}

.archive-heading dl div {
  min-width: 7rem;
  padding: 0.75rem 1rem;
  background: var(--color-surface, #fff);
}

.archive-heading dt {
  color: var(--color-text-muted, #607080);
  font-size: 0.61rem;
  font-weight: 750;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.archive-heading dd {
  margin: 0.2rem 0 0;
  font-size: 1.2rem;
  font-weight: 800;
  font-variant-numeric: tabular-nums;
}

.archive-filters {
  display: flex;
  align-items: end;
  gap: var(--space-sm, 0.5rem);
  padding: var(--space-md, 1rem);
  border: 1px solid var(--color-border, #d5dbe1);
  border-radius: var(--radius-md, 0.5rem);
  background: var(--color-surface, #fff);
}

.archive-filters label {
  display: grid;
  gap: 0.25rem;
  color: var(--color-text-muted, #607080);
  font-size: 0.65rem;
  font-weight: 700;
}

.archive-filters label:first-child { flex: 1; }
.archive-filters input,
.archive-filters select {
  min-height: 2.4rem;
  box-sizing: border-box;
  padding: 0.45rem 0.65rem;
  border: 1px solid var(--color-border, #d5dbe1);
  border-radius: var(--radius-sm, 0.35rem);
  background: var(--color-surface, #fff);
  color: var(--color-text, #17202a);
  font: inherit;
  font-size: 0.8rem;
}

.archive-filters input { width: 100%; }
.archive-filters input:focus,
.archive-filters select:focus { border-color: var(--color-accent, #2f78c4); outline: 2px solid color-mix(in srgb, var(--color-accent, #2f78c4) 20%, transparent); }

.archive-section {
  display: grid;
  gap: var(--space-md, 1rem);
}

.section-heading,
.games-section > header {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
}

.section-heading h2,
.games-section h2 { font-size: 1.05rem; }
.section-heading p,
.games-section header p { margin-block-start: 0.18rem; color: var(--color-text-muted, #607080); font-size: 0.72rem; }

.archive-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 21rem), 1fr));
  gap: var(--space-md, 1rem);
}

.games-section { overflow: hidden; padding: 0; }
.games-section > header { padding: var(--space-md, 1rem); border-block-end: 1px solid var(--color-border, #d5dbe1); }

@media (max-width: 46rem) {
  .archive-heading { align-items: stretch; flex-direction: column; }
  .archive-heading dl { align-self: stretch; }
  .archive-heading dl div { min-width: 0; flex: 1; }
}

@media (max-width: 34rem) {
  .archive-filters { align-items: stretch; flex-direction: column; }
}
</style>
