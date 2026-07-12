<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import AdminEmptyState from './AdminEmptyState.vue'
import EngineOptionsEditor from './EngineOptionsEditor.vue'
import InlineFeedback from './InlineFeedback.vue'
import ParticipantPicker from './ParticipantPicker.vue'
import TournamentSettingsEditor from './TournamentSettingsEditor.vue'
import { cloneData, configFromSeed, estimateGames, formatTimeControl, humanize, normalizeSettings, settingsFromFlat } from './format'
import type { FormSeed, TournamentConfig, TournamentSettings } from './types'

const props = withDefaults(defineProps<{
  seed: FormSeed
  pending?: boolean
  submitLabel?: string
}>(), {
  pending: false,
  submitLabel: 'Save tournament',
})

const emit = defineEmits<{
  submit: [payload: { name: string; config: TournamentConfig }]
  cancel: []
}>()

const name = ref(props.seed.form_name ?? (typeof props.seed.editing === 'object' && props.seed.editing ? props.seed.editing.name : ''))
const config = ref<TournamentConfig>(configFromSeed(props.seed))
const lastCategoryId = ref<number | null>(config.value.category_id ?? props.seed.categories[0]?.id ?? null)
const error = ref('')

const settings = computed<TournamentSettings>({
  get: () => config.value,
  set: (value) => { config.value = { ...config.value, ...value } },
})

const selectedCategory = computed(() => props.seed.categories.find((category) => category.id === config.value.category_id))
const selectedOpening = computed(() => props.seed.opening_suites.find((suite) => suite.id === config.value.opening_suite_id))
const selectedParticipantNames = computed(() => props.seed.engine_options
  .filter((engine) => config.value.participants.includes(engine.id))
  .map((engine) => engine.name))
const gameEstimate = computed(() => estimateGames(config.value.format, config.value.format_options, config.value.participants.length))
const waves = computed(() => gameEstimate.value ? Math.ceil(gameEstimate.value / Math.max(config.value.concurrency, 1)) : 0)

watch(() => props.seed, (seed) => {
  name.value = seed.form_name ?? (typeof seed.editing === 'object' && seed.editing ? seed.editing.name : '')
  config.value = configFromSeed(seed)
  lastCategoryId.value = config.value.category_id ?? seed.categories[0]?.id ?? null
}, { deep: true })

watch(() => config.value.participants, (participants) => {
  if (config.value.format === 'gauntlet' && 'hero_engine_id' in config.value.format_options && !participants.includes(config.value.format_options.hero_engine_id)) {
    config.value = {
      ...config.value,
      format_options: { ...config.value.format_options, hero_engine_id: participants[0] ?? 0 },
    }
  }
  config.value.uci_options = Object.fromEntries(
    Object.entries(config.value.uci_options ?? {}).filter(([engineId]) => participants.includes(Number(engineId))),
  )
}, { deep: true })

function engineOptions(engineId: number): Record<string, string | number | boolean> {
  return config.value.uci_options?.[String(engineId)] ?? {}
}

function setEngineOptions(engineId: number, options: Record<string, string | number | boolean>): void {
  config.value.uci_options = { ...config.value.uci_options, [String(engineId)]: options }
}

function categoryDefaults(categoryId: number): TournamentSettings {
  const raw = props.seed.category_defaults?.[String(categoryId)]
    ?? props.seed.categories.find((category) => category.id === categoryId)?.default_config
  if (!raw) return settings.value
  if ('time_control' in raw || 'format_options' in raw) return normalizeSettings(raw as Partial<TournamentSettings>)
  return settingsFromFlat(raw as Record<string, unknown>)
}

function selectCategory(categoryId: number): void {
  config.value.category_id = categoryId
  config.value.category_settings_linked = true
  lastCategoryId.value = categoryId
  applyDefaults(categoryId)
}

function setLinked(linked: boolean): void {
  config.value.category_settings_linked = linked
  if (!linked) {
    lastCategoryId.value = config.value.category_id
    config.value.category_id = null
    config.value.rated = false
    return
  }
  const categoryId = lastCategoryId.value ?? props.seed.categories[0]?.id ?? null
  config.value.category_id = categoryId
  if (categoryId !== null) applyDefaults(categoryId)
}

