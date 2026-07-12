<script setup lang="ts">
import { computed, ref, watch } from 'vue'

const props = withDefaults(defineProps<{
  modelValue: string
  files: File[]
  mode?: 'replace' | 'append'
  source?: 'files' | 'manual'
  editing?: boolean
}>(), { mode: 'replace', source: 'files', editing: false })

const emit = defineEmits<{
  'update:modelValue': [value: string]
  'update:files': [value: File[]]
  'update:mode': [value: 'replace' | 'append']
  'update:source': [value: 'files' | 'manual']
}>()

interface PreviewLine { name: string; fen: string }
const filePreview = ref<PreviewLine[]>([])
const fileParseNote = ref('')
const deferredFileCount = ref(0)
let readGeneration = 0

const manualLines = computed<PreviewLine[]>(() => props.modelValue
  .split(/\r?\n/)
  .map((line) => line.trim())
  .filter(Boolean)
  .map((line, index) => {
    const separator = line.indexOf(';')
    return separator > 0
      ? { name: line.slice(0, separator).trim(), fen: line.slice(separator + 1).trim() }
      : { name: `Position ${index + 1}`, fen: line }
  }))

const activePositions = computed(() => props.source === 'manual' ? manualLines.value : filePreview.value)
const preview = computed(() => activePositions.value.slice(0, 8))
const estimatedCount = computed(() => activePositions.value.length)

