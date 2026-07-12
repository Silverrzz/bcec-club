<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { api } from '@/api/client'
import { useConfirm } from '@/composables/useConfirm'
import { useToast } from '@/composables/useToast'
import AdminEmptyState from '@/components/admin/AdminEmptyState.vue'
import AdminPageHeader from '@/components/admin/AdminPageHeader.vue'
import InlineFeedback from '@/components/admin/InlineFeedback.vue'
import StatusBadge from '@/components/admin/StatusBadge.vue'
import { errorText, formatDate } from '@/components/admin/format'

interface ChatMessage { id: number; tournament_id: number; display_name: string; text: string; at: string }
interface Settings { enabled: boolean; allow_anonymous_names: boolean; max_message_length: number }
interface Response { messages: ChatMessage[]; settings: Settings; tournament_names: Record<string, string> }

const toast = useToast()
const { confirm } = useConfirm()
const messages = ref<ChatMessage[]>([])
const settings = reactive<Settings>({ enabled: true, allow_anonymous_names: true, max_message_length: 500 })
const loading = ref(true)
const pending = ref(false)
const deleting = ref<number | null>(null)
const error = ref('')
const query = ref('')
const tournamentNames = ref<Record<string, string>>({})
const filteredMessages = computed(() => {
  const needle = query.value.trim().toLocaleLowerCase()
  return needle ? messages.value.filter((message) => `${message.display_name} ${message.text} ${tournamentNames.value[String(message.tournament_id)] ?? ''}`.toLocaleLowerCase().includes(needle)) : messages.value
})

async function load(): Promise<void> {
  loading.value = true
  try {
    const response = await api.get<Response>('/api/admin/chat')
    messages.value = response.messages
    tournamentNames.value = response.tournament_names ?? {}
    Object.assign(settings, {
      enabled: response.settings.enabled,
      allow_anonymous_names: response.settings.allow_anonymous_names,
      max_message_length: response.settings.max_message_length,
    })
  } catch (cause) { error.value = errorText(cause) }
  finally { loading.value = false }
}

async function saveSettings(): Promise<void> {
  if (!Number.isInteger(settings.max_message_length) || settings.max_message_length < 1) { error.value = 'Maximum message length must be a whole number of at least 1.'; return }
  pending.value = true
  error.value = ''
  try {
    const response = await api.put<{ message: string }>('/api/admin/chat/settings', { body: { enabled: settings.enabled, allow_anonymous_names: settings.allow_anonymous_names, max_message_length: settings.max_message_length } })
    toast.success(response.message)
  } catch (cause) { error.value = errorText(cause); toast.error(cause) }
  finally { pending.value = false }
}

async function remove(message: ChatMessage): Promise<void> {
  const accepted = await confirm({ title: 'Delete chat message?', message: `Remove the message from ${message.display_name}? This takes effect immediately for all viewers.`, confirmLabel: 'Delete message', tone: 'danger' })
  if (!accepted) return
  deleting.value = message.id
  try {
    const response = await api.delete<{ message: string }>(`/api/admin/chat/messages/${message.id}`)
    messages.value = messages.value.filter((item) => item.id !== message.id)
    toast.success(response.message)
  } catch (cause) { error.value = errorText(cause); toast.error(cause) }
  finally { deleting.value = null }
}

onMounted(load)
</script>

<template>
  <div class="admin-page page-stack">
    <AdminPageHeader title="Tournament chat">
      <template #actions><StatusBadge :status="settings.enabled ? 'active' : 'paused'" :label="settings.enabled ? 'Chat enabled' : 'Chat disabled'" /></template>
    </AdminPageHeader>
    <InlineFeedback :message="error" />
    <div v-if="loading" class="panel page-loading" role="status">Loading chat moderation…</div>
    <template v-else>
      <form class="panel settings-card" @submit.prevent="saveSettings">
        <div class="settings-card__heading"><div><h2>Channel settings</h2></div><button class="button button--primary" type="submit" :disabled="pending">{{ pending ? 'Saving…' : 'Save settings' }}</button></div>
        <div class="settings-grid">
          <label class="setting-switch"><input v-model="settings.enabled" type="checkbox"><span><strong>Enable public chat</strong></span></label>
          <template v-if="settings.enabled">
            <label class="setting-switch"><input v-model="settings.allow_anonymous_names" type="checkbox"><span><strong>Allow anonymous display names</strong></span></label>
            <label class="field"><span>Maximum message length</span><div class="unit-input"><input v-model.number="settings.max_message_length" class="input" type="number" min="1" step="1" required><span>characters</span></div></label>
          </template>
        </div>
      </form>

      <section class="panel messages-panel">
        <div class="messages-panel__heading"><div><h2>Messages</h2></div><label class="message-search"><span class="sr-only">Search chat messages</span><svg aria-hidden="true" viewBox="0 0 24 24"><circle cx="11" cy="11" r="6.5" /><path d="m16 16 4 4" /></svg><input v-model="query" class="input" type="search" placeholder="Search name or message"></label></div>
        <div v-if="filteredMessages.length" class="message-list">
          <article v-for="message in filteredMessages" :key="message.id">
            <span class="message-avatar" aria-hidden="true">{{ message.display_name.slice(0, 2).toUpperCase() }}</span>
            <div class="message-body"><div><strong>{{ message.display_name }}</strong><time :datetime="message.at">{{ formatDate(message.at) }}</time></div><RouterLink class="message-context" :to="`/tournaments/${message.tournament_id}`">{{ tournamentNames[String(message.tournament_id)] ?? `Tournament ${message.tournament_id}` }}</RouterLink><p>{{ message.text }}</p></div>
            <button class="button button--danger button--small" type="button" :disabled="deleting === message.id" @click="remove(message)">{{ deleting === message.id ? 'Deleting…' : 'Delete' }}</button>
          </article>
        </div>
        <AdminEmptyState v-else :title="query ? 'No matching messages' : 'No chat messages'" />
      </section>
    </template>
  </div>
