<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { api } from '@/api/client'
import ChessBoard from '@/components/chess/ChessBoard.vue'
import ContentState from '@/components/public/ContentState.vue'
import GameTable from '@/components/public/GameTable.vue'
import ProgressBar from '@/components/public/ProgressBar.vue'
import StatusPill from '@/components/public/StatusPill.vue'
import { errorMessage } from '@/components/public/format'
import type { GameRecord, MoveRecord, OpeningRecord, TournamentSummary } from '@/components/public/types'

interface GamePreview {
  game: GameRecord
  moves: MoveRecord[]
  opening?: OpeningRecord | null
  last_move?: MoveRecord | null
  white_name: string
  black_name: string
}

interface RunningTournamentCard {
  tournament: TournamentSummary
  preview?: GamePreview | null
}

interface UpcomingRow {
  href: string
  tournament: string
  round: string
  white: string
  black: string
  status: string
}

interface HomeResponse {
  running_tournaments: RunningTournamentCard[]
  upcoming_rows: UpcomingRow[]
  recent_games: GameRecord[]
  engines: Record<string, string>
  tournament_names: Record<string, string>
}

const data = ref<HomeResponse | null>(null)
const loading = ref(true)
const loadError = ref('')
let controller: AbortController | null = null

const activeCount = computed(() => data.value?.running_tournaments.length || 0)

onMounted(load)
onBeforeUnmount(() => controller?.abort())

async function load(): Promise<void> {
  controller?.abort()
  controller = new AbortController()
  loading.value = true
  loadError.value = ''
  try {
    data.value = await api.get<HomeResponse>('/api/home', { signal: controller.signal })
  } catch (error) {
    if ((error as { name?: string })?.name !== 'AbortError') {
      loadError.value = errorMessage(error, 'The live overview could not be loaded.')
    }
  } finally {
    loading.value = false
  }
}

function progress(item: TournamentSummary): number {
  if (item.progress_percent != null) return item.progress_percent
  return item.summary.total ? Math.round((item.summary.finished || 0) / item.summary.total * 100) : 0
}
</script>

<template>
  <div class="page-container home-page">
    <ContentState v-if="loading" kind="loading" title="Loading tournament activity" />
    <ContentState v-else-if="loadError" kind="error" :message="loadError" action-label="Try again" @action="load" />

    <template v-else-if="data">
      <section class="home-heading">
        <div>
          <h1>COPE Chess</h1>
        </div>
        <div class="live-summary" :class="{ 'live-summary--active': activeCount }" role="status">
          <span aria-hidden="true"></span>
          <strong>{{ activeCount }}</strong>
          <p>{{ activeCount === 1 ? 'tournament running' : 'tournaments running' }}</p>
        </div>
      </section>

      <section class="section-stack" aria-labelledby="running-tournaments-title">
        <div class="section-heading">
          <div>
            <h2 id="running-tournaments-title">Running tournaments</h2>
          </div>
          <RouterLink to="/tournaments">All tournaments</RouterLink>
        </div>

        <div v-if="data.running_tournaments.length" class="live-grid">
          <article v-for="item in data.running_tournaments" :key="item.tournament.record.id" class="live-card" :class="{ 'live-card--without-preview': !item.preview }">
            <div v-if="item.preview" class="live-card__board" aria-hidden="true">
              <ChessBoard
                :fen="item.preview.opening?.fen || 'startpos'"
                :moves="item.preview.moves.map((move) => move.uci)"
                :controls="false"
                :coordinates="false"
                compact
                :label="`${item.preview.white_name} versus ${item.preview.black_name} position`"
              />
            </div>
            <div class="live-card__body">
              <header>
                <div>
                  <h3><RouterLink :to="`/tournaments/${item.tournament.record.id}`">{{ item.tournament.record.name }}</RouterLink></h3>
                  <p>{{ item.tournament.format || 'Tournament' }} / {{ item.tournament.time_control || 'Time control not set' }}</p>
                </div>
                <StatusPill :status="item.tournament.record.status" />
              </header>

              <div v-if="item.preview" class="live-card__preview-heading">
                <span>Live game</span>
                <RouterLink :to="`/tournaments/${item.tournament.record.id}?game_id=${item.preview.game.id}`">
                  {{ item.preview.white_name }} <span>vs</span> {{ item.preview.black_name }}
                </RouterLink>
                <small>Round {{ item.preview.game.round ?? '-' }}</small>
              </div>
              <p v-else class="live-card__meta">Waiting for the next game to start.</p>

              <ProgressBar :value="progress(item.tournament)" :label="`${item.tournament.summary.finished || 0} of ${item.tournament.summary.total} tournament games finished`" />
              <dl class="live-card__facts">
                <div><dt>Games</dt><dd>{{ item.tournament.summary.finished || 0 }} / {{ item.tournament.summary.total }}</dd></div>
                <div><dt>Live</dt><dd>{{ item.tournament.summary.live || 0 }}</dd></div>
                <div v-if="item.tournament.record.current_round"><dt>Round</dt><dd>{{ item.tournament.record.current_round }}</dd></div>
                <div v-if="item.preview"><dt>Preview plies</dt><dd>{{ item.preview.moves.length }}</dd></div>
                <div v-if="item.preview"><dt>Last move</dt><dd>{{ item.preview.last_move?.san || '-' }}</dd></div>
              </dl>
              <RouterLink v-if="item.preview" class="watch-link" :to="`/tournaments/${item.tournament.record.id}?game_id=${item.preview.game.id}`">Watch game</RouterLink>
              <RouterLink v-else class="watch-link" :to="`/tournaments/${item.tournament.record.id}`">Open tournament</RouterLink>
            </div>
          </article>
        </div>
        <ContentState v-else kind="empty" compact title="No running tournaments" />
      </section>

      <section class="home-tables">
        <section class="panel data-panel" aria-labelledby="upcoming-title">
          <div class="data-panel__header">
            <div>
              <h2 id="upcoming-title">Upcoming</h2>
            </div>
          </div>
          <div v-if="data.upcoming_rows.length" class="upcoming-list">
            <RouterLink v-for="row in data.upcoming_rows" :key="`${row.href}-${row.tournament}-${row.round}`" :to="row.href" class="upcoming-row">
              <div>
                <strong>{{ row.tournament }}</strong>
                <span>Round {{ row.round }}</span>
              </div>
              <p>{{ row.white }} <span aria-hidden="true">vs</span><span class="sr-only">versus</span> {{ row.black }}</p>
              <StatusPill :status="row.status" />
              <span class="row-arrow" aria-hidden="true">&gt;</span>
            </RouterLink>
          </div>
          <p v-else class="panel-empty">No upcoming games.</p>
        </section>

        <section class="panel data-panel" aria-labelledby="recent-title">
          <div class="data-panel__header">
            <div>
              <h2 id="recent-title">Recent results</h2>
            </div>
            <RouterLink to="/archive">Archive</RouterLink>
          </div>
          <GameTable
            v-if="data.recent_games.length"
            :games="data.recent_games"
            :engines="data.engines"
            :tournament-names="data.tournament_names"
            :show-tournament="true"
            :show-round="true"
            caption="Recent tournament results"
          />
          <p v-else class="panel-empty">No recent results.</p>
        </section>
      </section>
    </template>
  </div>
