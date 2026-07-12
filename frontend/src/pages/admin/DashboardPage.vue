<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '@/api/client'
import { useConfirm } from '@/composables/useConfirm'
import AdminEmptyState from '@/components/admin/AdminEmptyState.vue'
import AdminPageHeader from '@/components/admin/AdminPageHeader.vue'
import InlineFeedback from '@/components/admin/InlineFeedback.vue'
import StatusBadge from '@/components/admin/StatusBadge.vue'
import { errorText, formatDate, formatNumber, humanize } from '@/components/admin/format'
import type { Engine, Game, Tournament, WorkerRow } from '@/components/admin/types'

interface DashboardData {
  workers: WorkerRow[]
  live_games: Game[]
  engines: Engine[] | Record<string, Engine | string>
  db_stats: Record<string, number>
  running_tournaments: Tournament[]
  complete_tournaments: Tournament[]
  recent_games: Game[]
  system: { version: string; schema_version: number; services: Array<{ service: string; app_version: string; last_seen: string }> }
}

const data = ref<DashboardData | null>(null)
const loading = ref(true)
const error = ref('')
const commitPending = ref<number | null>(null)
const actionMessage = ref('')
const { confirm } = useConfirm()

const metrics = computed(() => [
  { label: 'Tournaments', value: data.value?.db_stats.tournaments, to: '/admin/tournaments', icon: 'tournament' },
  { label: 'Engines', value: data.value?.db_stats.engines, to: '/admin/engines', icon: 'engine' },
  { label: 'Categories', value: data.value?.db_stats.categories, to: '/admin/categories', icon: 'category' },
  { label: 'Opening suites', value: data.value?.db_stats.opening_suites, to: '/admin/openings', icon: 'opening' },
  { label: 'Workers', value: data.value?.db_stats.workers, to: '/admin/workers', icon: 'worker' },
])

function engineName(engineId: number): string {
  const engines = data.value?.engines
  if (Array.isArray(engines)) return engines.find((engine) => (engine.id ?? engine.engine_id) === engineId)?.name ?? `Engine ${engineId}`
  const value = engines?.[String(engineId)]
  return typeof value === 'string' ? value : value?.name ?? `Engine ${engineId}`
}

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    data.value = await api.get<DashboardData>('/api/admin/dashboard')
  } catch (cause) {
    error.value = errorText(cause)
  } finally {
    loading.value = false
  }
}

async function commit(tournament: Tournament): Promise<void> {
  const accepted = await confirm({
    title: 'Commit rating results?',
    message: `Apply ${tournament.name} to the category ratings? Applied rating results are permanent.`,
    confirmLabel: 'Commit ratings',
  })
  if (!accepted) return
  commitPending.value = tournament.id
  actionMessage.value = ''
  try {
    const response = await api.post<{ message: string }>(`/api/admin/tournaments/${tournament.id}/commit-results`, {})
    actionMessage.value = response.message
    await load()
  } catch (cause) {
    error.value = errorText(cause)
  } finally {
    commitPending.value = null
  }
}

onMounted(load)
</script>

