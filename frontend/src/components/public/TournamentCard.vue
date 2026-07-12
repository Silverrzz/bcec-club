<script setup lang="ts">
import { computed } from 'vue'

import type { TournamentSummary } from './types'
import ProgressBar from './ProgressBar.vue'
import StatusPill from './StatusPill.vue'

const props = defineProps<{
  item: TournamentSummary
  compact?: boolean
}>()

const finished = computed(() => props.item.summary.finished || 0)
const total = computed(() => props.item.summary.total || 0)
const progress = computed(() => props.item.progress_percent ?? (total.value ? Math.round(finished.value / total.value * 100) : 0))
const participants = computed(() => props.item.participant_preview || props.item.participant_names?.slice(0, 6) || [])
const overflow = computed(() => props.item.participant_overflow ?? Math.max(0, (props.item.participant_count || participants.value.length) - participants.value.length))
</script>

<template>
  <article class="tournament-card" :class="{ 'tournament-card--compact': compact }">
    <header class="tournament-card__header">
      <div class="tournament-card__heading">
        <h2><RouterLink :to="`/tournaments/${item.record.id}`">{{ item.record.name }}</RouterLink></h2>
        <p>{{ item.format || 'Tournament' }}<span aria-hidden="true"> / </span>{{ item.time_control || 'Time control not set' }}</p>
      </div>
      <StatusPill :status="item.record.status" />
    </header>

    <dl class="tournament-card__facts">
      <div>
        <dt>Engines</dt>
        <dd>{{ item.participant_count ?? item.participant_names?.length ?? 0 }}</dd>
      </div>
      <div>
        <dt>Games</dt>
        <dd>{{ finished }} / {{ total }}</dd>
      </div>
      <div>
        <dt>Live</dt>
        <dd>{{ item.summary.live || 0 }}</dd>
      </div>
      <div v-if="item.record.current_round">
        <dt>Round</dt>
        <dd>{{ item.record.current_round }}</dd>
      </div>
    </dl>

    <div v-if="participants.length" class="tournament-card__participants" aria-label="Participants">
      <span v-for="name in participants" :key="name">{{ name }}</span>
      <span v-if="overflow">+{{ overflow }} more</span>
    </div>

    <ProgressBar v-if="total" :value="progress" :label="`${finished} of ${total} games finished`" />
    <p v-else class="tournament-card__empty">No games scheduled yet.</p>

    <RouterLink class="tournament-card__open" :to="`/tournaments/${item.record.id}`" :aria-label="`Open ${item.record.name}`">
      Open tournament
    </RouterLink>
  </article>
</template>

<style scoped>
.tournament-card {
  position: relative;
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: var(--space-md, 1rem);
  padding: var(--space-lg, 1.5rem);
  border: 1px solid var(--color-border, #d5dbe1);
  border-radius: var(--radius-lg, 0.75rem);
  background: var(--color-surface, #fff);
  box-shadow: 0 0.3rem 1.4rem color-mix(in srgb, #000 4%, transparent);
  transition: border-color 140ms ease, transform 140ms ease, box-shadow 140ms ease;
}

.tournament-card:hover {
  border-color: color-mix(in srgb, var(--color-accent, #2f78c4) 50%, var(--color-border, #d5dbe1));
  box-shadow: 0 0.65rem 1.8rem color-mix(in srgb, #000 8%, transparent);
  transform: translateY(-1px);
}

.tournament-card__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-md, 1rem);
}

.tournament-card__heading {
  min-width: 0;
}

.tournament-card h2,
.tournament-card p,
.tournament-card dl {
  margin: 0;
}

.tournament-card h2 {
  font-size: 1.05rem;
  line-height: 1.25;
}

.tournament-card h2 a {
  color: var(--color-text, #17202a);
  text-decoration: none;
}

.tournament-card h2 a:hover {
  color: var(--color-accent, #2f78c4);
  text-decoration: underline;
  text-underline-offset: 0.16em;
}

.tournament-card__heading p {
  margin-block-start: 0.25rem;
  color: var(--color-text-muted, #607080);
  font-size: 0.78rem;
}

.tournament-card__facts {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-lg, 1.5rem);
}

.tournament-card__facts div {
  min-width: 3.5rem;
}

.tournament-card__facts dt {
  color: var(--color-text-muted, #607080);
  font-size: 0.65rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.tournament-card__facts dd {
  margin: 0.16rem 0 0;
  font-size: 1rem;
  font-weight: 760;
  font-variant-numeric: tabular-nums;
}

.tournament-card__participants {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
}

.tournament-card__participants span {
  max-width: 11rem;
  overflow: hidden;
  padding: 0.27rem 0.48rem;
  border-radius: 999px;
  background: color-mix(in srgb, var(--color-text, #17202a) 5.5%, transparent);
  color: var(--color-text-muted, #607080);
  font-size: 0.68rem;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tournament-card__empty {
  color: var(--color-text-muted, #607080);
  font-size: 0.78rem;
}

.tournament-card__open {
  align-self: flex-start;
  margin-block-start: auto;
  color: var(--color-accent, #2f78c4);
  font-size: 0.78rem;
  font-weight: 700;
  text-decoration: none;
}

.tournament-card__open:hover {
  text-decoration: underline;
  text-underline-offset: 0.18em;
}

.tournament-card--compact {
  gap: var(--space-sm, 0.5rem);
  padding: var(--space-md, 1rem);
}

.tournament-card--compact .tournament-card__participants,
.tournament-card--compact .tournament-card__facts div:nth-child(n + 3) {
  display: none;
}

@media (prefers-reduced-motion: reduce) {
  .tournament-card { transition: none; }
}
</style>
