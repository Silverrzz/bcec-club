<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@/api/client'
import { useToast } from '@/composables/useToast'
import AdminPageHeader from '@/components/admin/AdminPageHeader.vue'
import InlineFeedback from '@/components/admin/InlineFeedback.vue'
import OpeningImportEditor from '@/components/admin/OpeningImportEditor.vue'
import { errorText } from '@/components/admin/format'
import type { OpeningSuite } from '@/components/admin/types'

interface Response { suite?: OpeningSuite | null; positions_text?: string }
const route = useRoute()
const router = useRouter()
const toast = useToast()
const id = computed(() => Number(route.params.id) || null)
const loading = ref(true)
const pending = ref(false)
const error = ref('')
const form = reactive({ name: '', description: '', positions: '', mode: 'replace' as 'replace' | 'append', source: 'files' as 'files' | 'manual', files: [] as File[] })
const originalPositions = ref('')

async function load(): Promise<void> {
  try {
    const response = await api.get<Response>(id.value ? `/api/admin/openings/${id.value}` : '/api/admin/openings/form')
    if (response.suite) { form.name = response.suite.name; form.description = response.suite.description ?? ''; form.source = 'manual' }
    form.positions = response.positions_text ?? ''
    originalPositions.value = form.positions
  } catch (cause) { error.value = errorText(cause) }
  finally { loading.value = false }
}

function setMode(mode: 'replace' | 'append'): void {
  if (id.value && mode === 'append' && form.mode === 'replace' && form.positions === originalPositions.value) form.positions = ''
  if (id.value && mode === 'replace' && form.mode === 'append' && !form.positions.trim() && !form.files.length) form.positions = originalPositions.value
  form.mode = mode
}

async function save(): Promise<void> {
  error.value = ''
  const hasPositions = form.source === 'files' ? form.files.length > 0 : Boolean(form.positions.trim())
  if (!form.name.trim()) { error.value = 'Enter a suite name.'; return }
  if (!id.value && !hasPositions) { error.value = 'Add at least one PGN, EPD, FEN, or manual position.'; return }
  if (id.value && form.mode === 'append' && !hasPositions) { error.value = 'Add at least one position to append.'; return }
  if (id.value && form.mode === 'replace' && !hasPositions) { error.value = 'Add at least one position for the replacement set.'; return }
  pending.value = true
  const body = new FormData()
  body.set('name', form.name.trim())
  body.set('description', form.description.trim())
  body.set('positions', form.source === 'manual' ? form.positions : '')
  body.set('mode', form.mode)
  if (form.source === 'files') form.files.forEach((file) => body.append('files', file, file.name))
  try {
    const response = id.value ? await api.put<{ id: number; message: string }>(`/api/admin/openings/${id.value}`, { body }) : await api.post<{ id: number; message: string }>('/api/admin/openings', { body })
    toast.success(response.message)
    await router.push('/admin/openings')
  } catch (cause) {
    error.value = errorText(cause)
    toast.error(cause, { title: 'Import was not saved' })
  } finally { pending.value = false }
}
onMounted(load)
</script>

<template>
  <div class="admin-page page-stack">
    <AdminPageHeader :title="id ? `Edit ${form.name || 'opening suite'}` : 'Import opening suite'">
      <template #actions><RouterLink class="button button--ghost" to="/admin/openings">Back to suites</RouterLink></template>
    </AdminPageHeader>
    <InlineFeedback :message="error" />
    <div v-if="loading" class="panel form-loading" role="status">Loading opening suite…</div>
    <form v-else class="opening-form" novalidate @submit.prevent="save">
      <section class="panel form-card">
        <div class="form-card__heading"><h2>Suite details</h2></div>
        <div class="form-grid"><label class="field"><span>Name</span><input v-model="form.name" class="input" required maxlength="100"></label><label class="field"><span>Description <small>optional</small></span><input v-model="form.description" class="input" maxlength="240"></label></div>
      </section>
      <section class="panel form-card">
        <div class="form-card__heading"><h2>Positions</h2></div>
        <OpeningImportEditor v-model="form.positions" v-model:files="form.files" v-model:source="form.source" :mode="form.mode" :editing="!!id" @update:mode="setMode" />
      </section>
      <div class="form-actions"><RouterLink class="button button--ghost" to="/admin/openings">Cancel</RouterLink><button class="button button--primary" type="submit" :disabled="pending">{{ pending ? 'Importing…' : id ? 'Save suite' : 'Create suite' }}</button></div>
    </form>
  </div>
</template>

<style scoped>
.opening-form { display: grid; gap: 1rem; }
.form-card { display: grid; gap: 1rem; padding: clamp(1rem, 2vw, 1.35rem); }
.form-card__heading { border-bottom: 1px solid var(--color-border, #d9e0ea); padding-bottom: .8rem; }
.form-card__heading h2 { font-size: .95rem; margin: 0; }
.form-card__heading p { color: var(--color-text-muted, #64748b); font-size: .75rem; line-height: 1.45; margin: .25rem 0 0; }
.form-grid { display: grid; gap: .85rem; grid-template-columns: repeat(2, minmax(0, 1fr)); }
.field { display: grid; gap: .38rem; }
.field > span { font-size: .8rem; font-weight: 650; }
.field small { color: var(--color-text-muted, #64748b); font-size: .7rem; font-weight: 500; }
.form-actions { display: flex; gap: .6rem; justify-content: flex-end; }
.form-loading { color: var(--color-text-muted, #64748b); min-height: 16rem; padding: 2rem; }
@media (max-width: 40rem) { .form-grid { grid-template-columns: 1fr; } }
</style>