function applyDefaults(categoryId: number): void {
  const defaults = categoryDefaults(categoryId) as TournamentSettings & { engine_threads?: number; engine_hash_mb?: number }
  const tournamentFields = {
    format: config.value.format,
    format_options: config.value.format_options,
    concurrency: config.value.concurrency,
    opening_suite_id: config.value.opening_suite_id,
  }
  config.value = {
    ...config.value,
    ...defaults,
    ...tournamentFields,
    engine_threads: defaults.engine_threads ?? 1,
    engine_hash_mb: defaults.engine_hash_mb ?? 16,
    uci_options: {},
  }
}

function validate(): string {
  if (!name.value.trim()) return 'Enter a tournament name.'
  if (config.value.category_settings_linked && !props.seed.categories.some((category) => category.id === config.value.category_id)) return 'Create or select an active rating category.'
  if (!config.value.category_settings_linked && config.value.category_id !== null) return 'Custom tournaments cannot have a rating category.'
  if (config.value.participants.length < 2) return 'Select at least two participating engines.'
  if (new Set(config.value.participants).size !== config.value.participants.length) return 'Each participant can only be selected once.'
  if (!Number.isInteger(config.value.concurrency) || config.value.concurrency < 1) return 'Concurrent games must be a whole number of at least 1.'
  if (!Number.isInteger(config.value.engine_threads) || config.value.engine_threads < 1) return 'Engine threads must be a whole number of at least 1.'
  if (!Number.isInteger(config.value.engine_hash_mb) || config.value.engine_hash_mb < 1) return 'Engine hash must be a whole number of at least 1 MB.'
  for (const options of Object.values(config.value.uci_options ?? {})) {
    if (Object.keys(options).some((name) => ['threads', 'hash'].includes(name.trim().toLowerCase()))) return 'Use the tournament thread and hash fields instead of adding Threads or Hash as UCI overrides.'
  }
  if (config.value.adjudication.max_moves !== null && (!Number.isInteger(config.value.adjudication.max_moves) || config.value.adjudication.max_moves < 1)) return 'Maximum moves must be a whole number of at least 1.'

  const options = config.value.format_options
  if (config.value.format === 'round_robin' && (!('games_per_pairing' in options) || !Number.isInteger(options.games_per_pairing) || options.games_per_pairing < 1)) return 'Games per pairing must be a whole number of at least 1.'
  if (config.value.format === 'swiss' && (!('rounds' in options) || !Number.isInteger(options.rounds) || options.rounds < 1)) return 'Swiss rounds must be a whole number of at least 1.'
  if (config.value.format === 'knockout' && (!('games_per_match' in options) || !Number.isInteger(options.games_per_match) || options.games_per_match < 1)) return 'Games per match must be a whole number of at least 1.'
  if (config.value.format === 'gauntlet') {
    if (!('hero_engine_id' in options) || !config.value.participants.includes(options.hero_engine_id)) return 'Select a hero from the participating engines.'
    if (!Number.isInteger(options.games_per_opponent) || options.games_per_opponent < 1) return 'Games per opponent must be a whole number of at least 1.'
  }

  const control = config.value.time_control
  if (control.category === 'increment' && (control.initial_ms <= 0 || control.increment_ms < 0)) return 'Enter a positive initial time and a non-negative increment.'
  if (control.category === 'movetime' && control.move_time_ms <= 0) return 'Time per move must be greater than zero.'
  if (control.category === 'movestogo' && (control.initial_ms <= 0 || !Number.isInteger(control.moves_to_go) || control.moves_to_go < 1)) return 'Enter a positive clock time and move quota.'
  if (control.category === 'movenodes' && (!Number.isInteger(control.nodes) || control.nodes < 1)) return 'Nodes per move must be a whole number of at least 1.'
  return ''
}

function submit(): void {
  error.value = validate()
  if (error.value) return
  emit('submit', { name: name.value.trim(), config: cloneData(config.value) })
}
</script>