watch(() => props.files, async (files) => {
  const generation = ++readGeneration
  filePreview.value = []
  fileParseNote.value = ''
  deferredFileCount.value = 0
  for (const file of files) {
    if (file.size > 2 * 1024 * 1024) {
      deferredFileCount.value += 1
      filePreview.value.push({ name: file.name, fen: 'Contents will be parsed by the server when saved' })
      fileParseNote.value = 'Large files are uploaded without a size limit and parsed by the server.'
      continue
    }
    const text = await file.text()
    if (generation !== readGeneration) return
    if (/\.(?:epd|fen|txt)$/i.test(file.name)) {
      const lines = text.split(/\r?\n/).map((line) => line.trim()).filter((line) => line && !line.startsWith('#'))
      filePreview.value.push(...lines.map((line, index) => ({ name: `${file.name} ${index + 1}`, fen: line.split(/\s+(?=(?:bm|am|id)\s)/)[0] ?? line })))
    } else {
      const games = Math.max((text.match(/^\[Event\s/mg) ?? []).length, text.trim() ? 1 : 0)
      filePreview.value.push(...Array.from({ length: games }, (_, index) => ({ name: `${file.name} game ${index + 1}`, fen: 'PGN mainline position' })))
      fileParseNote.value = 'PGN positions are validated and expanded by the server when you save.'
    }
  }
}, { immediate: true, deep: true })

function chooseFiles(event: Event): void {
  emit('update:files', Array.from((event.target as HTMLInputElement).files ?? []))
}

function removeFile(index: number): void {
  emit('update:files', props.files.filter((_, fileIndex) => fileIndex !== index))
}
</script>

<template>
  <div class="opening-importer">
    <fieldset v-if="editing" class="import-mode">
      <legend>Import behaviour</legend>
      <label :class="{ 'import-mode__option--selected': mode === 'replace' }">
        <input type="radio" name="opening-mode" value="replace" :checked="mode === 'replace'" @change="emit('update:mode', 'replace')">
        <span><strong>Replace positions</strong></span>
      </label>
      <label :class="{ 'import-mode__option--selected': mode === 'append' }">
        <input type="radio" name="opening-mode" value="append" :checked="mode === 'append'" @change="emit('update:mode', 'append')">
        <span><strong>Append positions</strong></span>
      </label>
    </fieldset>

    <fieldset class="import-mode source-mode">
      <legend>Position source</legend>
      <label :class="{ 'import-mode__option--selected': source === 'files' }">
        <input type="radio" name="position-source" value="files" :checked="source === 'files'" @change="emit('update:source', 'files')">
        <span><strong>Upload files</strong></span>
      </label>
      <label :class="{ 'import-mode__option--selected': source === 'manual' }">
        <input type="radio" name="position-source" value="manual" :checked="source === 'manual'" @change="emit('update:source', 'manual')">
        <span><strong>Paste positions</strong></span>
      </label>
    </fieldset>

    <div class="import-grid">
      <div class="import-inputs">
        <label v-if="source === 'files'" class="file-drop">
          <svg aria-hidden="true" viewBox="0 0 24 24"><path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5M5 14v4.5A1.5 1.5 0 0 0 6.5 20h11a1.5 1.5 0 0 0 1.5-1.5V14" /></svg>
          <span><strong>PGN, EPD, FEN, or text files</strong></span>
          <input type="file" accept=".pgn,.epd,.fen,.txt" multiple @change="chooseFiles">
        </label>
        <ul v-if="source === 'files' && files.length" class="file-list" aria-label="Selected files">
          <li v-for="(file, index) in files" :key="`${file.name}-${file.lastModified}`">
            <span><strong>{{ file.name }}</strong><small>{{ (file.size / 1024).toFixed(file.size < 1024 ? 1 : 0) }} KB</small></span>
            <button class="icon-button" type="button" :aria-label="`Remove ${file.name}`" @click="removeFile(index)">
              <svg aria-hidden="true" viewBox="0 0 24 24"><path d="m7 7 10 10M17 7 7 17" /></svg>
            </button>
          </li>
        </ul>

        <label v-if="source === 'manual'" class="field">
          <span class="field__label">FEN or EPD positions</span>
          <textarea class="input input--mono" :value="modelValue" rows="11" spellcheck="false" @input="emit('update:modelValue', ($event.target as HTMLTextAreaElement).value)"></textarea>
        </label>
      </div>

      <aside class="import-preview" aria-live="polite">
        <div class="import-preview__heading">
          <span>Import preview</span>
          <strong v-if="source === 'files' && deferredFileCount">{{ estimatedCount - deferredFileCount > 0 ? `${(estimatedCount - deferredFileCount).toLocaleString()}+` : '' }} <small>counted on save</small></strong>
          <strong v-else>{{ estimatedCount.toLocaleString() }} <small>{{ estimatedCount === 1 ? 'position' : 'positions' }}</small></strong>
        </div>
        <ol v-if="preview.length">
          <li v-for="(position, index) in preview" :key="`${position.name}-${index}`">
            <span>{{ position.name }}</span>
            <code>{{ position.fen }}</code>
          </li>
        </ol>
        <p v-else>{{ source === 'files' ? 'Choose one or more files to preview the import.' : 'Paste a position to preview the import.' }}</p>
        <small v-if="estimatedCount > preview.length">Showing the first {{ preview.length }} positions.</small>
        <small v-if="fileParseNote">{{ fileParseNote }}</small>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.opening-importer { display: grid; gap: 1rem; }
.import-mode { border: 0; display: grid; gap: .55rem; grid-template-columns: repeat(2, minmax(0, 1fr)); margin: 0; padding: 0; }
.import-mode legend { font-size: .82rem; font-weight: 650; grid-column: 1 / -1; margin-bottom: .05rem; }
.import-mode label { align-items: flex-start; border: 1px solid var(--color-border, #d9e0ea); border-radius: var(--radius-md, .6rem); cursor: pointer; display: flex; gap: .65rem; padding: .75rem; }
.import-mode__option--selected { background: color-mix(in srgb, var(--color-accent, #315fcc) 7%, transparent); border-color: var(--color-accent, #315fcc) !important; }
.import-mode input { height: 1rem; margin: .15rem 0 0; width: 1rem; }
.import-mode span { display: grid; gap: .15rem; }
.import-mode strong { font-size: .82rem; }
.import-mode small { color: var(--color-text-muted, #64748b); font-size: .73rem; line-height: 1.4; }
.import-grid { align-items: start; display: grid; gap: 1rem; grid-template-columns: minmax(0, 1.35fr) minmax(15rem, .65fr); }
.import-inputs { display: grid; gap: .85rem; }
.file-drop { align-items: center; border: 1px dashed var(--color-border-strong, #aeb9c8); border-radius: var(--radius-md, .6rem); cursor: pointer; display: flex; gap: .75rem; min-height: 5rem; padding: .9rem; position: relative; }
.file-drop:hover { background: var(--color-surface-subtle, #f6f8fb); border-color: var(--color-accent, #315fcc); }
.file-drop:focus-within { box-shadow: 0 0 0 3px color-mix(in srgb, var(--color-accent, #315fcc) 20%, transparent); }
.file-drop > svg { fill: none; flex: 0 0 auto; height: 1.45rem; stroke: var(--color-accent, #315fcc); stroke-linecap: round; stroke-linejoin: round; stroke-width: 1.7; width: 1.45rem; }
.file-drop span { display: grid; gap: .2rem; }
.file-drop strong { font-size: .85rem; }
.file-drop small { color: var(--color-text-muted, #64748b); font-size: .74rem; }
.file-drop input { inset: 0; opacity: 0; position: absolute; width: 100%; }
.file-list { display: grid; gap: .35rem; list-style: none; margin: 0; padding: 0; }
.file-list li { align-items: center; background: var(--color-surface-subtle, #f6f8fb); border-radius: .45rem; display: flex; gap: .65rem; justify-content: space-between; padding: .5rem .6rem; }
.file-list li > span { display: flex; gap: .5rem; min-width: 0; }
.file-list strong { font-size: .76rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.file-list small { color: var(--color-text-muted, #64748b); font-size: .7rem; white-space: nowrap; }
.file-list svg { fill: none; height: 1rem; stroke: currentColor; stroke-linecap: round; stroke-width: 2; width: 1rem; }
.field { display: grid; gap: .4rem; }
.field__label { font-size: .82rem; font-weight: 650; }
.field__label small { color: var(--color-text-muted, #64748b); font-size: .73rem; font-weight: 500; }
.import-preview { background: var(--color-surface-subtle, #f6f8fb); border: 1px solid var(--color-border, #d9e0ea); border-radius: var(--radius-md, .6rem); overflow: hidden; }
.import-preview__heading { align-items: baseline; border-bottom: 1px solid var(--color-border, #d9e0ea); display: flex; gap: .6rem; justify-content: space-between; padding: .8rem; }
.import-preview__heading > span { color: var(--color-text-muted, #64748b); font-size: .72rem; font-weight: 700; letter-spacing: .05em; text-transform: uppercase; }
.import-preview__heading strong { color: var(--color-accent, #315fcc); font-size: 1.05rem; }
.import-preview__heading small { font-size: .68rem; font-weight: 550; }
.import-preview ol { display: grid; gap: .65rem; list-style-position: inside; margin: 0; padding: .8rem; }
.import-preview li { min-width: 0; }
.import-preview li::marker { color: var(--color-text-muted, #64748b); font-size: .72rem; }
.import-preview li span { font-size: .74rem; font-weight: 650; }
.import-preview code { color: var(--color-text-muted, #64748b); display: block; font-size: .64rem; margin: .16rem 0 0 1rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.import-preview > p, .import-preview > small { color: var(--color-text-muted, #64748b); display: block; font-size: .73rem; line-height: 1.45; margin: 0; padding: .8rem; }
.import-preview > small + small { padding-top: 0; }
@media (max-width: 52rem) { .import-grid { grid-template-columns: 1fr; } }
@media (max-width: 36rem) { .import-mode { grid-template-columns: 1fr; } }
</style>
