import { computed, ref } from "vue";
import { defineStore } from "pinia";

import { ApiError, api, setCsrfToken } from "@/api/client";
import type { SessionPayload } from "@/types/api";

export const useSessionStore = defineStore("session", () => {
  const session = ref<SessionPayload | null>(null);
  const loading = ref(false);
  const initialized = ref(false);
  let bootstrapRequest: Promise<SessionPayload | null> | null = null;

  const authenticated = computed(() => Boolean(session.value?.authenticated));
  const user = computed(() => session.value?.user ?? null);

  function applySession(payload: SessionPayload | null): void {
    session.value = payload;
    setCsrfToken(payload?.csrf_token ?? payload?.csrfToken);
  }

  async function bootstrap(force = false): Promise<SessionPayload | null> {
    if (initialized.value && !force) return session.value;
    if (bootstrapRequest) return bootstrapRequest;

    bootstrapRequest = (async () => {
      loading.value = true;
      try {
        const payload = await api.get<SessionPayload>("/api/session");
        applySession(payload);
      } catch (error) {
        if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
          applySession({ authenticated: false });
        } else {
          applySession(null);
        }
      } finally {
        loading.value = false;
        initialized.value = true;
        bootstrapRequest = null;
      }
      return session.value;
    })();

    return bootstrapRequest;
  }

  function clear(): void {
    applySession({ authenticated: false });
    initialized.value = true;
  }

  return { session, loading, initialized, authenticated, user, bootstrap, applySession, clear };
});
