<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api/client'
import { useConfirm } from '@/composables/useConfirm'
import { useToast } from '@/composables/useToast'
import AdminEmptyState from '@/components/admin/AdminEmptyState.vue'
import AdminPageHeader from '@/components/admin/AdminPageHeader.vue'
import InlineFeedback from '@/components/admin/InlineFeedback.vue'
import StatusBadge from '@/components/admin/StatusBadge.vue'
import WorkerTokenPanel from '@/components/admin/WorkerTokenPanel.vue'
import { errorText, formatDate } from '@/components/admin/format'

interface WorkerListItem {
  id: number; label: string; status: string; last_seen?: string | null; pool_id?: number | null
  work?: { summary: string; detail?: string; meta?: string; href?: string | null; abnormal?: boolean }
  machine?: { status: string; label: string; detail?: string }
  hardware?: { reported: boolean; summary: string; detail: string; cores?: string; memory?: string }
}
interface MachineListItem {
  id: string; label: string; worker_count: number; active_worker_count: number
  reserved_threads: number; reserved_hash_mb: number
  hardware?: { reported: boolean; summary: string; detail: string; gpu?: string | null; os?: string }
}
interface WorkerPoolItem {
  id: number; label: string; status: string; enrollment_expires_at?: string | null
  machine_id?: string | null; slot_count: number; created_worker_count: number
  active_worker_count: number; assigned_threads: number; assigned_hash_mb: number
  reserved_threads: number; reserved_hash_mb: number; start_command?: string | null
}
interface PoolEnrollment {
  pool_id: number; token: string; expires_at: string; start_command: string; message: string
}
const router = useRouter()
const toast = useToast()
const { confirm } = useConfirm()
const workers = ref<WorkerListItem[]>([])
const page = ref(1)
const perPage = 100
const totalWorkers = ref(0)
const connectedWorkers = ref(0)
const machines = ref<MachineListItem[]>([])
const pools = ref<WorkerPoolItem[]>([])
const loading = ref(true)
const error = ref('')
const streamConnected = ref(false)
const creating = ref(false)
const showCreate = ref(false)
const showPoolCreate = ref(false)
const label = ref('')
const assignedThreads = ref(1)
const assignedHashMb = ref(32)
const deleting = ref<number | null>(null)
const revoking = ref<number | null>(null)
const poolLabel = ref('')
const poolSlots = ref(1)
const poolThreads = ref(1)
const poolHashMb = ref(32)
const poolPending = ref<number | 'create' | null>(null)
const poolEnrollment = ref<PoolEnrollment | null>(null)
const copiedPool = ref<number | null>(null)
let source: EventSource | null = null

const totalPages = computed(() => Math.max(1, Math.ceil(totalWorkers.value / perPage)))

async function load(): Promise<void> {
  loading.value = true
  try {
    const response = await api.get<{ workers: WorkerListItem[]; machines: MachineListItem[]; pools: WorkerPoolItem[]; total_workers: number; connected_workers: number }>(`/api/admin/workers?page=${page.value}&per_page=${perPage}`)
    workers.value = response.workers
    totalWorkers.value = response.total_workers ?? response.workers.length
    connectedWorkers.value = response.connected_workers ?? 0
    machines.value = response.machines
    pools.value = response.pools
  } catch (cause) { error.value = errorText(cause) }
  finally { loading.value = false }
}

function connectStream(): void {
  source?.close()
  source = new EventSource(`/admin/workers/events?page=${page.value}`)
  source.addEventListener('open', () => { streamConnected.value = true })
  source.addEventListener('error', () => { streamConnected.value = false })
  source.addEventListener('workers.snapshot', (event) => {
    try {
      const envelope = JSON.parse((event as MessageEvent).data)
      if (Array.isArray(envelope.data?.workers)) {
        workers.value = envelope.data.workers
        totalWorkers.value = envelope.data.total_workers ?? workers.value.length
        connectedWorkers.value = envelope.data.connected_workers ?? 0
        machines.value = Array.isArray(envelope.data?.machines) ? envelope.data.machines : []
        if (Array.isArray(envelope.data?.pools)) {
          const commands = new Map(pools.value.map((pool) => [pool.id, pool.start_command]))
          pools.value = envelope.data.pools.map((pool: WorkerPoolItem) => ({ ...pool, start_command: pool.start_command ?? commands.get(pool.id) }))
        }
      }
    } catch { /* A malformed event should not replace the last usable snapshot. */ }
  })
}