<template>
  <form class="tournament-form" novalidate @submit.prevent="submit">
    <div class="tournament-form__main">
      <InlineFeedback :message="error" />

      <section class="panel form-panel">
        <div class="form-panel__heading">
          <span class="step-number" aria-hidden="true">1</span>
          <div><h2>Identity and ratings</h2></div>
        </div>
        <div class="field-grid">
          <label class="field field--span-2">
            <span class="field__label">Tournament name</span>
            <input v-model="name" class="input" required maxlength="120" autocomplete="off">
          </label>
          <label v-if="config.category_settings_linked && seed.categories.length" class="field">
            <span class="field__label">Rating category</span>
            <select class="input" :value="config.category_id" required @change="selectCategory(Number(($event.target as HTMLSelectElement).value))">
              <option v-for="category in seed.categories" :key="category.id" :value="category.id">{{ category.name }}</option>
            </select>
          </label>
          <div v-else-if="config.category_settings_linked" class="missing-category field--span-2" role="alert">
            <div><strong>No active rating categories</strong></div>
            <RouterLink class="button button--secondary button--small" to="/admin/categories/new">Create category</RouterLink>
          </div>
          <label class="choice-card">
            <input type="checkbox" :checked="config.category_settings_linked" @change="setLinked(($event.target as HTMLInputElement).checked)">
            <span><strong>Use a rating category</strong></span>
          </label>
        </div>
      </section>

      <section class="panel form-panel">
        <div class="form-panel__heading">
          <span class="step-number" aria-hidden="true">2</span>
          <div><h2>Participants</h2></div>
        </div>
        <ParticipantPicker v-if="seed.engine_options.length" v-model="config.participants" :engines="seed.engine_options" />
        <AdminEmptyState v-else title="No active engines">
          <RouterLink class="button button--primary button--small" to="/admin/engines/new">Register an engine</RouterLink>
        </AdminEmptyState>
      </section>

      <section class="panel form-panel">
        <div class="form-panel__heading">
          <span class="step-number" aria-hidden="true">3</span>
          <div><h2>Play settings</h2></div>
        </div>
        <AdminEmptyState v-if="config.category_settings_linked && !seed.categories.length" title="Category required" />
        <div v-else-if="config.category_settings_linked" class="category-settings">
          <div class="linked-settings">
            <svg aria-hidden="true" viewBox="0 0 24 24"><path d="M8.5 11V8.5a3.5 3.5 0 0 1 7 0V11M6 11h12v9H6z" /></svg>
            <div><strong>{{ selectedCategory?.name ?? 'Category' }}</strong></div>
            <button class="button button--secondary button--small" type="button" @click="setLinked(false)">Use independent settings</button>
          </div>
          <TournamentSettingsEditor v-model="settings" :engines="seed.engine_options" :opening-suites="seed.opening_suites" :participants="config.participants" :allow-rated="false" structure-only />
        </div>
        <div v-else class="custom-settings">
          <TournamentSettingsEditor v-model="settings" :engines="seed.engine_options" :opening-suites="seed.opening_suites" :participants="config.participants" :allow-rated="false" />
        </div>
      </section>

      <section class="panel form-panel">
        <div class="form-panel__heading">
          <span class="step-number" aria-hidden="true">4</span>
          <div><h2>{{ config.category_settings_linked ? 'Engine resources' : 'Engine resources and UCI options' }}</h2></div>
        </div>
        <div class="field-grid">
          <label class="field">
            <span class="field__label">Threads per engine</span>
            <input v-model.number="config.engine_threads" class="input" type="number" min="1" step="1" :disabled="config.category_settings_linked">
          </label>
          <label class="field">
            <span class="field__label">Hash per engine <small>MB</small></span>
            <input v-model.number="config.engine_hash_mb" class="input" type="number" min="1" step="1" :disabled="config.category_settings_linked">
          </label>
        </div>
        <div v-if="!config.category_settings_linked && selectedParticipantNames.length" class="tournament-options">
          <details v-for="engine in seed.engine_options.filter((item) => config.participants.includes(item.id))" :key="engine.id">
            <summary><strong>{{ engine.name }}</strong><span>{{ Object.keys(engineOptions(engine.id)).length }} additional option{{ Object.keys(engineOptions(engine.id)).length === 1 ? '' : 's' }}</span></summary>
            <div><EngineOptionsEditor :model-value="engineOptions(engine.id)" @update:model-value="setEngineOptions(engine.id, $event)" /></div>
          </details>
        </div>
      </section>

      <div class="form-actions">
        <button class="button button--ghost" type="button" :disabled="pending" @click="emit('cancel')">Cancel</button>
        <button class="button button--primary" type="submit" :disabled="pending || !seed.engine_options.length || (config.category_settings_linked && !seed.categories.length)" :aria-busy="pending">
          <span v-if="pending" class="button-spinner" aria-hidden="true" />
          {{ pending ? 'Saving…' : submitLabel }}
        </button>
      </div>
    </div>

    <aside class="panel tournament-summary" aria-label="Tournament summary">
      <div class="tournament-summary__heading">
        <span>Draft summary</span>
        <strong>{{ gameEstimate.toLocaleString() }} <small>estimated games</small></strong>
      </div>
      <dl>
        <div><dt>Category</dt><dd>{{ selectedCategory?.name ?? 'None (custom)' }}</dd></div>
        <div><dt>Participants</dt><dd>{{ config.participants.length }}</dd></div>
        <div><dt>Format</dt><dd>{{ humanize(config.format) }}</dd></div>
        <div><dt>Time control</dt><dd>{{ formatTimeControl(config.time_control) }}</dd></div>
        <div><dt>Opening suite</dt><dd>{{ selectedOpening?.name ?? 'None' }}</dd></div>
        <div><dt>Concurrent games</dt><dd>{{ config.concurrency }}</dd></div>
        <div><dt>Estimated waves</dt><dd>{{ waves.toLocaleString() }}</dd></div>
        <div><dt>Engine threads</dt><dd>{{ config.engine_threads }}</dd></div>
        <div><dt>Hash per engine</dt><dd>{{ config.engine_hash_mb.toLocaleString() }} MB</dd></div>
        <div><dt>Ratings</dt><dd>{{ config.category_id === null ? 'Not eligible' : config.rated ? 'Rated' : 'Unrated' }}</dd></div>
      </dl>
      <div v-if="selectedParticipantNames.length" class="tournament-summary__engines">
        <span v-for="engine in selectedParticipantNames.slice(0, 5)" :key="engine">{{ engine }}</span>
        <span v-if="selectedParticipantNames.length > 5">+{{ selectedParticipantNames.length - 5 }} more</span>
      </div>
    </aside>
  </form>
