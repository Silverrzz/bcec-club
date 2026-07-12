<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@/api/client'
import { useConfirm } from '@/composables/useConfirm'
import { useToast } from '@/composables/useToast'
import AdminEmptyState from '@/components/admin/AdminEmptyState.vue'
import AdminPageHeader from '@/components/admin/AdminPageHeader.vue'
import InlineFeedback from '@/components/admin/InlineFeedback.vue'
import StatusBadge from '@/components/admin/StatusBadge.vue'
import TournamentConfigForm from '@/components/admin/TournamentConfigForm.vue'
import { errorText, formatDate, formatTimeControl, humanize } from '@/components/admin/format'
import type { Category, Engine, FormSeed, Game, Tournament, TournamentConfig } from '@/components/admin/types'

interface Commit { status: string; requested_at: string; applied_at?: string | null; error?: string | null }
interface Response {
  tournament: Tournament
  games: Game[]
  engines: Engine[] | Record<string, Engine | string>
  category?: Category | null
  settings?: Array<[string, string] | { label: string; value: string }> | Record<string, string>
  commit?: Commit | null
  actions: Record<string, string>
  form?: FormSeed
  dependency_status?: { blocked_games: number; required_dependencies: string[]; missing_dependencies: string[] }
}

const route = useRoute()
const router = useRouter()
const toast = useToast()
const { confirm } = useConfirm()
const data = ref<Response | null>(null)
const loading = ref(true)
const error = ref('')
const pending = ref('')
const id = computed(() => Number(route.params.id))
const settingsRows = computed(() => {
  if (!data.value?.settings) return []
  return Array.isArray(data.value.settings)
    ? data.value.settings.map((row) => Array.isArray(row) ? row : [row.label, row.value] as [string, string])
    : Object.entries(data.value.settings)
})

function engineName(engineId: number): string {
  const engines = data.value?.engines
  if (Array.isArray(engines)) return engines.find((engine) => (engine.id ?? engine.engine_id) === engineId)?.name ?? `Engine ${engineId}`
  const engine = engines?.[String(engineId)]
  return typeof engine === 'string' ? engine : engine?.name ?? `Engine ${engineId}`
}

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try { data.value = await api.get<Response>(`/api/admin/tournaments/${id.value}`) }
  catch (cause) { error.value = errorText(cause) }
  finally { loading.value = false }
}

async function changeStatus(action: string): Promise<void> {
  if (action === 'abort') {
    const accepted = await confirm({ title: 'Abort tournament?', message: `Abort “${data.value?.tournament.name}”? Unfinished games will not be played.`, confirmLabel: 'Abort tournament', tone: 'danger' })
    if (!accepted) return
  }
  pending.value = action
  try {
    const response = await api.post<{ message: string }>(`/api/admin/tournaments/${id.value}/status`, { body: { action } })
    toast.success(response.message)
    await load()
  } catch (cause) { error.value = errorText(cause); toast.error(cause) }
  finally { pending.value = '' }
}

async function saveDraft(payload: { name: string; config: TournamentConfig }): Promise<void> {
  pending.value = 'save'
  try {
    const response = await api.put<{ message: string }>(`/api/admin/tournaments/${id.value}`, { body: payload })
    toast.success(response.message)
    await load()
  } catch (cause) { error.value = errorText(cause); toast.error(cause) }
  finally { pending.value = '' }
}

async function commitRatings(): Promise<void> {
  const accepted = await confirm({
    title: 'Commit rating results?',
    message: `Apply ${data.value?.tournament.name ?? 'this tournament'} to the category ratings? Applied rating results are permanent.`,
    confirmLabel: 'Commit ratings',
  })
  if (!accepted) return
  pending.value = 'commit'
  try {
    const response = await api.post<{ message: string }>(`/api/admin/tournaments/${id.value}/commit-results`)
    toast.success(response.message)
    await load()
  } catch (cause) { error.value = errorText(cause); toast.error(cause) }
  finally { pending.value = '' }
}

async function remove(): Promise<void> {
  if (!data.value) return
  const accepted = await confirm({ title: 'Delete tournament?', message: `Delete “${data.value.tournament.name}” and every associated game? This cannot be undone.`, confirmLabel: 'Delete tournament', tone: 'danger' })
  if (!accepted) return
  pending.value = 'delete'
  try {
    const response = await api.delete<{ message: string }>(`/api/admin/tournaments/${id.value}`)
    toast.success(response.message)
    await router.push('/admin/tournaments')
  } catch (cause) { error.value = errorText(cause); toast.error(cause) }
  finally { pending.value = '' }
}

