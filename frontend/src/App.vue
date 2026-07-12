<script setup lang="ts">
import { onBeforeUnmount, onMounted } from "vue";
import { RouterView, useRouter } from "vue-router";

import AppToastHost from "@/components/ui/AppToastHost.vue";
import ConfirmationDialog from "@/components/ui/ConfirmationDialog.vue";
import { useToast } from "@/composables/useToast";
import { useSessionStore } from "@/stores/session";

const session = useSessionStore();
const router = useRouter();
const toast = useToast();
let handlingExpiredSession = false;

async function handleExpiredSession(): Promise<void> {
  if (handlingExpiredSession) return;
  const current = router.currentRoute.value;
  if (!current.path.startsWith("/admin") || current.name === "admin-login") return;
  handlingExpiredSession = true;
  session.clear();
  toast.warning("Your admin session expired. Sign in again.", { duration: 0 });
  try {
    await router.replace({ name: "admin-login", query: { redirect: current.fullPath } });
  } finally {
    handlingExpiredSession = false;
  }
}

onMounted(() => {
  void session.bootstrap();
  window.addEventListener("cope:session-expired", handleExpiredSession);
});

onBeforeUnmount(() => window.removeEventListener("cope:session-expired", handleExpiredSession));
</script>

<template>
  <RouterView />
  <AppToastHost />
  <ConfirmationDialog />
</template>