</template>

<style scoped>
.home-page {
  display: grid;
  gap: clamp(1.5rem, 3vw, 2.5rem);
  padding-block: clamp(1.2rem, 2.5vw, 2.25rem) 3rem;
}

.home-heading {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--space-xl, 2rem);
  padding-block-end: var(--space-lg, 1.5rem);
  border-block-end: 1px solid var(--color-border, #d5dbe1);
}

.home-heading h1,
.home-heading p,
.section-heading h2,
.section-heading p,
.data-panel h2,
.data-panel p {
  margin: 0;
}

.home-heading h1 {
  font-size: clamp(2rem, 5vw, 4rem);
  letter-spacing: -0.045em;
  line-height: 0.98;
}

.live-summary {
  display: grid;
  grid-template-columns: auto auto;
  align-items: center;
  gap: 0 0.5rem;
  min-width: 9.5rem;
  padding: 0.8rem 1rem;
  border: 1px solid var(--color-border, #d5dbe1);
  border-radius: var(--radius-md, 0.5rem);
  background: var(--color-surface, #fff);
}

.live-summary > span {
  width: 0.58rem;
  height: 0.58rem;
  border-radius: 50%;
  background: var(--color-text-muted, #607080);
}

.live-summary--active > span {
  background: var(--color-success, #16794b);
  box-shadow: 0 0 0 0.24rem color-mix(in srgb, var(--color-success, #16794b) 14%, transparent);
}

.live-summary strong {
  font-size: 1.25rem;
  font-variant-numeric: tabular-nums;
}

.live-summary p {
  grid-column: 1 / -1;
  margin-block-start: 0.1rem;
  color: var(--color-text-muted, #607080);
  font-size: 0.7rem;
}

.section-heading,
.data-panel__header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--space-md, 1rem);
}

.section-heading h2,
.data-panel h2 {
  font-size: 1.05rem;
}

.section-heading p,
.data-panel__header p {
  margin-block-start: 0.2rem;
  color: var(--color-text-muted, #607080);
  font-size: 0.76rem;
}

.section-heading a,
.data-panel__header a {
  color: var(--color-accent, #2f78c4);
  font-size: 0.78rem;
  font-weight: 700;
  text-decoration: none;
  white-space: nowrap;
}

.live-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 31rem), 1fr));
  gap: var(--space-md, 1rem);
}

.live-card {
  display: grid;
  grid-template-columns: minmax(9rem, 0.72fr) minmax(0, 1.4fr);
  gap: var(--space-md, 1rem);
  padding: var(--space-md, 1rem);
  border: 1px solid var(--color-border, #d5dbe1);
  border-radius: var(--radius-lg, 0.75rem);
  background: var(--color-surface, #fff);
}

.live-card__board {
  align-self: center;
  min-width: 0;
}

.live-card__body {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 0.75rem;
}

.live-card--without-preview {
  grid-template-columns: 1fr;
}

.live-card header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.75rem;
}

.live-card h3,
.live-card p,
.live-card dl {
  margin: 0;
}

.live-card h3 {
  font-size: 0.92rem;
  line-height: 1.3;
}

.live-card h3 a,
.live-card header p a {
  color: inherit;
  text-decoration: none;
}

.live-card h3 a:hover,
.live-card header p a:hover {
  color: var(--color-accent, #2f78c4);
  text-decoration: underline;
  text-underline-offset: 0.16em;
}

.live-card h3 span,
.live-card header p,
.live-card__meta {
  color: var(--color-text-muted, #607080);
  font-size: 0.7rem;
  font-weight: 500;
}

.live-card__preview-heading {
  display: grid;
  gap: 0.14rem;
}

.live-card__preview-heading > span,
.live-card__preview-heading small {
  color: var(--color-text-muted, #607080);
  font-size: 0.64rem;
}

.live-card__preview-heading > span {
  font-weight: 750;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.live-card__preview-heading a {
  color: inherit;
  font-size: 0.82rem;
  font-weight: 750;
  text-decoration: none;
}

.live-card__preview-heading a:hover {
  color: var(--color-accent, #2f78c4);
  text-decoration: underline;
  text-underline-offset: 0.16em;
}

.live-card__preview-heading a span {
  color: var(--color-text-muted, #607080);
  font-weight: 500;
}

.live-card dl {
  display: flex;
  gap: 1.25rem;
}

.live-card dt {
  color: var(--color-text-muted, #607080);
  font-size: 0.61rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.live-card dd {
  margin: 0.12rem 0 0;
  font-size: 0.8rem;
  font-weight: 700;
}

.watch-link {
  align-self: flex-start;
  margin-block-start: auto;
  color: var(--color-accent, #2f78c4);
  font-size: 0.76rem;
  font-weight: 750;
  text-decoration: none;
}

.home-tables {
  display: grid;
  grid-template-columns: minmax(20rem, 0.75fr) minmax(30rem, 1.25fr);
  gap: var(--space-md, 1rem);
  align-items: start;
}

.data-panel {
  overflow: hidden;
  padding: 0;
}

.data-panel__header {
  padding: var(--space-md, 1rem);
  border-block-end: 1px solid var(--color-border, #d5dbe1);
}

.upcoming-list {
  display: grid;
}

.upcoming-row {
  display: grid;
  grid-template-columns: minmax(8rem, 0.75fr) minmax(10rem, 1.25fr) auto auto;
  align-items: center;
  gap: 0.65rem;
  padding: 0.72rem 1rem;
  border-block-end: 1px solid var(--color-border, #d5dbe1);
  color: inherit;
  font-size: 0.76rem;
  text-decoration: none;
}

.upcoming-row:last-child {
  border-block-end: 0;
}

.upcoming-row:hover {
  background: color-mix(in srgb, var(--color-accent, #2f78c4) 5%, transparent);
}

.upcoming-row > div {
  display: flex;
  min-width: 0;
  flex-direction: column;
}

.upcoming-row strong,
.upcoming-row p {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.upcoming-row > div span,
.row-arrow {
  color: var(--color-text-muted, #607080);
  font-size: 0.66rem;
}

.row-arrow {
  font-size: 1rem;
}

.panel-empty {
  padding: 2.5rem 1rem;
  color: var(--color-text-muted, #607080);
  font-size: 0.82rem;
  text-align: center;
}

@media (max-width: 68rem) {
  .home-tables { grid-template-columns: 1fr; }
}

@media (max-width: 42rem) {
  .home-heading { align-items: stretch; flex-direction: column; }
  .live-summary { align-self: flex-start; }
  .live-card { grid-template-columns: 7rem minmax(0, 1fr); }
  .live-card dl { flex-wrap: wrap; }
  .upcoming-row { grid-template-columns: minmax(0, 1fr) auto; }
  .upcoming-row > p { grid-column: 1; }
  .upcoming-row :deep(.status-pill) { grid-column: 2; grid-row: 1; }
  .row-arrow { grid-column: 2; grid-row: 2; }
}

@media (max-width: 30rem) {
  .live-card { grid-template-columns: 1fr; }
  .live-card__board { width: min(11rem, 100%); }
}
</style>
