<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api/client'
import { useToast } from '@/composables/useToast'
import AdminPageHeader from '@/components/admin/AdminPageHeader.vue'
import InlineFeedback from '@/components/admin/InlineFeedback.vue'
import TournamentConfigForm from '@/components/admin/TournamentConfigForm.vue'
import { errorText } from '@/components/admin/format'
import type { FormSeed, TournamentConfig } from '@/components/admin/types'

const router = useRouter()
const toast = useToast()
const seed = ref<FormSeed | null>(null)
const loading = ref(true)
const pending = ref(false)
const error = ref('')

async function load(): Promise<void> {
  loading.value = true
  try { seed.value = await api.get<FormSeed>('/api/admin/tournaments/form') }
  catch (cause) { error.value = errorText(cause) }
  finally { loading.value = false }
}

async function save(payload: { name: string; config: TournamentConfig }): Promise<void> {
  pending.value = true
  error.value = ''
  try {
    const response = await api.post<{ id: number; message: string }>('/api/admin/tournaments', { body: payload })
    toast.success(response.message)
    await router.push(`/admin/tournaments/${response.id}`)
  } catch (cause) { error.value = errorText(cause); toast.error(cause) }
  finally { pending.value = false }
}

onMounted(load)
</script>

<template>
  <div class="admin-page page-stack">
    <AdminPageHeader title="New tournament">
      <template #actions><RouterLink class="button button--ghost" to="/admin/tournaments">Back to tournaments</RouterLink></template>
    </AdminPageHeader>
    <InlineFeedback :message="error" />
    <div v-if="loading" class="panel form-loading" role="status">Loading tournament options…</div>
    <TournamentConfigForm v-else-if="seed" :seed="seed" :pending="pending" submit-label="Create tournament" @submit="save" @cancel="router.push('/admin/tournaments')" />
  </div>
</template>

<style scoped>.form-loading { color: var(--color-text-muted, #64748b); min-height: 18rem; padding: 2rem; }</style>
