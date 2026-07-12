<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@/api/client'
import { useConfirm } from '@/composables/useConfirm'
import { useToast } from '@/composables/useToast'
import AdminPageHeader from '@/components/admin/AdminPageHeader.vue'
import InlineFeedback from '@/components/admin/InlineFeedback.vue'
import StatusBadge from '@/components/admin/StatusBadge.vue'
import WorkerTokenPanel from '@/components/admin/WorkerTokenPanel.vue'
import { errorText, formatDate, formatNumber } from '@/components/admin/format'
import type { Worker, WorkerRow } from '@/components/admin/types'

interface WorkerFailure { id: number; worker_id: number | null; worker_label: string; pool_id: number | null; machine_id: string | null; assignment_id: number | null; game_id: number | null; engine_id: number | null; engine_name: string; stage: string; error: string; occurred_at: string }
interface Response { row: WorkerRow; worker: Worker; worker_launch_command?: string | null; failures: WorkerFailure[] }
interface Minted { token: string; expires_at: string; start_command?: string; message: string }
interface WorkerTokenBindings { token: string; expiresAt: string; startCommand?: string }
const route = useRoute()
const router = useRouter()
const toast = useToast()
const { confirm } = useConfirm()
const id = computed(() => Number(route.params.id))
const data = ref<Response | null>(null)
const minted = ref<Minted | null>(null)
const loading = ref(true)
const error = ref('')
const pending = ref('')
const label = ref('')
const copied = ref(false)
const streamConnected = ref(false)
let source: EventSource | null = null

function workerTokenBindings(value: Minted): WorkerTokenBindings {
  const bindings: WorkerTokenBindings = { token: value.token, expiresAt: value.expires_at }
  if (value.start_command !== undefined) bindings.startCommand = value.start_command
  return bindings
}

async function load(background = false): Promise<void> {
  if (!background) loading.value = true
  try { const response = await api.get<Response>(`/api/admin/workers/${id.value}`); data.value = response; label.value = response.worker.label }
  catch (cause) { error.value = errorText(cause) }
  finally { if (!background) loading.value = false }
}

function connectStream(): void {
  source?.close()
  source = new EventSource(`/admin/workers/${id.value}/events`)
  source.addEventListener('open', () => { streamConnected.value = true })
  source.addEventListener('error', () => { streamConnected.value = false })
  source.addEventListener('worker.snapshot', (event) => {
    try {
      const envelope = JSON.parse((event as MessageEvent<string>).data) as { data?: Response & { deleted?: boolean } }
      if (envelope.data?.deleted) { void router.replace('/admin/workers'); return }
      if (!envelope.data?.worker || !envelope.data.row) return
      data.value = envelope.data
      if (pending.value !== 'label') label.value = envelope.data.worker.label
    } catch { /* Keep the last complete worker snapshot. */ }
  })
}

async function rename(): Promise<void> {
  if (!label.value.trim()) { error.value = 'Enter a worker label.'; return }
  pending.value = 'label'
  try { const response = await api.put<{ message: string }>(`/api/admin/workers/${id.value}/label`, { body: { label: label.value.trim() } }); toast.success(response.message); await load() }
  catch (cause) { error.value = errorText(cause); toast.error(cause) }
  finally { pending.value = '' }
}

async function generateToken(): Promise<void> {
  const accepted = minted.value ? await confirm({ title: 'Replace one-time token?', message: 'The token currently visible on this page will stop working. The replacement will also be shown only once.', confirmLabel: 'Generate replacement' }) : true
  if (!accepted) return
  pending.value = 'token'
  try { const response = await api.post<Minted>(`/api/admin/workers/${id.value}/token`, { body: { ttl_seconds: 7200 } }); minted.value = response; toast.success(response.message); await load() }
  catch (cause) { error.value = errorText(cause); toast.error(cause) }
  finally { pending.value = '' }
}

async function revoke(): Promise<void> {
  const accepted = await confirm({ title: 'Revoke worker?', message: `Revoke “${data.value?.worker.label}”? It will be removed and cannot reconnect with its current credentials.`, confirmLabel: 'Revoke worker', tone: 'danger' })
  if (!accepted) return
  pending.value = 'revoke'
  try { const response = await api.post<{ message: string }>(`/api/admin/workers/${id.value}/revoke`); toast.success(response.message); minted.value = null; await router.push('/admin/workers') }
  catch (cause) { error.value = errorText(cause); toast.error(cause) }
  finally { pending.value = '' }
}

