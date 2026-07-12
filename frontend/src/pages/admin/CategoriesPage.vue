<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '@/api/client'
import { useConfirm } from '@/composables/useConfirm'
import { useToast } from '@/composables/useToast'
import AdminEmptyState from '@/components/admin/AdminEmptyState.vue'
import AdminPageHeader from '@/components/admin/AdminPageHeader.vue'
import InlineFeedback from '@/components/admin/InlineFeedback.vue'
import StatusBadge from '@/components/admin/StatusBadge.vue'
import { errorText, formatNumber } from '@/components/admin/format'
import type { Category } from '@/components/admin/types'

interface Response { categories: Category[]; tournament_counts: Record<string, number> }
const toast = useToast()
const { confirm } = useConfirm()
const data = ref<Response | null>(null)
const loading = ref(true)
const error = ref('')
const deleting = ref<number | null>(null)

async function load(): Promise<void> {
  loading.value = true
  try { data.value = await api.get<Response>('/api/admin/categories') }
  catch (cause) { error.value = errorText(cause) }
  finally { loading.value = false }
}

async function remove(category: Category): Promise<void> {
  const count = data.value?.tournament_counts[String(category.id)] ?? 0
  if (category.id === 1 || count > 0) return
  const accepted = await confirm({ title: 'Delete category?', message: `Delete “${category.name}”? Ratings associated with it may also be affected.`, confirmLabel: 'Delete category', tone: 'danger' })
  if (!accepted) return
  deleting.value = category.id
  try { const response = await api.delete<{ message: string }>(`/api/admin/categories/${category.id}`); toast.success(response.message); await load() }
  catch (cause) { error.value = errorText(cause); toast.error(cause) }
  finally { deleting.value = null }
}
onMounted(load)
</script>

<template>
  <div class="admin-page page-stack">
    <AdminPageHeader title="Rating categories">
      <template #actions><RouterLink class="button button--primary" to="/admin/categories/new">New category</RouterLink></template>
    </AdminPageHeader>
    <InlineFeedback :message="error" />
    <section class="panel category-panel">
      <div v-if="loading" class="index-loading" role="status">Loading categories…</div>
      <div v-else-if="data?.categories.length" class="category-list">
        <article v-for="category in data.categories" :key="category.id">
          <div class="category-list__main"><div class="category-list__heading"><h2>{{ category.name }}</h2><StatusBadge :status="category.active ? 'active' : 'inactive'" /><span v-if="category.id === 1" class="protected-label">Required</span></div><p v-if="category.description">{{ category.description }}</p></div>
          <div class="category-list__count"><strong>{{ formatNumber(data.tournament_counts[String(category.id)]) }}</strong><span>tournaments</span></div>
          <div class="category-list__actions"><RouterLink class="button button--secondary button--small" :to="`/admin/categories/${category.id}`">Edit defaults</RouterLink><button class="button button--danger button--small" type="button" :disabled="deleting === category.id || category.id === 1 || (data.tournament_counts[String(category.id)] ?? 0) > 0" :title="category.id === 1 ? 'The required default category cannot be deleted.' : (data.tournament_counts[String(category.id)] ?? 0) > 0 ? 'Move or delete referenced tournaments first.' : 'Delete category'" @click="remove(category)">{{ deleting === category.id ? 'Deleting…' : 'Delete' }}</button></div>
        </article>
      </div>
      <AdminEmptyState v-else title="No rating categories"><RouterLink class="button button--primary button--small" to="/admin/categories/new">New category</RouterLink></AdminEmptyState>
    </section>
  </div>
</template>

<style scoped>
.category-panel { overflow: hidden; padding: 0; }
.category-list { display: grid; }
.category-list article { align-items: center; border-bottom: 1px solid var(--color-border, #d9e0ea); display: grid; gap: 1rem; grid-template-columns: minmax(0, 1fr) auto auto; padding: .9rem 1rem; }
.category-list article:last-child { border-bottom: 0; }
.category-list__main { min-width: 0; }
.category-list__heading { align-items: center; display: flex; gap: .55rem; }
.protected-label { color: var(--color-text-muted, #64748b); font-size: .65rem; font-weight: 650; }
.category-list h2 { font-size: .88rem; margin: 0; }
.category-list p { color: var(--color-text-muted, #64748b); font-size: .74rem; margin: .3rem 0 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.category-list__count { display: grid; min-width: 5rem; text-align: right; }
.category-list__count strong { font-size: .9rem; }
.category-list__count span { color: var(--color-text-muted, #64748b); font-size: .65rem; }
.category-list__actions { display: flex; gap: .45rem; }
.index-loading { color: var(--color-text-muted, #64748b); min-height: 14rem; padding: 2rem; }
@media (max-width: 42rem) { .category-list article { grid-template-columns: 1fr auto; } .category-list__count { grid-column: 2; grid-row: 1; } .category-list__actions { grid-column: 1 / -1; } }
</style>
