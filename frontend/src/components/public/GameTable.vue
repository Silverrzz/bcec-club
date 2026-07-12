<script setup lang="ts">
import type { GameRecord } from './types'
import { engineName, resultLabel, shortResult, tournamentName } from './format'
import StatusPill from './StatusPill.vue'

withDefaults(defineProps<{
  games: GameRecord[]
  engines?: Record<string, string>
  tournamentNames?: Record<string, string>
  showTournament?: boolean
  showRound?: boolean
  caption?: string
}>(), {
  engines: () => ({}),
  tournamentNames: () => ({}),
  showTournament: false,
  showRound: true,
  caption: 'Chess games',
})

function gameUrl(game: GameRecord): string {
  return `/tournaments/${game.tournament_id}?game_id=${game.id}`
}
</script>

<template>
  <div class="game-table-wrap">
    <table class="game-table">
      <caption class="sr-only">{{ caption }}</caption>
      <thead>
        <tr>
          <th v-if="showTournament">Tournament</th>
          <th v-if="showRound" class="column-small">Round</th>
          <th>White</th>
          <th>Black</th>
          <th>Status</th>
          <th>Result</th>
          <th class="column-action"><span class="sr-only">Open game</span></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="game in games" :key="game.id">
          <td v-if="showTournament" data-label="Tournament">
            <RouterLink :to="gameUrl(game)">{{ tournamentName(tournamentNames, game.tournament_id) }}</RouterLink>
          </td>
          <td v-if="showRound" class="column-small" data-label="Round">{{ game.round ?? '-' }}</td>
          <td data-label="White">
            <RouterLink :to="`/engines/${game.white_engine_id}`">
              {{ engineName(engines, game.white_engine_id, game.white_name) }}
            </RouterLink>
          </td>
          <td data-label="Black">
            <RouterLink :to="`/engines/${game.black_engine_id}`">
              {{ engineName(engines, game.black_engine_id, game.black_name) }}
            </RouterLink>
          </td>
          <td data-label="Status"><StatusPill :status="game.status" /></td>
          <td class="column-result" data-label="Result" :title="resultLabel(game.result)">{{ shortResult(game.result) }}</td>
          <td class="column-action">
            <RouterLink class="open-game" :to="gameUrl(game)" :aria-label="`Open game ${engineName(engines, game.white_engine_id, game.white_name)} versus ${engineName(engines, game.black_engine_id, game.black_name)}`">
              View
            </RouterLink>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.game-table-wrap {
  width: 100%;
  overflow-x: auto;
  scrollbar-gutter: stable;
}

.game-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.84rem;
}

.game-table th,
.game-table td {
  padding: 0.7rem 0.75rem;
  border-block-end: 1px solid var(--color-border, #d5dbe1);
  text-align: start;
  vertical-align: middle;
}

.game-table th {
  color: var(--color-text-muted, #607080);
  font-size: 0.67rem;
  font-weight: 750;
  letter-spacing: 0.045em;
  text-transform: uppercase;
  white-space: nowrap;
}

.game-table tbody tr:last-child td {
  border-block-end: 0;
}

.game-table tbody tr:hover {
  background: color-mix(in srgb, var(--color-accent, #2f78c4) 4.5%, transparent);
}

.game-table a {
  color: inherit;
  font-weight: 600;
  text-decoration: none;
}

.game-table a:hover {
  color: var(--color-accent, #2f78c4);
  text-decoration: underline;
  text-underline-offset: 0.16em;
}

.column-small {
  width: 4.5rem;
  font-variant-numeric: tabular-nums;
}

.column-result {
  width: 5rem;
  font-weight: 750;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.column-action {
  width: 4.5rem;
  text-align: end !important;
}

.open-game {
  color: var(--color-accent, #2f78c4) !important;
  font-size: 0.77rem;
}

@media (max-width: 42rem) {
  .game-table thead {
    display: none;
  }

  .game-table,
  .game-table tbody,
  .game-table tr,
  .game-table td {
    display: block;
    width: 100%;
  }

  .game-table tbody {
    display: grid;
    gap: var(--space-sm, 0.5rem);
    padding: var(--space-sm, 0.5rem);
  }

  .game-table tr {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    padding: 0.55rem 0.65rem;
    border: 1px solid var(--color-border, #d5dbe1);
    border-radius: var(--radius-sm, 0.35rem);
  }

  .game-table td {
    grid-column: 1;
    padding: 0.22rem 0;
    border: 0;
  }

  .game-table td::before {
    display: inline-block;
    width: 5.3rem;
    color: var(--color-text-muted, #607080);
    content: attr(data-label);
    font-size: 0.68rem;
    font-weight: 700;
  }

  .game-table .column-action {
    grid-column: 2;
    grid-row: 1 / span 6;
    align-self: center;
    width: auto;
    padding-inline-start: 0.75rem;
  }

  .game-table .column-action::before {
    display: none;
  }
}
</style>
