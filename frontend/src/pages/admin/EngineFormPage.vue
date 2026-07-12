<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@/api/client'
import { useConfirm } from '@/composables/useConfirm'
import { useToast } from '@/composables/useToast'
import AdminPageHeader from '@/components/admin/AdminPageHeader.vue'
import EngineOptionsEditor from '@/components/admin/EngineOptionsEditor.vue'
import InlineFeedback from '@/components/admin/InlineFeedback.vue'
import { errorText, formatDate, formatNumber } from '@/components/admin/format'
import type { Engine, EngineFamily } from '@/components/admin/types'

const route = useRoute()
const router = useRouter()
const toast = useToast()
const { confirm } = useConfirm()
const id = computed(() => Number(route.params.id) || null)
const loading = ref(!!id.value)
const pending = ref(false)
const uploadPending = ref(false)
const versionPending = ref<number | null>(null)
const error = ref('')
const form = reactive({ name: '', author: '', active: true })
const versions = ref<Engine[]>([])
const newVersion = ref('')
const newOptions = ref<Record<string, string | number | boolean>>({})
const newActive = ref(true)
const binary = ref<File | null>(null)

async function load(): Promise<void> {
  if (!id.value) return
  loading.value = true
  try {
    const response = await api.get<{ engine: EngineFamily; versions: Engine[] }>(`/api/admin/engines/${id.value}`)
    Object.assign(form, response.engine)
    versions.value = response.versions
  } catch (cause) { error.value = errorText(cause) }
  finally { loading.value = false }
}

async function saveIdentity(): Promise<void> {
  if (!form.name.trim()) { error.value = 'Enter an engine name.'; return }
  pending.value = true
  error.value = ''
  try {
    const body = { name: form.name.trim(), author: form.author.trim(), active: form.active }
    const response = id.value
      ? await api.put<{ id: number; message: string }>(`/api/admin/engines/${id.value}`, { body })
      : await api.post<{ id: number; message: string }>('/api/admin/engines', { body })
    toast.success(response.message)
    if (!id.value) await router.replace(`/admin/engines/${response.id}/edit`)
    else await load()
  } catch (cause) { error.value = errorText(cause); toast.error(cause) }
  finally { pending.value = false }
}

function chooseBinary(event: Event): void {
  binary.value = (event.target as HTMLInputElement).files?.[0] ?? null
}

async function uploadVersion(): Promise<void> {
  if (!id.value) return
  if (!newVersion.value.trim()) { error.value = 'Enter a version label.'; return }
  if (!binary.value) { error.value = 'Choose the compiled engine binary.'; return }
  uploadPending.value = true
  error.value = ''
  const body = new FormData()
  body.set('version', newVersion.value.trim())
  body.set('binary', binary.value)
  body.set('uci_options', JSON.stringify(newOptions.value))
  body.set('active', String(newActive.value))
  try {
    const response = await api.post<{ id: number; message: string }>(`/api/admin/engines/${id.value}/versions`, { body })
    toast.success(response.message)
    newVersion.value = ''
    newOptions.value = {}
    newActive.value = true
    binary.value = null
    const input = document.querySelector<HTMLInputElement>('#engine-binary')
    if (input) input.value = ''
    await load()
  } catch (cause) { error.value = errorText(cause); toast.error(cause) }
  finally { uploadPending.value = false }
}

async function saveVersion(version: Engine): Promise<void> {
  versionPending.value = version.id
  try {
    const response = await api.put<{ message: string }>(`/api/admin/engine-versions/${version.id}`, { body: { active: version.active, uci_options: version.uci_options } })
    toast.success(response.message)
  } catch (cause) { error.value = errorText(cause); toast.error(cause) }
  finally { versionPending.value = null }
}

async function removeVersion(version: Engine): Promise<void> {
  if (!await confirm({ title: 'Delete engine version?', message: `Delete ${form.name} ${version.version}? Uploaded binary data is removed when no other version uses it.`, confirmLabel: 'Delete version', tone: 'danger' })) return
  versionPending.value = version.id
  try {
    const response = await api.delete<{ message: string }>(`/api/admin/engine-versions/${version.id}`)
    toast.success(response.message)
    await load()
  } catch (cause) { error.value = errorText(cause); toast.error(cause) }
  finally { versionPending.value = null }
}

onMounted(load)
</script>

