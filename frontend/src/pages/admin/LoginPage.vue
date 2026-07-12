<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@/api/client'
import InlineFeedback from '@/components/admin/InlineFeedback.vue'
import { useSessionStore } from '@/stores/session'
import type { SessionPayload } from '@/types/api'

const route = useRoute()
const router = useRouter()
const sessionStore = useSessionStore()
const token = ref('')
const showToken = ref(false)
const pending = ref(false)
const error = ref('')
const adminConfigured = computed(() => sessionStore.session?.admin_configured !== false)
const secureContext = computed(() => sessionStore.session?.secure_context !== false)
const blockedMessage = computed(() => {
  if (!adminConfigured.value) return 'Admin access is not configured on this server. Set the server admin token before signing in.'
  if (!secureContext.value) return 'Admin access requires HTTPS unless you are connecting from the local machine.'
  return ''
})

async function signIn(): Promise<void> {
  error.value = ''
  if (!token.value) {
    error.value = 'Enter the admin token.'
    return
  }
  pending.value = true
  try {
    const response = await api.post<SessionPayload>('/api/session', { body: new URLSearchParams({ token: token.value }) })
    sessionStore.applySession(response)
    token.value = ''
    const candidate = typeof route.query.redirect === 'string' ? route.query.redirect : typeof route.query.next === 'string' ? route.query.next : ''
    const next = candidate.startsWith('/admin') && !candidate.startsWith('/admin/login') ? candidate : '/admin'
    await router.replace(next)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'Could not sign in. Check the token and try again.'
  } finally {
    pending.value = false
  }
}
</script>

<template>
  <section class="login-card">
      <div class="login-card__mark" aria-hidden="true">
        <svg viewBox="0 0 48 48"><path d="M16 37h20M19 37v-5.5h14V37M18 31.5 14 20l7-9 3 7 3-7 7 9-4 11.5M18 23h12" /></svg>
      </div>
      <div class="login-card__heading">
        <h1>Admin sign in</h1>
        <span>Use the token configured on this server. It stays in a secure, HTTP-only session cookie.</span>
      </div>

      <InlineFeedback :message="blockedMessage" tone="info" />
      <InlineFeedback :message="error" />

      <form class="login-form" novalidate @submit.prevent="signIn">
        <label>
          <span>Admin token</span>
          <span class="password-field">
            <input v-model="token" class="input" :type="showToken ? 'text' : 'password'" autocomplete="current-password" autofocus required>
            <button type="button" :aria-label="showToken ? 'Hide token' : 'Show token'" :aria-pressed="showToken" @click="showToken = !showToken">
              <svg v-if="showToken" aria-hidden="true" viewBox="0 0 24 24"><path d="M3 3l18 18M10.6 10.7a2 2 0 0 0 2.7 2.7M9.9 4.4A10.8 10.8 0 0 1 12 4.2c5.5 0 9 5 9 5.8a12 12 0 0 1-2.1 2.7M6.3 6.3C4.2 7.7 3 9.6 3 10c0 .8 3.5 5.8 9 5.8 1 0 2-.2 2.9-.5" /></svg>
              <svg v-else aria-hidden="true" viewBox="0 0 24 24"><path d="M3 12c0-.8 3.5-5.8 9-5.8s9 5 9 5.8-3.5 5.8-9 5.8S3 12.8 3 12Z" /><circle cx="12" cy="12" r="2.3" /></svg>
            </button>
          </span>
        </label>
        <button class="button button--primary login-form__submit" type="submit" :disabled="pending || !!blockedMessage" :aria-busy="pending">
          <span v-if="pending" class="button-spinner" aria-hidden="true" />
          {{ pending ? 'Signing in...' : 'Sign in' }}
        </button>
      </form>
  </section>
</template>

<style scoped>
.login-card { display: grid; gap: 1.1rem; width: 100%; }
.login-card__mark { align-items: center; background: var(--color-primary, #2d63bf); border-radius: .7rem; color: var(--color-on-primary, #fff); display: flex; height: 2.8rem; justify-content: center; width: 2.8rem; }
.login-card__mark svg { fill: none; height: 1.8rem; stroke: currentColor; stroke-linecap: round; stroke-linejoin: round; stroke-width: 1.6; width: 1.8rem; }
.login-card__heading p { color: var(--color-accent, #315fcc); font-size: .7rem; font-weight: 750; letter-spacing: .08em; margin: 0 0 .35rem; text-transform: uppercase; }
.login-card__heading h1 { font-size: clamp(1.45rem, 5vw, 1.8rem); margin: 0; }
.login-card__heading span { color: var(--color-text-muted, #64748b); display: block; font-size: .83rem; line-height: 1.5; margin-top: .45rem; }
.login-form { display: grid; gap: .9rem; }
.login-form label { display: grid; font-size: .82rem; font-weight: 650; gap: .4rem; }
.password-field { position: relative; }
.password-field input { padding-right: 2.8rem; width: 100%; }
.password-field button { align-items: center; background: none; border: 0; color: var(--color-text-muted, #64748b); cursor: pointer; display: flex; height: 100%; justify-content: center; position: absolute; right: .25rem; top: 0; width: 2.35rem; }
.password-field button:focus-visible { border-radius: .3rem; outline: 2px solid var(--color-accent, #315fcc); outline-offset: -2px; }
.password-field svg { fill: none; height: 1.1rem; stroke: currentColor; stroke-linecap: round; stroke-linejoin: round; stroke-width: 1.7; width: 1.1rem; }
.login-form__submit { justify-content: center; min-height: 2.55rem; width: 100%; }
</style>
