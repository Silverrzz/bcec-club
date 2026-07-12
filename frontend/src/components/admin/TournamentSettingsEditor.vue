<script setup lang="ts">
import { computed } from 'vue'
import type { Engine, OpeningSuite, TimeControlCategory, TournamentFormat, TournamentSettings } from './types'

const props = withDefaults(defineProps<{
  modelValue: TournamentSettings
  engines?: Engine[]
  openingSuites?: OpeningSuite[]
  participants?: number[]
  allowGauntlet?: boolean
  allowRated?: boolean
  allowFormat?: boolean
  allowConcurrency?: boolean
  allowOpeningSuite?: boolean
  structureOnly?: boolean
  idPrefix?: string
}>(), {
  engines: () => [],
  openingSuites: () => [],
  participants: () => [],
  allowGauntlet: true,
  allowRated: true,
  allowFormat: true,
  allowConcurrency: true,
  allowOpeningSuite: true,
  structureOnly: false,
  idPrefix: 'tournament',
})

const emit = defineEmits<{ 'update:modelValue': [value: TournamentSettings] }>()

const model = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})

const participantEngines = computed(() => props.engines.filter((engine) => props.participants.includes(engine.id)))

function patch(patchValue: Partial<TournamentSettings>): void {
  model.value = { ...model.value, ...patchValue }
}

function setFormat(format: TournamentFormat): void {
  const options = format === 'round_robin'
    ? { games_per_pairing: 2 }
    : format === 'swiss'
      ? { rounds: 7 }
      : format === 'knockout'
        ? { games_per_match: 2, tiebreak: 'armageddon' as const }
        : { hero_engine_id: props.participants[0] ?? 0, games_per_opponent: 2 }
  patch({ format, format_options: options })
}

function patchFormatOption(key: string, value: string | number | boolean): void {
  patch({ format_options: { ...model.value.format_options, [key]: value } as TournamentSettings['format_options'] })
}

function setTimeControl(category: TimeControlCategory): void {
  const time_control = category === 'increment'
    ? { category: 'increment' as const, initial_ms: 60_000, increment_ms: 1_000 }
    : category === 'movetime'
      ? { category: 'movetime' as const, move_time_ms: 1_000 }
      : category === 'movestogo'
        ? { category: 'movestogo' as const, initial_ms: 60_000, moves_to_go: 40 }
        : { category: 'movenodes' as const, nodes: 100_000 }
  patch({ time_control })
}

function seconds(field: 'initial_ms' | 'increment_ms' | 'move_time_ms'): number {
  const control = model.value.time_control as unknown as Record<string, number>
  return (control[field] ?? 0) / 1000
}

function patchTime(field: string, value: number): void {
  patch({ time_control: { ...model.value.time_control, [field]: value } as TournamentSettings['time_control'] })
}

function patchSeconds(field: string, value: number): void {
  patchTime(field, Math.round(value * 1000))
}

function numberOption(key: string): number {
  return Number((model.value.format_options as unknown as Record<string, unknown>)[key] ?? 0)
}
</script>

