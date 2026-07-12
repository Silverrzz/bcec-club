<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { api } from '@/api/client'
import ContentState from '@/components/public/ContentState.vue'
import TournamentCard from '@/components/public/TournamentCard.vue'
import { errorMessage } from '@/components/public/format'
import type { TournamentSummary } from '@/components/public/types'

interface TournamentStats {
  total: number
  active: number
  live_games: number
  completion_percent: number
}

interface TournamentsResponse {
  tournaments: TournamentSummary[]
  tournament_stats: TournamentStats
}

const route = useRoute()
const router = useRouter()
const data = ref<TournamentsResponse | null>(null)
const loading = ref(true)
const loadError = ref('')
let controller: AbortController | null = null

const search = computed({
  get: () => queryValue(route.query.q),
  set: (value: string) => updateQuery({ q: value.trim() || undefined }),
})
const statusFilter = computed({
  get: () => queryValue(route.query.status) || 'all',
  set: (value: string) => updateQuery({ status: value === 'all' ? undefined : value }),
})

const publicTournaments = computed(() => (data.value?.tournaments || []).filter((item) => item.record.status !== 'draft'))
const filtered = computed(() => {
  const term = search.value.toLocaleLowerCase()
  return publicTournaments.value.filter((item) => {
    const status = item.record.status
    const statusMatches = statusFilter.value === 'all'
      || (statusFilter.value === 'active' && ['scheduled', 'running', 'paused'].includes(status))
      || (statusFilter.value === 'live' && (status === 'running' || (item.summary.live || 0) > 0))
      || (statusFilter.value === 'ended' && ['finished', 'aborted'].includes(status))
      || status === statusFilter.value
    if (!statusMatches) return false
    if (!term) return true
    return [item.record.name, item.format, item.time_control, ...(item.participant_names || [])]
      .some((value) => value?.toLocaleLowerCase().includes(term))
  })
})

onMounted(load)
onBeforeUnmount(() => controller?.abort())

async function load(): Promise<void> {
  controller?.abort()
  controller = new AbortController()
  loading.value = true
  loadError.value = ''
  try {
    data.value = await api.get<TournamentsResponse>('/api/tournaments', { signal: controller.signal })
  } catch (error) {
    if ((error as { name?: string })?.name !== 'AbortError') {
      loadError.value = errorMessage(error, 'Tournaments could not be loaded.')
    }
  } finally {
    loading.value = false
  }
}

function queryValue(value: unknown): string {
  return Array.isArray(value) ? String(value[0] || '') : typeof value === 'string' ? value : ''
}

function updateQuery(values: Record<string, string | undefined>): void {
  const query = { ...route.query }
  for (const [key, value] of Object.entries(values)) {
    if (value) query[key] = value
    else delete query[key]
  }
  void router.replace({ query })
}

function clearFilters(): void {
  updateQuery({ q: undefined, status: undefined })
}
</script>

<template>
  <div class="page-container tournaments-page">
    <ContentState v-if="loading" kind="loading" title="Loading tournaments" />
    <ContentState v-else-if="loadError" kind="error" :message="loadError" action-label="Try again" @action="load" />

    <template v-else-if="data">
      <section class="tournament-hero">
        <div>
          <h1>Tournaments</h1>
        </div>
        <dl aria-label="Tournament overview">
          <div><dt>Tournaments</dt><dd>{{ publicTournaments.length }}</dd></div>
          <div><dt>Active</dt><dd>{{ data.tournament_stats.active }}</dd></div>
          <div><dt>Live games</dt><dd>{{ data.tournament_stats.live_games }}</dd></div>
          <div><dt>Games complete</dt><dd>{{ data.tournament_stats.completion_percent }}%</dd></div>
        </dl>
      </section>

      <section v-if="publicTournaments.length" class="tournament-content" aria-labelledby="tournament-list-title">
        <div class="list-heading">
          <div>
            <h2 id="tournament-list-title">All tournaments</h2>
            <p>{{ filtered.length }} of {{ publicTournaments.length }} shown</p>
          </div>
          <form class="filters" role="search" @submit.prevent>
            <label>
              <span>Search</span>
              <input v-model="search" type="search" name="q" placeholder="Name or engine">
            </label>
            <label>
              <span>Status</span>
              <select v-model="statusFilter" name="status">
                <option value="all">All statuses</option>
                <option value="active">Active</option>
                <option value="live">Live</option>
                <option value="scheduled">Scheduled</option>
                <option value="ended">Ended</option>
              </select>
            </label>
          </form>
        </div>

        <div v-if="filtered.length" class="tournament-grid">
          <TournamentCard v-for="item in filtered" :key="item.record.id" :item="item" />
        </div>
        <ContentState
          v-else
          kind="empty"
          compact
          title="No matching tournaments"
          action-label="Clear filters"
          @action="clearFilters"
        />
      </section>

      <ContentState
        v-else
        kind="empty"
        title="No public tournaments yet"
      />
    </template>
  </div>
