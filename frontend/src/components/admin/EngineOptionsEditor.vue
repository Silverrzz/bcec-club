<script setup lang="ts">
import { ref, watch } from 'vue'

type OptionValue = string | number | boolean
interface OptionRow { id: number; name: string; value: string; type: 'string' | 'number' | 'boolean' }

const props = defineProps<{ modelValue: Record<string, OptionValue> }>()
const emit = defineEmits<{ 'update:modelValue': [value: Record<string, OptionValue>] }>()

let nextId = 1
const rows = ref<OptionRow[]>(optionRows(props.modelValue))

watch(() => props.modelValue, (value) => {
  if (sameOptions(optionsFromRows(rows.value), value)) return
  rows.value = optionRows(value)
}, { deep: true })

function optionRows(options: Record<string, OptionValue> | undefined): OptionRow[] {
  return Object.entries(options ?? {}).map<OptionRow>(([name, value]) => ({
    id: nextId++,
    name,
    value: String(value),
    type: typeof value === 'boolean' ? 'boolean' : typeof value === 'number' ? 'number' : 'string',
  }))
}

function optionsFromRows(nextRows: OptionRow[]): Record<string, OptionValue> {
  const options: Record<string, OptionValue> = {}
  for (const row of nextRows) {
    const name = row.name.trim()
    if (!name) continue
    options[name] = row.type === 'number'
      ? Number(row.value)
      : row.type === 'boolean'
        ? row.value === 'true'
        : row.value
  }
  return options
}

function sameOptions(left: Record<string, OptionValue>, right: Record<string, OptionValue>): boolean {
  const leftEntries = Object.entries(left)
  const rightEntries = Object.entries(right)
  return leftEntries.length === rightEntries.length
    && leftEntries.every(([name, value]) => Object.is(right[name], value))
}

function update(nextRows: OptionRow[]): void {
  rows.value = nextRows
  emit('update:modelValue', optionsFromRows(nextRows))
}

function change(index: number, key: 'name' | 'value' | 'type', value: string): void {
  const copy = rows.value.map((row) => ({ ...row }))
  const row = copy[index]
  if (!row) return
  if (key === 'name') row.name = value
  else if (key === 'value') row.value = value
  else {
    row.type = value as OptionRow['type']
    row.value = value === 'boolean' ? 'true' : ''
  }
  update(copy)
}

function add(): void {
  update([...rows.value, { id: nextId++, name: `Option ${rows.value.length + 1}`, value: '', type: 'string' }])
}

function remove(index: number): void {
  update(rows.value.filter((_, rowIndex) => rowIndex !== index))
}
</script>

<template>
  <div class="option-editor">
    <div v-if="rows.length" class="option-editor__rows">
      <div v-for="(row, index) in rows" :key="row.id" class="option-row">
        <label>
          <span>Option name</span>
          <input class="input" :value="row.name" autocomplete="off" @input="change(index, 'name', ($event.target as HTMLInputElement).value)">
        </label>
        <label>
          <span>Value type</span>
          <select class="input" :value="row.type" @change="change(index, 'type', ($event.target as HTMLSelectElement).value)">
            <option value="string">Text</option>
            <option value="number">Number</option>
            <option value="boolean">Boolean</option>
          </select>
        </label>
        <label>
          <span>Value</span>
          <select v-if="row.type === 'boolean'" class="input" :value="row.value" @change="change(index, 'value', ($event.target as HTMLSelectElement).value)">
            <option value="true">True</option>
            <option value="false">False</option>
          </select>
          <input v-else class="input" :type="row.type === 'number' ? 'number' : 'text'" :value="row.value" @input="change(index, 'value', ($event.target as HTMLInputElement).value)">
        </label>
        <button class="icon-button option-row__remove" type="button" :aria-label="`Remove ${row.name || 'option'}`" @click="remove(index)">
          <svg aria-hidden="true" viewBox="0 0 24 24"><path d="m7 7 10 10M17 7 7 17" /></svg>
        </button>
      </div>
    </div>
    <p v-else class="option-editor__empty">No UCI overrides.</p>
    <button class="button button--secondary button--small" type="button" @click="add">Add UCI option</button>
  </div>
</template>

<style scoped>
.option-editor { display: grid; gap: .8rem; }
.option-editor__rows { display: grid; gap: .65rem; }
.option-row { align-items: end; display: grid; gap: .6rem; grid-template-columns: minmax(10rem, 1.2fr) minmax(7rem, .6fr) minmax(10rem, 1fr) auto; }
.option-row label { display: grid; font-size: .8rem; font-weight: 600; gap: .35rem; }
.option-row__remove { margin-bottom: .05rem; }
.option-row__remove svg { fill: none; height: 1.1rem; stroke: currentColor; stroke-linecap: round; stroke-width: 2; width: 1.1rem; }
.option-editor__empty { color: var(--color-text-muted, #64748b); margin: 0; }
@media (max-width: 48rem) {
  .option-row { align-items: stretch; grid-template-columns: 1fr 1fr; }
  .option-row label:first-child { grid-column: 1 / -1; }
  .option-row__remove { align-self: end; justify-self: end; }
}
</style>
