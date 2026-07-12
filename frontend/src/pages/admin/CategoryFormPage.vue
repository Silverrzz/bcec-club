<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@/api/client'
import { useToast } from '@/composables/useToast'
import AdminPageHeader from '@/components/admin/AdminPageHeader.vue'
import InlineFeedback from '@/components/admin/InlineFeedback.vue'
import StatusBadge from '@/components/admin/StatusBadge.vue'
import TournamentSettingsEditor from '@/components/admin/TournamentSettingsEditor.vue'
import { defaultCategorySettings, errorText, normalizeCategorySettings, settingsFromFlat } from '@/components/admin/format'
import type { Category, CategorySettings, Engine, OpeningSuite, Tournament, TournamentSettings } from '@/components/admin/types'

interface Response { category?: Category | null; default_config?: Partial<CategorySettings>; form_values?: Record<string, unknown>; engine_options: Engine[]; opening_suites: OpeningSuite[]; tournaments?: Tournament[] }
const route = useRoute()
const router = useRouter()
const toast = useToast()
const id = computed(() => Number(route.params.id) || null)
const loading = ref(true)
const pending = ref(false)
const error = ref('')
const options = ref<{ engines: Engine[]; openings: OpeningSuite[] }>({ engines: [], openings: [] })
const tournaments = ref<Tournament[]>([])
const form = reactive<{ name: string; description: string; active: boolean; default_config: CategorySettings }>({ name: '', description: '', active: true, default_config: defaultCategorySettings() })

async function load(): Promise<void> {
  try {
    const response = await api.get<Response>(id.value ? `/api/admin/categories/${id.value}` : '/api/admin/categories/form')
    if (response.category) {
      form.name = response.category.name
      form.description = response.category.description ?? ''
      form.active = response.category.active ?? true
      form.default_config = normalizeCategorySettings(response.category.default_config)
    } else if (response.default_config) form.default_config = normalizeCategorySettings(response.default_config)
    else if (response.form_values) form.default_config = { ...settingsFromFlat(response.form_values), engine_threads: 1, engine_hash_mb: 16 }
    if (form.default_config.format === 'gauntlet') form.default_config = defaultCategorySettings()
    options.value = { engines: response.engine_options ?? [], openings: response.opening_suites ?? [] }
    tournaments.value = response.tournaments ?? []
  } catch (cause) { error.value = errorText(cause) }
  finally { loading.value = false }
}

function validate(): string {
  if (!form.name.trim()) return 'Enter a category name.'
  if (form.default_config.format === 'gauntlet') return 'Gauntlet cannot be a category default because its hero is tournament-specific.'
  if (!Number.isInteger(form.default_config.concurrency) || form.default_config.concurrency < 1) return 'Concurrent games must be a whole number of at least 1.'
  if (!Number.isInteger(form.default_config.engine_threads) || form.default_config.engine_threads < 1) return 'Engine threads must be a whole number of at least 1.'
  if (!Number.isInteger(form.default_config.engine_hash_mb) || form.default_config.engine_hash_mb < 1) return 'Engine hash must be a whole number of at least 1 MB.'
  return ''
}

function updateCategorySettings(value: TournamentSettings): void {
  form.default_config = { ...form.default_config, ...value }
}

async function save(): Promise<void> {
  error.value = validate()
  if (error.value) return
  pending.value = true
  const body = { name: form.name.trim(), description: form.description.trim(), active: form.active, default_config: form.default_config }
  try {
    const response = id.value ? await api.put<{ message: string }>(`/api/admin/categories/${id.value}`, { body }) : await api.post<{ id: number; message: string }>('/api/admin/categories', { body })
    toast.success(response.message)
    await router.push('/admin/categories')
  } catch (cause) { error.value = errorText(cause); toast.error(cause) }
  finally { pending.value = false }
}
onMounted(load)
</script>