async function changePage(nextPage: number): Promise<void> {
  page.value = Math.min(Math.max(nextPage, 1), totalPages.value)
  await load()
  connectStream()
}

async function createWorker(): Promise<void> {
  if (!Number.isInteger(assignedThreads.value) || assignedThreads.value < 1 || !Number.isInteger(assignedHashMb.value) || assignedHashMb.value < 1) {
    error.value = 'Worker threads and hash must be positive whole numbers.'
    return
  }
  creating.value = true
  try {
    const response = await api.post<{ id: number; message: string }>('/api/admin/workers', { body: { label: label.value.trim() || 'worker', assigned_threads: assignedThreads.value, assigned_hash_mb: assignedHashMb.value } })
    toast.success(response.message)
    await router.push(`/admin/workers/${response.id}`)
  } catch (cause) { error.value = errorText(cause); toast.error(cause) }
  finally { creating.value = false }
}

async function remove(worker: WorkerListItem): Promise<void> {
  const accepted = await confirm({ title: 'Delete worker?', message: `Delete “${worker.label}”? Any active connection will stop receiving work.`, confirmLabel: 'Delete worker', tone: 'danger' })
  if (!accepted) return
  deleting.value = worker.id
  try { const response = await api.delete<{ message: string }>(`/api/admin/workers/${worker.id}`); toast.success(response.message); await load() }
  catch (cause) { error.value = errorText(cause); toast.error(cause) }
  finally { deleting.value = null }
}

async function revoke(worker: WorkerListItem): Promise<void> {
  const accepted = await confirm({ title: 'Revoke worker?', message: `Revoke “${worker.label}”? It will be removed and cannot reconnect with its current credentials.`, confirmLabel: 'Revoke worker', tone: 'danger' })
  if (!accepted) return
  revoking.value = worker.id
  try { const response = await api.post<{ message: string }>(`/api/admin/workers/${worker.id}/revoke`); toast.success(response.message); await load() }
  catch (cause) { error.value = errorText(cause); toast.error(cause) }
  finally { revoking.value = null }
}

async function createPool(): Promise<void> {
  if (![poolSlots.value, poolThreads.value, poolHashMb.value].every((value) => Number.isInteger(value) && value > 0)) {
    error.value = 'Pool slots, threads, and hash must be positive whole numbers.'
    return
  }
  poolPending.value = 'create'
  try {
    const response = await api.post<PoolEnrollment>('/api/admin/worker-pools', { body: {
      label: poolLabel.value.trim() || 'machine pool', slot_count: poolSlots.value,
      assigned_threads: poolThreads.value, assigned_hash_mb: poolHashMb.value, ttl_seconds: 900,
    } })
    poolEnrollment.value = response
    showPoolCreate.value = false
    toast.success(response.message)
    await load()
  } catch (cause) { error.value = errorText(cause); toast.error(cause) }
  finally { poolPending.value = null }
}

async function renewPool(pool: WorkerPoolItem): Promise<void> {
  poolPending.value = pool.id
  try {
    const response = await api.post<PoolEnrollment>(`/api/admin/worker-pools/${pool.id}/token`, { body: { ttl_seconds: 900 } })
    poolEnrollment.value = response
    toast.success(response.message)
    await load()
  } catch (cause) { error.value = errorText(cause); toast.error(cause) }
  finally { poolPending.value = null }
}

async function revokePool(pool: WorkerPoolItem): Promise<void> {
  const accepted = await confirm({ title: 'Revoke machine pool?', message: `Revoke “${pool.label}” and every worker slot it owns? Active games will be returned to the scheduler.`, confirmLabel: 'Revoke pool', tone: 'danger' })
  if (!accepted) return
  poolPending.value = pool.id
  try {
    const response = await api.post<{ message: string }>(`/api/admin/worker-pools/${pool.id}/revoke`)
    if (poolEnrollment.value?.pool_id === pool.id) poolEnrollment.value = null
    toast.success(response.message)
    await load()
  } catch (cause) { error.value = errorText(cause); toast.error(cause) }
  finally { poolPending.value = null }
}

async function copyPoolCommand(pool: WorkerPoolItem): Promise<void> {
  if (!pool.start_command) return
  await navigator.clipboard.writeText(pool.start_command)
  copiedPool.value = pool.id
  window.setTimeout(() => { if (copiedPool.value === pool.id) copiedPool.value = null }, 1600)
}

onMounted(async () => { await load(); connectStream() })
onBeforeUnmount(() => source?.close())
</script>

