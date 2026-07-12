<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '@/api/client'
import { useConfirm } from '@/composables/useConfirm'
import { useToast } from '@/composables/useToast'
import AdminEmptyState from '@/components/admin/AdminEmptyState.vue'
import AdminPageHeader from '@/components/admin/AdminPageHeader.vue'
import InlineFeedback from '@/components/admin/InlineFeedback.vue'
import StatusBadge from '@/components/admin/StatusBadge.vue'
import { errorText, formatNumber } from '@/components/admin/format'
import type { Engine } from '@/components/admin/types'

interface Response { engines: Engine[]; game_counts: Record<string, number> }
const toast = useToast()
const { confirm } = useConfirm()
const data = ref<Response | null>(null)
const loading = ref(true)
const error = ref('')
const query = ref('')
const activeOnly = ref(false)
const deleting = ref<number | null>(null)

const filtered = computed(() => {
  const needle = query.value.trim().toLocaleLowerCase()
  return (data.value?.engines ?? []).filter((engine) =>
    (!activeOnly.value || engine.active) && (!needle || `${engine.name} ${engine.author ?? ''} ${engine.version ?? ''}`.toLocaleLowerCase().includes(needle)),
  )
})

async function load(): Promise<void> {
  loading.value = true
  try { data.value = await api.get<Response>('/api/admin/engines') }
  catch (cause) { error.value = errorText(cause) }
  finally { loading.value = false }
}

async function remove(engine: Engine): Promise<void> {
  const count = data.value?.game_counts[String(engine.id)] ?? 0
  if (count > 0) return
  const accepted = await confirm({
    title: 'Delete engine?',
    message: `Delete “${engine.name}”? This cannot be undone.`,
    confirmLabel: 'Delete engine', tone: 'danger',
  })
  if (!accepted) return
  deleting.value = engine.id
  try {
    const response = await api.delete<{ message: string }>(`/api/admin/engines/${engine.id}`)
    toast.success(response.message)
    await load()
  } catch (cause) { error.value = errorText(cause); toast.error(cause) }
  finally { deleting.value = null }
}

onMounted(load)
</script>