onMounted(load)
</script>

<template>
  <div class="admin-page page-stack">
    <div v-if="loading" class="panel detail-loading" role="status">Loading tournament…</div>
    <template v-else-if="data">
      <AdminPageHeader :title="data.tournament.name" :description="`${data.category?.name ?? 'Custom tournament'} · Created ${formatDate(data.tournament.created_at)}`">
        <template #actions><RouterLink class="button button--ghost" to="/admin/tournaments">All tournaments</RouterLink><RouterLink class="button button--secondary" :to="`/tournaments/${id}`">Public page</RouterLink></template>
      </AdminPageHeader>
      <InlineFeedback :message="error" />
      <section v-if="data.dependency_status?.blocked_games" class="panel dependency-warning" role="status"><div><h2>Waiting for worker dependencies</h2><p>{{ data.dependency_status.blocked_games }} pending game{{ data.dependency_status.blocked_games === 1 ? '' : 's' }} currently has no capable connected worker.</p></div><code>{{ (data.dependency_status.missing_dependencies.length ? data.dependency_status.missing_dependencies : data.dependency_status.required_dependencies).join(', ') }}</code></section>

      <section class="panel control-bar">
        <div class="control-bar__status"><span>Current state</span><StatusBadge :status="data.tournament.status" /></div>
        <div class="control-bar__actions">
          <button v-for="(_, action) in data.actions" :key="action" class="button" :class="action === 'abort' ? 'button--danger' : 'button--primary'" type="button" :disabled="!!pending" @click="changeStatus(String(action))">{{ pending === action ? 'Working…' : humanize(String(action)) }}</button>
          <button v-if="data.tournament.status === 'finished' && data.tournament.config.rated && data.tournament.category_id !== null && (!data.commit || data.commit.status === 'failed')" class="button button--primary" type="button" :disabled="!!pending" @click="commitRatings">{{ pending === 'commit' ? 'Requesting…' : data.commit ? 'Retry rating commit' : 'Commit ratings' }}</button>
          <button v-if="!['scheduled', 'running'].includes(data.tournament.status) && (!data.commit || data.commit.status === 'failed')" class="button button--danger" type="button" :disabled="!!pending" @click="remove">{{ pending === 'delete' ? 'Deleting…' : 'Delete' }}</button>
        </div>
      </section>

      <section v-if="data.commit" class="panel commit-panel">
        <div><h2>Rating commit</h2><p>Requested {{ formatDate(data.commit.requested_at) }}<template v-if="data.commit.applied_at"> · Applied {{ formatDate(data.commit.applied_at) }}</template></p></div>
        <StatusBadge :status="data.commit.status" />
        <p v-if="data.commit.error" class="commit-panel__error" role="alert">{{ data.commit.error }}</p>
      </section>

      <TournamentConfigForm v-if="data.tournament.status === 'draft' && data.form" :seed="data.form" :pending="pending === 'save'" submit-label="Save draft" @submit="saveDraft" @cancel="router.push('/admin/tournaments')" />

      <section v-else class="panel settings-panel">
        <div class="settings-panel__heading"><div><h2>Settings</h2></div><span v-if="data.tournament.settings_unlinked">Custom settings</span></div>
        <dl v-if="settingsRows.length" class="definition-list">
          <div v-for="([label, value], index) in settingsRows" :key="`${label}-${index}`"><dt>{{ label }}</dt><dd>{{ value }}</dd></div>
        </dl>
        <dl v-else class="definition-list">
          <div><dt>Format</dt><dd>{{ humanize(data.tournament.config.format) }}</dd></div>
          <div><dt>Time control</dt><dd>{{ formatTimeControl(data.tournament.config.time_control) }}</dd></div>
          <div><dt>Participants</dt><dd>{{ data.tournament.config.participants.length }}</dd></div>
          <div><dt>Concurrency</dt><dd>{{ data.tournament.config.concurrency }}</dd></div>
          <div><dt>Engine threads</dt><dd>{{ data.tournament.config.engine_threads }}</dd></div>
          <div><dt>Hash per engine</dt><dd>{{ data.tournament.config.engine_hash_mb }} MB</dd></div>
          <div><dt>Ratings</dt><dd>{{ data.tournament.config.rated ? 'Rated' : 'Unrated' }}</dd></div>
        </dl>
      </section>

      <section class="panel games-panel">
        <div class="games-panel__heading"><div><h2>Games</h2><p>{{ data.games.length }} generated game{{ data.games.length === 1 ? '' : 's' }}</p></div></div>
        <div v-if="data.games.length" class="game-table-wrap">
          <table class="data-table"><thead><tr><th>Round</th><th>White</th><th>Result</th><th>Black</th><th>Status</th><th>Finished</th></tr></thead><tbody>
            <tr v-for="game in data.games" :key="game.id">
              <td>{{ game.round }}</td><td><RouterLink :to="`/tournaments/${id}?game_id=${game.id}`">{{ engineName(game.white_engine_id) }}</RouterLink></td><td><strong>{{ game.result ?? 'vs' }}</strong></td><td>{{ engineName(game.black_engine_id) }}</td><td><StatusBadge :status="game.status" /></td><td>{{ formatDate(game.finished_at) }}</td>
            </tr>
          </tbody></table>
        </div>
        <AdminEmptyState v-else title="No games generated" />
      </section>
    </template>
    <InlineFeedback v-else :message="error" />
  </div>
