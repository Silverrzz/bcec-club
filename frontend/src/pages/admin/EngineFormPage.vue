<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@/api/client'
import { useToast } from '@/composables/useToast'
import AdminPageHeader from '@/components/admin/AdminPageHeader.vue'
import EngineOptionsEditor from '@/components/admin/EngineOptionsEditor.vue'
import InlineFeedback from '@/components/admin/InlineFeedback.vue'
import { errorText } from '@/components/admin/format'
import type { Engine } from '@/components/admin/types'

const route = useRoute()
const router = useRouter()
const toast = useToast()
const id = computed(() => Number(route.params.id) || null)
const loading = ref(!!id.value)
const pending = ref(false)
const error = ref('')
const form = reactive<Engine>({ id: 0, name: '', author: '', version: '', git_url: '', branch: '', commit: '', build_cmd: '', binary_path: '', required_dependencies: [], uci_options: {}, active: true })
const dependenciesText = ref('')

async function load(): Promise<void> {
  if (!id.value) return
  try {
    const response = await api.get<{ engine: Engine }>(`/api/admin/engines/${id.value}`)
    Object.assign(form, response.engine)
    dependenciesText.value = (response.engine.required_dependencies ?? []).join('\n')
  } catch (cause) { error.value = errorText(cause) }
  finally { loading.value = false }
}

function validate(): string {
  if (!form.name.trim()) return 'Enter an engine name.'
  if (!form.git_url.trim()) return 'Enter the source repository URL.'
  if (!/^[0-9a-f]{40}$/i.test(form.commit.trim())) return 'Commit SHA must be the full 40-character hexadecimal hash.'
  if (!form.build_cmd.trim()) return 'Enter the command used to build this engine.'
  if (!form.binary_path.trim()) return 'Enter the binary path relative to the repository root.'
  const dependencies = dependenciesText.value.split(/[\n,]/).map((value) => value.trim()).filter(Boolean)
  if (dependencies.some((value) => !/^[A-Za-z0-9][A-Za-z0-9._+:-]{0,79}$/.test(value))) return 'Dependencies must be executable names without paths, arguments, or shell syntax.'
  const names = Object.keys(form.uci_options ?? {})
  if (names.some((name) => !name.trim())) return 'Every UCI option needs a name.'
  if (Object.values(form.uci_options ?? {}).some((value) => typeof value === 'number' && !Number.isFinite(value))) return 'Every numeric UCI option needs a valid number.'
  return ''
}

async function save(): Promise<void> {
  error.value = validate()
  if (error.value) return
  pending.value = true
  const required_dependencies = [...new Set(dependenciesText.value.split(/[\n,]/).map((value) => value.trim()).filter(Boolean))]
  const body = { ...form, id: undefined, engine_id: undefined, name: form.name.trim(), author: form.author?.trim() ?? '', version: form.version?.trim() ?? '', git_url: form.git_url.trim(), branch: form.branch?.trim() ?? '', commit: form.commit.trim().toLowerCase(), build_cmd: form.build_cmd.trim(), binary_path: form.binary_path.trim(), required_dependencies, uci_options: form.uci_options ?? {}, active: form.active ?? true }
  try {
    const response = id.value
      ? await api.put<{ id: number; message: string }>(`/api/admin/engines/${id.value}`, { body })
      : await api.post<{ id: number; message: string }>('/api/admin/engines', { body })
    toast.success(response.message)
    await router.push('/admin/engines')
  } catch (cause) { error.value = errorText(cause); toast.error(cause) }
  finally { pending.value = false }
}

onMounted(load)
</script>

