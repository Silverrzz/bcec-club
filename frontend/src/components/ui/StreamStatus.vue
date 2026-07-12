<script setup lang="ts">
import { computed } from "vue";

import type { StreamConnectionState } from "@/composables/useEventStream";
import StatusBadge from "./StatusBadge.vue";

const props = withDefaults(
  defineProps<{
    state: StreamConnectionState;
    label?: string;
    showWhenIdle?: boolean;
  }>(),
  { showWhenIdle: true },
);

const presentation = computed(() => {
  if (props.state === "live") return { label: props.label ?? "Live", tone: "success" as const, pulse: true };
  if (props.state === "connecting") return { label: "Connecting", tone: "info" as const, pulse: true };
  if (props.state === "reconnecting") return { label: "Reconnecting", tone: "warning" as const, pulse: true };
  if (props.state === "error") return { label: "Updates unavailable", tone: "danger" as const, pulse: false };
  if (props.state === "closed") return { label: "Updates paused", tone: "neutral" as const, pulse: false };
  return { label: "Not connected", tone: "neutral" as const, pulse: false };
});
</script>

<template>
  <StatusBadge v-if="state !== 'idle' || showWhenIdle" :tone="presentation.tone" dot :pulse="presentation.pulse">
    {{ presentation.label }}
  </StatusBadge>
</template>