<template>
  <div class="admin-page dashboard-page">
    <AdminPageHeader title="Dashboard">
      <template #actions><RouterLink class="button button--primary" to="/admin/tournaments/new">New tournament</RouterLink></template>
    </AdminPageHeader>
    <InlineFeedback :message="error" />
    <InlineFeedback :message="actionMessage" tone="info" />

    <div v-if="loading" class="panel loading-panel" role="status">Loading dashboard…</div>
    <template v-else-if="data">
      <section class="metric-grid" aria-label="Database totals">
        <RouterLink v-for="metric in metrics" :key="metric.label" class="metric-card" :to="metric.to">
          <span class="metric-card__icon" aria-hidden="true">
            <svg v-if="metric.icon === 'tournament'" viewBox="0 0 24 24"><path d="M7 4h10v4a5 5 0 0 1-10 0V4ZM9 17h6M12 13v4M5 6H3v1a4 4 0 0 0 4 4M19 6h2v1a4 4 0 0 1-4 4M7 20h10" /></svg>
            <svg v-else-if="metric.icon === 'engine'" viewBox="0 0 24 24"><path d="M7 7h10v10H7zM9 4v3m3-3v3m3-3v3M9 17v3m3-3v3m3-3v3M4 9h3m-3 3h3m-3 3h3m10-6h3m-3 3h3m-3 3h3" /></svg>
            <svg v-else-if="metric.icon === 'category'" viewBox="0 0 24 24"><path d="M4 6h16M4 12h10M4 18h7" /></svg>
            <svg v-else-if="metric.icon === 'opening'" viewBox="0 0 24 24"><path d="M5 4h11a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3V4Zm3 16a3 3 0 0 1 0-6h11M9 8h6" /></svg>
            <svg v-else viewBox="0 0 24 24"><rect x="4" y="6" width="16" height="12" rx="2" /><path d="M8 10h.01M12 10h.01M16 10h.01M8 14h8" /></svg>
          </span>
          <span><strong>{{ formatNumber(metric.value) }}</strong><small>{{ metric.label }}</small></span>
          <svg class="metric-card__arrow" aria-hidden="true" viewBox="0 0 24 24"><path d="m9 6 6 6-6 6" /></svg>
        </RouterLink>
      </section>

      <section class="panel system-strip"><div><span>Release</span><code>{{ data.system.version }}</code></div><div><span>Schema</span><strong>v{{ data.system.schema_version }}</strong></div><div v-for="service in data.system.services" :key="service.service"><span>{{ humanize(service.service) }}</span><strong>{{ formatDate(service.last_seen) }}</strong></div></section>

      <div class="dashboard-grid">
        <section class="panel dashboard-panel dashboard-panel--wide">
          <div class="panel-heading"><div><h2>Active tournaments</h2></div><RouterLink to="/admin/tournaments">View all</RouterLink></div>
          <div v-if="data.running_tournaments.length" class="compact-list">
            <RouterLink v-for="tournament in data.running_tournaments" :key="tournament.id" :to="`/admin/tournaments/${tournament.id}`" class="compact-row">
              <span class="compact-row__primary"><strong>{{ tournament.name }}</strong><small>Round {{ tournament.current_round || 1 }} · {{ tournament.config.participants.length }} engines</small></span>
              <StatusBadge :status="tournament.status" />
              <svg aria-hidden="true" viewBox="0 0 24 24"><path d="m9 6 6 6-6 6" /></svg>
            </RouterLink>
          </div>
          <AdminEmptyState v-else title="Nothing is running">
            <RouterLink class="button button--secondary button--small" to="/admin/tournaments">Open tournaments</RouterLink>
          </AdminEmptyState>
        </section>

        <section class="panel dashboard-panel">
          <div class="panel-heading"><div><h2>Workers</h2></div><RouterLink to="/admin/workers">Manage</RouterLink></div>
          <div v-if="data.workers.length" class="worker-list">
            <RouterLink v-for="row in data.workers.slice(0, 6)" :key="row.worker.id" :to="`/admin/workers/${row.worker.id}`">
              <span class="worker-avatar" aria-hidden="true">{{ row.worker.label.slice(0, 2).toUpperCase() }}</span>
              <span><strong>{{ row.worker.label }}</strong><small>{{ formatDate(row.worker.last_seen) }}</small></span>
              <StatusBadge :status="row.status" />
            </RouterLink>
          </div>
          <AdminEmptyState v-else title="No workers registered" />
        </section>

        <section class="panel dashboard-panel">
          <div class="panel-heading"><div><h2>Live games</h2></div></div>
          <div v-if="data.live_games.length" class="game-list">
            <RouterLink v-for="game in data.live_games.slice(0, 6)" :key="game.id" :to="`/tournaments/${game.tournament_id}?game_id=${game.id}`">
              <span><strong>{{ engineName(game.white_engine_id) }}</strong><small>White</small></span>
              <em>vs</em>
              <span class="game-list__black"><strong>{{ engineName(game.black_engine_id) }}</strong><small>Black</small></span>
            </RouterLink>
          </div>
          <AdminEmptyState v-else title="No live games" />
        </section>

        <section v-if="data.complete_tournaments.length" class="panel dashboard-panel dashboard-panel--wide">
          <div class="panel-heading"><div><h2>Ratings awaiting commit</h2></div></div>
          <div class="commit-list">
            <div v-for="tournament in data.complete_tournaments" :key="tournament.id">
              <span><RouterLink :to="`/admin/tournaments/${tournament.id}`">{{ tournament.name }}</RouterLink><small>{{ tournament.config.participants.length }} participants</small></span>
              <button class="button button--primary button--small" type="button" :disabled="commitPending === tournament.id" @click="commit(tournament)">{{ commitPending === tournament.id ? 'Requesting…' : 'Commit results' }}</button>
            </div>
          </div>
        </section>

        <section class="panel dashboard-panel dashboard-panel--wide">
          <div class="panel-heading"><div><h2>Recent results</h2></div></div>
          <div v-if="data.recent_games.length" class="results-list">
            <RouterLink v-for="game in data.recent_games.slice(0, 8)" :key="game.id" :to="`/tournaments/${game.tournament_id}?game_id=${game.id}`">
              <span>{{ engineName(game.white_engine_id) }}</span><strong>{{ game.result ?? '½-½' }}</strong><span>{{ engineName(game.black_engine_id) }}</span><small>{{ formatDate(game.finished_at) }}</small>
            </RouterLink>
          </div>
          <AdminEmptyState v-else title="No finished games" />
        </section>
      </div>
    </template>
  </div>