<template>
  <div class="admin-page page-stack">
    <AdminPageHeader title="Workers">
      <template #actions><button class="button button--secondary" type="button" @click="showCreate = !showCreate; showPoolCreate = false">New worker</button><button class="button button--primary" type="button" @click="showPoolCreate = !showPoolCreate; showCreate = false">New machine pool</button></template>
    </AdminPageHeader>
    <InlineFeedback :message="error" />
    <WorkerTokenPanel
      v-if="poolEnrollment"
      :token="poolEnrollment.token"
      :expires-at="poolEnrollment.expires_at"
      :start-command="poolEnrollment.start_command"
      title="One-time machine pool enrollment"
      warning="Copy the token, run the start command on the target machine, and paste the token when prompted. The command stores separate slot credentials in a current-user-only state file."
    />

    <form v-if="showPoolCreate" class="panel create-pool" @submit.prevent="createPool">
      <div><h2>Create machine pool</h2></div>
      <label><span>Pool label</span><input v-model="poolLabel" class="input" maxlength="80" autofocus></label>
      <label><span>Game slots</span><input v-model.number="poolSlots" class="input" type="number" min="1" max="512" step="1"></label>
      <label><span>Threads <small>per slot</small></span><input v-model.number="poolThreads" class="input" type="number" min="1" step="1"></label>
      <label><span>Hash <small>total MB per slot</small></span><input v-model.number="poolHashMb" class="input" type="number" min="1" step="1"></label>
      <div class="pool-total"><span>Total reservation</span><strong>{{ (poolSlots * poolThreads).toLocaleString() }} threads</strong><small>{{ (poolSlots * poolHashMb).toLocaleString() }} MB hash</small></div>
      <div class="button-row"><button class="button button--ghost" type="button" @click="showPoolCreate = false">Cancel</button><button class="button button--primary" type="submit" :disabled="poolPending === 'create'">{{ poolPending === 'create' ? 'Creating…' : 'Create and enroll' }}</button></div>
    </form>

    <form v-if="showCreate" class="panel create-worker" @submit.prevent="createWorker">
      <div><h2>Create worker</h2></div>
      <label><span>Label</span><input v-model="label" class="input" maxlength="80" autofocus></label>
      <label><span>Reserved threads</span><input v-model.number="assignedThreads" class="input" type="number" min="1" step="1"></label>
      <label><span>Reserved hash <small>MB total</small></span><input v-model.number="assignedHashMb" class="input" type="number" min="1" step="1"></label>
      <div class="button-row"><button class="button button--ghost" type="button" @click="showCreate = false">Cancel</button><button class="button button--primary" type="submit" :disabled="creating">{{ creating ? 'Creating…' : 'Create worker' }}</button></div>
    </form>

    <section class="worker-summary" aria-label="Worker summary">
      <div><strong>{{ totalWorkers }}</strong><span>Registered</span></div><div><strong>{{ connectedWorkers }}</strong><span>Connected</span></div><div><span class="stream-dot" :class="{ connected: streamConnected }" aria-hidden="true" /><strong>{{ streamConnected ? 'Live' : 'Reconnecting' }}</strong><span>Status stream</span></div>
    </section>

    <section v-if="pools.length" class="panel pool-panel">
      <div class="panel-heading"><div><h2>Machine pools</h2></div></div>
      <div class="pool-list">
        <article v-for="pool in pools" :key="pool.id" class="pool-row">
          <div><strong>{{ pool.label }}</strong><small>Pool #{{ pool.id }}<template v-if="pool.machine_id"> · {{ pool.machine_id.slice(0, 12) }}</template></small></div>
          <StatusBadge :status="pool.status" />
          <div><strong>{{ pool.active_worker_count }} / {{ pool.slot_count }}</strong><small>active slots</small></div>
          <div><strong>{{ pool.reserved_threads.toLocaleString() }} threads</strong><small>{{ pool.reserved_hash_mb.toLocaleString() }} MB hash</small></div>
          <div class="pool-actions">
            <button v-if="pool.start_command && pool.status !== 'revoked'" class="button button--ghost button--small" type="button" @click="copyPoolCommand(pool)">{{ copiedPool === pool.id ? 'Copied' : pool.status === 'pending' ? 'Copy start command' : 'Copy resume command' }}</button>
            <button v-if="pool.status === 'pending'" class="button button--secondary button--small" type="button" :disabled="poolPending === pool.id" @click="renewPool(pool)">New enrollment token</button>
            <button v-if="pool.status !== 'revoked'" class="button button--danger button--small" type="button" :disabled="poolPending === pool.id" @click="revokePool(pool)">Revoke</button>
          </div>
        </article>
      </div>
    </section>

    <section class="panel worker-panel">
      <div v-if="loading" class="index-loading" role="status">Loading workers…</div>
      <div v-else-if="workers.length" class="table-scroll">
        <table class="data-table"><thead><tr><th>Worker</th><th>Status</th><th>Current work</th><th>Machine</th><th>Hardware</th><th>Last seen</th><th><span class="sr-only">Actions</span></th></tr></thead><tbody>
          <tr v-for="worker in workers" :key="worker.id" :class="{ 'worker-row--warning': worker.work?.abnormal }">
            <td><RouterLink :to="`/admin/workers/${worker.id}`"><strong>{{ worker.label }}</strong><small>#{{ worker.id }}</small></RouterLink></td>
            <td><StatusBadge :status="worker.status" /></td>
            <td class="work-cell"><strong>{{ worker.work?.summary ?? 'No active assignment' }}</strong><small v-if="worker.status !== 'ready'">{{ worker.work?.detail }}</small></td>
            <td><span class="state-label">{{ worker.machine?.label ?? 'Unknown' }}</span></td>
            <td><span>{{ worker.hardware?.summary ?? 'Not reported' }}</span><small>{{ worker.hardware?.detail }}</small></td>
            <td>{{ formatDate(worker.last_seen) }}</td>
            <td class="row-actions"><RouterLink class="button button--ghost button--small" :to="`/admin/workers/${worker.id}`">Open</RouterLink><button class="button button--danger button--small" type="button" :disabled="revoking === worker.id" @click="revoke(worker)">{{ revoking === worker.id ? 'Revoking…' : 'Revoke' }}</button><button v-if="!worker.pool_id" class="icon-button icon-button--danger" type="button" :disabled="deleting === worker.id" :aria-label="`Delete ${worker.label}`" @click="remove(worker)"><svg aria-hidden="true" viewBox="0 0 24 24"><path d="M5 7h14M9 7V4h6v3m2 0-1 13H8L7 7m3 4v5m4-5v5" /></svg></button></td>
          </tr>
        </tbody></table>
      </div>
      <AdminEmptyState v-else title="No workers registered"><button class="button button--primary button--small" type="button" @click="showCreate = true">New worker</button></AdminEmptyState>
      <nav v-if="totalPages > 1" class="worker-pagination" aria-label="Worker pages">
        <button class="button button--ghost button--small" type="button" :disabled="page <= 1" @click="changePage(page - 1)">Previous</button>
        <span>Page {{ page }} of {{ totalPages }}</span>
        <button class="button button--ghost button--small" type="button" :disabled="page >= totalPages" @click="changePage(page + 1)">Next</button>
      </nav>
    </section>

    <section v-if="machines.length" class="panel machine-panel">
      <div class="panel-heading"><div><h2>Machines</h2></div></div>
      <div class="table-scroll">
        <table class="data-table machine-table"><thead><tr><th>Machine</th><th>Capacity</th><th>Workers</th><th>Reserved</th></tr></thead><tbody>
          <tr v-for="machine in machines" :key="machine.id">
            <td><span class="machine-id" :title="machine.id">{{ machine.label }}</span></td>
            <td>{{ machine.hardware?.detail ?? 'Not reported' }}</td>
            <td>{{ machine.active_worker_count }} / {{ machine.worker_count }} active</td>
            <td>{{ machine.reserved_threads }} cores · {{ machine.reserved_hash_mb }}MB</td>
          </tr>
        </tbody></table>
      </div>
    </section>
  </div>