<template>
  <div class="settings-editor">
    <fieldset v-if="allowFormat" class="form-section">
      <legend>Format</legend>
      <div class="field-grid field-grid--wide">
        <label class="field">
          <span class="field__label">Pairing format</span>
          <select class="input" :value="model.format" @change="setFormat(($event.target as HTMLSelectElement).value as TournamentFormat)">
            <option value="round_robin">Round robin</option>
            <option value="swiss">Swiss</option>
            <option value="knockout">Knockout</option>
            <option v-if="allowGauntlet" value="gauntlet">Gauntlet</option>
          </select>
        </label>

        <label v-if="model.format === 'round_robin'" class="field">
          <span class="field__label">Games per pairing</span>
          <input class="input" type="number" min="1" step="1" :value="numberOption('games_per_pairing')" @input="patchFormatOption('games_per_pairing', Number(($event.target as HTMLInputElement).value))">
        </label>

        <label v-else-if="model.format === 'swiss'" class="field">
          <span class="field__label">Rounds</span>
          <input class="input" type="number" min="1" step="1" :value="numberOption('rounds')" @input="patchFormatOption('rounds', Number(($event.target as HTMLInputElement).value))">
        </label>

        <template v-else-if="model.format === 'knockout'">
          <label class="field">
            <span class="field__label">Games per match</span>
            <input class="input" type="number" min="1" step="1" :value="numberOption('games_per_match')" @input="patchFormatOption('games_per_match', Number(($event.target as HTMLInputElement).value))">
          </label>
          <label class="field">
            <span class="field__label">Tiebreak</span>
            <select class="input" :value="'tiebreak' in model.format_options ? model.format_options.tiebreak : 'armageddon'" @change="patchFormatOption('tiebreak', ($event.target as HTMLSelectElement).value)">
              <option value="armageddon">Armageddon</option>
              <option value="extra_pair">Extra game pair</option>
            </select>
          </label>
        </template>

        <template v-else-if="allowGauntlet">
          <label class="field">
            <span class="field__label">Hero engine</span>
            <select class="input" :value="numberOption('hero_engine_id')" @change="patchFormatOption('hero_engine_id', Number(($event.target as HTMLSelectElement).value))">
              <option value="0" disabled>Select a participant</option>
              <option v-for="engine in participantEngines" :key="engine.id" :value="engine.id">{{ engine.name }}</option>
            </select>
          </label>
          <label class="field">
            <span class="field__label">Games per opponent</span>
            <input class="input" type="number" min="1" step="1" :value="numberOption('games_per_opponent')" @input="patchFormatOption('games_per_opponent', Number(($event.target as HTMLInputElement).value))">
          </label>
        </template>
      </div>
    </fieldset>

    <fieldset v-if="!structureOnly" class="form-section">
      <legend>Time control</legend>
      <div class="field-grid field-grid--wide">
        <label class="field">
          <span class="field__label">Limit type</span>
          <select class="input" :value="model.time_control.category" @change="setTimeControl(($event.target as HTMLSelectElement).value as TimeControlCategory)">
            <option value="increment">Clock with increment</option>
            <option value="movetime">Fixed time per move</option>
            <option value="movestogo">Clock for a move quota</option>
            <option value="movenodes">Nodes per move</option>
          </select>
        </label>

        <template v-if="model.time_control.category === 'increment'">
          <label class="field">
            <span class="field__label">Initial time <small>seconds</small></span>
            <input class="input" type="number" min="0.001" step="0.1" :value="seconds('initial_ms')" @input="patchSeconds('initial_ms', Number(($event.target as HTMLInputElement).value))">
          </label>
          <label class="field">
            <span class="field__label">Increment <small>seconds</small></span>
            <input class="input" type="number" min="0" step="0.1" :value="seconds('increment_ms')" @input="patchSeconds('increment_ms', Number(($event.target as HTMLInputElement).value))">
          </label>
        </template>

        <label v-else-if="model.time_control.category === 'movetime'" class="field">
          <span class="field__label">Time per move <small>seconds</small></span>
          <input class="input" type="number" min="0.001" step="0.1" :value="seconds('move_time_ms')" @input="patchSeconds('move_time_ms', Number(($event.target as HTMLInputElement).value))">
        </label>

        <template v-else-if="model.time_control.category === 'movestogo'">
          <label class="field">
            <span class="field__label">Clock time <small>seconds</small></span>
            <input class="input" type="number" min="0.001" step="0.1" :value="seconds('initial_ms')" @input="patchSeconds('initial_ms', Number(($event.target as HTMLInputElement).value))">
          </label>
          <label class="field">
            <span class="field__label">Moves to go</span>
            <input class="input" type="number" min="1" step="1" :value="model.time_control.moves_to_go" @input="patchTime('moves_to_go', Number(($event.target as HTMLInputElement).value))">
          </label>
        </template>

        <label v-else class="field">
          <span class="field__label">Nodes per move</span>
          <input class="input" type="number" min="1" step="1" :value="model.time_control.nodes" @input="patchTime('nodes', Number(($event.target as HTMLInputElement).value))">
        </label>
      </div>
    </fieldset>

    <fieldset class="form-section">
      <legend>Execution</legend>
      <div class="field-grid field-grid--wide">
        <label v-if="allowConcurrency" class="field">
          <span class="field__label">Concurrent games</span>
          <input class="input" type="number" min="1" step="1" :value="model.concurrency" @input="patch({ concurrency: Number(($event.target as HTMLInputElement).value) })">
        </label>
        <label v-if="allowOpeningSuite" class="field">
          <span class="field__label">Opening suite</span>
          <select class="input" :value="model.opening_suite_id ?? ''" @change="patch({ opening_suite_id: Number(($event.target as HTMLSelectElement).value) || null })">
            <option value="">No opening suite</option>
            <option v-for="suite in openingSuites" :key="suite.id" :value="suite.id">{{ suite.name }}</option>
          </select>
        </label>
        <label v-if="!structureOnly" class="field">
          <span class="field__label">Maximum full moves <small>optional</small></span>
          <input class="input" type="number" min="1" step="1" :value="model.adjudication.max_moves ?? ''" placeholder="No limit" @input="patch({ adjudication: { ...model.adjudication, max_moves: Number(($event.target as HTMLInputElement).value) || null } })">
        </label>
      </div>
      <label v-if="allowRated && !structureOnly" class="choice-row">
        <input type="checkbox" :checked="model.rated" @change="patch({ rated: ($event.target as HTMLInputElement).checked })">
        <span><strong>Rated tournament</strong></span>
      </label>
    </fieldset>
  </div>
</template>

<style scoped>
.settings-editor { display: grid; gap: 1rem; }
.form-section { border: 0; border-top: 1px solid var(--color-border, #d9e0ea); margin: 0; min-width: 0; padding: 1.25rem 0 0; }
.form-section:first-child { border-top: 0; padding-top: 0; }
.form-section legend { color: var(--color-text, #172033); font-size: .95rem; font-weight: 700; margin-bottom: .9rem; padding: 0; }
.field-grid { display: grid; gap: .9rem; grid-template-columns: repeat(auto-fit, minmax(min(100%, 13rem), 1fr)); }
.field-grid--wide { align-items: start; }
.field { display: grid; gap: .4rem; min-width: 0; }
.field__label { color: var(--color-text, #172033); font-size: .82rem; font-weight: 650; }
.field__label small { color: var(--color-text-muted, #64748b); font-size: .74rem; font-weight: 500; }
.choice-row { align-items: flex-start; cursor: pointer; display: flex; gap: .65rem; margin-top: .9rem; }
.choice-row input { flex: 0 0 auto; height: 1rem; margin: .15rem 0 0; width: 1rem; }
.choice-row span { display: grid; gap: .16rem; }
.choice-row strong { font-size: .86rem; }
.choice-row small { color: var(--color-text-muted, #64748b); font-size: .76rem; line-height: 1.4; }
</style>