<template>
  <div class="admin-page page-stack">
    <AdminPageHeader :title="id ? `Edit ${form.name || 'category'}` : 'New rating category'">
      <template #actions><RouterLink class="button button--ghost" to="/admin/categories">Back to categories</RouterLink></template>
    </AdminPageHeader>
    <InlineFeedback :message="error" />
    <div v-if="loading" class="panel form-loading" role="status">Loading category…</div>
    <form v-else class="category-form" novalidate @submit.prevent="save">
      <section class="panel form-card">
        <div class="form-card__heading"><h2>Category identity</h2></div>
        <div class="form-grid">
          <label class="field"><span>Name</span><input v-model="form.name" class="input" required maxlength="80"></label>
          <label class="field"><span>Description <small>optional</small></span><input v-model="form.description" class="input" maxlength="240"></label>
          <label class="switch-row form-span-full"><input v-model="form.active" type="checkbox"><span><strong>Active category</strong></span></label>
        </div>
      </section>
      <section class="panel form-card">
        <div class="form-card__heading"><h2>Category rules</h2></div>
        <TournamentSettingsEditor :model-value="form.default_config" :opening-suites="options.openings" :engines="options.engines" :allow-gauntlet="false" :allow-format="false" :allow-concurrency="false" :allow-opening-suite="false" id-prefix="category" @update:model-value="updateCategorySettings" />
        <div class="form-grid category-resources">
          <label class="field"><span>Threads per engine</span><input v-model.number="form.default_config.engine_threads" class="input" type="number" min="1" step="1"></label>
          <label class="field"><span>Hash per engine <small>MB</small></span><input v-model.number="form.default_config.engine_hash_mb" class="input" type="number" min="1" step="1"></label>
        </div>
      </section>
      <div class="form-actions"><RouterLink class="button button--ghost" to="/admin/categories">Cancel</RouterLink><button class="button button--primary" type="submit" :disabled="pending">{{ pending ? 'Saving…' : id ? 'Save changes' : 'Create category' }}</button></div>
    </form>

    <section v-if="id && tournaments.length" class="panel related-panel">
      <div class="related-panel__heading"><h2>Tournaments in this category</h2><span>{{ tournaments.length }}</span></div>
      <RouterLink v-for="tournament in tournaments" :key="tournament.id" :to="`/admin/tournaments/${tournament.id}`"><span>{{ tournament.name }}</span><StatusBadge :status="tournament.status" /></RouterLink>
    </section>
  </div>
</template>

<style scoped>
.category-form { display: grid; gap: 1rem; }
.form-card { display: grid; gap: 1rem; padding: clamp(1rem, 2vw, 1.35rem); }
.form-card__heading { border-bottom: 1px solid var(--color-border, #d9e0ea); padding-bottom: .8rem; }
.form-card__heading h2, .related-panel h2 { font-size: .95rem; margin: 0; }
.form-card__heading p { color: var(--color-text-muted, #64748b); font-size: .75rem; line-height: 1.45; margin: .25rem 0 0; max-width: 75ch; }
.form-grid { display: grid; gap: .85rem; grid-template-columns: repeat(2, minmax(0, 1fr)); }
.form-span-full { grid-column: 1 / -1; }
.field { display: grid; gap: .38rem; }
.field > span { font-size: .8rem; font-weight: 650; }
.field small { color: var(--color-text-muted, #64748b); font-size: .7rem; font-weight: 500; }
.category-resources { border-top: 1px solid var(--color-border, #d9e0ea); padding-top: 1.1rem; }
.switch-row { align-items: flex-start; cursor: pointer; display: flex; gap: .6rem; }
.switch-row input { height: 1rem; margin-top: .12rem; width: 1rem; }
.switch-row span { display: grid; gap: .15rem; }
.switch-row strong { font-size: .8rem; }
.switch-row small { color: var(--color-text-muted, #64748b); font-size: .72rem; }
.form-actions { display: flex; gap: .6rem; justify-content: flex-end; }
.form-loading { color: var(--color-text-muted, #64748b); min-height: 16rem; padding: 2rem; }
.related-panel { overflow: hidden; padding: 0; }
.related-panel__heading, .related-panel > a { align-items: center; display: flex; gap: .8rem; justify-content: space-between; padding: .75rem 1rem; }
.related-panel__heading { border-bottom: 1px solid var(--color-border, #d9e0ea); }
.related-panel__heading span { color: var(--color-text-muted, #64748b); font-size: .72rem; }
.related-panel > a { border-bottom: 1px solid var(--color-border, #d9e0ea); color: inherit; font-size: .78rem; text-decoration: none; }
.related-panel > a:last-child { border-bottom: 0; }
@media (max-width: 40rem) { .form-grid { grid-template-columns: 1fr; } .form-span-full { grid-column: auto; } }
</style>