<template>
  <div class="admin-page page-stack">
    <AdminPageHeader :title="id ? `Manage ${form.name || 'engine'}` : 'Register engine'">
      <template #actions><RouterLink class="button button--ghost" to="/admin/engines">Back to engines</RouterLink></template>
    </AdminPageHeader>
    <InlineFeedback :message="error" />
    <div v-if="loading" class="panel form-card" role="status">Loading engine…</div>
    <template v-else>
      <form class="panel form-card" @submit.prevent="saveIdentity">
        <div class="form-card__heading"><h2>Engine identity</h2><p>Name and author are shared by every uploaded version.</p></div>
        <div class="form-grid">
          <label class="field"><span>Engine name</span><input v-model="form.name" class="input" required maxlength="80"></label>
          <label class="field"><span>Author <small>optional</small></span><input v-model="form.author" class="input" maxlength="120"></label>
          <label class="switch-row form-span-full"><input v-model="form.active" type="checkbox"><span><strong>Engine active</strong><small>Inactive engines and all their versions are unavailable for new tournaments.</small></span></label>
        </div>
        <div class="form-actions"><button class="button button--primary" type="submit" :disabled="pending">{{ pending ? 'Saving…' : id ? 'Save identity' : 'Register engine' }}</button></div>
      </form>

      <section v-if="id" class="panel form-card">
        <div class="form-card__heading"><h2>Upload a version</h2><p>Upload the ready-to-run Linux binary. COPE stores and verifies it by SHA-256.</p></div>
        <div class="form-grid">
          <label class="field"><span>Version</span><input v-model="newVersion" class="input" maxlength="80" placeholder="17.1" required></label>
          <label class="field"><span>Compiled binary</span><input id="engine-binary" class="input" type="file" required @change="chooseBinary"><small v-if="binary">{{ binary.name }} · {{ formatNumber(binary.size) }} bytes</small></label>
          <label class="switch-row form-span-full"><input v-model="newActive" type="checkbox"><span><strong>Version active</strong></span></label>
        </div>
        <div><h3>Default UCI options</h3><EngineOptionsEditor v-model="newOptions" /></div>
        <div class="form-actions"><button class="button button--primary" type="button" :disabled="uploadPending" @click="uploadVersion">{{ uploadPending ? 'Uploading and verifying…' : 'Upload version' }}</button></div>
      </section>

      <section v-if="id" class="versions">
        <div class="section-heading"><div><h2>Versions</h2><p>{{ versions.length }} uploaded version{{ versions.length === 1 ? '' : 's' }}</p></div></div>
        <article v-for="version in versions" :key="version.id" class="panel version-card">
          <div class="version-heading"><div><h3>{{ form.name }} {{ version.version }}</h3><p>{{ version.binary_filename }} · {{ formatNumber(version.binary_size) }} bytes · {{ formatDate(version.created_at) }}</p><p v-if="version.storage_status !== 'ready'" class="artifact-error">Artifact {{ version.storage_status }} on the main server. Deactivate this version and re-upload it.</p></div><label class="switch-row"><input v-model="version.active" type="checkbox"><span><strong>Active</strong></span></label></div>
          <dl><div><dt>SHA-256</dt><dd><code :title="version.binary_sha256">{{ version.binary_sha256 }}</code></dd></div><div><dt>Artifact ID</dt><dd>#{{ version.id }}</dd></div></dl>
          <EngineOptionsEditor v-model="version.uci_options" />
          <div class="form-actions"><button class="button button--danger" type="button" :disabled="versionPending === version.id" @click="removeVersion(version)">Delete</button><button class="button button--secondary" type="button" :disabled="versionPending === version.id" @click="saveVersion(version)">Save version</button></div>
        </article>
        <p v-if="!versions.length" class="panel empty">No runnable versions yet. Upload one above before creating a tournament.</p>
      </section>
    </template>
  </div>
</template>

<style scoped>
.form-card,.version-card { display:grid;gap:1rem;padding:clamp(1rem,2vw,1.35rem) }.form-card__heading{border-bottom:1px solid var(--color-border);padding-bottom:.8rem}.form-card__heading h2,.section-heading h2{font-size:.95rem;margin:0}.form-card__heading p,.section-heading p,.version-heading p{color:var(--color-text-muted);font-size:.72rem;margin:.2rem 0 0}.version-heading .artifact-error{color:var(--color-danger)}.form-grid{display:grid;gap:.85rem;grid-template-columns:repeat(2,minmax(0,1fr))}.form-span-full{grid-column:1/-1}.field{display:grid;gap:.38rem}.field>span{font-size:.8rem;font-weight:650}.field small{color:var(--color-text-muted);font-size:.7rem}.switch-row{align-items:flex-start;cursor:pointer;display:flex;gap:.6rem}.switch-row span{display:grid}.switch-row strong{font-size:.8rem}.switch-row small{color:var(--color-text-muted);font-size:.7rem}.form-actions{display:flex;gap:.6rem;justify-content:flex-end}.versions{display:grid;gap:.8rem}.version-heading{align-items:start;display:flex;justify-content:space-between}.version-heading h3{margin:0}.version-card dl{display:grid;gap:.5rem;grid-template-columns:minmax(0,1fr) auto;margin:0}.version-card dl div{min-width:0}.version-card dt{color:var(--color-text-muted);font-size:.65rem;text-transform:uppercase}.version-card dd{font-size:.72rem;margin:.2rem 0 0}.version-card code{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.empty{color:var(--color-text-muted);padding:1rem}@media(max-width:40rem){.form-grid{grid-template-columns:1fr}.form-span-full{grid-column:auto}.version-card dl{grid-template-columns:1fr}}
</style>