</template>

<style scoped>
.page-loading { color: var(--color-text-muted, #64748b); min-height: 16rem; padding: 2rem; }
.settings-card { display: grid; gap: 1rem; padding: 0; overflow: hidden; }
.settings-card__heading, .messages-panel__heading { align-items: flex-start; border-bottom: 1px solid var(--color-border, #d9e0ea); display: flex; gap: 1rem; justify-content: space-between; padding: .85rem 1rem; }
.settings-card h2, .messages-panel h2 { font-size: .92rem; margin: 0; }.settings-card__heading p, .messages-panel__heading p { color: var(--color-text-muted, #64748b); font-size: .72rem; margin: .2rem 0 0; }
.settings-grid { display: grid; gap: .8rem; grid-template-columns: repeat(3, minmax(0, 1fr)); padding: 0 1rem 1rem; }.setting-switch { align-items: flex-start; border: 1px solid var(--color-border, #d9e0ea); border-radius: var(--radius-md, .6rem); cursor: pointer; display: flex; gap: .65rem; padding: .8rem; }.setting-switch input { height: 1rem; margin: .15rem 0 0; width: 1rem; }.setting-switch span { display: grid; gap: .18rem; }.setting-switch strong, .field > span { font-size: .8rem; }.setting-switch small, .field > small { color: var(--color-text-muted, #64748b); font-size: .71rem; line-height: 1.4; }.field { display: grid; gap: .4rem; }.unit-input { position: relative; }.unit-input input { padding-right: 5.5rem; width: 100%; }.unit-input span { color: var(--color-text-muted, #64748b); font-size: .68rem; position: absolute; right: .65rem; top: 50%; transform: translateY(-50%); }
.chat-closed-note { align-self: center; color: var(--color-text-muted, #64748b); font-size: .74rem; grid-column: span 2; line-height: 1.45; margin: 0; }
.messages-panel { overflow: hidden; padding: 0; }.message-search { flex: 0 1 18rem; position: relative; }.message-search svg { fill: none; height: 1rem; left: .65rem; position: absolute; stroke: var(--color-text-muted, #64748b); stroke-width: 1.8; top: 50%; transform: translateY(-50%); width: 1rem; }.message-search input { padding-left: 2rem; width: 100%; }.message-list { display: grid; }.message-list article { align-items: flex-start; border-bottom: 1px solid var(--color-border, #d9e0ea); display: grid; gap: .75rem; grid-template-columns: auto minmax(0, 1fr) auto; padding: .8rem 1rem; }.message-list article:last-child { border-bottom: 0; }.message-avatar { align-items: center; background: var(--color-surface-subtle, #f1f5f9); border-radius: 50%; color: var(--color-text-muted, #64748b); display: flex; font-size: .62rem; font-weight: 750; height: 1.9rem; justify-content: center; width: 1.9rem; }.message-body { min-width: 0; }.message-body > div { align-items: baseline; display: flex; gap: .5rem; }.message-body strong { font-size: .76rem; }.message-body time { color: var(--color-text-muted, #64748b); font-size: .65rem; }.message-context { display: inline-block; font-size: .67rem; margin-top: .2rem; }.message-body p { font-size: .78rem; line-height: 1.5; margin: .32rem 0 0; overflow-wrap: anywhere; white-space: pre-wrap; }
@media (max-width: 56rem) { .settings-grid { grid-template-columns: 1fr; } }
@media (max-width: 40rem) { .settings-card__heading, .messages-panel__heading { align-items: stretch; flex-direction: column; }.message-search { flex-basis: auto; }.message-list article { grid-template-columns: auto 1fr; }.message-list article .button { grid-column: 2; justify-self: start; } }
</style>