</template>

<style scoped>
.tournaments-page {
  display: grid;
  gap: clamp(1.5rem, 3vw, 2.5rem);
  padding-block: clamp(1.2rem, 2.5vw, 2.25rem) 3rem;
}

.tournament-hero {
  display: grid;
  grid-template-columns: minmax(18rem, 1fr) auto;
  align-items: end;
  gap: clamp(1.5rem, 5vw, 5rem);
  padding-block-end: var(--space-xl, 2rem);
  border-block-end: 1px solid var(--color-border, #d5dbe1);
}

.tournament-hero h1,
.tournament-hero p,
.tournament-hero dl,
.list-heading h2,
.list-heading p {
  margin: 0;
}

.tournament-hero h1 {
  font-size: clamp(2rem, 5vw, 3.75rem);
  letter-spacing: -0.04em;
  line-height: 1;
}

.tournament-hero dl {
  display: grid;
  grid-template-columns: repeat(4, minmax(5.2rem, 1fr));
  gap: 1px;
  overflow: hidden;
  border: 1px solid var(--color-border, #d5dbe1);
  border-radius: var(--radius-md, 0.5rem);
  background: var(--color-border, #d5dbe1);
}

.tournament-hero dl div {
  min-width: 5.4rem;
  padding: 0.75rem 0.9rem;
  background: var(--color-surface, #fff);
}

.tournament-hero dt {
  color: var(--color-text-muted, #607080);
  font-size: 0.61rem;
  font-weight: 750;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.tournament-hero dd {
  margin: 0.2rem 0 0;
  font-size: 1.2rem;
  font-weight: 780;
  font-variant-numeric: tabular-nums;
}

.tournament-content {
  display: grid;
  gap: var(--space-lg, 1.5rem);
}

.list-heading {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: var(--space-lg, 1.5rem);
}

.list-heading h2 {
  font-size: 1.1rem;
}

.list-heading p {
  margin-block-start: 0.2rem;
  color: var(--color-text-muted, #607080);
  font-size: 0.75rem;
}

.filters {
  display: flex;
  align-items: end;
  gap: var(--space-sm, 0.5rem);
}

.filters label {
  display: grid;
  gap: 0.25rem;
  color: var(--color-text-muted, #607080);
  font-size: 0.66rem;
  font-weight: 700;
}

.filters input,
.filters select {
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

.filters input {
  width: min(18rem, 34vw);
}

.filters input:focus,
.filters select:focus {
  border-color: var(--color-accent, #2f78c4);
  outline: 2px solid color-mix(in srgb, var(--color-accent, #2f78c4) 20%, transparent);
}

.tournament-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 25rem), 1fr));
  gap: var(--space-md, 1rem);
}

@media (max-width: 58rem) {
  .tournament-hero { grid-template-columns: 1fr; }
  .tournament-hero dl { width: 100%; }
}

@media (max-width: 42rem) {
  .tournament-hero dl { grid-template-columns: repeat(2, 1fr); }
  .list-heading { align-items: stretch; flex-direction: column; }
  .filters { align-items: stretch; }
  .filters label:first-child { flex: 1; }
  .filters input { width: 100%; }
}

@media (max-width: 26rem) {
  .filters { flex-direction: column; }
}
</style>
