<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'

import { api } from '@/api/client'

import { errorMessage } from './format'
import type { ChatMessage, ChatSettings, Identifier } from './types'

const props = withDefaults(defineProps<{
  messages?: ChatMessage[]
  settings?: ChatSettings
  tournamentId?: Identifier | null
}>(), {
  messages: () => [],
  settings: () => ({}),
  tournamentId: null,
})

const emit = defineEmits<{
  sent: [message: ChatMessage]
}>()

const STORAGE_KEY = 'cope.chat.displayName'
const log = ref<HTMLElement | null>(null)
const displayName = ref('')
const text = ref('')
const submitting = ref(false)
const submitError = ref('')

const enabled = computed(() => props.settings.enabled !== false)
const maxLength = computed(() => Math.max(1, props.settings.max_message_length || 500))
const requiresName = computed(() => props.settings.allow_anonymous_names === false)
const canSend = computed(() => props.tournamentId !== null && enabled.value && !submitting.value && text.value.trim() && (!requiresName.value || displayName.value.trim()))

onMounted(() => {
  try { displayName.value = localStorage.getItem(STORAGE_KEY) || '' } catch { /* Storage can be disabled. */ }
  scrollToLatest()
})

watch(() => props.messages.length, scrollToLatest)
watch(displayName, (value) => {
  try {
    if (value.trim()) localStorage.setItem(STORAGE_KEY, value.trim())
    else localStorage.removeItem(STORAGE_KEY)
  } catch { /* Storage can be disabled. */ }
})

async function submit(): Promise<void> {
  if (!canSend.value) return
  submitting.value = true
  submitError.value = ''
  const body = new FormData()
  body.set('display_name', displayName.value.trim())
  body.set('text', text.value.trim())
  try {
    const response = await api.post<{ message?: ChatMessage | null }>(`/api/tournaments/${encodeURIComponent(String(props.tournamentId))}/chat`, { body })
    if (response.message) emit('sent', response.message)
    text.value = ''
    await scrollToLatest()
  } catch (error) {
    submitError.value = errorMessage(error, 'Your message could not be sent.')
  } finally {
    submitting.value = false
  }
}

async function scrollToLatest(): Promise<void> {
  await nextTick()
  if (log.value) log.value.scrollTop = log.value.scrollHeight
}
</script>

<template>
  <section id="chat" class="chat-panel" aria-labelledby="chat-title">
    <header>
      <h2 id="chat-title">Chat</h2>
      <span>{{ messages.length }} message{{ messages.length === 1 ? '' : 's' }}</span>
    </header>

    <div ref="log" class="chat-log" role="log" aria-live="polite" aria-relevant="additions">
      <ol v-if="messages.length">
        <li v-for="(message, index) in messages" :key="message.id ?? `${message.at}-${index}`">
          <div>
            <strong>{{ message.display_name }}</strong>
            <time v-if="message.at" :datetime="message.at">{{ new Date(message.at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) }}</time>
          </div>
          <p>{{ message.text }}</p>
        </li>
      </ol>
      <p v-else class="chat-empty">No messages yet.</p>
    </div>

    <form v-if="enabled" class="chat-form" autocomplete="off" @submit.prevent="submit">
      <label>
        <span>Name{{ requiresName ? '' : ' (optional)' }}</span>
        <input v-model="displayName" name="display_name" maxlength="40" autocomplete="nickname" :required="requiresName" placeholder="Your name">
      </label>
      <label>
        <span>Message</span>
        <textarea v-model="text" name="text" :maxlength="maxLength" rows="2" required placeholder="Write a message"></textarea>
      </label>
      <div class="chat-form__footer">
        <span>{{ text.length }} / {{ maxLength }}</span>
        <button type="submit" :disabled="!canSend">
          {{ submitting ? 'Sending...' : 'Send' }}
        </button>
      </div>
      <p v-if="submitError" class="chat-error" role="alert">{{ submitError }}</p>
    </form>
    <p v-else class="chat-disabled">Chat is currently closed.</p>
  </section>
</template>

<style scoped>
.chat-panel {
  display: flex;
  min-height: 0;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid var(--color-border, #d5dbe1);
  border-radius: var(--radius-md, 0.5rem);
  background: var(--color-surface, #fff);
}

.chat-panel > header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.75rem;
  padding: var(--space-sm, 0.5rem) var(--space-md, 1rem);
  border-block-end: 1px solid var(--color-border, #d5dbe1);
}

.chat-panel h2 {
  margin: 0;
  font-size: 0.95rem;
}

.chat-panel > header span {
  color: var(--color-text-muted, #607080);
  font-size: 0.7rem;
}

.chat-log {
  min-height: 0;
  flex: 1;
  overflow-y: auto;
  padding: 0.6rem 0.75rem;
  scrollbar-gutter: stable;
  overscroll-behavior: contain;
}

.chat-log ol {
  display: grid;
  gap: 0.7rem;
  margin: 0;
  padding: 0;
  list-style: none;
}

.chat-log li > div {
  display: flex;
  align-items: baseline;
  gap: 0.45rem;
}

.chat-log strong {
  font-size: 0.77rem;
}

.chat-log time {
  color: var(--color-text-muted, #607080);
  font-size: 0.62rem;
}

.chat-log p {
  margin: 0.16rem 0 0;
  font-size: 0.78rem;
  line-height: 1.4;
  overflow-wrap: anywhere;
}

.chat-empty,
.chat-disabled {
  color: var(--color-text-muted, #607080);
  text-align: center;
}

.chat-form {
  display: grid;
  gap: 0.55rem;
  padding: 0.7rem;
  border-block-start: 1px solid var(--color-border, #d5dbe1);
  background: color-mix(in srgb, var(--color-bg, #f5f7f9) 72%, var(--color-surface, #fff));
}

.chat-form label {
  display: grid;
  gap: 0.22rem;
  color: var(--color-text-muted, #607080);
  font-size: 0.67rem;
  font-weight: 700;
}

.chat-form input,
.chat-form textarea {
  width: 100%;
  box-sizing: border-box;
  padding: 0.48rem 0.58rem;
  border: 1px solid var(--color-border, #d5dbe1);
  border-radius: var(--radius-sm, 0.35rem);
  background: var(--color-surface, #fff);
  color: var(--color-text, #17202a);
  font: inherit;
  font-size: 0.78rem;
  resize: vertical;
}

.chat-form input:focus,
.chat-form textarea:focus {
  border-color: var(--color-accent, #2f78c4);
  outline: 2px solid color-mix(in srgb, var(--color-accent, #2f78c4) 22%, transparent);
}

.chat-form__footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.7rem;
}

.chat-form__footer > span {
  color: var(--color-text-muted, #607080);
  font-size: 0.65rem;
}

.chat-form button {
  min-height: 2.15rem;
  padding-inline: 0.85rem;
  border: 0;
  border-radius: var(--radius-sm, 0.35rem);
  background: var(--color-primary, var(--color-accent, #2f78c4));
  color: var(--color-on-primary, var(--color-on-accent, #fff));
  font: inherit;
  font-size: 0.75rem;
  font-weight: 750;
  cursor: pointer;
}

.chat-form button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.chat-error {
  margin: 0;
  color: var(--color-danger, #b42318);
  font-size: 0.72rem;
}

.chat-disabled {
  margin: 0;
  padding: 1rem;
  font-size: 0.78rem;
}
</style>