</template>

<style scoped>
.create-worker { align-items: end; display: grid; gap: 1rem; grid-template-columns: minmax(12rem, 1fr) minmax(10rem, .65fr) minmax(10rem, .65fr) minmax(10rem, .65fr) auto; padding: 1rem; }
.create-worker h2, .create-pool h2 { font-size: .9rem; margin: 0; }.create-worker p, .create-pool p { color: var(--color-text-muted, #64748b); font-size: .72rem; margin: .2rem 0 0; }.create-worker label, .create-pool label { display: grid; font-size: .76rem; font-weight: 650; gap: .35rem; }
.create-pool { align-items: end; display: grid; gap: 1rem; grid-template-columns: minmax(12rem, 1.1fr) repeat(4, minmax(8rem, .65fr)) minmax(9rem, auto); padding: 1rem; }.pool-total { display: grid; gap: .18rem; }.pool-total span, .pool-total small { color: var(--color-text-muted, #64748b); font-size: .65rem; }.pool-total strong { font-size: .78rem; }
.worker-summary { display: grid; gap: .75rem; grid-template-columns: repeat(3, minmax(0, 1fr)); }
.worker-summary > div { align-items: center; background: var(--color-surface, #fff); border: 1px solid var(--color-border, #d9e0ea); border-radius: var(--radius-md, .6rem); display: flex; gap: .5rem; padding: .7rem .8rem; }.worker-summary strong { font-size: .9rem; }.worker-summary span:last-child { color: var(--color-text-muted, #64748b); font-size: .7rem; margin-left: auto; }.stream-dot { background: var(--color-danger, #b42318); border-radius: 50%; height: .5rem; width: .5rem; }.stream-dot.connected { background: var(--color-success, #15803d); box-shadow: 0 0 0 .2rem color-mix(in srgb, var(--color-success, #15803d) 15%, transparent); }
.worker-panel { overflow: hidden; padding: 0; }.table-scroll { overflow-x: auto; }.data-table { border-collapse: collapse; min-width: 66rem; width: 100%; }.data-table th { color: var(--color-text-muted, #64748b); font-size: .65rem; letter-spacing: .04em; padding: .65rem .75rem; text-align: left; text-transform: uppercase; }.data-table td { border-top: 1px solid var(--color-border, #d9e0ea); font-size: .74rem; padding: .7rem .75rem; vertical-align: middle; }.worker-row--warning { background: color-mix(in srgb, var(--color-warning, #b7791f) 6%, transparent); }.data-table td:first-child a { color: inherit; display: grid; text-decoration: none; }.data-table small { color: var(--color-text-muted, #64748b); display: block; font-size: .64rem; margin-top: .15rem; }.work-cell { max-width: 18rem; }.work-cell strong, .work-cell small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.state-label { background: var(--color-surface-subtle, #f1f5f9); border-radius: 999px; font-size: .66rem; padding: .28rem .45rem; }.row-actions { align-items: center; display: flex; gap: .3rem; justify-content: flex-end; }.row-actions svg { fill: none; height: 1rem; stroke: currentColor; stroke-linecap: round; stroke-linejoin: round; stroke-width: 1.7; width: 1rem; }.index-loading { color: var(--color-text-muted, #64748b); min-height: 14rem; padding: 2rem; }
.worker-pagination { align-items: center; border-top: 1px solid var(--color-border, #d9e0ea); display: flex; gap: .75rem; justify-content: flex-end; padding: .65rem .75rem; }.worker-pagination span { color: var(--color-text-muted, #64748b); font-size: .7rem; }
.machine-panel { overflow: hidden; padding: 0; }.panel-heading { border-bottom: 1px solid var(--color-border, #d9e0ea); padding: .85rem 1rem; }.panel-heading h2 { font-size: .9rem; margin: 0; }.panel-heading p { color: var(--color-text-muted, #64748b); font-size: .72rem; margin: .2rem 0 0; }.machine-table { min-width: 44rem; }.machine-id { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .7rem; }
.pool-panel { overflow: hidden; padding: 0; }.pool-list { display: grid; }.pool-row { align-items: center; border-top: 1px solid var(--color-border, #d9e0ea); display: grid; gap: 1rem; grid-template-columns: minmax(10rem, 1fr) auto minmax(6rem, auto) minmax(9rem, auto) minmax(16rem, auto); padding: .75rem 1rem; }.pool-row:first-child { border-top: 0; }.pool-row > div { display: grid; }.pool-row small { color: var(--color-text-muted, #64748b); font-size: .64rem; margin-top: .15rem; }.pool-row strong { font-size: .76rem; }.pool-actions { display: flex !important; flex-wrap: wrap; gap: .35rem; justify-content: flex-end; }
@media (max-width: 64rem) { .create-pool { grid-template-columns: repeat(2, minmax(0, 1fr)); }.create-pool > div:first-child, .create-pool .button-row { grid-column: 1 / -1; }.pool-row { grid-template-columns: minmax(10rem, 1fr) auto minmax(6rem, auto); }.pool-actions { grid-column: 1 / -1; justify-content: flex-start; } }
@media (max-width: 50rem) { .create-worker, .create-pool { align-items: stretch; grid-template-columns: 1fr; }.create-worker .button-row, .create-pool .button-row { grid-column: auto; justify-content: flex-start; }.worker-summary { grid-template-columns: 1fr; }.pool-row { align-items: flex-start; grid-template-columns: 1fr auto; } }
</style>
