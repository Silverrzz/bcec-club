<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '@/api/client'
import { useConfirm } from '@/composables/useConfirm'
import { useToast } from '@/composables/useToast'
import AdminEmptyState from '@/components/admin/AdminEmptyState.vue'
import AdminPageHeader from '@/components/admin/AdminPageHeader.vue'
import InlineFeedback from '@/components/admin/InlineFeedback.vue'
import { errorText, formatDate, formatNumber } from '@/components/admin/format'
import type { OpeningSuite } from '@/components/admin/types'

interface Response { suites: OpeningSuite[]; opening_counts: Record<string, number>; usage_counts: Record<string, number> }
const toast = useToast()
const { confirm } = useConfirm()
const data = ref<Response | null>(null)
const loading = ref(true)
const error = ref('')
const deleting = ref<number | null>(null)

async function load(): Promise<void> {
  loading.value = true
  try { data.value = await api.get<Response>('/api/admin/openings') }
  catch (cause) { error.value = errorText(cause) }
  finally { loading.value = false }
}

async function remove(suite: OpeningSuite): Promise<void> {
  const usage = data.value?.usage_counts[String(suite.id)] ?? 0
  if (usage > 0) return
  const accepted = await confirm({ title: 'Delete opening suite?', message: `Delete “${suite.name}” and every position in it?`, confirmLabel: 'Delete suite', tone: 'danger' })
  if (!accepted) return
  deleting.value = suite.id
  try { const response = await api.delete<{ message: string }>(`/api/admin/openings/${suite.id}`); toast.success(response.message); await load() }
  catch (cause) { error.value = errorText(cause); toast.error(cause) }
  finally { deleting.value = null }
}
onMounted(load)
</script>

<template>
  <div class="admin-page page-stack">
    <AdminPageHeader title="Opening suites">
      <template #actions><RouterLink class="button button--primary" to="/admin/openings/new">Import suite</RouterLink></template>
    </AdminPageHeader>
    <InlineFeedback :message="error" />
    <section class="panel opening-panel">
      <div v-if="loading" class="index-loading" role="status">Loading opening suites…</div>
      <div v-else-if="data?.suites.length" class="suite-grid">
        <article v-for="suite in data.suites" :key="suite.id" class="suite-card">
          <div class="suite-card__cover" aria-hidden="true"><svg viewBox="0 0 48 48"><path d="M10 8h22a6 6 0 0 1 6 6v26H16a6 6 0 0 1-6-6V8Zm6 32a6 6 0 0 1 0-12h22M18 16h12M18 21h8" /></svg></div>
          <div class="suite-card__body"><div><h2>{{ suite.name }}</h2><p v-if="suite.description">{{ suite.description }}</p></div><dl><div><dt>Positions</dt><dd>{{ formatNumber(data.opening_counts[String(suite.id)]) }}</dd></div><div><dt>Used by</dt><dd>{{ formatNumber(data.usage_counts[String(suite.id)]) }} tournaments</dd></div><div><dt>Created</dt><dd>{{ formatDate(suite.created_at) }}</dd></div></dl></div>
          <div class="suite-card__actions"><RouterLink class="button button--secondary button--small" :to="`/admin/openings/${suite.id}`">Edit and import</RouterLink><button class="button button--danger button--small" type="button" :disabled="deleting === suite.id || (data.usage_counts[String(suite.id)] ?? 0) > 0" :title="(data.usage_counts[String(suite.id)] ?? 0) > 0 ? 'This suite is referenced by a tournament.' : 'Delete opening suite'" @click="remove(suite)">{{ deleting === suite.id ? 'Deleting…' : 'Delete' }}</button></div>
        </article>
      </div>
      <AdminEmptyState v-else title="No opening suites"><RouterLink class="button button--primary button--small" to="/admin/openings/new">Import suite</RouterLink></AdminEmptyState>
    </section>
  </div>
</template>

<style scoped>
.opening-panel { overflow: hidden; padding: 0; }
.suite-grid { display: grid; gap: .8rem; grid-template-columns: repeat(auto-fill, minmax(min(100%, 23rem), 1fr)); padding: .8rem; }
.suite-card { border: 1px solid var(--color-border, #d9e0ea); border-radius: var(--radius-md, .6rem); display: grid; gap: .9rem; grid-template-columns: auto minmax(0, 1fr); padding: .9rem; }
.suite-card__cover { align-items: center; background: linear-gradient(145deg, color-mix(in srgb, var(--color-accent, #315fcc) 16%, transparent), var(--color-surface-subtle, #f1f5f9)); border-radius: .55rem; color: var(--color-accent, #315fcc); display: flex; height: 5.5rem; justify-content: center; width: 4.5rem; }
.suite-card__cover svg { fill: none; height: 2.5rem; stroke: currentColor; stroke-linecap: round; stroke-linejoin: round; stroke-width: 1.5; width: 2.5rem; }
.suite-card__body { display: grid; gap: .7rem; min-width: 0; }
.suite-card h2 { font-size: .9rem; margin: 0; }
.suite-card p { color: var(--color-text-muted, #64748b); font-size: .72rem; line-height: 1.4; margin: .22rem 0 0; }
.suite-card dl { display: flex; flex-wrap: wrap; gap: .7rem 1.1rem; margin: 0; }
.suite-card dl div { display: grid; gap: .12rem; }
.suite-card dt { color: var(--color-text-muted, #64748b); font-size: .61rem; text-transform: uppercase; }
.suite-card dd { font-size: .7rem; font-weight: 650; margin: 0; }
.suite-card__actions { display: flex; gap: .5rem; grid-column: 1 / -1; }
.index-loading { color: var(--color-text-muted, #64748b); min-height: 14rem; padding: 2rem; }
</style>