<template>
  <div class="admin-page page-stack">
    <AdminPageHeader :title="id ? `Edit ${form.name || 'engine'}` : 'Register engine'">
      <template #actions><RouterLink class="button button--ghost" to="/admin/engines">Back to engines</RouterLink></template>
    </AdminPageHeader>
    <InlineFeedback :message="error" />
    <div v-if="loading" class="panel form-loading" role="status">Loading engine…</div>
    <form v-else class="engine-form" novalidate @submit.prevent="save">
      <section class="panel form-card">
        <div class="form-card__heading"><h2>Identity</h2></div>
        <div class="form-grid">
          <label class="field form-span-full"><span>Engine name</span><input v-model="form.name" class="input" required maxlength="80" autocomplete="off"></label>
          <label class="field"><span>Author <small>optional</small></span><input v-model="form.author" class="input" maxlength="120" autocomplete="off"></label>
          <label class="field"><span>Version <small>optional</small></span><input v-model="form.version" class="input" maxlength="80" autocomplete="off"></label>
          <label class="switch-row form-span-full"><input v-model="form.active" type="checkbox"><span><strong>Active</strong></span></label>
        </div>
      </section>

      <section class="panel form-card">
        <div class="form-card__heading"><h2>Source and build</h2></div>
        <div class="form-grid">
          <label class="field form-span-full"><span>Git repository URL</span><input v-model="form.git_url" class="input" required type="url"></label>
          <label class="field"><span>Branch <small>optional</small></span><input v-model="form.branch" class="input" maxlength="120"></label>
          <label class="field"><span>Full commit SHA</span><input v-model="form.commit" class="input input--mono" required minlength="40" maxlength="40" pattern="[0-9a-fA-F]{40}"></label>
          <label class="field form-span-full"><span>Build command</span><input v-model="form.build_cmd" class="input input--mono" required></label>
          <label class="field form-span-full"><span>Binary path</span><input v-model="form.binary_path" class="input input--mono" required></label>
          <label class="field form-span-full"><span>Required executables <small>optional, one per line or comma-separated</small></span><textarea v-model="dependenciesText" class="input input--mono" rows="4" placeholder="clang++&#10;cmake&#10;cargo"></textarea><small>Workers report executable names available on their service PATH. COPE does not install them.</small></label>
        </div>
      </section>

      <section class="panel form-card">
        <div class="form-card__heading"><h2>UCI options</h2></div>
        <EngineOptionsEditor v-model="form.uci_options" />
      </section>

      <div class="form-actions"><RouterLink class="button button--ghost" to="/admin/engines">Cancel</RouterLink><button class="button button--primary" type="submit" :disabled="pending" :aria-busy="pending">{{ pending ? 'Saving…' : id ? 'Save changes' : 'Register engine' }}</button></div>
    </form>
  </div>
</template>

<style scoped>
.engine-form { display: grid; gap: 1rem; }
.form-card { display: grid; gap: 1rem; padding: clamp(1rem, 2vw, 1.35rem); }
.form-card__heading { border-bottom: 1px solid var(--color-border, #d9e0ea); padding-bottom: .8rem; }
.form-card__heading h2 { font-size: .95rem; margin: 0; }
.form-card__heading p { color: var(--color-text-muted, #64748b); font-size: .76rem; margin: .2rem 0 0; }
.form-grid { display: grid; gap: .85rem; grid-template-columns: repeat(2, minmax(0, 1fr)); }
.form-span-full { grid-column: 1 / -1; }
.field { display: grid; gap: .38rem; }
.field > span { font-size: .8rem; font-weight: 650; }
.field > span small, .field > small { color: var(--color-text-muted, #64748b); font-size: .7rem; font-weight: 500; }
.switch-row { align-items: flex-start; cursor: pointer; display: flex; gap: .6rem; }
.switch-row input { height: 1rem; margin-top: .12rem; width: 1rem; }
.switch-row span { display: grid; gap: .15rem; }
.switch-row strong { font-size: .8rem; }
.switch-row small { color: var(--color-text-muted, #64748b); font-size: .72rem; }
.form-actions { display: flex; gap: .6rem; justify-content: flex-end; }
.form-loading { color: var(--color-text-muted, #64748b); min-height: 16rem; padding: 2rem; }
@media (max-width: 40rem) { .form-grid { grid-template-columns: 1fr; } .form-span-full { grid-column: auto; } }
</style>