</template>

<style scoped>
.detail-loading { color: var(--color-text-muted, #64748b); min-height: 18rem; padding: 2rem; }
.control-bar { align-items: center; display: flex; gap: 1rem; justify-content: space-between; padding: .8rem 1rem; }
.dependency-warning { align-items: center; background: color-mix(in srgb, var(--color-warning, #b7791f) 8%, var(--color-surface, #fff)); border-color: color-mix(in srgb, var(--color-warning, #b7791f) 30%, var(--color-border, #d9e0ea)); display: flex; gap: 1rem; justify-content: space-between; padding: .85rem 1rem; }.dependency-warning h2 { font-size: .85rem; margin: 0; }.dependency-warning p { color: var(--color-text-muted, #64748b); font-size: .72rem; margin: .2rem 0 0; }.dependency-warning code { font-size: .72rem; }
.control-bar__status { align-items: center; display: flex; gap: .65rem; }
.control-bar__status > span { color: var(--color-text-muted, #64748b); font-size: .72rem; font-weight: 650; }
.control-bar__actions { display: flex; flex-wrap: wrap; gap: .5rem; justify-content: flex-end; }
.commit-panel { align-items: center; display: grid; gap: 1rem; grid-template-columns: minmax(0, 1fr) auto; padding: 1rem; }
.commit-panel h2, .settings-panel h2, .games-panel h2 { font-size: .92rem; margin: 0; }
.commit-panel p, .settings-panel__heading p, .games-panel__heading p { color: var(--color-text-muted, #64748b); font-size: .73rem; margin: .2rem 0 0; }
.commit-panel__error { background: color-mix(in srgb, var(--color-danger, #b42318) 8%, transparent); border-radius: .4rem; color: var(--color-danger, #b42318) !important; grid-column: 1 / -1; padding: .65rem; }
.settings-panel, .games-panel { overflow: hidden; padding: 0; }
.settings-panel__heading, .games-panel__heading { align-items: center; border-bottom: 1px solid var(--color-border, #d9e0ea); display: flex; justify-content: space-between; padding: .85rem 1rem; }
.settings-panel__heading > span { background: var(--color-surface-subtle, #f1f5f9); border-radius: 999px; color: var(--color-text-muted, #64748b); font-size: .68rem; font-weight: 650; padding: .3rem .5rem; }
.definition-list { display: grid; grid-template-columns: repeat(auto-fit, minmax(13rem, 1fr)); margin: 0; padding: .35rem 1rem 1rem; }
.definition-list div { border-bottom: 1px solid var(--color-border, #d9e0ea); padding: .7rem 0; }
.definition-list dt { color: var(--color-text-muted, #64748b); font-size: .68rem; }
.definition-list dd { font-size: .78rem; font-weight: 650; margin: .2rem 0 0; }
.game-table-wrap { overflow-x: auto; }
.data-table { border-collapse: collapse; min-width: 48rem; width: 100%; }
.data-table th { color: var(--color-text-muted, #64748b); font-size: .65rem; letter-spacing: .04em; padding: .65rem .8rem; text-align: left; text-transform: uppercase; }
.data-table td { border-top: 1px solid var(--color-border, #d9e0ea); font-size: .76rem; padding: .7rem .8rem; }
@media (max-width: 42rem) { .control-bar { align-items: stretch; flex-direction: column; } .control-bar__actions { justify-content: flex-start; } }
</style>