<template>
  <div class="admin-page page-stack">
    <AdminPageHeader title="Engines">
      <template #actions><RouterLink class="button button--primary" to="/admin/engines/new">Register engine</RouterLink></template>
    </AdminPageHeader>
    <InlineFeedback :message="error" />
    <section class="panel engine-index">
      <div class="engine-index__toolbar">
        <label class="search-field"><span class="sr-only">Search engines</span><svg aria-hidden="true" viewBox="0 0 24 24"><circle cx="11" cy="11" r="6.5" /><path d="m16 16 4 4" /></svg><input v-model="query" class="input" type="search" placeholder="Search engine, author, or version"></label>
        <label class="active-filter"><input v-model="activeOnly" type="checkbox"><span>Active only</span></label>
        <span class="engine-count">{{ filtered.length }} engine{{ filtered.length === 1 ? '' : 's' }}</span>
      </div>
      <div v-if="loading" class="index-loading" role="status">Loading engines…</div>
      <div v-else-if="filtered.length" class="engine-grid">
        <article v-for="engine in filtered" :key="engine.id" class="engine-card">
          <div class="engine-card__heading">
            <span class="engine-card__mark" aria-hidden="true">{{ engine.name.slice(0, 1).toUpperCase() }}</span>
            <div><h2>{{ engine.name }}</h2><p v-if="engine.author || engine.version">{{ [engine.author, engine.version].filter(Boolean).join(' · ') }}</p></div>
            <StatusBadge :status="engine.active ? 'active' : 'inactive'" />
          </div>
          <dl>
            <div><dt>Games</dt><dd>{{ formatNumber(data?.game_counts[String(engine.id)]) }}</dd></div>
            <div><dt>Branch</dt><dd>{{ engine.branch || 'Default' }}</dd></div>
            <div><dt>Commit</dt><dd><code>{{ engine.commit.slice(0, 10) }}</code></dd></div>
            <div><dt>UCI options</dt><dd>{{ Object.keys(engine.uci_options ?? {}).length }}</dd></div>
          </dl>
          <div class="engine-card__source"><span>Source</span><a :href="engine.git_url" target="_blank" rel="noreferrer">{{ engine.git_url.replace(/^https?:\/\//, '') }}</a></div>
          <div class="engine-card__actions">
            <RouterLink class="button button--secondary button--small" :to="`/admin/engines/${engine.id}/edit`">Edit</RouterLink>
            <button class="button button--danger button--small" type="button" :disabled="deleting === engine.id || (data?.game_counts[String(engine.id)] ?? 0) > 0" :title="(data?.game_counts[String(engine.id)] ?? 0) > 0 ? 'Deactivate engines with recorded games instead of deleting them.' : 'Delete engine'" @click="remove(engine)">{{ deleting === engine.id ? 'Deleting…' : 'Delete' }}</button>
          </div>
        </article>
      </div>
      <AdminEmptyState v-else :title="query || activeOnly ? 'No matching engines' : 'No engines registered'">
        <RouterLink v-if="!query && !activeOnly" class="button button--primary button--small" to="/admin/engines/new">Register engine</RouterLink>
      </AdminEmptyState>
    </section>
  </div>
</template>

<style scoped>
.engine-index { overflow: hidden; padding: 0; }
.engine-index__toolbar { align-items: center; border-bottom: 1px solid var(--color-border, #d9e0ea); display: flex; gap: .75rem; padding: .75rem; }
.search-field { flex: 1 1 20rem; max-width: 28rem; position: relative; }
.search-field svg { fill: none; height: 1rem; left: .7rem; position: absolute; stroke: var(--color-text-muted, #64748b); stroke-width: 1.8; top: 50%; transform: translateY(-50%); width: 1rem; }
.search-field input { padding-left: 2.1rem; width: 100%; }
.active-filter { align-items: center; cursor: pointer; display: flex; font-size: .76rem; gap: .4rem; }
.engine-count { color: var(--color-text-muted, #64748b); font-size: .72rem; margin-left: auto; }
.engine-grid { display: grid; gap: .8rem; grid-template-columns: repeat(auto-fill, minmax(min(100%, 19rem), 1fr)); padding: .8rem; }
.engine-card { border: 1px solid var(--color-border, #d9e0ea); border-radius: var(--radius-md, .6rem); display: grid; gap: .8rem; min-width: 0; padding: .9rem; }
.engine-card__heading { align-items: center; display: grid; gap: .65rem; grid-template-columns: auto minmax(0, 1fr) auto; }
.engine-card__mark { align-items: center; background: color-mix(in srgb, var(--color-accent, #315fcc) 10%, transparent); border-radius: .5rem; color: var(--color-accent, #315fcc); display: flex; font-size: .9rem; font-weight: 750; height: 2.1rem; justify-content: center; width: 2.1rem; }
.engine-card h2 { font-size: .88rem; margin: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.engine-card__heading p { color: var(--color-text-muted, #64748b); font-size: .68rem; margin: .18rem 0 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.engine-card dl { display: grid; grid-template-columns: repeat(2, 1fr); margin: 0; }
.engine-card dl div { border-top: 1px solid var(--color-border, #d9e0ea); display: grid; gap: .18rem; padding: .55rem 0; }
.engine-card dt, .engine-card__source > span { color: var(--color-text-muted, #64748b); font-size: .64rem; text-transform: uppercase; }
.engine-card dd { font-size: .75rem; font-weight: 650; margin: 0; }
.engine-card__source { display: grid; gap: .2rem; min-width: 0; }
.engine-card__source a { font-size: .7rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.engine-card__actions { display: flex; gap: .5rem; margin-top: auto; }
.index-loading { color: var(--color-text-muted, #64748b); min-height: 14rem; padding: 2rem; }
@media (max-width: 38rem) { .engine-index__toolbar { align-items: stretch; flex-wrap: wrap; } .search-field { flex-basis: 100%; max-width: none; } }
</style>