async function remove(): Promise<void> {
  const accepted = await confirm({ title: 'Delete worker?', message: `Permanently delete “${data.value?.worker.label}”?`, confirmLabel: 'Delete worker', tone: 'danger' })
  if (!accepted) return
  pending.value = 'delete'
  try { const response = await api.delete<{ message: string }>(`/api/admin/workers/${id.value}`); toast.success(response.message); await router.push('/admin/workers') }
  catch (cause) { error.value = errorText(cause); toast.error(cause) }
  finally { pending.value = '' }
}

async function copy(value: string): Promise<void> { await navigator.clipboard.writeText(value); copied.value = true; window.setTimeout(() => { copied.value = false }, 1600) }
onMounted(async () => { await load(); connectStream() })
onBeforeUnmount(() => source?.close())
</script>

<template>
  <div class="admin-page page-stack">
    <InlineFeedback :message="error" />
    <div v-if="loading" class="panel detail-loading" role="status">Loading worker…</div>
    <template v-else-if="data">
      <AdminPageHeader :title="data.worker.label" :description="`Worker #${data.worker.id} · Last seen ${formatDate(data.worker.last_seen)}`">
        <template #actions><span class="live-state"><span :class="{ connected: streamConnected }" aria-hidden="true"></span>{{ streamConnected ? 'Live' : 'Reconnecting' }}</span><RouterLink class="button button--ghost" to="/admin/workers">All workers</RouterLink></template>
      </AdminPageHeader>
      <WorkerTokenPanel v-if="minted" v-bind="workerTokenBindings(minted)" />

      <section class="panel current-work">
        <div><span>Current work</span><h2>{{ data.row.work?.summary ?? 'No active assignment' }}</h2><p v-if="data.row.status !== 'ready'">{{ data.row.work?.detail || 'The scheduler has not assigned a game.' }}</p><small v-if="data.row.work?.meta">{{ data.row.work.meta }}</small></div>
        <StatusBadge :status="data.row.status" />
      </section>

      <section v-if="data.failures.length" class="panel failure-panel" aria-labelledby="worker-failures-title">
        <div class="failure-panel__heading">
          <div><h2 id="worker-failures-title">Engine failures</h2><p>The newest download, verification, or runtime failure is shown first.</p></div>
          <span>{{ data.failures.length }} recent</span>
        </div>
        <details v-for="(failure, index) in data.failures" :key="failure.id" class="failure-entry" :open="index === 0">
          <summary>
            <span><strong>{{ failure.engine_name }}</strong><small>{{ failure.stage }} failed</small></span>
            <time :datetime="failure.occurred_at">{{ formatDate(failure.occurred_at) }}</time>
          </summary>
          <div class="failure-entry__body">
            <dl>
              <div><dt>Worker</dt><dd>{{ failure.worker_label }} (#{{ failure.worker_id ?? data.worker.id }})</dd></div>
              <div><dt>Machine</dt><dd>{{ failure.machine_id ?? 'Unknown' }}</dd></div>
              <div><dt>Pool</dt><dd>{{ failure.pool_id ? `#${failure.pool_id}` : 'Standalone' }}</dd></div>
              <div><dt>Game / assignment</dt><dd>#{{ failure.game_id ?? '—' }} / #{{ failure.assignment_id ?? '—' }}</dd></div>
              <div><dt>Engine</dt><dd>{{ failure.engine_name }} (#{{ failure.engine_id ?? '—' }})</dd></div>
              <div><dt>Stage</dt><dd>{{ failure.stage }}</dd></div>
            </dl>
            <pre>{{ failure.error }}</pre>
          </div>
        </details>
      </section>

      <div class="worker-grid">
        <section class="panel detail-card"><div class="detail-card__heading"><h2>Identity</h2></div><form class="rename-form" @submit.prevent="rename"><label><span>Worker label</span><input v-model="label" class="input" required maxlength="80"></label><button class="button button--primary button--small" type="submit" :disabled="pending === 'label'">{{ pending === 'label' ? 'Saving…' : 'Save label' }}</button></form></section>
        <section class="panel detail-card"><div class="detail-card__heading"><h2>Connection state</h2></div><dl class="fact-list"><div><dt>Overall</dt><dd><StatusBadge :status="data.row.status" /></dd></div><div><dt>Machine</dt><dd>{{ data.row.machine?.label ?? 'Unknown' }}<small>{{ data.row.machine?.detail }}</small></dd></div><div><dt>Session</dt><dd>{{ data.row.session?.label ?? 'None' }}<small>{{ data.row.session?.detail }}</small></dd></div><div><dt>Token</dt><dd>{{ data.row.token?.label ?? 'None' }}<small>{{ data.row.token?.detail }}</small></dd></div></dl></section>
        <section class="panel detail-card"><div class="detail-card__heading"><h2>Hardware</h2></div><dl v-if="data.worker.hw" class="fact-list"><div><dt>CPU</dt><dd>{{ data.worker.hw.cpu_model }}</dd></div><div><dt>Cores</dt><dd>{{ data.worker.hw.physical_cores }} physical · {{ data.worker.hw.logical_cores }} logical</dd></div><div><dt>Memory</dt><dd>{{ data.worker.hw.ram_gb }} GB</dd></div><div v-if="data.worker.hw.gpu"><dt>GPU</dt><dd>{{ data.worker.hw.gpu }}</dd></div><div v-if="data.worker.hw.bench?.nps_probe"><dt>Bench</dt><dd>{{ formatNumber(data.worker.hw.bench.nps_probe) }} NPS</dd></div></dl><p v-else class="card-empty">Not reported.</p></section>
        <section class="panel detail-card"><div class="detail-card__heading"><h2>Resource reservation</h2></div><dl class="fact-list"><div><dt>CPU</dt><dd>{{ data.worker.assigned_threads }} physical thread{{ data.worker.assigned_threads === 1 ? '' : 's' }}</dd></div><div><dt>Engine hash</dt><dd>{{ formatNumber(data.worker.assigned_hash_mb) }} MB total</dd></div><div><dt>Machine ID</dt><dd>{{ data.worker.machine_id ?? 'Reported on first connection' }}</dd></div></dl></section>
        <section class="panel detail-card"><div class="detail-card__heading"><h2>Credentials</h2></div><div class="credential-actions"><button v-if="data.worker.status !== 'revoked' && !data.worker.session_id && !data.worker.pool_id" class="button button--primary button--small" type="button" :disabled="pending === 'token'" @click="generateToken">{{ pending === 'token' ? 'Generating…' : minted ? 'Regenerate token' : 'Generate one-time token' }}</button><button v-if="data.worker_launch_command" class="button button--secondary button--small" type="button" @click="copy(data.worker_launch_command)">{{ copied ? 'Copied' : 'Copy start command' }}</button><p v-if="data.worker.pool_id">This slot is authenticated and started by machine pool #{{ data.worker.pool_id }}.</p><p v-else-if="data.worker.session_id">This worker already registered. Its existing session command can be copied without exposing a registration token.</p><p v-else>A registration token is valid for two hours and shown only until this page is left or refreshed.</p></div></section>
      </div>

      <section class="panel danger-zone"><div><h2>Worker access</h2><p>Revocation removes the worker and blocks reconnection. Pool slots can be revoked individually.</p></div><div><button class="button button--secondary" type="button" :disabled="!!pending" @click="revoke">{{ pending === 'revoke' ? 'Revoking…' : 'Revoke worker' }}</button><button v-if="!data.worker.pool_id" class="button button--danger" type="button" :disabled="!!pending" @click="remove">{{ pending === 'delete' ? 'Deleting…' : 'Delete worker' }}</button></div></section>
    </template>
  </div>
</template>

<style scoped>
.detail-loading { color: var(--color-text-muted, #64748b); min-height: 16rem; padding: 2rem; }
.live-state { align-items: center; color: var(--color-text-muted, #64748b); display: inline-flex; font-size: .7rem; font-weight: 650; gap: .4rem; }
.live-state > span { background: var(--color-warning, #b7791f); border-radius: 50%; height: .48rem; width: .48rem; }
.live-state > span.connected { background: var(--color-success, #24865a); box-shadow: 0 0 0 .2rem color-mix(in srgb, var(--color-success, #24865a) 15%, transparent); }
.current-work { align-items: center; display: flex; gap: 1rem; justify-content: space-between; padding: 1rem; }.current-work > div > span { color: var(--color-text-muted, #64748b); font-size: .64rem; font-weight: 700; letter-spacing: .05em; text-transform: uppercase; }.current-work h2 { font-size: .95rem; margin: .25rem 0 0; }.current-work p { color: var(--color-text-muted, #64748b); font-size: .75rem; margin: .2rem 0 0; }.current-work small { color: var(--color-text-muted, #64748b); display: block; font-size: .68rem; margin-top: .2rem; }
.failure-panel { border-color: color-mix(in srgb, var(--color-danger, #b42318) 30%, var(--color-border, #d9e0ea)); overflow: hidden; padding: 0; }.failure-panel__heading { align-items: center; background: color-mix(in srgb, var(--color-danger, #b42318) 7%, var(--color-surface, #fff)); display: flex; justify-content: space-between; padding: .8rem 1rem; }.failure-panel__heading h2 { color: var(--color-danger, #b42318); font-size: .9rem; margin: 0; }.failure-panel__heading p, .failure-panel__heading span { color: var(--color-text-muted, #64748b); font-size: .68rem; margin: .18rem 0 0; }.failure-entry { border-top: 1px solid var(--color-border, #d9e0ea); }.failure-entry summary { align-items: center; cursor: pointer; display: flex; justify-content: space-between; padding: .7rem 1rem; }.failure-entry summary > span { display: grid; gap: .15rem; }.failure-entry summary strong { font-size: .78rem; }.failure-entry summary small, .failure-entry summary time { color: var(--color-text-muted, #64748b); font-size: .66rem; }.failure-entry__body { background: var(--color-surface-subtle, #f8fafc); border-top: 1px solid var(--color-border, #d9e0ea); padding: .8rem 1rem 1rem; }.failure-entry__body dl { display: grid; gap: .45rem 1rem; grid-template-columns: repeat(3, minmax(0, 1fr)); margin: 0 0 .75rem; }.failure-entry__body dl > div { min-width: 0; }.failure-entry__body dt { color: var(--color-text-muted, #64748b); font-size: .62rem; text-transform: uppercase; }.failure-entry__body dd { font-size: .72rem; font-weight: 600; margin: .15rem 0 0; overflow-wrap: anywhere; }.failure-entry__body pre { background: #171717; border-radius: .45rem; color: #f5f5f5; font-size: .68rem; line-height: 1.5; margin: 0; max-height: 18rem; overflow: auto; padding: .75rem; white-space: pre-wrap; word-break: break-word; }
.dependency-list { display: flex; flex-wrap: wrap; gap: .4rem; padding: 1rem; }.dependency-list code { background: var(--color-surface-subtle, #f1f5f9); border: 1px solid var(--color-border, #d9e0ea); border-radius: .35rem; font-size: .7rem; padding: .28rem .42rem; }.dependency-checked { border-top: 1px solid var(--color-border, #d9e0ea); color: var(--color-text-muted, #64748b); font-size: .65rem; margin: 0; padding: .6rem 1rem; }
.dependency-missing { background: color-mix(in srgb, var(--color-warning, #b7791f) 9%, transparent); color: var(--color-warning, #8a5a12); font-size: .7rem; margin: 0; padding: .65rem 1rem; }
.worker-grid { display: grid; gap: .9rem; grid-template-columns: repeat(2, minmax(0, 1fr)); }.detail-card { overflow: hidden; padding: 0; }.detail-card__heading { border-bottom: 1px solid var(--color-border, #d9e0ea); padding: .75rem 1rem; }.detail-card h2, .danger-zone h2 { font-size: .88rem; margin: 0; }.rename-form { align-items: end; display: grid; gap: .7rem; grid-template-columns: minmax(0, 1fr) auto; padding: 1rem; }.rename-form label { display: grid; font-size: .75rem; font-weight: 650; gap: .35rem; }.fact-list { display: grid; margin: 0; }.fact-list > div { align-items: center; border-bottom: 1px solid var(--color-border, #d9e0ea); display: grid; gap: .75rem; grid-template-columns: minmax(5rem, .35fr) minmax(0, 1fr); padding: .65rem 1rem; }.fact-list > div:last-child { border-bottom: 0; }.fact-list dt { color: var(--color-text-muted, #64748b); font-size: .69rem; }.fact-list dd { font-size: .75rem; font-weight: 600; margin: 0; }.fact-list dd small { color: var(--color-text-muted, #64748b); display: block; font-size: .65rem; font-weight: 400; margin-top: .15rem; }.card-empty { color: var(--color-text-muted, #64748b); font-size: .75rem; margin: 0; padding: 1rem; }.credential-actions { align-items: flex-start; display: flex; flex-direction: column; gap: .65rem; padding: 1rem; }.credential-actions p { color: var(--color-text-muted, #64748b); font-size: .72rem; line-height: 1.45; margin: 0; }.danger-zone { align-items: center; border-color: color-mix(in srgb, var(--color-danger, #b42318) 25%, var(--color-border, #d9e0ea)); display: flex; gap: 1rem; justify-content: space-between; padding: 1rem; }.danger-zone p { color: var(--color-text-muted, #64748b); font-size: .72rem; margin: .2rem 0 0; }.danger-zone > div:last-child { display: flex; gap: .5rem; }
@media (max-width: 48rem) { .worker-grid { grid-template-columns: 1fr; }.danger-zone { align-items: flex-start; flex-direction: column; }.failure-entry__body dl { grid-template-columns: 1fr; } }
@media (max-width: 32rem) { .rename-form { grid-template-columns: 1fr; }.rename-form .button { justify-self: start; } }
</style>