</template>

<style scoped>
.dashboard-page { display: grid; gap: 1rem; }
.loading-panel { color: var(--color-text-muted, #64748b); min-height: 12rem; padding: 2rem; }
.metric-grid { display: grid; gap: .75rem; grid-template-columns: repeat(5, minmax(0, 1fr)); }
.system-strip { display: flex; flex-wrap: wrap; gap: 1.2rem; padding: .75rem 1rem; }.system-strip > div { display: grid; gap: .15rem; }.system-strip span { color: var(--color-text-muted, #64748b); font-size: .62rem; font-weight: 700; letter-spacing: .04em; text-transform: uppercase; }.system-strip strong, .system-strip code { font-size: .72rem; }
.metric-card { align-items: center; background: var(--color-surface, #fff); border: 1px solid var(--color-border, #d9e0ea); border-radius: var(--radius-lg, .8rem); color: inherit; display: flex; gap: .7rem; min-width: 0; padding: .8rem; text-decoration: none; transition: border-color 120ms ease, transform 120ms ease; }
.metric-card:hover { border-color: var(--color-accent, #315fcc); transform: translateY(-1px); }
.metric-card__icon { align-items: center; background: var(--color-surface-subtle, #f1f5f9); border-radius: .5rem; color: var(--color-accent, #315fcc); display: flex; flex: 0 0 auto; height: 2rem; justify-content: center; width: 2rem; }
.metric-card__icon svg, .metric-card__arrow, .compact-row > svg { fill: none; height: 1rem; stroke: currentColor; stroke-linecap: round; stroke-linejoin: round; stroke-width: 1.7; width: 1rem; }
.metric-card > span:nth-child(2) { display: grid; min-width: 0; }
.metric-card strong { font-size: 1.05rem; }
.metric-card small { color: var(--color-text-muted, #64748b); font-size: .68rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.metric-card__arrow { color: var(--color-text-muted, #64748b); margin-left: auto; }
.dashboard-grid { display: grid; gap: .9rem; grid-template-columns: repeat(2, minmax(0, 1fr)); }
.dashboard-panel { min-width: 0; overflow: hidden; padding: 0; }
.dashboard-panel--wide { grid-column: 1 / -1; }
.panel-heading { align-items: flex-start; border-bottom: 1px solid var(--color-border, #d9e0ea); display: flex; gap: 1rem; justify-content: space-between; padding: .9rem 1rem; }
.panel-heading h2 { font-size: .9rem; margin: 0; }
.panel-heading p { color: var(--color-text-muted, #64748b); font-size: .72rem; margin: .2rem 0 0; }
.panel-heading > a { font-size: .75rem; }
.compact-list, .worker-list, .game-list, .commit-list, .results-list { display: grid; }
.compact-row { align-items: center; border-bottom: 1px solid var(--color-border, #d9e0ea); color: inherit; display: grid; gap: .8rem; grid-template-columns: minmax(0, 1fr) auto auto; padding: .75rem 1rem; text-decoration: none; }
.compact-row:last-child { border-bottom: 0; }
.compact-row:hover { background: var(--color-surface-subtle, #f6f8fb); }
.compact-row__primary, .worker-list a > span:nth-child(2), .commit-list div > span { display: grid; min-width: 0; }
.compact-row strong, .worker-list strong { font-size: .8rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.compact-row small, .worker-list small, .commit-list small { color: var(--color-text-muted, #64748b); font-size: .68rem; margin-top: .15rem; }
.worker-list a { align-items: center; border-bottom: 1px solid var(--color-border, #d9e0ea); color: inherit; display: grid; gap: .65rem; grid-template-columns: auto minmax(0, 1fr) auto; padding: .7rem 1rem; text-decoration: none; }
.worker-list a:last-child { border-bottom: 0; }
.worker-avatar { align-items: center; background: var(--color-surface-subtle, #f1f5f9); border-radius: 50%; color: var(--color-text-muted, #64748b); display: flex; font-size: .62rem; font-weight: 750; height: 1.8rem; justify-content: center; width: 1.8rem; }
.game-list a { align-items: center; border-bottom: 1px solid var(--color-border, #d9e0ea); color: inherit; display: grid; gap: .5rem; grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr); padding: .75rem 1rem; text-decoration: none; }
.game-list a:last-child { border-bottom: 0; }
.game-list a > span { display: grid; min-width: 0; }
.game-list strong { font-size: .78rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.game-list small { color: var(--color-text-muted, #64748b); font-size: .65rem; }
.game-list em { color: var(--color-text-muted, #64748b); font-size: .65rem; font-style: normal; }
.game-list__black { text-align: right; }
.commit-list > div { align-items: center; border-bottom: 1px solid var(--color-border, #d9e0ea); display: flex; gap: .8rem; justify-content: space-between; padding: .75rem 1rem; }
.commit-list > div:last-child { border-bottom: 0; }
.commit-list a { font-size: .8rem; font-weight: 650; }
.results-list a { align-items: center; border-bottom: 1px solid var(--color-border, #d9e0ea); color: inherit; display: grid; font-size: .78rem; gap: .65rem; grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr) auto; padding: .7rem 1rem; text-decoration: none; }
.results-list a:last-child { border-bottom: 0; }
.results-list a span:nth-child(3) { text-align: right; }
.results-list strong { background: var(--color-surface-subtle, #f1f5f9); border-radius: .3rem; padding: .25rem .4rem; }
.results-list small { color: var(--color-text-muted, #64748b); font-size: .68rem; }
@media (max-width: 68rem) { .metric-grid { grid-template-columns: repeat(3, 1fr); } }
@media (max-width: 48rem) { .dashboard-grid { grid-template-columns: 1fr; } .dashboard-panel--wide { grid-column: auto; } .metric-grid { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 32rem) { .metric-grid { grid-template-columns: 1fr; } .results-list a { grid-template-columns: 1fr auto 1fr; } .results-list small { display: none; } }
</style>