</template>

<style scoped>
.tournament-form { align-items: start; display: grid; gap: 1.25rem; grid-template-columns: minmax(0, 1fr) minmax(16rem, 21rem); }
.tournament-form__main { display: grid; gap: 1rem; min-width: 0; }
.form-panel { display: grid; gap: 1.2rem; padding: clamp(1rem, 2vw, 1.5rem); }
.form-panel__heading { align-items: flex-start; display: flex; gap: .75rem; }
.form-panel__heading h2 { font-size: 1rem; margin: 0; }
.form-panel__heading p { color: var(--color-text-muted, #64748b); font-size: .82rem; margin: .25rem 0 0; }
.step-number { align-items: center; background: color-mix(in srgb, var(--color-accent, #315fcc) 11%, transparent); border-radius: 50%; color: var(--color-accent, #315fcc); display: flex; flex: 0 0 auto; font-size: .75rem; font-weight: 750; height: 1.65rem; justify-content: center; width: 1.65rem; }
.field-grid { display: grid; gap: .9rem; grid-template-columns: repeat(2, minmax(0, 1fr)); }
.field { display: grid; gap: .4rem; }
.field--span-2 { grid-column: 1 / -1; }
.field__label { font-size: .82rem; font-weight: 650; }
.choice-card { align-items: flex-start; background: var(--color-surface-subtle, #f6f8fb); border: 1px solid var(--color-border, #d9e0ea); border-radius: var(--radius-md, .6rem); cursor: pointer; display: flex; gap: .65rem; padding: .75rem; }
.choice-card input { flex: 0 0 auto; height: 1rem; margin: .14rem 0 0; width: 1rem; }
.choice-card span { display: grid; gap: .2rem; }
.choice-card strong { font-size: .83rem; }
.choice-card small { color: var(--color-text-muted, #64748b); font-size: .74rem; line-height: 1.4; }
.category-settings { display: grid; gap: 1rem; }
.missing-category { align-items: center; background: color-mix(in srgb, var(--color-danger, #b42318) 7%, transparent); border: 1px solid color-mix(in srgb, var(--color-danger, #b42318) 25%, transparent); border-radius: var(--radius-md, .6rem); display: flex; gap: .8rem; justify-content: space-between; padding: .75rem; }
.missing-category strong { color: var(--color-danger, #b42318); font-size: .8rem; }.missing-category p { color: var(--color-text-muted, #64748b); font-size: .72rem; margin: .18rem 0 0; }
.linked-settings { align-items: center; background: var(--color-surface-subtle, #f6f8fb); border: 1px dashed var(--color-border-strong, #bbc5d3); border-radius: var(--radius-md, .6rem); display: grid; gap: .8rem; grid-template-columns: auto minmax(0, 1fr) auto; padding: 1rem; }
.linked-settings svg { fill: none; height: 1.35rem; stroke: var(--color-text-muted, #64748b); stroke-linecap: round; stroke-linejoin: round; stroke-width: 1.7; width: 1.35rem; }
.linked-settings strong { font-size: .86rem; }
.linked-settings p { color: var(--color-text-muted, #64748b); font-size: .78rem; margin: .2rem 0 0; }
.form-actions { align-items: center; display: flex; gap: .65rem; justify-content: flex-end; padding-block: .25rem; }
.tournament-summary { overflow: hidden; padding: 0; position: sticky; top: calc(var(--app-header-height, 0px) + 1rem); }
.tournament-summary__heading { background: var(--color-surface-subtle, #f6f8fb); border-bottom: 1px solid var(--color-border, #d9e0ea); display: grid; gap: .55rem; padding: 1rem; }
.tournament-summary__heading > span { color: var(--color-text-muted, #64748b); font-size: .72rem; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; }
.tournament-summary__heading strong { color: var(--color-accent, #315fcc); font-size: 1.45rem; }
.tournament-summary__heading small { color: var(--color-text-muted, #64748b); font-size: .72rem; font-weight: 550; }
.tournament-summary dl { display: grid; margin: 0; padding: .5rem 1rem; }
.tournament-summary dl div { align-items: baseline; border-bottom: 1px solid var(--color-border, #d9e0ea); display: flex; gap: 1rem; justify-content: space-between; padding: .65rem 0; }
.tournament-summary dl div:last-child { border-bottom: 0; }
.tournament-summary dt { color: var(--color-text-muted, #64748b); font-size: .76rem; }
.tournament-summary dd { font-size: .78rem; font-weight: 650; margin: 0; max-width: 60%; text-align: right; }
.tournament-summary__engines { display: flex; flex-wrap: wrap; gap: .35rem; padding: .2rem 1rem .8rem; }
.tournament-summary__engines span { background: var(--color-surface-subtle, #f6f8fb); border-radius: 999px; color: var(--color-text-muted, #64748b); font-size: .68rem; padding: .25rem .45rem; }
.tournament-options { display: grid; gap: .6rem; }
.tournament-options details { border: 1px solid var(--color-border, #d9e0ea); border-radius: var(--radius-md, .6rem); overflow: hidden; }
.tournament-options summary { align-items: center; cursor: pointer; display: flex; justify-content: space-between; padding: .75rem .85rem; }
.tournament-options summary strong { font-size: .82rem; }
.tournament-options summary span { color: var(--color-text-muted, #64748b); font-size: .72rem; }
.tournament-options details > div { border-top: 1px solid var(--color-border, #d9e0ea); padding: .85rem; }
@media (max-width: 64rem) {
  .tournament-form { grid-template-columns: 1fr; }
  .tournament-summary { grid-row: 1; position: static; }
  .tournament-summary dl { grid-template-columns: repeat(2, 1fr); }
  .tournament-summary dl div:nth-child(odd) { padding-right: .7rem; }
  .tournament-summary dl div:nth-child(even) { padding-left: .7rem; }
}
@media (max-width: 38rem) {
  .field-grid { grid-template-columns: 1fr; }
  .field--span-2 { grid-column: auto; }
  .linked-settings { grid-template-columns: auto 1fr; }
  .linked-settings .button { grid-column: 1 / -1; }
  .tournament-summary dl { grid-template-columns: 1fr; }
  .tournament-summary dl div { padding-inline: 0 !important; }
}
</style>
